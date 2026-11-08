"""Check every stream of the dataset, then update the health of each stream.

Usage:
  python -m checker.run --data DATA_DIR --history HISTORY.json.gz --out HEALTH_DIR [--limit N]

DATA_DIR holds v1/stations/*.ndjson. HISTORY keeps the last results of each stream,
from one run to the next. HEALTH_DIR receives v1/health/XX.ndjson.gz, one file per
country like the stations, plus a summary.

A stream is declared dead only after failing on DEAD_DAYS distinct days in a row,
and comes back at its first success. Geo-blocking cannot be told apart from a
failure from one place: the state says "failing", never why it might be. A domain
blocked by the local resolver (an answer of 0.0.0.0) is not counted at all.
"""
import argparse
import gzip
import json
import random
import statistics
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .probe import probe

WORKERS = 64
PER_HOST = 2
KEEP_RUNS = 14
DEAD_DAYS = 3
# Errors caused by the checking machine itself, never counted against a stream.
LOCAL_ERRORS = {"blocked_locally"}
FIELDS = ("codec", "profile", "sample_rate", "channels", "bitrate_kbps", "container",
          "hls_variants_kbps", "now_playing", "video")


def load_streams(data):
    streams = []
    for path in sorted((data / "v1" / "stations").glob("*.ndjson")):
        shard = path.stem
        for line in path.open(encoding="utf-8"):
            station = json.loads(line)
            if station["status"] != "active":
                continue
            for stream in station["streams"]:
                streams.append({"id": stream["id"], "url": stream["url"], "shard": shard})
    return streams


def check_all(streams, workers=WORKERS, prober=probe):
    """Probes in a random order, at most PER_HOST at once on one host."""
    locks = defaultdict(lambda: threading.BoundedSemaphore(PER_HOST))
    guard = threading.Lock()

    def one(stream):
        host = urlsplit(stream["url"]).hostname or ""
        with guard:
            lock = locks[host]
        with lock:
            return stream, prober(stream["url"])

    order = list(streams)
    random.shuffle(order)
    results = {}
    with ThreadPoolExecutor(workers) as pool:
        for future in as_completed([pool.submit(one, s) for s in order]):
            stream, result = future.result()
            results[stream["id"]] = result
    return results


def update(history, streams, results, today):
    """Adds today's result to each stream's history and returns the health records."""
    records = {}
    for stream in streams:
        sid = stream["id"]
        past = history.get(sid, {"runs": []})
        result = results.get(sid)
        if result is not None and result.get("error") in LOCAL_ERRORS:
            result = None  # Says nothing about the stream: keep its previous state.
        if result is not None:
            run = {"day": today, "ok": result["ok"]}
            if result["ok"]:
                run.update({k: result[k] for k in FIELDS if k in result})
                run["ttfb_ms"] = result.get("ttfb_ms")
            else:
                run["error"] = result.get("error", "unknown")
            past["runs"] = (past["runs"] + [run])[-KEEP_RUNS:]
            if result["ok"]:
                past["last_ok"] = today
        history[sid] = past
        records[sid] = health(sid, past)
    for sid in set(history) - {s["id"] for s in streams}:
        del history[sid]  # Gone from the dataset: forget it.
    return records


def health(sid, past):
    runs = past["runs"]
    record = {"id": sid, "state": "unknown"}
    if not runs:
        return record
    last = runs[-1]
    record["checked_at"] = last["day"]
    if past.get("last_ok"):
        record["last_ok_at"] = past["last_ok"]
    failed_days = []
    for run in reversed(runs):
        if run["ok"]:
            break
        if run["day"] not in failed_days:
            failed_days.append(run["day"])
    if last["ok"]:
        record["state"] = "ok"
    elif len(failed_days) >= DEAD_DAYS:
        record["state"] = "dead"
    else:
        record["state"] = "failing"
    if not last["ok"]:
        record["error"] = last["error"]
    record["success_rate"] = round(sum(r["ok"] for r in runs) / len(runs), 2)
    good = [r for r in runs if r["ok"]]
    if good:
        latest = good[-1]
        for key in FIELDS:
            if key in latest:
                record[key] = latest[key]
        ttfb = [r["ttfb_ms"] for r in good if r.get("ttfb_ms") is not None]
        if ttfb:
            record["ttfb_ms_p50"] = round(statistics.median(ttfb))
    return record


def write(records, results, streams, out, today):
    shards = defaultdict(list)
    for stream in streams:
        shards[stream["shard"]].append(records[stream["id"]])
    target = out / "v1" / "health"
    target.mkdir(parents=True, exist_ok=True)
    for shard, items in shards.items():
        text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                       for r in sorted(items, key=lambda r: r["id"]))
        with gzip.GzipFile(target / f"{shard}.ndjson.gz", "wb", mtime=0) as handle:
            handle.write(text.encode())
    states = Counter(r["state"] for r in records.values())
    errors = Counter(r.get("error") for r in records.values() if r.get("error"))
    blocked = sum(1 for r in results.values() if r.get("error") in LOCAL_ERRORS)
    summary = {"checked_at": today, "streams": len(records), "states": dict(states),
               "errors": dict(errors.most_common()),
               "codecs": dict(Counter(r.get("codec") for r in records.values() if r["state"] == "ok").most_common()),
               "now_playing": sum(r.get("now_playing") == "icy" for r in records.values()),
               "blocked_locally": blocked}
    (target / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--history", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--limit", type=int, help="check only a random sample of this size")
    parser.add_argument("--workers", type=int, default=WORKERS)
    args = parser.parse_args()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    streams = load_streams(args.data)
    history = {}
    if args.history.exists():
        history = json.loads(gzip.decompress(args.history.read_bytes()))
    sample = random.sample(streams, args.limit) if args.limit else streams
    results = check_all(sample, args.workers)
    records = update(history, streams, results, today)
    with gzip.GzipFile(args.history, "wb", mtime=0) as handle:
        handle.write(json.dumps(history, sort_keys=True, separators=(",", ":")).encode())
    print(json.dumps(write(records, results, streams, args.out, today), indent=2))


if __name__ == "__main__":
    main()
