"""Download the stations added by installations, from the contribution API.

Usage: python -m pipeline.fetch_contributions API_BASE OUTPUT.json

Reads every page of GET /v1/contributions/stations and keeps the latest state of
each proposal. Any failure stops with an error: a build without the contributions
would retire every contributed station.
"""
import json
import sys
import urllib.parse
import urllib.request

from .fetch import USER_AGENT

MAX_PAGES = 1000
MAX_BYTES = 8 * 1024 * 1024


def fetch_all(base, get=None):
    get = get or _get
    latest, after = {}, ""
    for _ in range(MAX_PAGES):
        query = urllib.parse.urlencode({"after": after}) if after else ""
        page = get(f"{base.rstrip('/')}/v1/contributions/stations" + (f"?{query}" if query else ""))
        for item in page["stations"]:
            latest[item["id"]] = item
        if not page.get("next"):
            return sorted(latest.values(), key=lambda item: item["id"])
        after = page["next"]
    raise SystemExit("too many pages")


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise SystemExit("page larger than expected")
    return json.loads(data)


def main():
    base, output = sys.argv[1], sys.argv[2]
    if not base.startswith("https://"):
        raise SystemExit("the API must be reached over https")
    items = fetch_all(base)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(items, handle, ensure_ascii=False)
    print(f"{len(items)} contributions", file=sys.stderr)


if __name__ == "__main__":
    main()
