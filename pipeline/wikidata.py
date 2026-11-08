"""Match stations with Wikidata items (CC0), only when the match is sure.

A group of rows (one future station) matches an item when they are in the same
country, share a name (label or alias, compared like station names), and either:
- the item's official website and one of the station's addresses (homepage or
  stream) share a domain that is not shared hosting; or
- the name is unique on both sides in that country, and no website contradicts it.
An item matched by two stations matches neither. A doubtful match is never applied.

A matched station gets ids.wikidata, its Wikipedia articles by language, the
item's website when it has none, and the item's logo from Wikimedia Commons.
"""
import hashlib
import re
from collections import defaultdict
from urllib.parse import quote

from .normalize import name_key, registrable_domain, web_url

LOGO_WIDTH = 500
LOGO_TYPES = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp")


def commons_thumbnail(filename, width=LOGO_WIDTH):
    """Address of a raster thumbnail of a Commons file. SVG logos come out as PNG."""
    name = filename.replace(" ", "_")
    if not name.lower().endswith(LOGO_TYPES) or "/" in name:
        return None
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    encoded = quote(name, safe="()_-.,!")
    suffix = f"{encoded}.png" if name.lower().endswith(".svg") else encoded
    return f"https://upload.wikimedia.org/wikipedia/commons/thumb/{digest[0]}/{digest[:2]}/{encoded}/{width}px-{suffix}"


def _domains(urls, shared):
    return {d for d in map(registrable_domain, urls) if d and d not in shared}


def match_groups(groups, items, shared=frozenset()):
    """Returns {group index: item} for sure matches only."""
    by_name = defaultdict(list)
    for item in items:
        for key in {name_key(n) for n in item["names"]} - {""}:
            by_name[(item["country"], key)].append(item)
    group_names, group_count = [], defaultdict(int)
    for rows in groups:
        country = max((r["country"] for r in rows), key=lambda c: (sum(r["country"] == c for r in rows), c))
        keys = {r["name_key"] for r in rows} - {""}
        group_names.append((country, keys))
        for key in keys:
            group_count[(country, key)] += 1
    found = {}
    for index, rows in enumerate(groups):
        country, keys = group_names[index]
        if not country:
            continue
        candidates = {item["q"]: item for key in keys for item in by_name.get((country, key), [])}
        if not candidates:
            continue
        mine = _domains([r["stream"] for r in rows] + [r["homepage"] for r in rows if r.get("homepage")], shared)
        by_domain = [i for i in candidates.values() if _domains(i.get("websites", []), shared) & mine]
        if len(by_domain) == 1:
            found[index] = by_domain[0]
            continue
        if len(candidates) != 1 or by_domain:
            continue
        item = next(iter(candidates.values()))
        unique = all(group_count[(country, k)] == 1 for k in keys if (country, k) in by_name)
        theirs = _domains(item.get("websites", []), shared)
        homepage = _domains([r["homepage"] for r in rows if r.get("homepage")], shared)
        if unique and (not theirs or not homepage):
            found[index] = item
    claimed = defaultdict(list)
    for index, item in found.items():
        claimed[item["q"]].append(index)
    return {index: item for index, item in found.items() if len(claimed[item["q"]]) == 1}


def enrich(record, item):
    """Adds what the item knows to a record built from source rows."""
    record.setdefault("ids", {})["wikidata"] = item["q"]
    if item.get("wikipedia"):
        record["wikipedia"] = {lang: title for lang, title in item["wikipedia"].items()
                               if re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})*", lang) and 0 < len(title) <= 250}
        if not record["wikipedia"]:
            del record["wikipedia"]
    if "homepage" not in record:
        for website in sorted(item.get("websites", []), key=lambda w: not w.startswith("https:")):
            url = web_url(website)
            if url:
                record["homepage"] = url
                break
    logo = commons_thumbnail(item["logo"]) if item.get("logo") else None
    if logo:
        record["logo_url"] = logo
    return record
