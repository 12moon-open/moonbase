#!/usr/bin/env python3
"""Publish the stream health written by the stream checker, after checking it.

Usage: moondata_health.py SOURCE_DIR WWW_HEALTH_DIR

SOURCE_DIR holds the checker's output (v1/health/XX.ndjson.gz and summary.json).
Each file is checked: its name, that it decompresses within limits, that every line
is a health record. A manifest with the sha256 of each file is written, the new
version is placed next to the previous ones, and WWW_HEALTH_DIR/current is switched
atomically. The last KEEP versions are kept. Nothing is published when a check fails.
"""
import gzip
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SHARD = re.compile(r"[A-Z]{2}\.ndjson\.gz")
STREAM = re.compile(r"sm_[0-9a-z]{26}")
STATES = {"ok", "failing", "dead", "unknown"}
MAX_FILE = 20 * 1024 * 1024
MAX_UNPACKED = 100 * 1024 * 1024
MIN_STREAMS = 30_000
KEEP = 5


class Refused(Exception):
    pass


def check_file(path):
    raw = path.read_bytes()
    if len(raw) > MAX_FILE:
        raise Refused(f"{path.name} too large")
    try:
        text = gzip.decompress(raw)
    except OSError as error:
        raise Refused(f"{path.name} is not gzip") from error
    if len(text) > MAX_UNPACKED:
        raise Refused(f"{path.name} unpacks too large")
    count = 0
    for line in text.decode("utf-8").splitlines():
        record = json.loads(line)
        if not isinstance(record, dict) or not STREAM.fullmatch(str(record.get("id"))) or record.get("state") not in STATES:
            raise Refused(f"{path.name}: invalid record")
        count += 1
    return {"shard": path.name.split(".")[0], "path": f"{path.name}", "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw), "count": count}


def publish(source, target, now=None):
    now = now or datetime.now(timezone.utc)
    folder = source / "v1" / "health"
    names = sorted(p.name for p in folder.iterdir() if p.is_file())
    unexpected = [n for n in names if not SHARD.fullmatch(n) and n != "summary.json"]
    if unexpected:
        raise Refused(f"unexpected files: {unexpected[:3]}")
    entries = [check_file(folder / n) for n in names if SHARD.fullmatch(n)]
    total = sum(e["count"] for e in entries)
    if total < MIN_STREAMS:
        raise Refused(f"only {total} streams")
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8")) if "summary.json" in names else {}
    checked = str(summary.get("checked_at", ""))
    manifest = {"contract": "1.0.0", "checked_at": checked if re.fullmatch(r"\d{4}-\d{2}-\d{2}", checked) else None,
                "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "license": "CC0-1.0", "files": entries}
    releases = target / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=releases, prefix=".incoming-"))
    try:
        for entry in entries:
            shutil.copyfile(folder / entry["path"], work / entry["path"])
        (work / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
        for path in work.iterdir():
            path.chmod(0o644)
        work.chmod(0o755)
        version = releases / now.strftime("%Y%m%dT%H%M%SZ")
        work.rename(version)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    link = target / "current.tmp"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(Path("releases") / version.name)
    os.replace(link, target / "current")
    for old in sorted(p for p in releases.iterdir() if not p.name.startswith("."))[:-KEEP]:
        shutil.rmtree(old)
    return f"published {version.name}: {total} streams in {len(entries)} files"


def main():
    try:
        print(publish(Path(sys.argv[1]), Path(sys.argv[2])))
    except (Refused, OSError, ValueError) as error:
        print(f"refused, keeping the current health: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
