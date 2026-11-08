"""Find two station records that broadcast the same sound.

Usage: python -m checker.fingerprint --data DATA_DIR --state STATE.json --out PROPOSALS.json [--limit N]

Only candidate pairs are compared, never every pair: active stations with the same
name in different records (in any country). For each pair, one stream of each is
captured at the same time for CAPTURE_SECONDS, fingerprinted with Chromaprint
(through ffmpeg) in memory, and the two fingerprints are slid against each other,
up to MAX_OFFSET_SECONDS, because two streams of one station are not in sync.

A pair needs ROUNDS answers taken at different hours of different days:
- every round matches: "same", proposed for a merge;
- some rounds match: "shared", a shared programme, never merged;
- no round matches: "different".
Nothing is kept but the verdicts and their dates: no audio, no fingerprint.
"""
import argparse
import gzip
import itertools
import json
import subprocess
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from pipeline.normalize import name_key

from . import probe as probe_module

CAPTURE_SECONDS = 60
MAX_CAPTURE_BYTES = 3 * 1024 * 1024
ITEMS_PER_SECOND = 1 / 0.1238  # Chromaprint gives one 32-bit item every 0.1238 s.
MAX_OFFSET_SECONDS = 40
MIN_OVERLAP_SECONDS = 20
SAME_SOUND = 0.65  # Share of identical bits above which two captures are the same sound.
ROUNDS = 3
MIN_HOURS_APART = 4


