import hashlib
import importlib.util
import io
import json
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "moondata_sync", Path(__file__).resolve().parent.parent / "deploy" / "moondata_sync.py"
)
sync_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_module)


def release(version, stations=40_000, extra=None, tamper=False, drop_path=None):
    body = b"data"
    digest = hashlib.sha256(body).hexdigest()
    entry = {"shard": "FR", "path": "stations/FR.ndjson.gz", "sha256": digest, "bytes": 4, "count": stations}
    redirect = {"shard": "all", "path": "redirects.ndjson.gz", "sha256": digest, "bytes": 4, "count": 0}
    manifest = {"contract": "1.0.0", "dataset_version": version, "license": "CC0-1.0",
                "datasets": {"stations": [entry], "redirects": [redirect]}}
    files = {"v1/manifest.json": json.dumps(manifest).encode(),
             "v1/stations/FR.ndjson.gz": b"evil" if tamper else body,
             "v1/redirects.ndjson.gz": body}
    if drop_path:
        files.pop(drop_path)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for add in extra or []:
            add(tar)
    return buffer.getvalue()


def fetcher(archive, digest=None, calls=None):
    digest = digest or hashlib.sha256(archive).hexdigest()

    def fetch(name, limit):
        if calls is not None:
            calls.append(name)
        return archive if name == "dist.tar.gz" else f"{digest}  dist.tar.gz\n".encode()
    return fetch


def add_symlink(tar):
    info = tarfile.TarInfo("v1/link")
    info.type = tarfile.SYMTYPE
    info.linkname = "/srv/moondata/secrets/tunnel_token"
    tar.addfile(info)


def add_traversal(tar):
    info = tarfile.TarInfo("../../evil")
    info.size = 1
    tar.addfile(info, io.BytesIO(b"x"))


def add_outside(tar):
    info = tarfile.TarInfo("other/file")
    info.size = 1
    tar.addfile(info, io.BytesIO(b"x"))


def add_unlisted(tar):
    info = tarfile.TarInfo("v1/stations/XX.ndjson.gz")
    info.size = 1
    tar.addfile(info, io.BytesIO(b"x"))


def add_many_files(tar):
    for index in range(2_100):
        tar.addfile(tarfile.TarInfo(f"v1/many/{index}"), io.BytesIO(b""))


class Sync(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "releases").mkdir()

    def run_sync(self, archive, digest=None):
        return sync_module.sync(self.root, fetcher(archive, digest))

    def versions(self):
        return sorted(p.name for p in (self.root / "releases").iterdir() if not p.name.startswith("."))

    def current(self):
        return (self.root / "current").resolve().name

    def test_installs_and_switches(self):
        self.run_sync(release("2026-11-06.1"))
        self.assertEqual(self.current(), "2026-11-06.1")
        self.run_sync(release("2026-11-07.1"))
        self.assertEqual(self.current(), "2026-11-07.1")
        self.assertTrue((self.root / "current" / "v1" / "manifest.json").is_file())
        self.assertEqual((self.root / "releases/2026-11-07.1/v1/manifest.json").stat().st_mode & 0o777, 0o644)

    def test_same_version_changes_nothing(self):
        self.run_sync(release("2026-11-06.1"))
        self.assertIn("up to date", self.run_sync(release("2026-11-06.1")))

    def test_older_version_is_ignored(self):
        self.run_sync(release("2026-11-07.1"))
        self.run_sync(release("2026-11-06.1"))
        self.assertEqual(self.current(), "2026-11-07.1")

    def refused(self, archive, digest=None):
        self.run_sync(release("2026-11-06.1"))
        with self.assertRaises(sync_module.Refused):
            self.run_sync(archive, digest)
        self.assertEqual(self.current(), "2026-11-06.1")
        self.assertEqual(self.versions(), ["2026-11-06.1"])

    def test_bad_archive_checksum(self):
        self.refused(release("2026-11-07.1"), "0" * 64)

    def test_bad_file_checksum(self):
        self.refused(release("2026-11-07.1", tamper=True))

    def test_missing_file(self):
        self.refused(release("2026-11-07.1", drop_path="v1/redirects.ndjson.gz"))

    def test_too_few_stations(self):
        self.refused(release("2026-11-07.1", stations=20_000))

    def test_big_drop(self):
        self.run_sync(release("2026-11-06.1", stations=60_000))
        with self.assertRaises(sync_module.Refused):
            self.run_sync(release("2026-11-07.1", stations=40_000))

    def test_symlink(self):
        self.refused(release("2026-11-07.1", extra=[add_symlink]))

    def test_path_traversal(self):
        self.refused(release("2026-11-07.1", extra=[add_traversal]))

    def test_path_outside_v1(self):
        self.refused(release("2026-11-07.1", extra=[add_outside]))

    def test_unlisted_file(self):
        self.refused(release("2026-11-07.1", extra=[add_unlisted]))

    def test_bad_version_string(self):
        self.refused(release("../../etc"))

    def test_unchanged_archive_is_not_downloaded(self):
        archive = release("2026-11-06.1")
        self.run_sync(archive)
        calls = []
        result = sync_module.sync(self.root, fetcher(archive, calls=calls))
        self.assertEqual((result, calls), ("up to date: same archive", ["dist.tar.gz.sha256"]))

    def test_too_many_entries(self):
        self.refused(release("2026-11-07.1", extra=[add_many_files]))

    def test_version_with_trailing_newline(self):
        self.refused(release("2026-11-07.1\n"))

    def test_leftovers_are_removed(self):
        (self.root / "releases" / ".incoming-old").mkdir()
        self.run_sync(release("2026-11-06.1"))
        self.assertFalse((self.root / "releases" / ".incoming-old").exists())

    def test_keeps_seven_versions(self):
        for day in range(1, 11):
            self.run_sync(release(f"2026-11-{day:02}.1"))
        names = self.versions()
        self.assertEqual(len(names), 7)
        self.assertEqual(names[-1], "2026-11-10.1")
