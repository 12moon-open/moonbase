"""Check a built dataset against the contract. Usage: validate_dataset.py DATA_DIR DIST_DIR"""
import gzip
import hashlib
import json
import sys
from pathlib import Path

import jsonschema

SCHEMAS = Path(__file__).resolve().parent.parent / "contract" / "v1" / "schemas"


def validator(name):
    return jsonschema.Draft202012Validator(json.loads((SCHEMAS / f"{name}.schema.json").read_text()))


def main():
    data, dist = Path(sys.argv[1]), Path(sys.argv[2])
    station, errors, count = validator("station"), 0, 0
    for path in sorted((data / "v1" / "stations").glob("*.ndjson")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                count += 1
                errors += not station.is_valid(json.loads(line))
    manifest = json.loads((dist / "v1" / "manifest.json").read_text())
    validator("manifest").validate(manifest)
    shards = {"adapters": "now-playing-adapter", "templates": "now-playing-template",
              "blocked-hosts": "now-playing-blocked-host"}
    for entry in manifest["datasets"].get("now_playing", []):
        check = validator(shards[entry["shard"]])
        lines = gzip.decompress((dist / "v1" / entry["path"]).read_bytes()).decode("utf-8").splitlines()
        errors += sum(not check.is_valid(json.loads(line)) for line in lines) + (len(lines) != entry["count"])
    for entries in manifest["datasets"].values():
        for entry in entries:
            digest = hashlib.sha256((dist / "v1" / entry["path"]).read_bytes()).hexdigest()
            errors += digest != entry["sha256"]
    print(f"{count} records, {errors} errors")
    sys.exit(1 if errors or not count else 0)


if __name__ == "__main__":
    main()
