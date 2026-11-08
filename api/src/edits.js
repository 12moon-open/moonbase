import tagList from "../../contract/v1/tags.json" with { type: "json" };
import { bytesToBase64url, bytesToHex, randomId, sha256 } from "./encoding.js";
import { cleanText, cleanUrl, validateStationAdd } from "./stations.js";

// Editing stations, for the maintainer and the agents he trusts. Each editor has its
// own token; only its hash is kept. Every edit is recorded with its author, and the
// daily build applies the accepted ones.

export const ROLES = new Set(["maintainer", "agent"]);
export const DAILY_EDITS = { maintainer: 5000, agent: 1000 };
const DAILY_NEW_STATIONS = 200;
const TAGS = new Set(tagList.tags);
const DATA = "https://data.12moon.app/v1/";
const SET_FIELDS = new Set(["name", "homepage", "logo_url", "country", "place", "languages", "tags"]);
const EDIT_FIELDS = new Set(["station", "set", "add_streams", "remove_streams", "retire", "same_as", "note", "source"]);
// An agent's edit that removes something waits for the maintainer.
const NEEDS_REVIEW = ["remove_streams", "retire", "same_as"];
const STATION = /^st_[0-9a-z]{26}$/;
const STREAM = /^sm_[0-9a-z]{26}$/;
const isObject = (v) => v && typeof v === "object" && !Array.isArray(v);

// --- Tokens ---

export async function hashToken(token) {
  return bytesToHex(await sha256(`12moon-editor\n${token}`));
}

/** The editor behind a bearer token, or null. */
export async function editorOf(db, token, now) {
  if (typeof token !== "string" || !/^12m_[A-Za-z0-9_-]{43}$/.test(token)) return null;
  const row = await db.prepare("SELECT id, name, role FROM editors WHERE token_hash = ? AND revoked_at IS NULL")
    .bind(await hashToken(token)).first();
  if (!row) return null;
  await db.prepare("UPDATE editors SET last_used_at = ? WHERE id = ? AND (last_used_at IS NULL OR last_used_at < ?)")
    .bind(now, row.id, now - 300).run();
  return row;
}

/** A new editor. The token is shown once and never stored. */
export async function createEditor(db, body, now) {
  const name = isObject(body) && cleanText(body.name, 60);
  if (!name) return { error: "invalid name" };
  if (!ROLES.has(body.role)) return { error: "invalid role" };
  const token = "12m_" + bytesToBase64url(crypto.getRandomValues(new Uint8Array(32)));
  const id = await randomId("ed_");
  try {
    await db.prepare("INSERT INTO editors (id, name, role, token_hash, created_at) VALUES (?, ?, ?, ?, ?)")
      .bind(id, name, body.role, await hashToken(token), now).run();
  } catch {
    return { error: "name already used" };
  }
  return { id, name, role: body.role, token };
}

export async function listEditors(db) {
  const { results } = await db.prepare(
    "SELECT id, name, role, created_at, last_used_at, revoked_at FROM editors ORDER BY created_at").all();
  return results;
}

export async function revokeEditor(db, id, now) {
  const result = await db.prepare("UPDATE editors SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL").bind(now, id).run();
  return result.meta.changes ? { ok: true } : { error: "unknown editor" };
}

// --- Edits ---

function cleanPlace(place) {
  if (place === null) return { value: null };
  if (!isObject(place) || Object.keys(place).some((k) => !["name", "lat", "lon"].includes(k))) return { error: "invalid place" };
  const checked = validateStationAdd({ kind: "station_add", consent: "CC0-1.0", name: "x", country: "FR",
    streams: [{ url: "https://example.org/" }], place });
  return checked.error ? { error: checked.error } : { value: checked.value.place || null };
}

