"""Build the dataset. Previous output is the memory that keeps identifiers stable."""
import argparse
import base64
import gzip
import hashlib
import json
import re
import sys
from urllib.parse import urlsplit
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import now_playing as now_playing_data
from .group import group_rows, shared_domains
from .normalize import clean_name, logo_url, name_key, stream_key, stream_protocol, web_url
from .tags import clean_tags
from .wikidata import enrich, match_groups

CONTRACT = "1.7.0"
ALLOWED_SOURCES = {"radio-browser", "wikidata", "contribution", "editor", "radioarg"}
MIN_ROWS = 10_000
MIN_RATIO = 0.8  # Refuse to publish when active stations drop below this ratio.
NO_COUNTRY = "XX"


class Refused(Exception):
    """The source looks wrong: nothing is written."""


def _stable_id(prefix, seed):
    digest = hashlib.sha256(seed.encode()).digest()
    return prefix + base64.b32encode(digest).decode().lower()[:26]


def _fresh_id(seed, taken):
    """A new station id that no record, past or present, has used."""
    station_id, n = _stable_id("st_", seed), 1
    while station_id in taken:
        station_id, n = _stable_id("st_", f"{seed}#{n}"), n + 1
    return station_id


# Radio Browser codec names. AAC+ is HE-AAC. OGG says the container, not the codec,
# and the others are video: they are left out.
CODECS = {"MP3": "mp3", "AAC": "aac", "AAC+": "he-aac", "FLAC": "flac", "OPUS": "opus"}
MAX_BITRATE = 10_000


def read_checks(items):
    """Measures of Radio Browser's own checker, by station uuid. Failed checks are left out."""
    checks = {}
    for item in items:
        if item.get("lastcheckok") != 1 or not isinstance(item.get("stationuuid"), str):
            continue
        bitrate = item.get("bitrate")
        checks[item["stationuuid"]] = {
            "codec": CODECS.get(str(item.get("codec") or "").strip().upper()),
            "bitrate": bitrate if isinstance(bitrate, int) and 0 < bitrate <= MAX_BITRATE else None,
            "hls": item.get("hls") == 1,
        }
    return checks


def _aggregator(url, aggregators):
    host = (urlsplit(url).hostname or "") if url else ""
    return any(host == d or host.endswith("." + d) for d in aggregators)


def prepare_rows(source, checks=None, aggregators=()):
    """checks: from read_checks, or None when no measures were fetched.
    aggregators: domains whose pages are listings, never a station's own site."""
    rows, refused = [], Counter()
    for item in source:
        stream = web_url(item.get("url_stream"))
        name = clean_name(item.get("name"))
        if not stream:
            refused["stream"] += 1
            continue
        if not name:
            refused["name"] += 1
            continue
        country = (item.get("iso_3166_1") or "").strip().upper()
        homepage = web_url(item.get("url_homepage"))
        if _aggregator(homepage, aggregators):
            homepage = None
        measure = (checks or {}).get(item["stationuuid"], {})
        rows.append({
            "uuid": item["stationuuid"],
            "measured": checks is not None,
            "codec": measure.get("codec"),
            "bitrate": measure.get("bitrate"),
            "hls": measure.get("hls", False),
            "name": name,
            "name_key": name_key(name),
            "stream": stream,
            "stream_key": stream_key(stream),
            "country": country if re.fullmatch(r"[A-Z]{2}", country) else "",
            "subdivision": (item.get("iso_3166_2") or "").strip().upper(),
            "homepage": None if homepage and stream_key(homepage) == stream_key(stream) else homepage,
            "logo": logo_url(item.get("url_favicon")),
            "source": "radio-browser",
            "place_name": None,
            "languages": item.get("iso_639") or "",
            "tags": item.get("tags") or "",
            "lat": item.get("geo_lat"),
            "lon": item.get("geo_long"),
        })
    rows.sort(key=lambda r: r["uuid"])
    return rows, refused


