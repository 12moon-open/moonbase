import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import build as b
from pipeline import now_playing as n

STATION = "st_" + "a" * 26
MERGED = "st_" + "b" * 26


def adapter(station=STATION, suffix="a"):
    return {"format": "12moon.now_playing/1", "id": "np_" + suffix * 26, "rev": 1, "status": "active",
            "station": station, "template": "nrj.livemeta/1", "params": {"site": "www.nrj.fr", "id": "1"},
            "updated_at": "2026-11-08T00:00:00Z"}


class NowPlayingTest(unittest.TestCase):
    def setUp(self):
        _, self.templates, _ = n.load()
        self.stations = {STATION: {"status": "active"}}

    def test_real_sources_are_valid(self):
        adapters, templates, blocked = n.load()
        n.prepare(adapters, templates, blocked, {}, [])  # Checked even when every station is unknown.

    def test_redirect_is_followed_and_missing_station_left_out(self):
        redirects = [{"from": MERGED, "to": STATION, "at": "2026-11-08T00:00:00Z"}]
        kept, _, _, report = n.prepare([adapter(MERGED), adapter("st_" + "c" * 26, "c")], self.templates, [],
                                       self.stations, redirects)
        self.assertEqual([a["station"] for a in kept], [STATION])
        self.assertEqual(report["adapters_left_out"], 1)

    def test_invalid_records_are_refused(self):
        unknown = dict(adapter(), template="none/1")
        extra = dict(adapter(), surprise=1)
        no_id = {k: v for k, v in adapter().items() if k != "id"}
        twice = [adapter(), adapter()]
        bad_host = [{"host": "1.2.3.4", "subdomains": False, "reason": "maintainer", "since": "2026-11-08"}]
        for adapters, blocked in (([unknown], []), ([extra], []), ([no_id], []), (twice, []), ([], bad_host)):
            with self.assertRaises(n.Invalid):
                n.prepare(adapters, self.templates, blocked, self.stations, [])

    def test_written_in_the_manifest(self):
        blocked = [{"host": "example.org", "subdomains": True, "reason": "station_request", "since": "2026-11-08"}]
        playing = n.prepare([adapter()], self.templates, blocked, self.stations, [])[:3]
        with tempfile.TemporaryDirectory() as tmp:
            out, dist = Path(tmp, "out"), Path(tmp, "dist")
            stations = {STATION: {"id": STATION, "status": "active", "country": "FR"}}
            manifest = b.write(stations, [], out, dist, "2026-11-08T00:00:00Z", None, playing)
            entries = {e["shard"]: e for e in manifest["datasets"]["now_playing"]}
            self.assertEqual(sorted(entries), ["adapters", "blocked-hosts", "templates"])
            self.assertEqual(entries["adapters"]["path"], "now-playing/adapters.ndjson.gz")
            lines = gzip.decompress((dist / "v1" / entries["blocked-hosts"]["path"]).read_bytes()).splitlines()
            self.assertEqual(json.loads(lines[0])["host"], "example.org")
            self.assertEqual(entries["templates"]["count"], len(self.templates))
            again = b.write(stations, [], out, dist, "2026-11-08T00:00:00Z", None, copy.deepcopy(playing))
            self.assertEqual(again["dataset_version"], manifest["dataset_version"])


if __name__ == "__main__":
    unittest.main()
