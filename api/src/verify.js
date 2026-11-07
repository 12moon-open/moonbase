import { stableId } from "./encoding.js";
import { compareRelease, fetchRelease } from "./musicbrainz.js";

export const BATCH = 20;
const PAUSE_MS = 1100; // MusicBrainz asks for at most one request per second.
const RETRY_SECONDS = 600;
const WAIT_SECONDS = 86400;
const EXPIRE_SECONDS = 90 * 86400;
export const CONSENSUS = 2;

async function upsertLink(db, proposal, mbid, verifiedBy, now) {
  const id = await stableId("lk_", `${proposal.fingerprint}|${mbid}`);
  await db
    .prepare(
      `INSERT INTO links (id, kind, fingerprint, media, musicbrainz_release, verified_by, status, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
       ON CONFLICT (fingerprint, musicbrainz_release) DO UPDATE SET
         status = 'active',
         verified_by = CASE WHEN links.verified_by = 'musicbrainz' THEN links.verified_by ELSE excluded.verified_by END,
         updated_at = CASE WHEN links.status = 'active' AND links.verified_by = excluded.verified_by THEN links.updated_at ELSE excluded.updated_at END`,
    )
    .bind(id, proposal.kind, proposal.fingerprint, proposal.media, mbid, verifiedBy, now)
    .run();
  return id;
}

async function decide(db, proposalId, status, reason, linkId, now) {
  await db
    .prepare("UPDATE proposals SET status = ?, reason = ?, link_id = ?, decided_at = ? WHERE id = ?")
    .bind(status, reason, linkId, now, proposalId)
    .run();
}

async function postpone(db, proposal, seconds, now) {
  await db
    .prepare("UPDATE proposals SET attempts = attempts + 1, next_attempt_at = ? WHERE id = ?")
    .bind(now + seconds, proposal.id)
    .run();
}

async function supporters(db, proposal) {
  const row = await db
    .prepare(
      `SELECT COUNT(DISTINCT contributor_id) AS n FROM proposals
       WHERE fingerprint = ? AND musicbrainz_release = ? AND status IN ('pending', 'accepted') AND contributor_id IS NOT NULL
         AND contributor_id IN (SELECT id FROM contributors WHERE blocked_at IS NULL)`,
    )
    .bind(proposal.fingerprint, proposal.musicbrainz_release)
    .first();
  return row.n;
}

/** Decide pending proposals. Releases are fetched once per run, one per second. */
export async function verifyPending(db, { now, fetchImpl = fetch, sleep = (ms) => new Promise((r) => setTimeout(r, ms)) }) {
  const { results } = await db
    .prepare("SELECT * FROM proposals WHERE status = 'pending' AND next_attempt_at <= ? ORDER BY created_at LIMIT ?")
    .bind(now, BATCH)
    .all();
  const cache = new Map();
  const summary = { accepted: 0, rejected: 0, waiting: 0, retried: 0 };
  for (const proposal of results) {
    if (now - proposal.created_at > EXPIRE_SECONDS) {
      await decide(db, proposal.id, "rejected", "unconfirmed", null, now);
      summary.rejected += 1;
      continue;
    }
    if (!cache.has(proposal.musicbrainz_release)) {
      if (cache.size) await sleep(PAUSE_MS);
      let answer;
      try {
        answer = await fetchRelease(proposal.musicbrainz_release, fetchImpl);
      } catch {
        answer = { status: "unavailable" };
      }
      cache.set(proposal.musicbrainz_release, answer);
    }
    const answer = cache.get(proposal.musicbrainz_release);
    if (answer.status === "unavailable") {
      await postpone(db, proposal, RETRY_SECONDS * Math.min(proposal.attempts + 1, 12), now);
      summary.retried += 1;
      continue;
    }
    if (answer.status === "not_found") {
      await decide(db, proposal.id, "rejected", "unknown_release", null, now);
      summary.rejected += 1;
      continue;
    }
    const canonical = typeof answer.release.id === "string" ? answer.release.id : proposal.musicbrainz_release;
    const result = compareRelease(JSON.parse(proposal.media), answer.release);
    if (result === "match") {
      const linkId = await upsertLink(db, proposal, canonical, "musicbrainz", now);
      await decide(db, proposal.id, "accepted", null, linkId, now);
      summary.accepted += 1;
    } else if (result === "mismatch") {
      await decide(db, proposal.id, "rejected", "tracklist_mismatch", null, now);
      summary.rejected += 1;
    } else if ((await supporters(db, proposal)) >= CONSENSUS) {
      const linkId = await upsertLink(db, proposal, canonical, "consensus", now);
      await db
        .prepare(
          `UPDATE proposals SET status = 'accepted', reason = NULL, link_id = ?, decided_at = ?
           WHERE fingerprint = ? AND musicbrainz_release = ? AND status = 'pending'`,
        )
        .bind(linkId, now, proposal.fingerprint, proposal.musicbrainz_release)
        .run();
      summary.accepted += 1;
    } else {
      await postpone(db, proposal, WAIT_SECONDS, now);
      summary.waiting += 1;
    }
  }
  return summary;
}

/**
 * Block a contributor and undo what depends only on them: links accepted by
 * consensus that no longer have enough support are retracted. Links checked
 * against MusicBrainz stay, because they never depended on trust.
 */
export async function revokeContributor(db, contributorId, now) {
  await db.prepare("UPDATE contributors SET blocked_at = ? WHERE id = ?").bind(now, contributorId).run();
  await db
    .prepare("UPDATE proposals SET status = 'revoked', decided_at = ? WHERE contributor_id = ? AND status IN ('pending', 'accepted')")
    .bind(now, contributorId)
    .run();
  const { results } = await db.prepare("SELECT * FROM links WHERE verified_by = 'consensus' AND status = 'active'").all();
  let retracted = 0;
  for (const link of results) {
    const row = await db
      .prepare(
        `SELECT COUNT(DISTINCT contributor_id) AS n FROM proposals
         WHERE link_id = ? AND status = 'accepted' AND contributor_id IS NOT NULL
           AND contributor_id IN (SELECT id FROM contributors WHERE blocked_at IS NULL)`,
      )
      .bind(link.id)
      .first();
    if (row.n < CONSENSUS) {
      await db.prepare("UPDATE links SET status = 'retracted', updated_at = ? WHERE id = ?").bind(now, link.id).run();
      retracted += 1;
    }
  }
  return { retracted };
}
