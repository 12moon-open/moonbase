"""Fail when a schema change is not additive. Usage: check_contract_compat.py OLD_DIR NEW_DIR"""
import json
import sys
from pathlib import Path


def compare(old, new, path, errors):
    if not isinstance(old, dict) or not isinstance(new, dict):
        return
    for key in ("type", "const", "format"):
        if key in old and old.get(key) != new.get(key):
            errors.append(f"{path}: {key} changed")
    gained = set(new.get("required", [])) - set(old.get("required", []))
    if gained:
        errors.append(f"{path}: newly required {sorted(gained)}")
    if "enum" in old and not set(old["enum"]) <= set(new.get("enum", [])):
        errors.append(f"{path}: enum value removed")
    for key in ("pattern", "minLength", "maxLength", "minimum", "maximum", "minItems"):
        if key in new and old.get(key) != new[key]:
            errors.append(f"{path}: {key} tightened or changed")
    for name, schema in old.get("properties", {}).items():
        if name not in new.get("properties", {}):
            errors.append(f"{path}.{name}: removed")
        else:
            compare(schema, new["properties"][name], f"{path}.{name}", errors)
    for key in ("items", "additionalProperties"):
        if key in old:
            compare(old[key], new.get(key), f"{path}[{key}]", errors)


def check(old_dir, new_dir):
    errors = []
    for old_file in sorted(Path(old_dir).glob("*.schema.json")):
        new_file = Path(new_dir) / old_file.name
        if not new_file.exists():
            errors.append(f"{old_file.name}: removed")
            continue
        compare(json.loads(old_file.read_text()), json.loads(new_file.read_text()), old_file.stem, errors)
    return errors


if __name__ == "__main__":
    problems = check(sys.argv[1], sys.argv[2])
    print("\n".join(problems) or "Compatible.")
    sys.exit(1 if problems else 0)