def contribution_rows(items, aggregators=()):
    """Rows from stations added by installations and checked by the stream checker.

    items: the public export of the contribution API. Only published stations count;
    a withdrawn one simply has no rows any more, and its record is retired.
    """
    rows = []
    for item in items:
        if item.get("status") != "published" or not re.fullmatch(r"pr_[0-9a-z]{26}", str(item.get("id", ""))):
            continue
        name = clean_name(item.get("name"))
        country = str(item.get("country") or "")
        if not name or not re.fullmatch(r"[A-Z]{2}", country):
            continue
        place = item.get("place") or {}
        homepage = web_url(item.get("homepage"))
        if _aggregator(homepage, aggregators):
            homepage = None
        for stream in item.get("streams") or []:
            url = web_url(stream.get("url"))
            if not url:
                continue
            bitrate = stream.get("bitrate_kbps")
            rows.append({
                "uuid": item["id"], "source": "contribution",
                "name": name, "name_key": name_key(name),
                "stream": url, "stream_key": stream_key(url),
                "country": country, "subdivision": "",
                "homepage": homepage, "logo": logo_url(item.get("logo_url")),
                "languages": ",".join(item.get("languages") or []),
                "tags": ",".join(item.get("tags") or []),
                "lat": place.get("lat"), "lon": place.get("lon"), "place_name": clean_name(place.get("name")) or None,
                "place_wikidata": place.get("wikidata") if re.fullmatch(r"Q[1-9][0-9]{0,11}", str(place.get("wikidata", ""))) else None,
                "measured": "codec" in stream or "bitrate_kbps" in stream,
                "codec": stream.get("codec") if re.fullmatch(r"[a-z0-9-]{2,16}", str(stream.get("codec", ""))) else None,
                "bitrate": bitrate if isinstance(bitrate, int) and 0 < bitrate <= MAX_BITRATE else None,
                "hls": stream.get("protocol") == "hls",
            })
    rows.sort(key=lambda r: (r["uuid"], r["stream_key"]))
    return rows


def radioarg_rows(items, aggregators=()):
    """Rows from the stations radioarg.net lists, kept only when their stream played.

    Facts only: name, country, town, stream, the station's own website. Never radioarg.net.
    """
    rows = []
    for item in items:
        page = str(item.get("page", ""))
        name = clean_name(item.get("name"))
        country = str(item.get("country") or "")
        url = web_url(item.get("stream"))
        if not re.fullmatch(r"[a-z0-9-]{1,120}", page) or not name or not url or not re.fullmatch(r"[A-Z]{2}", country):
            continue
        homepage = web_url(item.get("homepage"))
        if _aggregator(homepage, tuple(aggregators) + ("radioarg.net",)):
            homepage = None
        checked = item.get("checked") or {}
        bitrate = checked.get("bitrate_kbps")
        rows.append({
            "uuid": f"ra:{page}", "source": "radioarg",
            "name": name, "name_key": name_key(name),
            "stream": url, "stream_key": stream_key(url),
            "country": country, "subdivision": "",
            "homepage": homepage, "logo": None, "languages": "", "tags": "",
            "lat": None, "lon": None, "place_name": clean_name(item.get("town")) or None,
            "measured": bool(checked),
            "codec": checked.get("codec") if re.fullmatch(r"[a-z0-9-]{2,16}", str(checked.get("codec", ""))) else None,
            "bitrate": bitrate if isinstance(bitrate, int) and 0 < bitrate <= MAX_BITRATE else None,
            "hls": bool(checked.get("hls")),
        })
    rows.sort(key=lambda r: r["uuid"])
    return rows


def _most_common(values):
    counts = Counter(v for v in values if v)
    if not counts:
        return None
    return sorted(counts, key=lambda v: (-counts[v], v))[0]


def _display_name(rows):
    counts = Counter(r["name"] for r in rows)
    # At equal frequency, prefer the spelling with the most capitals: "FIP" over "Fip".
    return sorted(counts, key=lambda n: (-counts[n], -sum(c.isupper() for c in n), n))[0]


