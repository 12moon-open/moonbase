"""Build the dataset. Previous output is the memory that keeps identifiers stable."""
import argparse
import base64
import gzip
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .group import group_rows
from .normalize import clean_name, logo_url, name_key, stream_key, stream_protocol, web_url
from .tags import clean_tags

CONTRACT = "1.0.0"
ALLOWED_SOURCES = {"radio-browser", "wikidata", "contribution", "editor"}
MIN_ROWS = 10_000
MIN_RATIO = 0.8  # Refuse to publish when active stations drop below this ratio.
NO_COUNTRY = "XX"


class Refused(Exception):
    """The source looks wrong: nothing is written."""


def _stable_id(prefix, seed):
    digest = hashlib.sha256(seed.encode()).digest()
    return prefix + base64.b32encode(digest).decode().lower()[:26]


def prepare_rows(source):
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
        rows.append({
            "uuid": item["stationuuid"],
            "name": name,
            "name_key": name_key(name),
            "stream": stream,
            "stream_key": stream_key(stream),
            "country": country if re.fullmatch(r"[A-Z]{2}", country) else "",
            "subdivision": (item.get("iso_3166_2") or "").strip().upper(),
            "homepage": None if homepage and stream_key(homepage) == stream_key(stream) else homepage,
            "logo": logo_url(item.get("url_favicon")),
            "languages": item.get("iso_639") or "",
            "tags": item.get("tags") or "",
            "lat": item.get("geo_lat"),
            "lon": item.get("geo_long"),
        })
    rows.sort(key=lambda r: r["uuid"])
    return rows, refused


def _most_common(values):
    counts = Counter(v for v in values if v)
    if not counts:
        return None
    return sorted(counts, key=lambda v: (-counts[v], v))[0]


def _display_name(rows):
    counts = Counter(r["name"] for r in rows)
    # At equal frequency, prefer the spelling with the most capitals: "FIP" over "Fip".
    return sorted(counts, key=lambda n: (-counts[n], -sum(c.isupper() for c in n), n))[0]


def _streams(rows, stream_ids):
    urls = {}
    for row in rows:
        known = urls.get(row["stream_key"])
        if known is None or (known.startswith("http:") and row["stream"].startswith("https:")):
            urls[row["stream_key"]] = row["stream"]
    ordered = sorted(urls.items(), key=lambda kv: (not kv[1].startswith("https:"), kv[0]))
    streams = []
    for index, (key, url) in enumerate(ordered):
        streams.append({
            "id": stream_ids.get(key) or _stable_id("sm_", key),
            "url": url,
            "protocol": stream_protocol(url),
            "role": "primary" if index == 0 else "alternate",
        })
    return streams


def _content(rows, stream_ids):
    """Everything in a record except id, rev, sources and updated_at."""
    name = _display_name(rows)
    record = {
        "status": "active",
        "name": name,
        "streams": _streams(rows, stream_ids),
        "ids": {"radio_browser": sorted(r["uuid"] for r in rows)},
    }
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
        if isinstance(lat, float) and isinstance(lon, float) and abs(lat) <= 90 and abs(lon) <= 180:
            record["place"] = {"lat": lat, "lon": lon, "scope": "reported"}
            break
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


def merge(groups, previous, redirects, as_of):
    date, stamp = as_of[:10], as_of
    id_by_uuid = {u: s["id"] for s in previous.values() for u in s.get("ids", {}).get("radio_browser", [])}
    stream_ids = {stream_key(m["url"]): m["id"] for s in previous.values() for m in s["streams"]}
    stations, seen, new_redirects = {}, set(), list(redirects)
    for rows in sorted(groups, key=lambda g: min(r["uuid"] for r in g)):
        # The record that brings the most rows keeps its id: a well-known station stays put.
        weight = Counter(id_by_uuid[r["uuid"]] for r in rows if r["uuid"] in id_by_uuid)
        known = sorted(set(weight) - seen, key=lambda i: (-weight[i], i))
        station_id = known[0] if known else _stable_id("st_", min(r["uuid"] for r in rows))
        seen.add(station_id)
        for old in known[1:]:
            seen.add(old)
            new_redirects.append({"from": old, "to": station_id, "at": date})
        content = _content(rows, stream_ids)
        before = previous.get(station_id)
        if before and all(before.get(k) == v for k, v in content.items()) and set(before) - {"id", "rev", "sources", "updated_at"} == set(content):
            stations[station_id] = before
        else:
            stations[station_id] = {
                "id": station_id,
                "rev": before["rev"] + 1 if before else 1,
                **content,
                "sources": before["sources"] if before else [{"source": "radio-browser", "retrieved_at": date}],
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


def write(stations, redirects, out, dist, as_of):
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
    manifest = {
        "contract": CONTRACT,
        "dataset_version": as_of[:10] + ".1",
        "generated_at": as_of,
        "license": "CC0-1.0",
        "datasets": {"stations": entries, "redirects": [redirect_entry]},
    }
    (dist / "v1" / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def build(source, out, dist, as_of):
    rows, refused = prepare_rows(source)
    previous, redirects = load_previous(out)
    stations, redirects = merge(group_rows(rows), previous, redirects, as_of)
    check(stations, previous, len(source))
    manifest = write(stations, redirects, out, dist, as_of)
    return {
        "source_rows": len(source),
        "refused": dict(refused),
        "stations": len(stations),
        "active": sum(s["status"] == "active" for s in stations.values()),
        "streams": sum(len(s["streams"]) for s in stations.values()),
        "redirects": len(redirects),
        "shards": len(manifest["datasets"]["stations"]),
        "bytes": sum(e["bytes"] for e in manifest["datasets"]["stations"]),
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
    args = parser.parse_args()
    with gzip.open(args.input, "rt", encoding="utf-8") as handle:
        source = json.load(handle)
    try:
        report = build(source, args.out, args.dist, as_of_from_name(args.input.name))
    except Refused as error:
        sys.exit(f"Refused, nothing written: {error}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
