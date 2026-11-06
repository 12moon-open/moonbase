#!/usr/bin/env python3
"""Install the newest published dataset, after checking it. Standard library only.

Runs on the server, as an unprivileged user, and only ever pulls. A release is
installed only when its checksum, layout and contents are valid; otherwise the
service keeps serving the current version.
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("MOONDATA_ROOT", "/srv/moondata/www"))
BASE = "https://github.com/12moon-open/moondust/releases/latest/download/"
USER_AGENT = "moondata-sync/1.0 (+https://github.com/12moon-open/moonbase)"
ARCHIVE = "dist.tar.gz"
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_UNPACKED = 256 * 1024 * 1024
MAX_MEMBERS = 2000
MIN_STATIONS = 30_000
MIN_RATIO = 0.8
KEEP = 7
VERSION = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d{1,3}$")
ENTRY_PATH = re.compile(r"^(?:[a-z]+/)?[A-Za-z0-9_-]+\.ndjson\.gz$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Refused(Exception):
    """The release is not acceptable: nothing changes."""


def download(name, limit):
    request = urllib.request.Request(BASE + name, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise Refused(f"{name} is too large")
    return data


def unpack(archive, target):
    """Extract regular files under v1/ only."""
    total = 0
    members = []
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if len(members) >= MAX_MEMBERS:
                raise Refused("too many entries")
            parts = Path(member.name).parts
            if not (member.isdir() or member.isfile()):
                raise Refused(f"unexpected entry type: {member.name!r}")
            if not parts or parts[0] != "v1" or ".." in parts or member.name.startswith("/"):
                raise Refused(f"unexpected path: {member.name!r}")
            total += member.size
            if total > MAX_UNPACKED:
                raise Refused("archive unpacks too large")
            members.append(member)
        tar.extractall(target, members=members, filter="data")


def check(directory, current_version, current_count):
    try:
        manifest = json.loads((directory / "v1" / "manifest.json").read_text(encoding="utf-8"))
        version = manifest["dataset_version"]
        datasets = manifest["datasets"]
        entries = [e for group in datasets.values() for e in group]
        count = sum(e["count"] for e in datasets["stations"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Refused(f"invalid manifest: {error!r}") from error
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise Refused("invalid version")
    if manifest.get("license") != "CC0-1.0" or not str(manifest.get("contract", "")).startswith("1."):
        raise Refused("unexpected licence or contract")
    if current_version and version <= current_version:
        return None, 0
    if count < MIN_STATIONS or count < current_count * MIN_RATIO:
        raise Refused(f"only {count} stations")
    expected = {"manifest.json"}
    for entry in entries:
        path, digest = entry.get("path"), entry.get("sha256")
        if not isinstance(path, str) or not ENTRY_PATH.fullmatch(path) or not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise Refused(f"invalid manifest entry: {path!r}")
        file = directory / "v1" / path
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise Refused(f"checksum mismatch: {path}")
        expected.add(path)
    found = {str(p.relative_to(directory / "v1")) for p in (directory / "v1").rglob("*") if p.is_file()}
    if found != expected:
        raise Refused(f"files not in the manifest: {sorted(found - expected)[:3]}")
    return version, count


def current_state(root):
    link = root / "current"
    try:
        manifest = json.loads((link / "v1" / "manifest.json").read_text(encoding="utf-8"))
        return manifest["dataset_version"], sum(e["count"] for e in manifest["datasets"]["stations"])
    except (OSError, ValueError, KeyError, TypeError):
        return None, 0


def activate(root, version):
    temporary = root / "current.tmp"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(Path("releases") / version)
    os.replace(temporary, root / "current")


def prune(root, version):
    releases = sorted(
        p for p in (root / "releases").iterdir() if p.is_dir() and VERSION.fullmatch(p.name)
    )
    for old in [p for p in releases if p.name != version][: max(0, len(releases) - KEEP)]:
        shutil.rmtree(old)


def make_readable(directory):
    for path in [directory, *directory.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)


def sync(root=ROOT, fetch=download):
    archive_bytes = fetch(ARCHIVE, MAX_ARCHIVE)
    line = fetch(ARCHIVE + ".sha256", 256).decode("ascii", "replace").split()
    if not line or not SHA256.fullmatch(line[0]) or hashlib.sha256(archive_bytes).hexdigest() != line[0]:
        raise Refused("archive checksum mismatch")
    for stale in (root / "releases").glob(".incoming-*"):
        shutil.rmtree(stale, ignore_errors=True)
    current_version, current_count = current_state(root)
    with tempfile.TemporaryDirectory(dir=root / "releases", prefix=".incoming-") as work:
        work = Path(work)
        archive = work / ARCHIVE
        archive.write_bytes(archive_bytes)
        unpacked = work / "unpacked"
        unpacked.mkdir()
        unpack(archive, unpacked)
        version, count = check(unpacked, current_version, current_count)
        if version is None:
            return f"up to date: {current_version}"
        make_readable(unpacked)
        target = root / "releases" / version
        if target.exists():
            shutil.rmtree(target)
        unpacked.rename(target)
    activate(root, version)
    prune(root, version)
    return f"installed {version}: {count} stations"


def main():
    try:
        print(sync())
    except (Refused, OSError, tarfile.TarError) as error:
        print(f"refused, keeping the current version: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
