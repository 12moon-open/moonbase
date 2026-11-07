import { bytesToBase64url, bytesToHex } from "./encoding.js";

// Stream measures: what installations saw when playing published streams.
// Nothing stored identifies an installation or links the streams of one report.

export const MIN_REPORTS = 3; // A week counts for a stream only when this many installations measured it.
export const WINDOW_WEEKS = 4;
const KEEP_WEEKS = 8;
const FAILURES = new Set(["timeout", "http_error", "not_audio", "tls", "dns", "geo_blocked"]);
const STREAM = /^sm_[0-9a-z]{26}$/;
const WEEK = /^([0-9]{4})-W(0[1-9]|[1-4][0-9]|5[0-3])$/;
const CODEC = /^[a-z0-9-]{2,16}$/;
const DAY_MS = 86_400_000;

const int = (v, min, max) => Number.isInteger(v) && v >= min && v <= max;

/** Monday 00:00 UTC of an ISO week, in ms, or null when the week does not exist. */
export function weekStart(week) {
  const m = WEEK.exec(week);
  if (!m) return null;
  const year = Number(m[1]);
  const jan4 = Date.UTC(year, 0, 4);
  const monday1 = jan4 - ((new Date(jan4).getUTCDay() + 6) % 7) * DAY_MS;
  const start = monday1 + (Number(m[2]) - 1) * 7 * DAY_MS;
  return isoWeek(start) === week ? start : null;
}

/** ISO week of a time in ms, like 2026-W45. */
export function isoWeek(ms) {
  const date = new Date(ms);
  const day = (date.getUTCDay() + 6) % 7;
  const thursday = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() - day + 3);
  const year = new Date(thursday).getUTCFullYear();
  const week = 1 + Math.floor((thursday - Date.UTC(year, 0, 4)) / (7 * DAY_MS) + ((new Date(Date.UTC(year, 0, 4)).getUTCDay() + 6) % 7) / 7);
  return `${year}-W${String(week).padStart(2, "0")}`;
}

/** The finished weeks a report may cover: the last WINDOW_WEEKS before the current one. */
export function acceptedWeeks(nowSeconds) {
  const now = nowSeconds * 1000;
  return Array.from({ length: WINDOW_WEEKS }, (_, i) => isoWeek(now - (i + 1) * 7 * DAY_MS));
}

/** Mirrors contract/v1/schemas/stream-measures.schema.json, plus the sum of failures. */
export function validateMeasures(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return "body must be an object";
  for (const key of Object.keys(body)) if (!["kind", "week", "streams"].includes(key)) return `unexpected field: ${key}`;
  if (body.kind !== "stream_measures") return "unknown kind";
  if (typeof body.week !== "string" || weekStart(body.week) === null) return "invalid week";
  if (!Array.isArray(body.streams) || body.streams.length < 1 || body.streams.length > 200) return "invalid streams";
  const seen = new Set();
  for (const s of body.streams) {
    if (!s || typeof s !== "object" || Array.isArray(s)) return "invalid stream entry";
    for (const key of Object.keys(s)) {
      if (!["stream", "attempts", "failures", "startup_ms", "stalls", "codec", "bitrate_kbps"].includes(key)) return `unexpected field: ${key}`;
    }
    if (typeof s.stream !== "string" || !STREAM.test(s.stream)) return "invalid stream";
    if (seen.has(s.stream)) return "stream listed twice";
    seen.add(s.stream);
    if (!int(s.attempts, 1, 20)) return "invalid attempts";
    if (s.failures !== undefined) {
      if (!s.failures || typeof s.failures !== "object" || Array.isArray(s.failures)) return "invalid failures";
      let total = 0;
      for (const [reason, n] of Object.entries(s.failures)) {
        if (!FAILURES.has(reason)) return "unknown failure reason";
        if (!int(n, 0, 20)) return "invalid failure count";
        total += n;
      }
      if (total > s.attempts) return "more failures than attempts";
    }
    if (s.startup_ms !== undefined && !(int(s.startup_ms, 0, 60000) && s.startup_ms % 100 === 0)) return "invalid startup_ms";
    if (s.stalls !== undefined && !int(s.stalls, 0, 50)) return "invalid stalls";
    if (s.codec !== undefined && (typeof s.codec !== "string" || !CODEC.test(s.codec))) return "invalid codec";
    if (s.bitrate_kbps !== undefined && !int(s.bitrate_kbps, 1, 10000)) return "invalid bitrate_kbps";
  }
  return null;
}

function randomHex(bytes) {
  return bytesToHex(crypto.getRandomValues(new Uint8Array(bytes)));
}

async function weekSecret(db, week) {
  await db.prepare("INSERT OR IGNORE INTO measure_weeks (week, secret) VALUES (?, ?)").bind(week, randomHex(32)).run();
  return (await db.prepare("SELECT secret FROM measure_weeks WHERE week = ?").bind(week).first()).secret;
}