def _streams(rows, previous_streams):
    urls, by_key = {}, {}
    for row in rows:
        known = urls.get(row["stream_key"])
        if known is None or (known.startswith("http:") and row["stream"].startswith("https:")):
            urls[row["stream_key"]] = row["stream"]
        by_key.setdefault(row["stream_key"], []).append(row)
    ordered = sorted(urls.items(), key=lambda kv: (not kv[1].startswith("https:"), kv[0]))
    streams = []
    for index, (key, url) in enumerate(ordered):
        before = previous_streams.get(key, {})
        stream = {
            "id": before.get("id") or _stable_id("sm_", key),
            "url": url,
            "protocol": stream_protocol(url),
            "role": "primary" if index == 0 else "alternate",
        }
        members = by_key[key]
        if any(r["measured"] for r in members):
            codec = _most_common(r["codec"] for r in members)
            bitrate = _most_common(r["bitrate"] for r in members)
            if stream["protocol"] == "http" and any(r["hls"] for r in members):
                stream["protocol"] = "hls"
        else:
            # No measures fetched this time: keep the last known ones.
            codec, bitrate = before.get("codec"), before.get("bitrate_kbps")
            if before.get("protocol") == "hls":
                stream["protocol"] = "hls"
        if codec:
            stream["codec"] = codec
        if bitrate:
            stream["bitrate_kbps"] = bitrate
        streams.append(stream)
    return streams


def _content(rows, previous_streams):
    """Everything in a record except id, rev, sources and updated_at."""
    name = _display_name(rows)
    record = {
        "status": "active",
        "name": name,
        "streams": _streams(rows, previous_streams),
        "ids": {},
    }
    for source, key in (("radio-browser", "radio_browser"), ("contribution", "contributions"), ("radioarg", "radioarg")):
        uuids = sorted({r["uuid"] for r in rows if r["source"] == source})
        if uuids:
            record["ids"][key] = uuids
    others = sorted({r["name"] for r in rows if r["name_key"] != name_key(name)})
    if others:
        record["alt_names"] = [{"name": n} for n in others]
    country = _most_common(r["country"] for r in rows)
    if country:
        record["country"] = country
        subdivision = _most_common(
            r["subdivision"] for r in rows if r["subdivision"].startswith(country + "-")
        )
        if subdivision and re.fullmatch(r"[A-Z]{2}-[A-Z0-9]{1,3}", subdivision):
            record["subdivision"] = subdivision
    for row in rows:
        lat, lon = row["lat"], row["lon"]
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and abs(lat) <= 90 and abs(lon) <= 180 \
                and not isinstance(lat, bool) and (lat, lon) != (0, 0):
            record["place"] = {"lat": float(lat), "lon": float(lon), "scope": "reported"}
            break
    place_name = _most_common(r["place_name"] for r in rows)
    if place_name:
        record.setdefault("place", {"scope": "reported"})["name"] = place_name
        town = _most_common(r.get("place_wikidata") for r in rows if r["place_name"] == place_name)
        if town:
            record["place"]["wikidata"] = town
    languages = sorted({
        code.strip().lower() for r in rows for code in r["languages"].split(",")
        if re.fullmatch(r"[a-z]{2,3}", code.strip().lower())
    })
    if languages:
        record["languages"] = languages
    tags = clean_tags(r["tags"] for r in rows)
    if tags:
        record["tags"] = tags
    homepage = _most_common(r["homepage"] for r in rows)
    if homepage:
        record["homepage"] = homepage
    logo = _most_common(r["logo"] for r in rows)
    if logo:
        record["logo_url"] = logo
    return record


