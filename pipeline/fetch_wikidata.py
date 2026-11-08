"""Download the radio stations known to Wikidata (CC0), one country at a time.

Usage: python -m pipeline.fetch_wikidata OUTPUT.json.gz

For each item that is a radio station (Q14350 or a subclass) with a country: its
labels and aliases, official websites, logo file on Commons, Wikipedia article
titles by language, call sign, and whether it is a college radio (an instance of
campus radio, Q1436229, or owned or operated by a higher education institution), and whether it is
a member of NPR (Q671510). The list of items per country, then their details in batches, one query after the other, with an
identifiable User-Agent, as the Wikidata Query Service asks.
"""
import gzip
import json
import sys
import time
import urllib.parse
import urllib.request

from .fetch import USER_AGENT

ENDPOINT = "https://query.wikidata.org/sparql"
PAUSE = 1.0
COUNTRIES = """
SELECT ?country ?code WHERE { ?country wdt:P297 ?code . }
"""
ITEMS = """
SELECT DISTINCT ?item WHERE {
  ?item wdt:P31/wdt:P279* wd:Q14350 ; wdt:P17 wd:%s .
  FILTER NOT EXISTS { ?item wdt:P576 ?dissolved }
}
"""
DETAILS = """
SELECT ?item
  (GROUP_CONCAT(DISTINCT ?name; separator="\u001f") AS ?names)
  (GROUP_CONCAT(DISTINCT STR(?website); separator="\u001f") AS ?websites)
  (SAMPLE(?logo) AS ?logoFile)
  (GROUP_CONCAT(DISTINCT CONCAT(?lang, "\u001e", ?title); separator="\u001f") AS ?articles)
  (SAMPLE(?call) AS ?callsign)
  (MAX(?isCollege) AS ?college)
  (MAX(?isNpr) AS ?npr)
WHERE {
  VALUES ?item { %s }
  OPTIONAL { ?item wdt:P2317 ?call }
  BIND(EXISTS { ?item wdt:P31/wdt:P279* wd:Q1436229 } ||
       EXISTS { ?item wdt:P127|wdt:P137|wdt:P749 ?owner . ?owner wdt:P31/wdt:P279* wd:Q38723 } AS ?isCollege)
  BIND(EXISTS { ?item wdt:P463|wdt:P361|wdt:P749|wdt:P127 wd:Q671510 } AS ?isNpr)
  OPTIONAL { ?item rdfs:label|skos:altLabel ?name }
  OPTIONAL { ?item wdt:P856 ?website }
  OPTIONAL { ?item wdt:P154 ?logo }
  OPTIONAL { ?article schema:about ?item ; schema:inLanguage ?lang ; schema:name ?title .
             FILTER(CONTAINS(STR(?article), ".wikipedia.org/")) }
}
GROUP BY ?item
"""
BATCH = 150


def query(text, attempts=4):
    request = urllib.request.Request(ENDPOINT, data=urllib.parse.urlencode({"query": text}).encode(), headers={
        "User-Agent": USER_AGENT, "Accept": "application/sparql-results+json",
        "Content-Type": "application/x-www-form-urlencoded"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read(64 * 1024 * 1024))["results"]["bindings"]
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            time.sleep(int(error.headers.get("Retry-After", "30") or 30))
        except (OSError, ValueError):
            if attempt == attempts - 1:
                raise
            time.sleep(30)
    raise RuntimeError("unreachable")


def split(value):
    return [v for v in (value or "").split("\x1f") if v]


def parse(rows, code):
    items = []
    for row in rows:
        item = {"q": row["item"]["value"].rsplit("/", 1)[1], "country": code,
                "names": sorted(set(split(row.get("names", {}).get("value"))))[:50],
                "websites": sorted(set(split(row.get("websites", {}).get("value"))))[:5]}
        logo = row.get("logoFile", {}).get("value", "")
        if "/Special:FilePath/" in logo:
            item["logo"] = urllib.parse.unquote(logo.rsplit("/Special:FilePath/", 1)[1])
        articles = {}
        for pair in split(row.get("articles", {}).get("value")):
            lang, _, title = pair.partition("\x1e")
            if lang and title:
                articles[lang] = title
        if articles:
            item["wikipedia"] = dict(sorted(articles.items()))
        call = row.get("callsign", {}).get("value", "").strip().upper()
        if call and len(call) <= 12:
            item["call_sign"] = call
        if row.get("college", {}).get("value") in ("true", "1"):
            item["college"] = True
        if row.get("npr", {}).get("value") in ("true", "1"):
            item["npr"] = True
        items.append(item)
    return items


def main():
    output = sys.argv[1]
    countries = sorted({(r["code"]["value"].upper(), r["country"]["value"].rsplit("/", 1)[1])
                        for r in query(COUNTRIES) if len(r["code"]["value"]) == 2})
    items = []
    for code, q in countries:
        time.sleep(PAUSE)
        ids = sorted({r["item"]["value"].rsplit("/", 1)[1] for r in query(ITEMS % q)}, key=lambda i: int(i[1:]))
        for start in range(0, len(ids), BATCH):
            time.sleep(PAUSE)
            values = " ".join(f"wd:{i}" for i in ids[start:start + BATCH])
            items += parse(query(DETAILS % values), code)
    items.sort(key=lambda i: (int(i["q"][1:]), i["country"]))
    if len(items) < 5000:
        raise SystemExit(f"only {len(items)} stations: refusing an incomplete download")
    with gzip.GzipFile(output, "wb", mtime=0) as handle:
        handle.write(json.dumps(items, ensure_ascii=False, separators=(",", ":")).encode())
    print(f"{len(items)} stations from {len(countries)} countries", file=sys.stderr)


if __name__ == "__main__":
    main()
