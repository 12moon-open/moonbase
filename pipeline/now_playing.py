"""The now_playing dataset: adapters, service templates and blocked hosts.

Sources: data/now-playing/adapters.json and blocked-hosts.json (reviewed by the
maintainer), contract/v1/now-playing/templates/*.json. Every record is checked
against its schema before anything is written. An adapter whose station was merged
follows the redirect; one whose station is gone or retired is left out, never
published pointing nowhere.
"""
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "contract" / "v1" / "schemas"
TEMPLATES = ROOT / "contract" / "v1" / "now-playing" / "templates"
DATA = ROOT / "data" / "now-playing"


class Invalid(ValueError):
    pass


def _validator(name):
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


def _check(validator, record, what):
    error = next(iter(validator.iter_errors(record)), None)
    if error is not None:
        raise Invalid(f"{what}: {error.message[:200]}")


def load(data=DATA, templates=TEMPLATES):
    adapters = json.loads((data / "adapters.json").read_text(encoding="utf-8"))["adapters"]
    blocked = json.loads((data / "blocked-hosts.json").read_text(encoding="utf-8"))["hosts"]
    items = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(templates.glob("*.json"))]
    return adapters, items, blocked


def prepare(adapters, templates, blocked, stations, redirects):
    """(adapters, templates, blocked, report): the records to publish, sorted, checked."""
    check_adapter, check_template = _validator("now-playing-adapter"), _validator("now-playing-template")
    check_blocked = _validator("now-playing-blocked-host")
    for template in templates:
        _check(check_template, template, f"template {template.get('id')}")
    known = {t["id"]: t for t in templates}
    if len(known) != len(templates):
        raise Invalid("two templates share an id")
    moved = {r["from"]: r["to"] for r in redirects}
    kept, left_out, ids = [], [], set()
    for adapter in adapters:
        _check(check_adapter, adapter, f"adapter {adapter.get('id')}")
        if "id" not in adapter or "status" not in adapter or "rev" not in adapter:
            raise Invalid(f"adapter for {adapter['station']}: id, rev and status are required to publish")
        if adapter["id"] in ids:
            raise Invalid(f"adapter id used twice: {adapter['id']}")
        ids.add(adapter["id"])
        if "template" in adapter and adapter["template"] not in known:
            raise Invalid(f"adapter {adapter['id']}: unknown template {adapter['template']}")
        station, seen = adapter["station"], set()
        while station in moved and station not in seen:
            seen.add(station)
            station = moved[station]
        if stations.get(station, {}).get("status") != "active":
            left_out.append(adapter["id"])
            continue
        kept.append({**adapter, "station": station})
    hosts = set()
    for entry in blocked:
        _check(check_blocked, entry, f"blocked host {entry.get('host')}")
        if entry["host"] in hosts:
            raise Invalid(f"blocked host listed twice: {entry['host']}")
        hosts.add(entry["host"])
    report = {"adapters": len(kept), "adapters_left_out": len(left_out), "templates": len(templates),
              "blocked_hosts": len(blocked)}
    return (sorted(kept, key=lambda a: a["id"]), sorted(templates, key=lambda t: t["id"]),
            sorted(blocked, key=lambda b: b["host"]), report)
