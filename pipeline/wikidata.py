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

CALL_SIGN = re.compile(r"\b([KW][A-Z]{2,3}|C[FHIJKY][A-Z]{2}|X[EH][A-Z]{2,3})(?:-(?:FM|AM|LP|LPFM|HD\d))?\b")
CALL_COUNTRIES = {"US", "CA", "MX"}
COLLEGE_TAG = "college radio"
NPR_TAG = "npr"
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


def _page(url):
    """host and path of a site address, for addresses on a shared domain: radiofrance.fr/fip."""
    match = re.match(r"https?://(?:www\.)?([^/?#]+)(/[^?#]*)?", url or "", re.IGNORECASE)
    if not match:
        return None
    path = (match.group(2) or "").rstrip("/").lower()
    return f"{match.group(1).lower()}{path}" if path else None


def _main_key(rows):
    names = defaultdict(int)
    for row in rows:
        names[row["name_key"]] += 1
    return max(names, key=lambda k: (names[k], k)) if names else ""


def _calls(texts):
    return {m.group(1) for t in texts for m in CALL_SIGN.finditer(t.upper())}


def _item_call(item):
    """The item's call sign (P2317), or a label that is one: WJCU, KEXP-FM."""
    call = item.get("call_sign") or ""
    found = _calls([call]) or {n for n in _calls(item["names"]) if any(re.fullmatch(rf"{n}(?:-(?:FM|AM|LP))?", x.upper()) for x in item["names"])}
    return next(iter(sorted(found)), None) if len(found) == 1 else None


def match_groups(groups, items, shared=frozenset()):
    """Returns {group index: item} for sure matches only."""
    by_name, by_site_domain = defaultdict(list), defaultdict(list)
    for item in items:
        for domain in _domains(item.get("websites", []), shared):
            by_site_domain[(item["country"], domain)].append(item)
    for item in items:
        for key in {name_key(n) for n in item["names"]} - {""}:
            by_name[(item["country"], key)].append(item)
    infos, group_count = [], defaultdict(int)
    for rows in groups:
        country = max((r["country"] for r in rows), key=lambda c: (sum(r["country"] == c for r in rows), c))
        main = _main_key(rows)
        infos.append((country, main, {r["name_key"] for r in rows} - {""}))
        if main:
            group_count[(country, main)] += 1
    # Call signs, in North America: a sure identifier, once common words are left out.
    by_call = defaultdict(list)
    for item in items:
        if item["country"] in CALL_COUNTRIES:
            call = _item_call(item)
            if call:
                by_call[(item["country"], call)].append(item)
    group_calls = [_calls(r["name"] for r in rows) if infos[i][0] in CALL_COUNTRIES else set() for i, rows in enumerate(groups)]
    call_use = defaultdict(int)
    for i, calls in enumerate(group_calls):
        for call in calls:
            call_use[(infos[i][0], call)] += 1
    found = {}
    for index, rows in enumerate(groups):
        country = infos[index][0]
        known = {c for c in group_calls[index] if call_use[(country, c)] <= 2 and len(by_call.get((country, c), [])) == 1}
        if len(known) == 1:
            found[index] = (by_call[(country, known.pop())][0], True)
    for index, rows in enumerate(groups):
        country, main, keys = infos[index]
        if index in found or not country or not main:
            continue
        # The main name first: other names often come from mislabelled source rows.
        candidates = {i["q"]: i for i in by_name.get((country, main), [])}
        by_main = bool(candidates)
        if not candidates:
            candidates = {i["q"]: i for k in keys for i in by_name.get((country, k), [])}
        if not candidates:
            # Same official site and one name inside the other: "KEXP 90.3 FM" and "KEXP".
            site = _domains([r["homepage"] for r in rows if r.get("homepage")], shared)
            near = {i["q"]: i for d in site for i in by_site_domain.get((country, d), [])
                    if any(len(k) >= 4 and (k in main or main in k) for k in {name_key(n) for n in i["names"]} - {""})}
            if len(near) == 1:
                found[index] = (next(iter(near.values())), False)
            continue
        addresses = [r["stream"] for r in rows] + [r["homepage"] for r in rows if r.get("homepage")]
        mine = _domains(addresses, shared)
        pages = {_page(r["homepage"]) for r in rows if r.get("homepage")} - {None}
        by_site = [i for i in candidates.values()
                   if _domains(i.get("websites", []), shared) & mine or {_page(w) for w in i.get("websites", [])} & pages]
        if len(by_site) == 1:
            found[index] = (by_site[0], by_main)
            continue
        if len(candidates) != 1 or by_site:
            continue
        item = next(iter(candidates.values()))
        theirs = _domains(item.get("websites", []), shared)
        homepage = _domains([r["homepage"] for r in rows if r.get("homepage")], shared)
        if by_main and group_count[(country, main)] == 1 and (not theirs or not homepage):
            found[index] = (item, by_main)
    claimed = defaultdict(list)
    for index, (item, main_name) in found.items():
        claimed[item["q"]].append((index, main_name))
    result = {}
    for claims in claimed.values():
        if len(claims) == 1:
            winners = claims
        else:  # Several stations claim one item: only a single claim by the main name wins.
            winners = [c for c in claims if c[1]]
        if len(winners) == 1:
            result[winners[0][0]] = found[winners[0][0]][0]
    return result


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
    extra = ({COLLEGE_TAG} if item.get("college") else set()) | ({NPR_TAG} if item.get("npr") else set())
    if extra:
        record["tags"] = sorted(set(record.get("tags", [])) | extra)
    return record
