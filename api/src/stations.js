import tagList from "../../contract/v1/tags.json" with { type: "json" };
import { randomId, sha256, bytesToHex } from "./encoding.js";

// Stations added by installations: validated here, checked by the stream checker,
// then published by the daily build under the source "contribution".

export const DAILY_STATIONS = 10;
export const DAILY_STATION_REPORTS = 20;
const DAY = 86400;
const CLAIM_SECONDS = 3600;
const TAGS = new Set(tagList.tags);
const FIELDS = new Set(["kind", "name", "country", "streams", "homepage", "logo_url", "place", "languages", "tags", "consent"]);
export const STATION_REPORT_REASONS = ["dead_stream", "wrong_info", "inappropriate", "not_a_station", "duplicate", "other"];
const PRIVATE_SUFFIXES = [".local", ".localhost", ".internal", ".lan", ".home", ".arpa"];

const isObject = (v) => v && typeof v === "object" && !Array.isArray(v);

/** True for a host that may be public. IP literals must be global unicast. */
export function publicHost(host) {
  host = (host || "").toLowerCase().replace(/\.$/, "");
  if (!host) return false;
  const v4 = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (v4) {
    const [a, b] = v4.slice(1).map(Number);
    if (v4.slice(1).some((n) => Number(n) > 255)) return false;
    return !(a === 0 || a === 10 || a === 127 || a >= 224 || (a === 100 && b >= 64 && b <= 127) ||
      (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) ||
      (a === 192 && b === 0) || (a === 198 && (b === 18 || b === 19)));
  }
  if (host.startsWith("[") || host.includes(":")) return false; // IPv6 literals: refused, too easy to get wrong.
  if (host === "localhost" || PRIVATE_SUFFIXES.some((s) => host.endsWith(s))) return false;
  const labels = host.split(".");
  return labels.length >= 2 && /^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$/.test(labels.at(-1));
}

/** A clean public http(s) address, or null. */
export function cleanUrl(raw) {
  if (typeof raw !== "string" || raw.length > 2000 || /\s/.test(raw)) return null;
  let url;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return null;
  if (!publicHost(url.hostname)) return null;
  url.hash = "";
  for (const key of [...url.searchParams.keys()]) {
    if (/^utm_/i.test(key) || ["fbclid", "gclid", "listenerid", "playsessionid", "uid", "userid"].includes(key.toLowerCase())) {
      url.searchParams.delete(key);
    }
  }
  return url.toString();
}

/** A name or a place: refused when it carries an address, an e-mail, a phone number or control characters. */
export function cleanText(raw, max) {
  if (typeof raw !== "string") return null;
  const text = raw.normalize("NFC").replace(/\s+/g, " ").trim();
  if (!text || text.length > max) return null;
  if (/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩]/.test(raw)) return null;
  if (/https?:|www\.|[a-z0-9-]+\.(?:com|net|org|fm|io|ly|me|info|xyz|ru|fr|de)\b\/?/i.test(text)) return null;
  if (/[^\s@]+@[^\s@]+\.[a-z]{2,}/i.test(text)) return null;
  if (/(?:\+|\b)\d[\d .()-]{7,}\d\b/.test(text) && (text.match(/\d/g) || []).length >= 9) return null;
  return text;
}

