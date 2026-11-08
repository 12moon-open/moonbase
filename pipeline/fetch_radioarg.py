"""Collect the facts radioarg.net lists about stations, then check each stream.

Usage: python -m pipeline.fetch_radioarg OUTPUT.json.gz [--limit N]

What is kept, facts only: the station's name, country, town, the address of its
first stream, and its own website (never radioarg.net). No text, logo, rating or
genre. The pages are read as HTML; their JavaScript is never run.

Politeness: robots.txt is read first and obeyed (no /search, no query strings); one
page every PAUSE seconds; an identifiable User-Agent. Each stream is then probed,
and only the streams that play are kept, with their measured codec and bitrate.
"""
import gzip
import html
import json
import re
import sys
import time
import urllib.request
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from .fetch import USER_AGENT
from .normalize import web_url

BASE = "https://radioarg.net"
PAUSE = 2.0
MAX_PAGE = 2 * 1024 * 1024
COUNTRIES = {"argentina": "AR", "perú": "PE", "peru": "PE", "chile": "CL", "uruguay": "UY", "paraguay": "PY",
             "bolivia": "BO", "méxico": "MX", "mexico": "MX", "colombia": "CO", "venezuela": "VE", "ecuador": "EC",
             "españa": "ES", "espana": "ES", "estados unidos": "US", "brasil": "BR"}


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(MAX_PAGE).decode("utf-8", "replace")


def _js_string(text):
    """A JavaScript string literal's content, as Nuxt writes it (\\u002F and friends)."""
    try:
        return json.loads(f'"{text}"')
    except ValueError:
        return text


def _arguments(page):
    """{variable: string} from the page state, window.__NUXT__=(function(a,b,...){...}("x",...)).

    The script is only read as text: its arguments are split at top-level commas, and
    only string literals are kept. Nothing is executed.
    """
    start = page.find("window.__NUXT__=(function(")
    if start < 0:
        return {}
    names = page[start + 26: page.find(")", start + 26)].split(",")
    end = page.find("</script>", start)
    body = page[start:end].rstrip().rstrip(";").rstrip(")")
    call = body.rfind("}(")
    if call < 0:
        return {}
    text, values, depth, token, in_string, escape = body[call + 2:], [], 0, "", False, False
    for ch in text:
        if in_string:
            token += ch
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            values.append(token.strip())
            token = ""
            continue
        token += ch
    values.append(token.strip())
    out = {}
    for name, value in zip(names, values):
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            out[name.strip()] = _js_string(value[1:-1])
    return out


_LITERAL = r'"((?:[^"\\]|\\.){0,400})"|([A-Za-z_$][\w$]{0,3})'


def _value(match, group, variables):
    literal, name = match.group(group), match.group(group + 1)
    return _js_string(literal) if literal is not None else variables.get(name)


def parse_page(page):
    """The facts of one station page, or None when the page is not a station."""
    variables = _arguments(page)
    audio = re.search(r'<audio[^>]*\ssrc="([^"]+)"', page)
    name = re.search(r"\bh1:(?:" + _LITERAL + r"),h1_after:", page)
    title = _value(name, 1, variables) if name else None
    if not audio or not title:
        return None
    out = {"name": html.unescape(title).strip(), "stream": html.unescape(audio.group(1))}
    site = re.search(r'\{id:"site",name:[^,]*,url:(?:' + _LITERAL + r")\}", page)
    value = _value(site, 1, variables) if site else None
    if value:
        url = web_url(value.split("###")[-1])
        if url and not (urlsplit(url).hostname or "").endswith("radioarg.net"):
            out["homepage"] = url
    city = re.search(r"city:\{id:\d+,name:(?:" + _LITERAL + r"),title:(?:" + _LITERAL + r")", page)
    town = _value(city, 1, variables) if city else None
    where_text = _value(city, 3, variables) if city else None
    if town:
        out["town"] = town.strip()
    if where_text:
        where = re.search(r"\(([^()]*)\)", where_text)
        if where:
            country = where.group(1).split(",")[-1].strip().lower()
            if country in COUNTRIES:
                out["country"] = COUNTRIES[country]
    country = re.search(r'"addressCountry":"([A-Z]{2})"', page)
    locality = re.search(r'"addressLocality":"((?:[^"\\]|\\.){1,100})"', page)
    if country:
        out["country"] = country.group(1)
    if locality and "town" not in out:
        out["town"] = _js_string(locality.group(1)).strip()
    return out


def station_pages(robots):
    sitemap = _get(BASE + "/sitemap.xml")
    locations = re.findall(r"<loc>([^<]+)</loc>", sitemap)
    if "<sitemapindex" in sitemap:
        pages = []
        for child in locations:
            time.sleep(PAUSE)
            pages += re.findall(r"<loc>([^<]+)</loc>", _get(child))
        locations = pages
    return [u for u in dict.fromkeys(locations)
            if u.startswith(BASE + "/") and u.rstrip("/") != BASE and robots.can_fetch(USER_AGENT, u)]


def main():
    output = sys.argv[1]
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    robots = urllib.robotparser.RobotFileParser(BASE + "/robots.txt")
    robots.read()
    pages = station_pages(robots)[:limit]
    stations = []
    for url in pages:
        time.sleep(PAUSE)
        try:
            facts = parse_page(_get(url))
        except OSError:
            continue
        if facts:
            facts["page"] = url.rsplit("/", 1)[1]
            stations.append(facts)
    # Check every stream from here: only those that play are kept.
    from checker import probe as probe_module
    probe_module.RESOLVER = "doh"
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda s: probe_module.probe(s["stream"]), stations))
    kept = []
    for facts, result in zip(stations, results):
        if result.get("ok"):
            facts["checked"] = {k: result[k] for k in ("codec", "bitrate_kbps", "hls") if k in result}
            kept.append(facts)
    with gzip.GzipFile(output, "wb", mtime=0) as handle:
        handle.write(json.dumps(sorted(kept, key=lambda s: s["page"]), ensure_ascii=False).encode())
    print(json.dumps({"pages": len(pages), "stations": len(stations), "playing": len(kept)}), file=sys.stderr)


if __name__ == "__main__":
    main()