def read_ndjson(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_previous(out):
    stations = {}
    for path in sorted((out / "v1" / "stations").glob("*.ndjson")):
        for record in read_ndjson(path):
            stations[record["id"]] = record
    return stations, read_ndjson(out / "v1" / "redirects.ndjson")


def _source_names(rows, item, edited=False):
    return sorted({r["source"] for r in rows} | ({"wikidata"} if item else set()) | ({"editor"} if edited else set()))


def _sources(rows, before, date, item=None, edited=False):
    """One entry per source of the record, keeping the first date each was seen."""
    seen = {s["source"]: s["retrieved_at"] for s in (before or {}).get("sources", [])}
    return [{"source": source, "retrieved_at": seen.get(source, date)} for source in _source_names(rows, item, edited)]


def apply_editor(record, edit, previous_streams):
    """A maintainer's or an editor's checked correction. Returns True when something was applied.

    edit: homepage and logo_url (null removes), name, country, place (null removes),
    languages, tags, add_streams, remove_streams (stream ids), retire.
    """
    applied = False
    for key, clean in (("homepage", web_url), ("logo_url", logo_url)):
        if key in edit:
            url = clean(edit[key]) if edit[key] else None
            if url:
                record[key] = url
            else:
                record.pop(key, None)
            applied = True
    if edit.get("name"):
        record["name"] = clean_name(edit["name"]) or record["name"]
        applied = True
    if edit.get("country"):
        record["country"] = edit["country"]
        applied = True
    if "place" in edit:
        if edit["place"]:
            record["place"] = {**{k: v for k, v in edit["place"].items() if k in ("name", "wikidata", "lat", "lon")}, "scope": "editor"}
        else:
            record.pop("place", None)
        applied = True
    for key in ("languages", "tags"):
        if key in edit:
            if edit[key]:
                record[key] = sorted(set(edit[key]))
            else:
                record.pop(key, None)
            applied = True
    gone = set(edit.get("remove_streams", ()))
    if gone and any(m["id"] in gone for m in record["streams"]):
        kept = [m for m in record["streams"] if m["id"] not in gone]
        if kept and not any(m.get("role") == "primary" for m in kept) and any(m.get("role") == "primary" for m in record["streams"]):
            kept[0] = {**kept[0], "role": "primary"}
        record["streams"] = kept
        if not kept:
            record["status"] = "retired"
        applied = True
    keys = {stream_key(m["url"]) for m in record["streams"]}
    for raw in edit.get("add_streams", []):
        url = web_url(raw)
        if url and stream_key(url) not in keys:
            key = stream_key(url)
            record["streams"].append({"id": previous_streams.get(key, {}).get("id") or _stable_id("sm_", key),
                                      "url": url, "protocol": stream_protocol(url), "role": "alternate"})
            keys.add(key)
            applied = True
    if edit.get("retire"):
        record["status"] = "retired"
        applied = True
    return applied


def editor_from_edits(editor, edits, redirects):
    """Adds the accepted edits from the API to the maintainer's file, oldest first.

    Returns (editor, same pairs). An edit of a merged station follows its redirect;
    a later edit of a field replaces an earlier one; streams to add or remove add up.
    """
    moved = {r["from"]: r["to"] for r in redirects}
    stations = {k: dict(v) for k, v in (editor or {}).get("stations", {}).items()}
    pairs = []
    for item in sorted((e for e in edits if e["status"] == "accepted"), key=lambda e: (e["created_at"], e["id"])):
        station = moved.get(item["station"], item["station"])
        change = item["change"]
        entry = stations.setdefault(station, {})
        entry.update(change.get("set", {}))
        for key in ("add_streams", "remove_streams"):
            if change.get(key):
                entry[key] = list(dict.fromkeys(entry.get(key, []) + change[key]))
        if change.get("retire"):
            entry["retire"] = True
        if change.get("same_as"):
            pairs.append([station, moved.get(change["same_as"], change["same_as"])])
    return {**(editor or {}), "stations": stations}, pairs


def join_same(groups, previous, pairs):
    """Joins the groups of two stations the maintainer confirmed as the same (audio fingerprint).

    pairs: [[st_a, st_b], ...]. A pair whose ids are unknown or retired does nothing.
    """
    owner = {}
    id_of_uuid = {u: s["id"] for s in previous.values()
                  for key in ("radio_browser", "contributions", "radioarg") for u in s.get("ids", {}).get(key, [])}
    for index, rows in enumerate(groups):
        for row in rows:
            station = id_of_uuid.get(row["uuid"])
            if station:
                owner.setdefault(station, index)
    parent = list(range(len(groups)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in pairs:
        if a in owner and b in owner:
            x, y = find(owner[a]), find(owner[b])
            if x != y:
                parent[max(x, y)] = min(x, y)
    joined = defaultdict(list)
    for index, rows in enumerate(groups):
        joined[find(index)].extend(rows)
    return list(joined.values())


def apply_measures(content, measures, previous_streams):
    """Our stream checker's codec and bitrate replace the sources' ones.

    measures: {stream id: {"codec", "bitrate_kbps"}} from the published health files, or None
    when they could not be read: each stream then keeps its last published values.
    """
    for stream in content["streams"]:
        if measures is None:
            measure = previous_streams.get(stream_key(stream["url"]), {})
        else:
            measure = measures.get(stream["id"], {})
        codec, bitrate = measure.get("codec"), measure.get("bitrate_kbps")
        if codec or bitrate:
            stream.pop("codec", None)
            stream.pop("bitrate_kbps", None)
        if codec:
            stream["codec"] = codec
        if bitrate:
            stream["bitrate_kbps"] = bitrate


def read_health(lines):
    """Codec and bitrate measured by our stream checker, by stream id, from health/*.ndjson lines."""
    measures = {}
    for line in lines:
        item = json.loads(line)
        if not isinstance(item, dict) or not re.fullmatch(r"sm_[a-z0-9]{26}", str(item.get("id", ""))):
            continue
        measure = {}
        if re.fullmatch(r"[a-z0-9-]{2,16}", str(item.get("codec", ""))):
            measure["codec"] = item["codec"]
        bitrate = item.get("bitrate_kbps")
        if isinstance(bitrate, int) and not isinstance(bitrate, bool) and 0 < bitrate <= MAX_BITRATE:
            measure["bitrate_kbps"] = bitrate
        if measure:
            measures[item["id"]] = measure
    return measures


def merge(groups, previous, redirects, as_of, matches=None, editor=None, measures=False):
    """matches: {id(rows): Wikidata item}, from wikidata.match_groups. editor: {station id: correction}.
    measures: see apply_measures; False leaves the sources' values alone."""
    matches = matches or {}
    editor = editor or {}
    date, stamp = as_of[:10], as_of
    id_by_uuid = {u: s["id"] for s in previous.values()
                  for key in ("radio_browser", "contributions", "radioarg") for u in s.get("ids", {}).get(key, [])}
    previous_streams = {stream_key(m["url"]): m for s in previous.values() for m in s["streams"]}
    stations, seen, new_redirects = {}, set(), list(redirects)
    # Ids never reused: those in service, those of the previous build and old redirects.
    taken = set(previous) | {r["from"] for r in redirects}
    for rows in sorted(groups, key=lambda g: min(r["uuid"] for r in g)):
        # The record that brings the most rows keeps its id: a well-known station stays put.
        weight = Counter(id_by_uuid[r["uuid"]] for r in rows if r["uuid"] in id_by_uuid)
        known = sorted(set(weight) - seen, key=lambda i: (-weight[i], i))
        station_id = known[0] if known else _fresh_id(min(r["uuid"] for r in rows), taken)
        seen.add(station_id)
        taken.add(station_id)
        for old in known[1:]:
            seen.add(old)
            new_redirects.append({"from": old, "to": station_id, "at": date})
        content = _content(rows, previous_streams)
        item = matches.get(id(rows))
        if item:
            enrich(content, item)
        edited = station_id in editor and apply_editor(content, editor[station_id], previous_streams)
        if measures is not False:
            apply_measures(content, measures, previous_streams)
        before = previous.get(station_id)
        if before and all(before.get(k) == v for k, v in content.items()) and set(before) - {"id", "rev", "sources", "updated_at"} == set(content) \
                and [x["source"] for x in before["sources"]] == _source_names(rows, item, edited):
            stations[station_id] = before
        else:
            stations[station_id] = {
                "id": station_id,
                "rev": before["rev"] + 1 if before else 1,
                **content,
                "sources": _sources(rows, before, date, item, edited),
                "updated_at": stamp,
            }
    moved = {r["from"]: r["to"] for r in new_redirects}
    for station_id, before in previous.items():
        if station_id in stations or station_id in moved:
            continue
        if before["status"] == "active":
            before = {**before, "status": "retired", "rev": before["rev"] + 1, "updated_at": stamp}
        stations[station_id] = before
    return stations, _collapse(new_redirects)


def _collapse(redirects):
    """Point every old id straight at its final id."""
    targets = {r["from"]: r["to"] for r in redirects}
    collapsed = {}
    for redirect in redirects:
        target, hops = redirect["to"], 0
        while target in targets and hops < len(targets):
            target, hops = targets[target], hops + 1
        collapsed[redirect["from"]] = {**redirect, "to": target}
    return [collapsed[k] for k in sorted(collapsed)]


def check(stations, previous, source_rows):
    if source_rows < MIN_ROWS:
        raise Refused(f"source has only {source_rows} rows")
    before = sum(s["status"] == "active" for s in previous.values())
    after = sum(s["status"] == "active" for s in stations.values())
    if before and after < before * MIN_RATIO:
        raise Refused(f"active stations fell from {before} to {after}")
    for record in stations.values():
        unknown = {s["source"] for s in record["sources"]} - ALLOWED_SOURCES
        if unknown:
            raise Refused(f"{record['id']} has unknown sources: {sorted(unknown)}")


def _dumps(record):
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_shard(text, relative, dist):
    path = dist / "v1" / (relative + ".gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0)
    path.write_bytes(data)
    return {"path": relative + ".gz", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _next_version(out, entries, date):
    """Same content, same version. New content: the build date and a counter for that day.

    The previous version and a digest of its files are kept in v1/VERSION.
    """
    digest = hashlib.sha256("".join(e["sha256"] for e in entries).encode()).hexdigest()
    path = out / "v1" / "VERSION"
    previous, previous_digest = (path.read_text(encoding="ascii").split() + ["", ""])[:2] if path.exists() else ("", "")
    if previous and previous_digest == digest:
        return previous
    day, _, counter = previous.partition(".")
    version = f"{date}.{int(counter) + 1}" if day == date and counter.isdigit() else f"{date}.1"
    if previous and version <= previous:
        raise Refused(f"version {version} is not after {previous}")
    path.write_text(f"{version} {digest}\n", encoding="ascii")
    return version


def _ndjson(records):
    return "".join(_dumps(r) + "\n" for r in records)


def write(stations, redirects, out, dist, as_of, build_date=None, now_playing=None):
    source_dir = out / "v1" / "stations"
    source_dir.mkdir(parents=True, exist_ok=True)
    for old in source_dir.glob("*.ndjson"):
        old.unlink()
    shards = {}
    for record in sorted(stations.values(), key=lambda s: s["id"]):
        shards.setdefault(record.get("country", NO_COUNTRY), []).append(_dumps(record))
    entries = []
    for shard in sorted(shards):
        text = "\n".join(shards[shard]) + "\n"
        (source_dir / f"{shard}.ndjson").write_text(text, encoding="utf-8")
        entry = _write_shard(text, f"stations/{shard}.ndjson", dist)
        entries.append({"shard": shard, **entry, "count": len(shards[shard])})
    text = "".join(_dumps(r) + "\n" for r in redirects)
    (out / "v1" / "redirects.ndjson").write_text(text, encoding="utf-8")
    redirect_entry = {"shard": "all", **_write_shard(text, "redirects.ndjson", dist), "count": len(redirects)}
    playing = []
    if now_playing is not None:
        np_dir = out / "v1" / "now-playing"
        np_dir.mkdir(parents=True, exist_ok=True)
        for shard, records in zip(("adapters", "templates", "blocked-hosts"), now_playing):
            text = _ndjson(records)
            (np_dir / f"{shard}.ndjson").write_text(text, encoding="utf-8")
            playing.append({"shard": shard, **_write_shard(text, f"now-playing/{shard}.ndjson", dist),
                            "count": len(records)})
    version = _next_version(out, entries + [redirect_entry] + playing, build_date or as_of[:10])
    manifest = {
        "contract": CONTRACT,
        "dataset_version": version,
        "generated_at": as_of,
        "license": "CC0-1.0",
        "datasets": {"stations": entries, "redirects": [redirect_entry]},
    }
    if playing:
        manifest["datasets"]["now_playing"] = playing
    (dist / "v1" / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def build(source, out, dist, as_of, checks=None, build_date=None, contributions=(), same=(), wikidata=(), editor=None,
          radioarg=(), now_playing=None, edits=(), measures=False):
    """now_playing: (adapters, templates, blocked hosts) as read by now_playing.load(), or None to leave it out.
    measures: our checker's measures, see apply_measures."""
    editor = editor or {}
    rows, refused = prepare_rows(source, checks, editor.get("aggregator_homepages", ()))
    rows += contribution_rows(contributions, editor.get("aggregator_homepages", ()))
    rows += radioarg_rows(radioarg, editor.get("aggregator_homepages", ()))
    previous, redirects = load_previous(out)
    editor, edited_pairs = editor_from_edits(editor, edits, redirects)
    groups = join_same(group_rows(rows), previous, list(same) + edited_pairs)
    found = match_groups(groups, wikidata, shared_domains(rows)) if wikidata else {}
    matches = {id(groups[index]): item for index, item in found.items()}
    stations, redirects = merge(groups, previous, redirects, as_of, matches, editor.get("stations", {}), measures)
    check(stations, previous, len(source))
    playing, playing_report = None, None
    if now_playing is not None:
        try:
            *playing, playing_report = now_playing_data.prepare(*now_playing, stations, redirects)
        except now_playing_data.Invalid as error:
            raise Refused(f"now_playing: {error}") from error
    manifest = write(stations, redirects, out, dist, as_of, build_date, playing)
    return {
        "source_rows": len(source),
        "refused": dict(refused),
        "stations": len(stations),
        "active": sum(s["status"] == "active" for s in stations.values()),
        "streams": sum(len(s["streams"]) for s in stations.values()),
        "measured_streams": sum("codec" in m for s in stations.values() for m in s["streams"]),
        "wikidata": sum("wikidata" in s.get("ids", {}) for s in stations.values() if s["status"] == "active"),
        "redirects": len(redirects),
        "dataset_version": manifest["dataset_version"],
        "shards": len(manifest["datasets"]["stations"]),
        "bytes": sum(e["bytes"] for e in manifest["datasets"]["stations"]),
        "now_playing": playing_report,
    }


def as_of_from_name(name):
    match = re.search(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", name)
    if match:
        y, mo, d, h, mi, s = match.groups()
        return f"{y}-{mo}-{d}T{h}:{mi}:{s}Z"
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Radio Browser export (.json.gz)")
    parser.add_argument("--out", required=True, type=Path, help="data repository")
    parser.add_argument("--dist", required=True, type=Path, help="directory to deploy")
    parser.add_argument("--checks", type=Path, help="Radio Browser checker measures (.json.gz), optional")
    parser.add_argument("--contributions", type=Path, help="stations added by installations (.json), optional")
    parser.add_argument("--same-stations", type=Path, help="pairs of station ids confirmed as one station (.json)")
    parser.add_argument("--wikidata", type=Path, help="radio stations from Wikidata (.json.gz), optional")
    parser.add_argument("--editor", type=Path, help="corrections checked by the maintainer (.json), optional")
    parser.add_argument("--edits", type=Path, help="accepted edits from the edit API (.json), optional")
    parser.add_argument("--now-playing", action="store_true",
                        help="publish the now_playing dataset from data/now-playing and the contract templates")
    parser.add_argument("--health", type=Path,
                        help="our checker's health files (directory of *.ndjson.gz); an empty or missing directory keeps the last values")
    parser.add_argument("--radioarg", type=Path, help="stations listed by radioarg.net, streams checked (.json.gz), optional")
    args = parser.parse_args()
    with gzip.open(args.input, "rt", encoding="utf-8") as handle:
        source = json.load(handle)
    checks = None
    if args.checks:
        with gzip.open(args.checks, "rt", encoding="utf-8") as handle:
            checks = read_checks(json.load(handle))
    measures = False
    if args.health:
        files = sorted(args.health.glob("*.ndjson.gz")) if args.health.is_dir() else []
        measures = read_health(line for f in files for line in gzip.open(f, "rt", encoding="utf-8")) if files else None
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        contributions = json.loads(args.contributions.read_text(encoding="utf-8")) if args.contributions else ()
        same = json.loads(args.same_stations.read_text(encoding="utf-8"))["same"] if args.same_stations else ()
        wikidata = json.loads(gzip.decompress(args.wikidata.read_bytes())) if args.wikidata else ()
        editor = json.loads(args.editor.read_text(encoding="utf-8")) if args.editor else None
        radioarg = json.loads(gzip.decompress(args.radioarg.read_bytes())) if args.radioarg else ()
        report = build(source, args.out, args.dist, as_of_from_name(args.input.name), checks, today, contributions, same, wikidata, editor,
                       radioarg, now_playing_data.load() if args.now_playing else None,
                       json.loads(args.edits.read_text(encoding="utf-8")) if args.edits else (), measures)
    except Refused as error:
        sys.exit(f"Refused, nothing written: {error}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