async function marker(secret, publicKey) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return bytesToBase64url(new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(publicKey))));
}

/** Stores one report. Returns { error }, { duplicate: true } or { accepted: n }. */
export async function addMeasures(db, publicKey, body, nowSeconds) {
  if (!acceptedWeeks(nowSeconds).includes(body.week)) return { error: "week not accepted" };
  const mark = await marker(await weekSecret(db, body.week), publicKey);
  const sender = await db.prepare("INSERT OR IGNORE INTO measure_senders (marker, week) VALUES (?, ?)").bind(mark, body.week).run();
  if (sender.meta.changes !== 1) return { duplicate: true };
  const rows = body.streams.map((s) => {
    const failures = s.failures || {};
    const geo = failures.geo_blocked || 0;
    const failed = Object.values(failures).reduce((a, b) => a + b, 0) - geo;
    const counted = s.attempts - geo;
    return db
      .prepare(
        `INSERT INTO stream_measures (stream, week, tie, success, startup_ms, stalls_per_play, geo_blocked, codec, bitrate_kbps)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .bind(
        s.stream, body.week, randomHex(8),
        counted > 0 ? (counted - failed) / counted : null,
        s.startup_ms ?? null,
        (s.stalls || 0) / s.attempts,
        geo > 0 ? 1 : 0,
        s.codec ?? null,
        s.bitrate_kbps ?? null,
      );
  });
  await db.batch(rows);
  return { accepted: rows.length };
}

function median(values) {
  const v = values.filter((x) => x !== null && x !== undefined).sort((a, b) => a - b);
  if (!v.length) return null;
  const mid = v.length >> 1;
  return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
}

/** A value at least MIN_REPORTS reports agree on, or null. */
function agreed(values) {
  const counts = new Map();
  for (const v of values) if (v !== null && v !== undefined) counts.set(v, (counts.get(v) || 0) + 1);
  const [value, n] = [...counts].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))[0] || [];
  return n >= MIN_REPORTS ? value : null;
}

function range(n) {
  return n >= 100 ? "100+" : n >= 10 ? "10+" : "3+";
}

/** Scores over the last WINDOW_WEEKS finished weeks, by stream id, after the cursor. */
export async function streamHealth(db, nowSeconds, after = "", limit = 1000) {
  const weeks = acceptedWeeks(nowSeconds);
  const marks = weeks.map(() => "?").join(", ");
  const qualifying = await db
    .prepare(
      `SELECT stream, week FROM stream_measures WHERE week IN (${marks}) AND stream > ?
       GROUP BY stream, week HAVING COUNT(*) >= ? ORDER BY stream`,
    )
    .bind(...weeks, after, MIN_REPORTS)
    .all();
  const byStream = new Map();
  for (const { stream, week } of qualifying.results) {
    if (!byStream.has(stream)) {
      if (byStream.size === limit) break;
      byStream.set(stream, []);
    }
    byStream.get(stream).push(week);
  }
  const scores = [];
  for (const [stream, streamWeeks] of byStream) {
    const rows = (
      await db
        .prepare(`SELECT * FROM stream_measures WHERE stream = ? AND week IN (${streamWeeks.map(() => "?").join(", ")})`)
        .bind(stream, ...streamWeeks)
        .all()
    ).results;
    const score = {
      id: stream,
      window: `${weeks.at(-1)}/${weeks[0]}`,
      reports: range(rows.length),
      geo_restricted: rows.filter((r) => r.geo_blocked).length >= MIN_REPORTS,
    };
    const success = median(rows.map((r) => r.success));
    if (success !== null) score.success_rate = Math.round(success * 100) / 100;
    const startup = median(rows.map((r) => r.startup_ms));
    if (startup !== null) score.startup_ms_p50 = Math.round(startup / 100) * 100;
    score.stalls_per_play = Math.round(median(rows.map((r) => r.stalls_per_play)) * 100) / 100;
    const codec = agreed(rows.map((r) => r.codec));
    if (codec) score.codec = codec;
    const bitrate = agreed(rows.map((r) => r.bitrate_kbps));
    if (bitrate) score.bitrate_kbps = bitrate;
    scores.push(score);
  }
  return scores;
}

/** Forgets old measures, and the week secrets and markers once no report can use them. */
export async function purgeMeasures(db, nowSeconds) {
  const oldest = isoWeek(nowSeconds * 1000 - KEEP_WEEKS * 7 * DAY_MS);
  const accepted = acceptedWeeks(nowSeconds);
  const keep = accepted.map(() => "?").join(", ");
  await db.batch([
    db.prepare("DELETE FROM stream_measures WHERE week < ?").bind(oldest),
    db.prepare(`DELETE FROM measure_senders WHERE week NOT IN (${keep})`).bind(...accepted),
    db.prepare(`DELETE FROM measure_weeks WHERE week NOT IN (${keep})`).bind(...accepted),
  ]);
}
