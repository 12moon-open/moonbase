"""Download the newest Radio Browser export. Usage: python -m pipeline.fetch DIRECTORY"""
import re
import sys
import urllib.request
from pathlib import Path

INDEX = "https://backups.radio-browser.info/"
USER_AGENT = "12moon-commons/1.0 (+https://github.com/12moon-open/moonbase)"
NAME = re.compile(r"radiobrowser_stations_\d{8}_\d{6}\.json\.gz")
MAX_BYTES = 100 * 1024 * 1024


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise SystemExit(f"{url} is larger than expected")
    return data


def latest_name(index_html):
    names = sorted(set(NAME.findall(index_html)))
    if not names:
        raise SystemExit("no export found in the index")
    return names[-1]


def main():
    directory = Path(sys.argv[1])
    directory.mkdir(parents=True, exist_ok=True)
    name = latest_name(_get(INDEX).decode("utf-8", "replace"))
    path = directory / name
    path.write_bytes(_get(INDEX + name))
    print(path)


if __name__ == "__main__":
    main()