/** Mirrors contract/v1/schemas/station-proposal.schema.json. Returns { error } or { value }. */
export function validateStationAdd(body) {
  if (!isObject(body)) return { error: "body must be an object" };
  for (const key of Object.keys(body)) if (!FIELDS.has(key)) return { error: `unexpected field: ${key}` };
  if (body.kind !== "station_add") return { error: "unknown kind" };
  if (body.consent !== "CC0-1.0") return { error: "consent required" };
  const name = cleanText(body.name, 100);
  if (!name) return { error: "invalid name" };
  if (typeof body.country !== "string" || !/^[A-Z]{2}$/.test(body.country)) return { error: "invalid country" };
  if (!Array.isArray(body.streams) || body.streams.length < 1 || body.streams.length > 5) return { error: "invalid streams" };
  const streams = [];
  for (const s of body.streams) {
    if (!isObject(s) || Object.keys(s).some((k) => k !== "url")) return { error: "invalid stream entry" };
    const url = cleanUrl(s.url);
    if (!url) return { error: "invalid stream url" };
    if (!streams.includes(url)) streams.push(url);
  }
  const value = { name, country: body.country, streams };
  for (const key of ["homepage", "logo_url"]) {
    if (body[key] !== undefined) {
      const url = cleanUrl(body[key]);
      if (!url) return { error: `invalid ${key}` };
      value[key] = url;
    }
  }
  if (body.place !== undefined) {
    const place = body.place;
    if (!isObject(place) || Object.keys(place).some((k) => !["name", "wikidata", "lat", "lon"].includes(k))) return { error: "invalid place" };
    const out = {};
    if (place.wikidata !== undefined) {
      if (typeof place.wikidata !== "string" || !/^Q[1-9][0-9]{0,11}$/.test(place.wikidata)) return { error: "invalid place wikidata" };
      out.wikidata = place.wikidata;
    }
    if (place.name !== undefined) {
      out.name = cleanText(place.name, 100);
      if (!out.name) return { error: "invalid place name" };
    }
    if ((place.lat === undefined) !== (place.lon === undefined)) return { error: "lat and lon go together" };
    if (place.lat !== undefined) {
      const ok = (v, m) => typeof v === "number" && Number.isFinite(v) && Math.abs(v) <= m;
      if (!ok(place.lat, 90) || !ok(place.lon, 180) || (place.lat === 0 && place.lon === 0)) return { error: "invalid coordinates" };
      out.lat = Math.round(place.lat * 1e4) / 1e4;
      out.lon = Math.round(place.lon * 1e4) / 1e4;
    }
    if (Object.keys(out).length) value.place = out;
  }
  if (body.languages !== undefined) {
    if (!Array.isArray(body.languages) || body.languages.length > 5 || body.languages.some((l) => typeof l !== "string" || !/^[a-z]{2,3}$/.test(l))) {
      return { error: "invalid languages" };
    }
    value.languages = [...new Set(body.languages)].sort();
  }
  if (body.tags !== undefined) {
    if (!Array.isArray(body.tags) || body.tags.length > 10 || body.tags.some((t) => !TAGS.has(t))) return { error: "invalid tags" };
    value.tags = [...new Set(body.tags)].sort();
  }
  return { value };
}

