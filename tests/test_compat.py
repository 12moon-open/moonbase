import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from check_contract_compat import check  # noqa: E402

SCHEMAS = ROOT / "contract" / "v1" / "schemas"


class Compat(unittest.TestCase):
    def changed(self, edit):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        new = tmp / "schemas"
        shutil.copytree(SCHEMAS, new)
        path = new / "station.schema.json"
        schema = json.loads(path.read_text())
        edit(schema)
        path.write_text(json.dumps(schema))
        return check(SCHEMAS, new)

    def test_same(self):
        self.assertEqual(check(SCHEMAS, SCHEMAS), [])

    def test_new_optional_field_passes(self):
        self.assertEqual(self.changed(lambda s: s["properties"].update(x={"type": "string"})), [])

    def test_removed_field_fails(self):
        self.assertTrue(self.changed(lambda s: s["properties"].pop("homepage")))

    def test_newly_required_fails(self):
        self.assertTrue(self.changed(lambda s: s["required"].append("homepage")))

    def test_removed_enum_value_fails(self):
        def edit(s):
            s["properties"]["sources"]["items"]["properties"]["source"]["enum"].remove("editor")
        self.assertTrue(self.changed(edit))
