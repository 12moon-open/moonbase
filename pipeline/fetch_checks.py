"""Download the measures of Radio Browser's own stream checker: codec, bitrate, HLS.

Usage: python -m pipeline.fetch_checks DIRECTORY

The daily export leaves them out, so they come from the public API, in one request.
Only the fields the build reads are kept. Prints the path of the file written.
"""
import gzip
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .fetch import USER_AGENT

SERVERS = ("de1", "de2", "fi1", "at1", "nl1")
PATH = "/json/stations?hidebroken=false&limit=200000"
MAX_BYTES = 300 * 1024 * 1024
MIN_STATIONS = 10_000
FIELDS = ("stationuuid", "codec", "bitrate", "hls", "lastcheckok")


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("larger than expected")
    return data


def slim(items):
    if not isinstance(items, list) or len(items) < MIN_STATIONS:
        raise ValueError("too few stations")
    return sorted(
        ({k: item.get(k) for k in FIELDS} for item in items if isinstance(item, dict)),
        key=lambda item: str(item["stationuuid"]),
    )


def main():
    directory = Path(sys.argv[1])
    directory.mkdir(parents=True, exist_ok=True)
    errors = []
    for server in SERVERS:
        try:
            items = slim(json.loads(_get(f"https://{server}.api.radio-browser.info{PATH}")))
            break
        except (OSError, ValueError) as error:
            errors.append(f"{server}: {error}")
    else:
        raise SystemExit("no checker measures: " + "; ".join(errors))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = directory / f"radiobrowser_checks_{stamp}.json.gz"
    with gzip.GzipFile(path, "wb", mtime=0) as handle:
        handle.write(json.dumps(items, separators=(",", ":")).encode())
    print(path)


if __name__ == "__main__":
    main()
