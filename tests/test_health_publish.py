import gzip
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from deploy import moondata_health as h


def shard(folder, name, records):
    data = "".join(json.dumps(r) + "\n" for r in records).encode()
    (folder / name).write_bytes(gzip.compress(data))


class HealthPublish(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.source = self.tmp / "out" / "v1" / "health"
        self.source.mkdir(parents=True)
        self.www = self.tmp / "www" / "health"
        self.saved = h.MIN_STREAMS
        h.MIN_STREAMS = 2
        self.addCleanup(setattr, h, "MIN_STREAMS", self.saved)

    def record(self, n, state="ok"):
        return {"id": "sm_" + str(n).rjust(26, "a"), "state": state}

    def test_publishes_with_a_manifest_and_switches_atomically(self):
        shard(self.source, "FR.ndjson.gz", [self.record(1), self.record(2, "dead")])
        (self.source / "summary.json").write_text(json.dumps({"checked_at": "2026-11-08"}))
        h.publish(self.tmp / "out", self.www)
        manifest = json.loads((self.www / "current" / "manifest.json").read_text())
        self.assertEqual(manifest["checked_at"], "2026-11-08")
        self.assertEqual([(e["shard"], e["count"]) for e in manifest["files"]], [("FR", 2)])
        self.assertTrue((self.www / "current").is_symlink())

    def test_refuses_bad_records_and_unexpected_files(self):
        shard(self.source, "FR.ndjson.gz", [{"id": "../../etc", "state": "ok"}, self.record(2)])
        with self.assertRaises(h.Refused):
            h.publish(self.tmp / "out", self.www)
        shard(self.source, "FR.ndjson.gz", [self.record(1), self.record(2)])
        (self.source / "evil.html").write_text("<script>")
        with self.assertRaises(h.Refused):
            h.publish(self.tmp / "out", self.www)
        self.assertFalse((self.www / "current").exists())

    def test_refuses_too_few_streams(self):
        shard(self.source, "FR.ndjson.gz", [self.record(1)])
        with self.assertRaises(h.Refused):
            h.publish(self.tmp / "out", self.www)
