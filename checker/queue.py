"""Check the stations added by installations, then tell the contribution API.

Usage: python -m checker.queue --api https://api.12moon.app --token-file FILE --data DATA_DIR

For each proposal handed out by the API:
- a stream already in the published data makes it a duplicate of that station;
- otherwise each stream is probed, and the station is published with the streams
  that play, or rejected when none does.

DATA_DIR is the directory served as data.12moon.app (it holds v1/stations/*.ndjson.gz).
"""
import argparse
import gzip
import http.client
import json
import os
import socket
import ssl
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

from pipeline.normalize import stream_key

from . import probe as probe_module
from .probe import USER_AGENT, probe

REJECTIONS = {"private_address": "private_address", "not_audio": "not_audio", "video_only": "not_audio"}


def known_streams(data):
    """stream key -> station id, for every active station of the published data."""
    index = {}
    for path in sorted((data / "v1" / "stations").glob("*.ndjson.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                station = json.loads(line)
                if station.get("status") == "active":
                    for stream in station["streams"]:
                        index.setdefault(stream_key(stream["url"]), station["id"])
    return index


MAX_STREAMS = 5


def decide(proposal, index, prober=probe):
    streams = [url for url in proposal["streams"] if isinstance(url, str)][:MAX_STREAMS]
    for url in streams:
        station = index.get(stream_key(url))
        if station:
            return {"status": "duplicate", "station": station}
    playing, errors = [], Counter()
    for url in streams:
        result = prober(url)
        if not result["ok"]:
            errors[result.get("error", "unknown")] += 1
            continue
        stream = {"url": url, "protocol": "hls" if result.get("hls") else "http"}
        if result.get("codec") in ("mp3", "aac", "he-aac", "he-aac-v2", "flac", "opus", "vorbis"):
            stream["codec"] = result["codec"]
        if isinstance(result.get("bitrate_kbps"), int) and 0 < result["bitrate_kbps"] <= 10000:
            stream["bitrate_kbps"] = result["bitrate_kbps"]
        playing.append(stream)
    if playing:
        return {"status": "published", "streams": playing}
    if set(errors) <= {"blocked_locally", "dns_resolver"}:
        return {"status": "pending"}  # The checker could not tell: try again later.
    error = errors.most_common(1)[0][0]
    return {"status": "rejected", "reason": REJECTIONS.get(error, "stream_unreachable")}


class _Connection(http.client.HTTPSConnection):
    """HTTPS to the API host, resolved over DNS-over-HTTPS like everything else, to a public address."""

    def connect(self):
        family, sockaddr = probe_module._public_addresses(self.host, self.port)[0]
        sock = socket.create_connection(sockaddr[:2], timeout=self.timeout)
        self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)


class Api:
    """Calls to the contribution API. Never follows a redirect: the token goes to the API host only."""

    def __init__(self, base, token):
        parts = urllib.parse.urlsplit(base)
        if parts.scheme != "https" or not parts.hostname:
            raise ValueError("the API must be reached over https")
        self.host, self.token = parts.hostname, token

    def call(self, method, path, body=None):
        connection = _Connection(self.host, 443, timeout=30)
        try:
            connection.request(method, path, body=None if body is None else json.dumps(body).encode(), headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "User-Agent": USER_AGENT})
            response = connection.getresponse()
            data = response.read(4 * 1024 * 1024)
        finally:
            connection.close()
        if response.status != 200:
            raise RuntimeError(f"API answered {response.status} on {path}")
        return json.loads(data)


def run(api, data, prober=probe):
    index = known_streams(data)
    decisions = Counter()
    for proposal in api.call("POST", "/v1/admin/station-proposals/claim")["proposals"]:
        decision = decide(proposal, index, prober)
        api.call("POST", f"/v1/admin/station-proposals/{proposal['id']}", decision)
        decisions[decision["status"]] += 1
    return dict(decisions)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", required=True)
    parser.add_argument("--token-file", type=Path, help="default: the systemd credential named token")
    parser.add_argument("--data", required=True, type=Path)
    args = parser.parse_args()
    if not args.api.startswith("https://"):
        sys.exit("the API must be reached over https")
    probe_module.RESOLVER = "doh"
    token_file = args.token_file or Path(os.environ.get("CREDENTIALS_DIRECTORY", "/nonexistent")) / "token"
    token = token_file.read_text(encoding="ascii").strip()
    print(json.dumps(run(Api(args.api, token), args.data)))


if __name__ == "__main__":
    main()
