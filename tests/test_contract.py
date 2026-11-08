import json
import unittest
from pathlib import Path

from pipeline import normalize

try:
    import jsonschema
except ImportError:
    jsonschema = None

ROOT = Path(__file__).resolve().parent.parent / "contract" / "v1"


def cases(kind):
    return [(p.name, json.loads(p.read_text())) for p in sorted((ROOT / "cases" / kind).glob("*.json"))]


def validator(name):
    schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


class Normalize(unittest.TestCase):
    def test_cases(self):
        for name, case in cases("normalize"):
            with self.subTest(name):
                function = getattr(normalize, case["function"])
                self.assertEqual(function(case["input"]), case["expected"])


@unittest.skipIf(jsonschema is None, "jsonschema is not installed")
class Schemas(unittest.TestCase):
    def test_valid(self):
        for name, case in cases("valid"):
            with self.subTest(name):
                validator(case["schema"]).validate(case["input"])

    def test_invalid(self):
        for name, case in cases("invalid"):
            with self.subTest(name):
                self.assertFalse(validator(case["schema"]).is_valid(case["input"]))


@unittest.skipIf(jsonschema is None, "jsonschema is not installed")
class NowPlayingCases(unittest.TestCase):
    def test_case_adapters_follow_the_schema(self):
        check = validator("now-playing-adapter")
        for name, case in cases("now-playing"):
            with self.subTest(name):
                check.validate(case["adapter"])
                self.assertTrue("expected" in case and "response" in case and "now" in case)

    def test_templates_follow_the_schema(self):
        check = validator("now-playing-template")
        for path in sorted((ROOT / "now-playing" / "templates").glob("*.json")):
            with self.subTest(path.name):
                check.validate(json.loads(path.read_text()))
