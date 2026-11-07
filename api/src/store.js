import { randomId, stableId } from "./encoding.js";

export const DAILY_PROPOSALS = 200;
export const DAILY_REPORTS = 20;
const DAY = 86400;

export async function fingerprintOf(media) {
  return (await stableId("fp_", JSON.stringify(media))).slice(3);
}

/** Records the nonce; false when it was already used (replay). */
export async function useNonce(db, nonce, now) {
  await db.prepare("DELETE FROM nonces WHERE expires_at < ?").bind(now).run();
  const result = await db
    .prepare("INSERT OR IGNORE INTO nonces (nonce, expires_at) VALUES (?, ?)")
    .bind(nonce, now + 2 * 300)
    .run();
  return result.meta.changes === 1;
}

/** Creates the contributor on first use. Returns null when blocked. */
export async function contributor(db, id, publicKey, now) {
  await db
    .prepare("INSERT OR IGNORE INTO contributors (id, public_key, created_at) VALUES (?, ?, ?)")
    .bind(id, publicKey, now)
    .run();
  const row = await db.prepare("SELECT blocked_at FROM contributors WHERE id = ?").bind(id).first();
  return row && row.blocked_at === null ? id : null;
}

export async function addProposal(db, contributorId, body, now) {
  const fingerprint = await fingerprintOf(body.media);
  const existing = await db
    .prepare("SELECT id, status FROM proposals WHERE contributor_id = ? AND fingerprint = ? AND musicbrainz_release = ?")
    .bind(contributorId, fingerprint, body.musicbrainz_release)
    .first();
  if (existing) return { id: existing.id, status: existing.status, duplicate: true };
  const recent = await db
    .prepare("SELECT COUNT(*) AS n FROM proposals WHERE contributor_id = ? AND created_at > ?")
    .bind(contributorId, now - DAY)
    .first();
  if (recent.n >= DAILY_PROPOSALS) return { limited: true };
  const id = await randomId("pr_");
  await db
    .prepare(
      `INSERT INTO proposals (id, contributor_id, kind, fingerprint, media, musicbrainz_release, status, next_attempt_at, created_at)
       VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)`,
    )
    .bind(id, contributorId, body.kind, fingerprint, JSON.stringify(body.media), body.musicbrainz_release, now, now)
    .run();
  return { id, status: "pending" };
}

export async function proposalStatus(db, id) {
  return db.prepare("SELECT id, status, reason, link_id FROM proposals WHERE id = ?").bind(id).first();
}

export async function addReport(db, contributorId, body, now) {
  if (!body || typeof body.link_id !== "string" || !/^lk_[0-9a-z]{26}$/.test(body.link_id)) return { error: "invalid link_id" };
  if (!["wrong_match", "duplicate", "other"].includes(body.reason)) return { error: "invalid reason" };
  if (Object.keys(body).some((k) => k !== "link_id" && k !== "reason")) return { error: "unexpected field" };
  const link = await db.prepare("SELECT id FROM links WHERE id = ?").bind(body.link_id).first();
  if (!link) return { error: "unknown link" };
  const recent = await db
    .prepare("SELECT COUNT(*) AS n FROM reports WHERE contributor_id = ? AND created_at > ?")
    .bind(contributorId, now - DAY)
    .first();
  if (recent.n >= DAILY_REPORTS) return { limited: true };
  const id = await randomId("rp_");
  await db
    .prepare("INSERT INTO reports (id, link_id, contributor_id, reason, status, created_at) VALUES (?, ?, ?, ?, 'open', ?)")
    .bind(id, body.link_id, contributorId, body.reason, now)
    .run();
  return { id };
}

/** Right to erasure: the contributor and its key disappear, published links stay. */
export async function eraseContributor(db, contributorId) {
  await db.batch([
    db.prepare("UPDATE proposals SET contributor_id = NULL WHERE contributor_id = ?").bind(contributorId),
    db.prepare("UPDATE reports SET contributor_id = NULL WHERE contributor_id = ?").bind(contributorId),
    db.prepare("DELETE FROM contributors WHERE id = ?").bind(contributorId),
  ]);
}

export async function exportLinks(db, afterUpdated, afterId, limit) {
  const { results } = await db
    .prepare(
      `SELECT id, status, media, musicbrainz_release, verified_by, updated_at FROM links
       WHERE (updated_at > ?) OR (updated_at = ? AND id > ?) ORDER BY updated_at, id LIMIT ?`,
    )
    .bind(afterUpdated, afterUpdated, afterId, limit)
    .all();
  return results.map((row) => ({
    id: row.id,
    status: row.status,
    media: JSON.parse(row.media),
    musicbrainz_release: row.musicbrainz_release,
    verified_by: row.verified_by,
    updated_at: new Date(row.updated_at * 1000).toISOString().replace(/\.\d{3}Z$/, "Z"),
    cursor: `${row.updated_at}.${row.id}`,
  }));
}
