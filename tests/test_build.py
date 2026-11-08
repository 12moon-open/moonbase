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

    def run_build(self, source, as_of=AS_OF, checks=None):
        return b.build(source, self.out, self.dist, as_of, checks)

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

    def test_row_without_country_joins_its_only_country(self):
        self.run_build(FIP + [row("a9", "FIP", "http://icecast.radiofrance.fr/fip-midfi.mp3", country="")] + filler())
        fip = self.named("FIP")
        self.assertEqual(len(fip), 1)
        self.assertEqual(fip[0]["country"], "FR")
        self.assertEqual(len(fip[0]["streams"]), 3)

    def test_row_without_country_stays_apart_when_two_countries_share_the_name(self):
        self.run_build([
            row("c1", "Radio Uno", "https://a.example.org/uno/uno.mp3", country="IT"),
            row("c2", "Radio Uno", "https://b.example.org/uno/uno.mp3", country="ES"),
            row("c3", "Radio Uno", "https://c.example.org/uno/uno.mp3", country=""),
        ] + filler())
        self.assertEqual(len(self.named("Radio Uno")), 3)

    def test_wikimedia_logo_gets_a_served_width(self):
        source = FIP + filler()
        source[0] = {**source[0], "url_favicon":
                     "https://upload.wikimedia.org/wikipedia/fr/thumb/d/d5/F.svg/1024px-F.svg.png"}
        self.run_build(source)
        self.assertTrue(self.named("FIP")[0]["logo_url"].endswith("/1280px-F.svg.png"))

    def test_same_name_and_domain_is_one_station(self):
        self.run_build([row("d1", "Radio Max", "https://streams.radiomax.de/live/mp3-192"),
                        row("d2", "Radio Max", "https://cdn.radiomax.de/max/aac-64")] + filler())
        self.assertEqual(len(self.named("Radio Max")), 1)

    def test_same_domain_with_other_channels_stays_apart(self):
        self.run_build([row("e1", "SomaFM Black Rock FM", "https://somafm.com/brfm64.pls", country="US"),
                        row("e2", "SomaFM Black Rock FM", "https://somafm.com/beatblender130.pls", country="US")] + filler())
        self.assertEqual(len(self.named("SomaFM Black Rock FM")), 2)

    def test_encoded_url_is_the_same_stream(self):
        self.run_build([row("g1", "BBC Radio 6 Music", "http://x.akamaized.net/6music/bbc_6music-audio=320000.m3u8", country="GB"),
                        row("g2", "BBC Radio 6 Music", "http://x.akamaized.net/6music/bbc_6music-audio%3d320000.m3u8", country="GB")]
                       + filler())
        six = self.named("BBC Radio 6 Music")
        self.assertEqual(len(six), 1)
        self.assertEqual(len(six[0]["streams"]), 1)

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

    def test_merge_keeps_the_id_of_the_biggest_record(self):
        self.run_build(FIP + filler())
        fip_id = self.named("FIP")[0]["id"]
        self.run_build(FIP + [row("a0", "FIP", "http://icecast.radiofrance.fr/fip-midfi.mp3", country="BE")] + filler(), LATER)
        lone = [s for s in self.stations().values() if s["name"] == "FIP" and s.get("country") == "BE"][0]
        self.run_build(FIP + [row("a0", "FIP", "http://icecast.radiofrance.fr/fip-midfi.mp3", country="")] + filler(),
                       "2026-11-08T12:00:00Z")
        redirects = b.load_previous(self.out)[1]
        self.assertEqual(redirects, [{"from": lone["id"], "to": fip_id, "at": "2026-11-08"}])
        self.assertEqual([s["id"] for s in self.named("FIP") if s["status"] == "active"], [fip_id])

    def test_split_station_loses_no_stream(self):
        one = row("h1", "Radio Hm", "https://a.example.org/live")
        two = row("h2", "Radio Hm", "https://a.example.org/stream")
        self.run_build([one, two] + filler())
        self.assertEqual(len(self.named("Radio Hm")), 1)
        # h2's stream now also carries another name: h2 leaves, and the group sorted first
        # takes the old id. The old id was derived from h1, which must not get it back.
        self.run_build([one, two, row("a0", "Other", "https://a.example.org/stream")] + filler(), LATER)
        urls = sorted(m["url"] for s in self.stations().values() if s["status"] == "active"
                      for m in s["streams"] if "a.example.org" in m["url"])
        self.assertEqual(urls, ["https://a.example.org/live", "https://a.example.org/stream"])
        ids = [s["id"] for s in self.stations().values()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_checker_measures_fill_codec_and_bitrate(self):
        checks = b.read_checks([
            {"stationuuid": "a1", "codec": "AAC+", "bitrate": 48, "hls": 0, "lastcheckok": 1},
            {"stationuuid": "a3", "codec": "AAC", "bitrate": 192, "hls": 1, "lastcheckok": 1},
            {"stationuuid": "a4", "codec": "MP3", "bitrate": 128, "hls": 0, "lastcheckok": 0},
        ])
        self.run_build(FIP + filler(), checks=checks)
        streams = {m["url"]: m for m in self.named("FIP")[0]["streams"]}
        aac = streams["https://icecast.radiofrance.fr/fip-hifi.aac"]
        self.assertEqual((aac["codec"], aac["bitrate_kbps"]), ("he-aac", 48))
        hls = streams["https://stream.radiofrance.fr/fip/fip_hifi.m3u8"]
        self.assertEqual((hls["codec"], hls["bitrate_kbps"], hls["protocol"]), ("aac", 192, "hls"))
        groove = self.named("FIP Groove")[0]["streams"][0]
        self.assertNotIn("codec", groove)  # failed check: nothing published

    def test_unknown_codecs_are_left_out(self):
        checks = b.read_checks([
            {"stationuuid": "a1", "codec": "OGG", "bitrate": 0, "hls": 0, "lastcheckok": 1},
            {"stationuuid": "a3", "codec": "AAC,H.264", "bitrate": 99999, "hls": 0, "lastcheckok": 1},
        ])
        self.run_build(FIP + filler(), checks=checks)
        for stream in self.named("FIP")[0]["streams"]:
            self.assertNotIn("codec", stream)
            self.assertNotIn("bitrate_kbps", stream)

    def test_measures_are_kept_when_not_fetched(self):
        checks = b.read_checks([{"stationuuid": "a1", "codec": "MP3", "bitrate": 128, "hls": 0, "lastcheckok": 1}])
        self.run_build(FIP + filler(), checks=checks)
        before = self.named("FIP")[0]
        self.run_build(FIP + filler(), LATER)
        after = self.named("FIP")[0]
        self.assertEqual(after["streams"], before["streams"])
        self.assertEqual(after["rev"], before["rev"])

    def contribution(self, status="published", stream="https://stream.example.fr/live.mp3", pid="pr_" + "a" * 26):
        return {"id": pid, "status": status, "name": "Radio Exemple", "country": "FR",
                "place": {"name": "Bordeaux", "lat": 44.8378, "lon": -0.5792}, "tags": ["jazz"],
                "streams": [{"url": stream, "protocol": "http", "codec": "mp3", "bitrate_kbps": 128}]}

    def test_published_contribution_becomes_a_station(self):
        b.build(FIP + filler(), self.out, self.dist, AS_OF, None, None, [self.contribution()])
        [station] = self.named("Radio Exemple")
        self.assertEqual([x["source"] for x in station["sources"]], ["contribution"])
        self.assertEqual(station["ids"], {"contributions": ["pr_" + "a" * 26]})
        self.assertEqual(station["place"], {"name": "Bordeaux", "lat": 44.8378, "lon": -0.5792, "scope": "reported"})
        self.assertEqual(station["streams"][0]["codec"], "mp3")
        self.assertEqual(station["tags"], ["jazz"])

    def test_contribution_of_a_known_stream_joins_the_station(self):
        known = self.contribution(stream="https://icecast.radiofrance.fr/fip-hifi.aac")
        known["name"] = "FIP"
        b.build(FIP + filler(), self.out, self.dist, AS_OF, None, None, [known])
        [fip] = self.named("FIP")
        self.assertEqual([x["source"] for x in fip["sources"]], ["contribution", "radio-browser"])
        self.assertIn("contributions", fip["ids"])

    def test_withdrawn_contribution_is_retired(self):
        b.build(FIP + filler(), self.out, self.dist, AS_OF, None, None, [self.contribution()])
        b.build(FIP + filler(), self.out, self.dist, LATER, None, None, [self.contribution(status="withdrawn")])
        [station] = self.named("Radio Exemple")
        self.assertEqual(station["status"], "retired")

    def test_confirmed_pair_is_merged_with_a_redirect(self):
        rows = FIP + [row("z1", "Radio Zed", "https://a.example.org/alpha"), row("z2", "Radio Zed", "https://b.example.net/beta")] + filler()
        self.run_build(rows)
        ids = sorted(s["id"] for s in self.named("Radio Zed"))
        self.assertEqual(len(ids), 2)
        b.build(rows, self.out, self.dist, LATER, None, None, (), [ids])
        active = [s for s in self.named("Radio Zed") if s["status"] == "active"]
        self.assertEqual(len(active), 1)
        self.assertEqual(len(active[0]["streams"]), 2)
        self.assertEqual(len(b.load_previous(self.out)[1]), 1)

    def test_editor_corrections(self):
        rows = FIP + [row("e1", "Radio Squat", "https://squat.example.org/live", homepage="https://squat.example.org/"),
                      row("e2", "Radio Index", "https://idx.example.net/live", homepage="https://you.radio/station/x"),
                      row("e3", "TV Channel", "https://tv.example.org/live")] + filler()
        self.run_build(rows)
        ids = {s["name"]: s["id"] for s in self.stations().values()}
        editor = {"aggregator_homepages": ["you.radio"], "stations": {
            ids["Radio Squat"]: {"homepage": None},
            ids["FIP"]: {"homepage": "https://www.radiofrance.fr/fip", "add_streams": ["https://extra.radiofrance.fr/fip.mp3"]},
            ids["TV Channel"]: {"retire": True}}}
        b.build(rows, self.out, self.dist, LATER, None, None, (), (), (), editor)
        st = {s["name"]: s for s in self.stations().values()}
        self.assertNotIn("homepage", st["Radio Squat"])
        self.assertEqual(st["Radio Squat"]["status"], "active")  # a dead site never retires a station
        self.assertNotIn("homepage", st["Radio Index"])
        self.assertEqual(st["FIP"]["homepage"], "https://www.radiofrance.fr/fip")
        self.assertIn("https://extra.radiofrance.fr/fip.mp3", [m["url"] for m in st["FIP"]["streams"]])
        self.assertEqual([x["source"] for x in st["FIP"]["sources"]], ["editor", "radio-browser"])
        self.assertEqual(st["TV Channel"]["status"], "retired")

    def version(self):
        return json.loads((self.dist / "v1" / "manifest.json").read_text())["dataset_version"]

    def test_version_moves_only_when_the_content_changes(self):
        b.build(FIP + filler(), self.out, self.dist, AS_OF, None, "2026-11-08")
        self.assertEqual(self.version(), "2026-11-08.1")
        b.build(FIP + filler(), self.out, self.dist, AS_OF, None, "2026-11-08")
        self.assertEqual(self.version(), "2026-11-08.1")
        b.build(FIP[:3] + filler(), self.out, self.dist, AS_OF, None, "2026-11-08")
        self.assertEqual(self.version(), "2026-11-08.2")
        b.build(FIP + filler(), self.out, self.dist, AS_OF, None, "2026-11-09")
        self.assertEqual(self.version(), "2026-11-09.1")

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
        groove = next(r for r in records if r["name"] == "FIP Groove")
        groove["sources"] = [{"source": "elsewhere", "retrieved_at": "2026-11-06"}]
        path.write_text("".join(json.dumps(r) + "\n" for r in records))
        # FIP Groove leaves the source: its record is kept as retired, with its sources.
        with self.assertRaises(b.Refused):
            self.run_build(FIP[:3] + filler(), LATER)


class FetchContributions(unittest.TestCase):
    def test_reads_every_page_and_keeps_the_latest_state(self):
        from pipeline.fetch_contributions import fetch_all
        pages = {
            "": {"stations": [{"id": "pr_b", "status": "published"}, {"id": "pr_a", "status": "published"}], "next": "5.pr_a"},
            "5.pr_a": {"stations": [{"id": "pr_b", "status": "withdrawn"}], "next": None},
        }
        seen = []

        def get(url):
            seen.append(url)
            after = url.split("after=")[1].replace("%2E", ".") if "after=" in url else ""
            return pages[after]

        items = fetch_all("https://api.example.org", get)
        self.assertEqual(items, [{"id": "pr_a", "status": "published"}, {"id": "pr_b", "status": "withdrawn"}])
        self.assertEqual(len(seen), 2)


class Fetch(unittest.TestCase):
    def test_picks_the_newest_export(self):
        from pipeline.fetch import latest_name
        html = '<a href="radiobrowser_stations_20261105_014528.json.gz">x</a> radiobrowser_stations_20261106_122303.json.gz'
        self.assertEqual(latest_name(html), "radiobrowser_stations_20261106_122303.json.gz")
