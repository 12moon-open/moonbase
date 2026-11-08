"""Download the edits accepted through the edit API.

Usage: python -m pipeline.fetch_edits API_BASE OUTPUT.json

Reads every page of GET /v1/edits and keeps the latest state of each edit (accepted,
or withdrawn when reverted). Any failure stops with an error: a build without them
would undo every edit.
"""
import json
import sys
import urllib.parse

from .fetch_contributions import MAX_PAGES, _get


def fetch_all(base, get=None):
    get = get or _get
    latest, after = {}, ""
    for _ in range(MAX_PAGES):
        query = urllib.parse.urlencode({"after": after}) if after else ""
        page = get(f"{base.rstrip('/')}/v1/edits" + (f"?{query}" if query else ""))
        for item in page["edits"]:
            latest[item["id"]] = item
        if not page.get("next"):
            return sorted(latest.values(), key=lambda item: (item["created_at"], item["id"]))
        after = page["next"]
    raise SystemExit("too many pages")


def main():
    base, output = sys.argv[1], sys.argv[2]
    if not base.startswith("https://"):
        raise SystemExit("the API must be reached over https")
    items = fetch_all(base)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(items, handle, ensure_ascii=False)
    print(f"{len(items)} edits", file=sys.stderr)


if __name__ == "__main__":
    main()