/** Returns { error } or { value, review }: value is what the build will apply. */
export function validateEdit(body, role) {
  if (!isObject(body)) return { error: "body must be an object" };
  for (const key of Object.keys(body)) if (!EDIT_FIELDS.has(key)) return { error: `unexpected field: ${key}` };
  if (!STATION.test(body.station || "")) return { error: "invalid station" };
  const value = {};
  if (body.set !== undefined) {
    if (!isObject(body.set)) return { error: "set must be an object" };
    const set = {};
    for (const [key, raw] of Object.entries(body.set)) {
      if (!SET_FIELDS.has(key)) return { error: `cannot set: ${key}` };
      if (key === "name") {
        set.name = cleanText(raw, 200);
        if (!set.name) return { error: "invalid name" };
      } else if (key === "homepage" || key === "logo_url") {
        set[key] = raw === null ? null : cleanUrl(raw);
        if (set[key] === null && raw !== null) return { error: `invalid ${key}` };
      } else if (key === "country") {
        if (typeof raw !== "string" || !/^[A-Z]{2}$/.test(raw)) return { error: "invalid country" };
        set.country = raw;
      } else if (key === "place") {
        const place = cleanPlace(raw);
        if (place.error) return place;
        set.place = place.value;
      } else if (key === "languages") {
        if (!Array.isArray(raw) || raw.length > 5 || raw.some((l) => typeof l !== "string" || !/^[a-z]{2,3}$/.test(l))) {
          return { error: "invalid languages" };
        }
        set.languages = [...new Set(raw)].sort();
      } else if (key === "tags") {
        if (!Array.isArray(raw) || raw.length > 10 || raw.some((t) => !TAGS.has(t))) return { error: "invalid tags" };
        set.tags = [...new Set(raw)].sort();
      }
    }
    if (Object.keys(set).length) value.set = set;
  }
  if (body.add_streams !== undefined) {
    if (!Array.isArray(body.add_streams) || body.add_streams.length > 5) return { error: "invalid add_streams" };
    const urls = body.add_streams.map(cleanUrl);
    if (urls.some((u) => !u)) return { error: "invalid stream url" };
    if (urls.length) value.add_streams = [...new Set(urls)];
  }
  if (body.remove_streams !== undefined) {
    if (!Array.isArray(body.remove_streams) || body.remove_streams.length > 20 || body.remove_streams.some((s) => !STREAM.test(s))) {
      return { error: "invalid remove_streams" };
    }
    if (body.remove_streams.length) value.remove_streams = [...new Set(body.remove_streams)].sort();
  }
  if (body.retire !== undefined) {
    if (body.retire !== true) return { error: "retire must be true" };
    value.retire = true;
  }
  if (body.same_as !== undefined) {
    if (!STATION.test(body.same_as) || body.same_as === body.station) return { error: "invalid same_as" };
    value.same_as = body.same_as;
  }
  if (!Object.keys(value).length) return { error: "nothing to change" };
  let note = null;
  if (body.note !== undefined) {
    if (typeof body.note !== "string" || body.note.length > 1000 || /[\u0000-\u0008\u000b-\u001f\u007f]/.test(body.note)) {
      return { error: "invalid note" };
    }
    note = body.note.trim() || null;
  }
  let source = null;
  if (body.source !== undefined) {
    source = cleanUrl(body.source);
    if (!source) return { error: "invalid source" };
  }
  const review = role !== "maintainer" && NEEDS_REVIEW.some((k) => k in value);
  return { value, note, source, review };
}

async function resolveStation(db, id) {
  const redirect = await db.prepare("SELECT to_id FROM catalog_redirects WHERE from_id = ?").bind(id).first();
  const target = redirect ? redirect.to_id : id;
  const row = await db.prepare("SELECT id, status FROM catalog WHERE id = ?").bind(target).first();
  return row ? row.id : null;
}

