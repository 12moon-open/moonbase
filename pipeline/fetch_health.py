"""Download the health files published by our stream checker, to read its measures.

Usage: python -m pipeline.fetch_health DIRECTORY

Reads https://data.12moon.app/v1/health/manifest.json and every file it lists, checked
against its sha256. Any failure stops with an error and leaves DIRECTORY empty: the build
then keeps the last published codec and bitrate.
"""
import hashlib
import json
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

from .fetch import USER_AGENT

BASE = "https://data.12moon.app/v1/health/"
MAX_BYTES = 50 * 1024 * 1024
TRIES = 3


def _get(url):
    for attempt in range(TRIES):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("larger than expected")
            return data
        except OSError:
            if attempt == TRIES - 1:
                raise
            time.sleep(2 * (attempt + 1))


def fetch(directory, get=_get):
    manifest = json.loads(get(BASE + "manifest.json"))
    count = 0
    for entry in manifest["files"]:
        if not re.fullmatch(r"[A-Z0-9]{2,8}\.ndjson\.gz", entry["path"]):
            raise ValueError(f"unexpected path {entry['path']!r}")
        data = get(BASE + entry["path"])
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"{entry['path']}: sha256 mismatch")
        (directory / entry["path"]).write_bytes(data)
        count += 1
    return manifest.get("checked_at"), count


def main():
    directory = Path(sys.argv[1])
    directory.mkdir(parents=True, exist_ok=True)
    try:
        checked_at, count = fetch(directory)
    except (OSError, ValueError, KeyError, TypeError) as error:
        shutil.rmtree(directory)
        directory.mkdir()
        raise SystemExit(f"no health files: {error}")
    print(f"{count} health files, checked {checked_at}", file=sys.stderr)


if __name__ == "__main__":
    main()
