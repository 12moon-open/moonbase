import unittest

from pipeline import build as b
from pipeline import wikidata as w
from tests.test_build import FIP, filler, row, AS_OF
import shutil
import tempfile
from pathlib import Path


def item(q, names, country="FR", websites=(), logo=None, wikipedia=None):
    out = {"q": q, "country": country, "names": list(names), "websites": list(websites)}
    if logo:
        out["logo"] = logo
    if wikipedia:
        out["wikipedia"] = wikipedia
    return out


class Matching(unittest.TestCase):
    def groups(self, rows):
        prepared, _ = b.prepare_rows(rows)
        from pipeline.group import group_rows
        return group_rows(prepared)

    def test_commons_thumbnail(self):
        self.assertEqual(w.commons_thumbnail("FIP logo 2021.svg"),
                         "https://upload.wikimedia.org/wikipedia/commons/thumb/1/16/FIP_logo_2021.svg/500px-FIP_logo_2021.svg.png")
        self.assertIsNone(w.commons_thumbnail("Sound.ogg"))

    def test_name_and_domain_is_sure(self):
        groups = self.groups(FIP + [row("x1", "FIP", "https://other.example.org/fip", country="BE")])
        items = [item("Q1", ["FIP"], websites=["https://www.radiofrance.fr/fip"])]
        found = w.match_groups(groups, items)
        matched = [groups[i] for i in found]
        self.assertEqual(len(matched), 1)
        self.assertEqual({r["country"] for r in matched[0]}, {"FR"})

    def test_two_items_with_the_name_and_no_domain_is_doubtful(self):
        groups = self.groups([row("y1", "Radio Uno", "https://a.example.org/x")])
        items = [item("Q1", ["Radio Uno"]), item("Q2", ["Radio Uno"])]
        self.assertEqual(w.match_groups(groups, items), {})

    def test_unique_name_without_contradiction(self):
        groups = self.groups([row("y1", "Radio Uno", "https://a.example.org/x")])
        self.assertEqual(len(w.match_groups(groups, [item("Q1", ["Radio Uno"])])), 1)
        homepage = self.groups([row("y1", "Radio Uno", "https://a.example.org/x", homepage="https://radio-uno.example.org/")])
        contradicted = [item("Q1", ["Radio Uno"], websites=["https://www.other-site.example.com/"])]
        self.assertEqual(w.match_groups(homepage, contradicted), {})

    def test_one_item_never_matches_two_stations(self):
        groups = self.groups([row("y1", "Radio Uno", "https://a.example.org/x"),
                              row("y2", "Radio Uno", "https://b.example.net/y")])
        self.assertEqual(w.match_groups(groups, [item("Q1", ["Radio Uno"])]), {})

    def test_main_name_wins_over_a_secondary_name(self):
        groups = self.groups(FIP + [row("g9", "FIP", "https://stream.radiofrance.fr/fipgroove/fipgroove.m3u8"),
                                    row("g8", "FIP Groove", "https://stream.radiofrance.fr/fipgroove/fipgroove.m3u8")])
        items = [item("Q1", ["FIP"], websites=["https://www.radiofrance.fr/fip"])]
        found = w.match_groups(groups, items)
        self.assertEqual(len(found), 1)
        [index] = found
        self.assertIn("FIP", {r["name"] for r in groups[index]})
        self.assertNotIn("FIP Groove", {r["name"] for r in groups[index]})

    def test_same_site_and_contained_name(self):
        groups = self.groups([row("k1", "KEXP 90.3 FM", "https://kexp.streamguys1.com/kexp160.aac", country="US",
                                  homepage="https://www.kexp.org/")])
        items = [item("Q761627", ["KEXP", "KCMU"], country="US", websites=["https://www.kexp.org/"]),
                 item("Q9", ["Other Radio"], country="US", websites=["https://www.kexp.org/other"])]
        found = w.match_groups(groups, items)
        self.assertEqual([i["q"] for i in found.values()], ["Q761627"])

    def test_call_sign_matches_and_adds_the_college_tag(self):
        groups = self.groups([row("w1", "WJCU 88.7 FM University Heights", "https://jcu.example.org/live", country="US"),
                              row("w2", "Kiss FM", "https://a.example.org/kiss", country="US"),
                              row("w3", "KISS 104", "https://b.example.org/kiss", country="US"),
                              row("w4", "Kiss Country", "https://c.example.org/kc", country="US")])
        items = [item("Q1", ["WJCU"], country="US", wikipedia={"en": "WJCU"}), item("Q2", ["KISS"], country="US")]
        items[0]["college"] = True
        found = w.match_groups(groups, items)
        self.assertEqual([i["q"] for i in found.values()], ["Q1"])  # KISS is a common word here
        record = w.enrich({"tags": ["rock"]}, items[0])
        self.assertEqual(record["tags"], ["college radio", "rock"])

    def test_other_country_never_matches(self):
        groups = self.groups([row("y1", "Radio Uno", "https://a.example.org/x", country="IT")])
        self.assertEqual(w.match_groups(groups, [item("Q1", ["Radio Uno"], country="FR")]), {})


class Enrich(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_build_adds_wikidata_facts(self):
        items = [item("Q1435613", ["FIP"], websites=["https://www.radiofrance.fr/fip"], logo="FIP logo 2021.svg",
                      wikipedia={"fr": "FIP", "en": "FIP (radio station)"})]
        b.build(FIP + filler(), self.tmp / "out", self.tmp / "dist", AS_OF, None, None, (), (), items)
        fip = [s for s in b.load_previous(self.tmp / "out")[0].values() if s["name"] == "FIP"][0]
        self.assertEqual(fip["ids"]["wikidata"], "Q1435613")
        self.assertEqual(fip["wikipedia"], {"en": "FIP (radio station)", "fr": "FIP"})
        self.assertTrue(fip["logo_url"].endswith("/500px-FIP_logo_2021.svg.png"))
        self.assertEqual(fip["homepage"], "https://www.radiofrance.fr/fip")
        self.assertEqual([s["source"] for s in fip["sources"]], ["radio-browser", "wikidata"])