export async function addEdit(db, editor, body, now) {
  const checked = validateEdit(body, editor.role);
  if (checked.error) return checked;
  const station = await resolveStation(db, body.station);
  if (!station) return { error: "unknown station", status: 404 };
  if (checked.value.same_as && !(await resolveStation(db, checked.value.same_as))) return { error: "unknown same_as station", status: 404 };
  const recent = await db.prepare("SELECT COUNT(*) AS n FROM edits WHERE editor_id = ? AND created_at > ?")
    .bind(editor.id, now - 86400).first();
  if (recent.n >= DAILY_EDITS[editor.role]) return { limited: true };
  const id = await randomId("ed_");
  const status = checked.review ? "pending" : "accepted";
  await db.prepare(
    `INSERT INTO edits (id, station, body, note, source, editor_id, status, decided_by, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).bind(id, station, JSON.stringify(checked.value), checked.note, checked.source, editor.id, status,
    status === "accepted" ? editor.id : null, now, now).run();
  return { id, station, status };
}

const DECISIONS = { pending: ["accepted", "rejected"], accepted: ["reverted"] };

export async function decideEdit(db, editor, id, status, now) {
  const row = await db.prepare("SELECT status FROM edits WHERE id = ?").bind(id).first();
  if (!row) return { error: "unknown edit", status: 404 };
  if (!(DECISIONS[row.status] || []).includes(status)) return { error: `cannot go from ${row.status} to ${status}` };
  await db.prepare("UPDATE edits SET status = ?, decided_by = ?, updated_at = ? WHERE id = ?").bind(status, editor.id, now, id).run();
  return { id, status };
}

export async function listEdits(db, { status, station, editor, limit = 200 }) {
  const where = [], args = [];
  for (const [column, value] of [["e.status", status], ["e.station", station], ["e.editor_id", editor]]) {
    if (value) {
      where.push(`${column} = ?`);
      args.push(value);
    }
  }
  const { results } = await db.prepare(
    `SELECT e.id, e.station, e.body, e.note, e.source, e.status, e.created_at, e.updated_at, x.name AS editor, c.record
     FROM edits e JOIN editors x ON x.id = e.editor_id LEFT JOIN catalog c ON c.id = e.station
     ${where.length ? "WHERE " + where.join(" AND ") : ""} ORDER BY e.created_at DESC LIMIT ?`,
  ).bind(...args, Math.min(limit, 500)).all();
  return results.map(({ record, body, ...r }) => ({ ...r, change: JSON.parse(body), station_name: record ? JSON.parse(record).name : null }));
}

/** Public export for the build: accepted edits, and those reverted since. No editor, no note. */
export async function exportEdits(db, afterUpdated, afterId, limit) {
  const { results } = await db.prepare(
    `SELECT id, station, body, status, created_at, updated_at FROM edits
     WHERE status IN ('accepted', 'reverted') AND ((updated_at > ?) OR (updated_at = ? AND id > ?))
     ORDER BY updated_at, id LIMIT ?`,
  ).bind(afterUpdated, afterUpdated, afterId, limit).all();
  const iso = (s) => new Date(s * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
  return results.map((r) => ({
    id: r.id, station: r.station, status: r.status === "accepted" ? "accepted" : "withdrawn",
    change: JSON.parse(r.body), created_at: iso(r.created_at), updated_at: iso(r.updated_at), cursor: `${r.updated_at}.${r.id}`,
  }));
}

// --- New stations: checked by the stream checker like those from installations ---

export async function addStation(db, editor, body, now) {
  if (!isObject(body)) return { error: "body must be an object" };
  const { note, ...rest } = body;
  const checked = validateStationAdd({ ...rest, kind: "station_add", consent: "CC0-1.0" });
  if (checked.error) return checked;
  for (const url of checked.value.streams) {
    const known = await findByUrl(db, url);
    if (known) return { error: "stream already in a station", station: known, status: 409 };
  }
  const recent = await db.prepare("SELECT COUNT(*) AS n FROM station_proposals WHERE editor_id = ? AND created_at > ?")
    .bind(editor.id, now - 86400).first();
  if (recent.n >= DAILY_NEW_STATIONS) return { limited: true };
  const fingerprint = bytesToHex(await sha256(checked.value.streams.slice().sort().join("\n"))).slice(0, 32);
  const twice = await db.prepare("SELECT id, status FROM station_proposals WHERE editor_id = ? AND fingerprint = ?")
    .bind(editor.id, fingerprint).first();
  if (twice) return { id: twice.id, status: twice.status, duplicate: true };
  const id = await randomId("pr_");
  await db.prepare(
    `INSERT INTO station_proposals (id, contributor_id, editor_id, fingerprint, body, status, reason, created_at, updated_at)
     VALUES (?, NULL, ?, ?, ?, 'pending', ?, ?, ?)`,
  ).bind(id, editor.id, fingerprint, JSON.stringify(checked.value), typeof note === "string" ? note.slice(0, 300) : null, now, now).run();
  return { id, status: "pending" };
}

async function findByUrl(db, url) {
  const key = url.toLowerCase().replace(/^https?:\/\//, "").replace(/\/+$/, "");
  if (key.length < 8) return null;
  const row = await db.prepare("SELECT id FROM catalog WHERE find LIKE ? ESCAPE '\\' LIMIT 1")
    .bind(`%${key.replace(/[\\%_]/g, (c) => "\\" + c)}%`).first();
  return row ? row.id : null;
}

// --- Search ---

export function nameKey(text) {
  return (typeof text === "string" ? text : "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

function findText(record) {
  const alt = (record.alt_names || []).map((n) => (typeof n === "string" ? n : n && n.name));
  const parts = [nameKey(record.name), ...alt.map(nameKey), record.id];
  if (record.homepage) parts.push(record.homepage.toLowerCase().replace(/^https?:\/\//, ""));
  for (const s of record.streams || []) parts.push(s.id, s.url.toLowerCase().replace(/^https?:\/\//, ""));
  return parts.join(" | ");
}

export async function search(db, q, country, limit = 50) {
  q = (q || "").trim().slice(0, 200);
  const like = (s) => `%${s.replace(/[\\%_]/g, (c) => "\\" + c)}%`;
  if (/^st_[0-9a-z]{26}$/.test(q)) {
    const id = await resolveStation(db, q);
    q = id || q;
  }
  const words = /[./:_]/.test(q) ? [q.toLowerCase().replace(/^https?:\/\//, "")] : nameKey(q).split(" ").filter(Boolean);
  if (!words.length && !country) return [];
  const where = words.map(() => "find LIKE ? ESCAPE '\\'");
  const args = words.map(like);
  if (country) {
    where.push("country = ?");
    args.push(country);
  }
  const { results } = await db.prepare(
    `SELECT id, record FROM catalog WHERE ${where.join(" AND ")}
     ORDER BY status = 'active' DESC, name_key = ? DESC, name_key LIKE ? DESC, length(name_key) LIMIT ?`,
  ).bind(...args, nameKey(q), `${nameKey(q)}%`, Math.min(limit, 200)).all();
  return results.map(({ record }) => {
    const r = JSON.parse(record);
    return { id: r.id, name: r.name, country: r.country || null, status: r.status, homepage: r.homepage || null,
      streams: (r.streams || []).length, logo_url: r.logo_url || null };
  });
}

export async function stationView(db, id, fetcher = fetch) {
  const target = await resolveStation(db, id);
  if (!target) return null;
  const row = await db.prepare("SELECT shard, record FROM catalog WHERE id = ?").bind(target).first();
  const station = JSON.parse(row.record);
  const health = {};
  try {
    const records = await readShard(fetcher, `${DATA}health/${row.shard}.ndjson.gz`, 3600);
    const ids = new Set((station.streams || []).map((s) => s.id));
    for (const h of records) if (ids.has(h.id)) health[h.id] = h;
  } catch {
    // Health is a help, never required.
  }
  return { station, health, edits: await listEdits(db, { station: target, limit: 50 }), redirected_from: target !== id ? id : undefined };
}

// --- The catalog, refreshed from the published dataset ---

async function readShard(fetcher, url, cacheSeconds = 0) {
  const response = await fetcher(url, { cf: { cacheTtl: cacheSeconds }, headers: { "user-agent": "12moon-api" } });
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  const stream = response.body.pipeThrough(new DecompressionStream("gzip"));
  const text = await new Response(stream).text();
  return text.split("\n").filter(Boolean).map((line) => JSON.parse(line));
}

/**
 * Brings the catalog up to date, a few shards per call: only the shards whose sha256
 * changed in the manifest are read again. Returns what was done.
 */
export async function refreshCatalog(db, { fetcher = fetch, maxShards = 4 } = {}) {
  const manifest = await (await fetcher(`${DATA}manifest.json`, { headers: { "user-agent": "12moon-api" } })).json();
  const entries = manifest.datasets.stations;
  const { results } = await db.prepare("SELECT shard, sha256 FROM catalog_shards").all();
  const known = new Map(results.map((r) => [r.shard, r.sha256]));
  const done = [];
  for (const entry of entries) {
    if (done.length >= maxShards) break;
    if (known.get(entry.shard) === entry.sha256) continue;
    const records = await readShard(fetcher, DATA + entry.path);
    const { results: existing } = await db.prepare("SELECT id, rev FROM catalog WHERE shard = ?").bind(entry.shard).all();
    const revs = new Map(existing.map((r) => [r.id, r.rev]));
    const statements = [];
    for (const r of records) {
      if (revs.get(r.id) === r.rev) continue;
      statements.push(db.prepare(
        `INSERT INTO catalog (id, shard, rev, name_key, find, country, status, record) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET shard = excluded.shard, rev = excluded.rev, name_key = excluded.name_key,
           find = excluded.find, country = excluded.country, status = excluded.status, record = excluded.record`,
      ).bind(r.id, entry.shard, r.rev, nameKey(r.name), findText(r), r.country || null, r.status, JSON.stringify(r)));
    }
    const present = new Set(records.map((r) => r.id));
    for (const r of existing) if (!present.has(r.id)) statements.push(db.prepare("DELETE FROM catalog WHERE id = ? AND shard = ?").bind(r.id, entry.shard));
    for (let i = 0; i < statements.length; i += 100) await db.batch(statements.slice(i, i + 100));
    await db.prepare("INSERT INTO catalog_shards (shard, sha256, version) VALUES (?, ?, ?) ON CONFLICT(shard) DO UPDATE SET sha256 = excluded.sha256, version = excluded.version")
      .bind(entry.shard, entry.sha256, manifest.dataset_version).run();
    done.push({ shard: entry.shard, changed: statements.length });
  }
  const gone = [...known.keys()].filter((s) => s !== "_redirects" && !entries.some((e) => e.shard === s));
  for (const shard of gone) {
    await db.batch([db.prepare("DELETE FROM catalog WHERE shard = ?").bind(shard), db.prepare("DELETE FROM catalog_shards WHERE shard = ?").bind(shard)]);
  }
  const redirect = manifest.datasets.redirects[0];
  const state = await db.prepare("SELECT sha256 FROM catalog_shards WHERE shard = '_redirects'").first();
  if (redirect && (!state || state.sha256 !== redirect.sha256) && done.length < maxShards) {
    const rows = await readShard(fetcher, DATA + redirect.path);
    const statements = [db.prepare("DELETE FROM catalog_redirects")];
    for (const r of rows) statements.push(db.prepare("INSERT OR REPLACE INTO catalog_redirects (from_id, to_id) VALUES (?, ?)").bind(r.from, r.to));
    for (let i = 0; i < statements.length; i += 100) await db.batch(statements.slice(i, i + 100));
    await db.prepare("INSERT INTO catalog_shards (shard, sha256, version) VALUES ('_redirects', ?, ?) ON CONFLICT(shard) DO UPDATE SET sha256 = excluded.sha256, version = excluded.version")
      .bind(redirect.sha256, manifest.dataset_version).run();
    done.push({ shard: "_redirects", changed: rows.length });
  }
  return { version: manifest.dataset_version, done };
}

export async function catalogState(db) {
  const row = await db.prepare("SELECT COUNT(*) AS stations FROM catalog").first();
  const v = await db.prepare("SELECT MIN(version) AS oldest, MAX(version) AS newest FROM catalog_shards WHERE shard != '_redirects'").first();
  return { stations: row.stations, oldest: v.oldest, newest: v.newest };
}
