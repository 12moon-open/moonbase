import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pipeline import build as b

AS_OF = "2026-11-06T12:00:00Z"
LATER = "2026-11-07T12:00:00Z"


def row(uuid, name, url, country="FR", homepage="", tags=""):
    return {"stationuuid": uuid, "name": name, "url_stream": url, "url_homepage": homepage,
            "url_favicon": "", "tags": tags, "iso_3166_1": country, "iso_3166_2": None,
            "iso_639": None, "geo_lat": None, "geo_long": None}


def filler(n=10_000):
    return [row(f"f{i:05}", f"Filler {i}", f"https://s{i}.example.net/live", "DE") for i in range(n)]


FIP = [
    row("a1", "FIP", "https://icecast.radiofrance.fr/fip-hifi.aac", tags="jazz,Music"),
    row("a2", "Fip", "http://icecast.radiofrance.fr/fip-hifi.aac?utm_source=x"),
    row("a3", "FIP (hifi.aac)", "https://stream.radiofrance.fr/fip/fip_hifi.m3u8"),
    row("a4", "FIP Groove", "https://icecast.radiofrance.fr/fipgroove-hifi.aac"),
]


class Build(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.out, self.dist = self.tmp / "data", self.tmp / "dist"

    def run_build(self, source, as_of=AS_OF):
        return b.build(source, self.out, self.dist, as_of)

    def stations(self):
        return b.load_previous(self.out)[0]

    def named(self, name):
        return [s for s in self.stations().values() if s["name"] == name]

    def test_one_station_many_streams(self):
        self.run_build(FIP + filler())
        fip = self.named("FIP")
        self.assertEqual(len(fip), 1)
        self.assertEqual(len(fip[0]["streams"]), 2)
        self.assertEqual(fip[0]["tags"], ["jazz"])
        self.assertEqual(len(self.named("FIP Groove")), 1)

    def test_mislabelled_row_does_not_merge_channels(self):
        self.run_build(FIP + [
            row("a5", "FIP", "https://stream.radiofrance.fr/fipgroove/fipgroove.m3u8"),
            row("a6", "FIP Groove", "https://stream.radiofrance.fr/fipgroove/fipgroove.m3u8"),
            row("a7", "FIP Groove", "https://direct.fipradio.fr/live/fipgroove-hifi.aac"),
        ] + filler())
        urls = [m["url"] for m in self.named("FIP")[0]["streams"]]
        self.assertEqual(len(self.named("FIP")), 1)
        self.assertFalse(any("groove" in u for u in urls))

    def test_same_channel_on_two_domains_is_one_station(self):
        self.run_build(FIP + [row("a8", "FIP", "https://direct.fipradio.fr/live/fip-hifi.aac")] + filler())
        self.assertEqual(len(self.named("FIP")), 1)
        self.assertEqual(len(self.named("FIP")[0]["streams"]), 3)

    def test_same_name_without_signal_stays_apart(self):
        self.run_build([row("b1", "Radio One", "https://a.example.org/x"),
                        row("b2", "Radio One", "https://b.example.com/y")] + filler())
        self.assertEqual(len(self.named("Radio One")), 2)

    def test_rebuild_is_byte_identical(self):
        source = FIP + filler()
        self.run_build(source)
        first = {p: p.read_bytes() for p in self.dist.rglob("*") if p.is_file()}
        self.run_build(source)
        self.assertEqual(first, {p: p.read_bytes() for p in self.dist.rglob("*") if p.is_file()})

    def test_unchanged_record_keeps_rev_on_later_build(self):
        source = FIP + filler()
        self.run_build(source)
        before = self.named("FIP")[0]
        self.run_build(source, LATER)
        self.assertEqual(self.named("FIP")[0], before)

    def test_removed_station_is_retired_not_deleted(self):
        self.run_build(FIP + filler())
        self.run_build(FIP[:3] + filler(), LATER)
        groove = self.named("FIP Groove")[0]
        self.assertEqual((groove["status"], groove["rev"]), ("retired", 2))

    def test_merge_leaves_a_redirect(self):
        one = row("c1", "Alpha", "https://a.example.org/x")
        two = row("c2", "Beta", "https://b.example.org/y")
        self.run_build([one, two] + filler())
        old = {s["name"]: s["id"] for s in self.stations().values()}
        self.run_build([one, {**two, "url_stream": "https://a.example.org/x"}] + filler(), LATER)
        redirects = b.load_previous(self.out)[1]
        self.assertEqual(len(redirects), 1)
        self.assertEqual({redirects[0]["from"], redirects[0]["to"]}, {old["Alpha"], old["Beta"]})

    def test_private_stream_is_refused(self):
        report = self.run_build([row("d1", "Evil", "http://192.168.1.1/")] + filler())
        self.assertEqual(report["refused"], {"stream": 1})

    def test_truncated_source_is_refused(self):
        with self.assertRaises(b.Refused):
            self.run_build(FIP)
        self.assertFalse(self.out.exists())

    def test_big_drop_is_refused_and_keeps_data(self):
        self.run_build(FIP + filler(20_000))
        with self.assertRaises(b.Refused):
            self.run_build(filler(10_000), LATER)
        self.assertEqual(sum(s["status"] == "active" for s in self.stations().values()), 20_002)

    def test_unknown_source_is_refused(self):
        self.run_build(FIP + filler())
        path = next((self.out / "v1" / "stations").glob("FR.ndjson"))
        records = [json.loads(l) for l in path.read_text().splitlines()]
        records[0]["sources"] = [{"source": "elsewhere", "retrieved_at": "2026-11-06"}]
        path.write_text("".join(json.dumps(r) + "\n" for r in records))
        with self.assertRaises(b.Refused):
            self.run_build(FIP + filler(), LATER)