def fingerprint(audio, ffmpeg="ffmpeg"):
    """Raw Chromaprint fingerprint of some audio bytes, as a list of 32-bit integers."""
    try:
        result = subprocess.run(
            [ffmpeg, "-v", "error", "-protocol_whitelist", "pipe", "-i", "pipe:0", "-t", str(CAPTURE_SECONDS),
             "-f", "chromaprint", "-fp_format", "raw", "pipe:1"],
            input=audio, capture_output=True, timeout=120, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    data = result.stdout
    return [int.from_bytes(data[i:i + 4], "little") for i in range(0, len(data) - len(data) % 4, 4)]


def similarity(a, b, items_per_second=ITEMS_PER_SECOND):
    """Best share of identical bits between two fingerprints, over the allowed offsets."""
    max_offset = int(MAX_OFFSET_SECONDS * items_per_second)
    min_overlap = int(MIN_OVERLAP_SECONDS * items_per_second)
    best = 0.0
    for offset in range(-max_offset, max_offset + 1):
        pairs = zip(a[max(offset, 0):], b[max(-offset, 0):])
        same = total = 0
        for x, y in pairs:
            same += 32 - (x ^ y).bit_count()
            total += 32
        if total >= 32 * min_overlap:
            best = max(best, same / total)
    return best


def capture(url, allow_private=False, depth=0):
    """CAPTURE_SECONDS of audio bytes from a stream, or b"" when it cannot be read."""
    if depth == 0:
        probe_module._local.deadline = time.monotonic() + CAPTURE_SECONDS + 30
    try:
        final, response, body = probe_module._fetch(url, MAX_CAPTURE_BYTES, CAPTURE_SECONDS, allow_private)
        if body[:7] == b"#EXTM3U" or body[:10].lower().startswith(b"[playlist]"):
            return _capture_playlist(final, body[:probe_module.MAX_PLAYLIST], allow_private, depth) if depth < 2 else b""
        metaint = int(response.headers["icy-metaint"]) if response.headers.get("icy-metaint", "").isdigit() else 0
        return probe_module.strip_icy(body, metaint)
    except probe_module.Failure:
        return b""
    finally:
        if depth == 0:
            probe_module._local.deadline = None


def _capture_playlist(base, body, allow_private, depth):
    text = body.decode("utf-8", "replace")
    if text.lower().lstrip().startswith("[playlist]"):
        target = probe_module.parse_pls(text)
        return capture(target, allow_private, depth + 1) if target else b""
    kind, items = probe_module.parse_m3u(text, base)
    if kind == "master" and items:
        _, _, variant = min(items, key=lambda v: v[0] or 10**9)
        final, _, body = probe_module._fetch(variant, probe_module.MAX_PLAYLIST, None, allow_private)
        kind, items = probe_module.parse_m3u(body.decode("utf-8", "replace"), final)
    if kind == "list" and items:
        return capture(items[0], allow_private, depth + 1)
    audio = b""
    for segment in items[:20]:  # A live playlist lists the last 30 to 60 s.
        _, _, part = probe_module._fetch(segment, MAX_CAPTURE_BYTES - len(audio), None, allow_private)
        audio += part
        if len(audio) >= MAX_CAPTURE_BYTES:
            break
    return audio


def candidates(data):
    """Pairs of active station ids with the same name, and one stream url for each."""
    by_name = defaultdict(list)
    for path in sorted((data / "v1" / "stations").glob("*.ndjson.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                station = json.loads(line)
                key = name_key(station["name"])
                if station["status"] == "active" and key and station["streams"]:
                    by_name[key].append((station["id"], station["streams"][0]["url"]))
    pairs = []
    for members in by_name.values():
        if 2 <= len(members) <= 6:  # A name shared by many records is a generic label.
            pairs.extend(itertools.combinations(sorted(members), 2))
    return pairs


def compare(pair, capturer=capture, fingerprinter=fingerprint):
    """True, False, or None when one stream could not be heard."""
    (_, url_a), (_, url_b) = pair
    with ThreadPoolExecutor(2) as pool:  # At the same time: both streams are live.
        audio_a, audio_b = pool.map(capturer, (url_a, url_b))
    fp_a, fp_b = fingerprinter(audio_a), fingerprinter(audio_b)
    if len(fp_a) < 200 or len(fp_b) < 200:
        return None
    return similarity(fp_a, fp_b) >= SAME_SOUND


def verdict(rounds):
    answers = [r["same"] for r in rounds]
    if len(answers) < ROUNDS:
        return "pending"
    if all(answers):
        return "same"
    return "shared" if any(answers) else "different"


def due(rounds, now):
    """A pair is due when it has fewer than ROUNDS answers and the last is MIN_HOURS_APART old,
    on another day and at another hour of the day."""
    if len(rounds) >= ROUNDS:
        return False
    if not rounds:
        return True
    last = datetime.fromisoformat(rounds[-1]["at"])
    hours = {datetime.fromisoformat(r["at"]).hour // 6 for r in rounds}
    return (now - last).total_seconds() >= MIN_HOURS_APART * 3600 and now.date() != last.date() \
        and now.hour // 6 not in hours


def run(data, state, limit, workers=8, capturer=capture, fingerprinter=fingerprint, now=None):
    now = now or datetime.now(timezone.utc)
    lock = threading.Lock()
    todo = []
    for a, b in candidates(data):
        key = f"{a[0]}|{b[0]}"
        if due(state.get(key, []), now):
            todo.append((key, (a, b)))
    todo = todo[:limit]

    def one(item):
        key, pair = item
        same = compare(pair, capturer, fingerprinter)
        if same is not None:
            with lock:
                state.setdefault(key, []).append({"at": now.isoformat(timespec="minutes"), "same": same})

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(one, todo))
    return {key: verdict(rounds) for key, rounds in state.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    probe_module.RESOLVER = "doh"
    state = json.loads(args.state.read_text()) if args.state.exists() else {}
    started = time.monotonic()
    verdicts = run(args.data, state, args.limit, args.workers)
    args.state.write_text(json.dumps(state, sort_keys=True, indent=0))
    same = sorted(k.split("|") for k, v in verdicts.items() if v == "same")
    args.out.write_text(json.dumps({"same": same, "shared": sorted(k.split("|") for k, v in verdicts.items() if v == "shared")}, indent=1))
    counts = defaultdict(int)
    for v in verdicts.values():
        counts[v] += 1
    print(json.dumps({"pairs": len(verdicts), **counts, "seconds": round(time.monotonic() - started)}))


if __name__ == "__main__":
    main()