function streamKey(url) {
  return decodeURIComponent(url.replace(/^https?:\/\//, "")).replace(/[/;]+$/, "");
}

export async function addStationProposal(db, contributorId, value, now) {
  const fingerprint = bytesToHex(await sha256(value.streams.map(streamKey).sort().join("\n"))).slice(0, 32);
  const existing = await db
    .prepare("SELECT id, status FROM station_proposals WHERE contributor_id = ? AND fingerprint = ?")
    .bind(contributorId, fingerprint)
    .first();
  if (existing) return { id: existing.id, status: existing.status, duplicate: true };
  const recent = await db
    .prepare("SELECT COUNT(*) AS n FROM station_proposals WHERE contributor_id = ? AND created_at > ?")
    .bind(contributorId, now - DAY)
    .first();
  if (recent.n >= DAILY_STATIONS) return { limited: true };
  const id = await randomId("pr_");
  await db
    .prepare(
      `INSERT INTO station_proposals (id, contributor_id, fingerprint, body, status, created_at, updated_at)
       VALUES (?, ?, ?, ?, 'pending', ?, ?)`,
    )
    .bind(id, contributorId, fingerprint, JSON.stringify(value), now, now)
    .run();
  return { id, status: "pending" };
}

export async function stationProposalStatus(db, id) {
  const row = await db.prepare("SELECT id, status, reason, station FROM station_proposals WHERE id = ?").bind(id).first();
  if (!row) return null;
  const out = { id: row.id, status: row.status === "verifying" ? "pending" : row.status };
  if (row.reason) out.reason = row.reason;
  if (row.station) out.station = row.station;
  return out;
}

export async function addStationReport(db, contributorId, body, now) {
  if (!isObject(body) || Object.keys(body).some((k) => k !== "station" && k !== "reason")) return { error: "unexpected field" };
  if (typeof body.station !== "string" || !/^st_[0-9a-z]{26}$/.test(body.station)) return { error: "invalid station" };
  if (!STATION_REPORT_REASONS.includes(body.reason)) return { error: "invalid reason" };
  const recent = await db
    .prepare("SELECT COUNT(*) AS n FROM station_reports WHERE contributor_id = ? AND created_at > ?")
    .bind(contributorId, now - DAY)
    .first();
  if (recent.n >= DAILY_STATION_REPORTS) return { limited: true };
  const id = await randomId("rp_");
  await db
    .prepare("INSERT INTO station_reports (id, station, contributor_id, reason, status, created_at) VALUES (?, ?, ?, ?, 'open', ?)")
    .bind(id, body.station, contributorId, body.reason, now)
    .run();
  return { id };
}

// --- For the stream checker and the maintainer, behind the admin token. ---

/** Hands out up to `limit` proposals to check. A claim left unanswered for an hour is handed out again. */
export async function claimStationProposals(db, now, limit = 20) {
  const { results } = await db
    .prepare(
      `SELECT id, body FROM station_proposals
       WHERE status = 'pending' OR (status = 'verifying' AND claimed_at < ?)
       ORDER BY created_at LIMIT ?`,
    )
    .bind(now - CLAIM_SECONDS, limit)
    .all();
  for (const row of results) {
    await db.prepare("UPDATE station_proposals SET status = 'verifying', claimed_at = ? WHERE id = ?").bind(now, row.id).run();
  }
  return results.map((row) => ({ id: row.id, ...JSON.parse(row.body) }));
}

const DECISIONS = new Set(["published", "duplicate", "rejected", "hidden", "revoked", "pending"]);
const REJECT_REASONS = new Set(["stream_unreachable", "not_audio", "private_address", "invalid_name", "not_a_station", "inappropriate", "other"]);

/** The checker's or the maintainer's decision on one proposal. */
export async function decideStationProposal(db, id, decision, now) {
  if (!isObject(decision) || !DECISIONS.has(decision.status)) return { error: "invalid status" };
  const row = await db.prepare("SELECT body FROM station_proposals WHERE id = ?").bind(id).first();
  if (!row) return { error: "unknown proposal" };
  let streams = null;
  if (decision.status === "published") {
    const sent = new Set(JSON.parse(row.body).streams);
    if (!Array.isArray(decision.streams) || !decision.streams.length) return { error: "streams required" };
    streams = [];
    for (const s of decision.streams) {
      if (!isObject(s) || !sent.has(s.url)) return { error: "unknown stream" };
      const out = { url: s.url, protocol: ["http", "hls", "dash"].includes(s.protocol) ? s.protocol : "http" };
      if (typeof s.codec === "string" && /^[a-z0-9-]{2,16}$/.test(s.codec)) out.codec = s.codec;
      if (Number.isInteger(s.bitrate_kbps) && s.bitrate_kbps > 0 && s.bitrate_kbps <= 10000) out.bitrate_kbps = s.bitrate_kbps;
      streams.push(out);
    }
  }
  if (decision.status === "duplicate" && !/^st_[0-9a-z]{26}$/.test(decision.station || "")) return { error: "station required" };
  if (decision.status === "rejected" && !REJECT_REASONS.has(decision.reason)) return { error: "invalid reason" };
  await db
    .prepare("UPDATE station_proposals SET status = ?, reason = ?, station = ?, streams = COALESCE(?, streams), updated_at = ? WHERE id = ?")
    .bind(decision.status, decision.reason || null, decision.station || null, streams && JSON.stringify(streams), now, id)
    .run();
  return { ok: true };
}

export async function listStationReports(db, status = "open") {
  const { results } = await db
    .prepare("SELECT id, station, reason, status, created_at FROM station_reports WHERE status = ? ORDER BY created_at LIMIT 500")
    .bind(status)
    .all();
  return results;
}

export async function decideStationReport(db, id, status) {
  if (!["accepted", "dismissed"].includes(status)) return { error: "invalid status" };
  const result = await db.prepare("UPDATE station_reports SET status = ? WHERE id = ?").bind(status, id).run();
  return result.meta.changes ? { ok: true } : { error: "unknown report" };
}

/** Lists proposals for the maintainer, with the contributor, to block one if needed. */
export async function listStationProposals(db, status) {
  const { results } = await db
    .prepare("SELECT id, contributor_id, status, reason, station, body, created_at FROM station_proposals WHERE status = ? ORDER BY created_at DESC LIMIT 500")
    .bind(status)
    .all();
  return results.map((r) => ({ ...r, body: JSON.parse(r.body) }));
}

/** Blocking a contributor hides every station it added. */
export async function hideStationsOf(db, contributorId, now) {
  await db
    .prepare("UPDATE station_proposals SET status = 'revoked', updated_at = ? WHERE contributor_id = ? AND status IN ('pending', 'verifying', 'published')")
    .bind(now, contributorId)
    .run();
}

/** Public export for the daily build: published stations, and those withdrawn since. No contributor. */
export async function exportStations(db, afterUpdated, afterId, limit) {
  const { results } = await db
    .prepare(
      `SELECT id, status, body, streams, updated_at FROM station_proposals
       WHERE status IN ('published', 'hidden', 'revoked') AND streams IS NOT NULL
         AND ((updated_at > ?) OR (updated_at = ? AND id > ?))
       ORDER BY updated_at, id LIMIT ?`,
    )
    .bind(afterUpdated, afterUpdated, afterId, limit)
    .all();
  return results.map((row) => {
    const body = JSON.parse(row.body);
    const out = { id: row.id, status: row.status === "published" ? "published" : "withdrawn",
      updated_at: new Date(row.updated_at * 1000).toISOString().replace(/\.\d{3}Z$/, "Z"),
      cursor: `${row.updated_at}.${row.id}` };
    if (out.status === "published") Object.assign(out, body, { streams: JSON.parse(row.streams) });
    return out;
  });
}
