const MBID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const FIELDS = new Set(["kind", "media", "musicbrainz_release"]);
const MAX_TRACKS = 400;

/** Mirrors contract/v1/schemas/proposal.schema.json. Returns an error string or null. */
export function validateProposal(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return "body must be an object";
  for (const key of Object.keys(body)) if (!FIELDS.has(key)) return `unexpected field: ${key}`;
  if (body.kind !== "release_match") return "unknown kind";
  if (typeof body.musicbrainz_release !== "string" || !MBID.test(body.musicbrainz_release)) {
    return "invalid musicbrainz_release";
  }
  const media = body.media;
  if (!Array.isArray(media) || media.length < 1 || media.length > 20) return "invalid media";
  let total = 0;
  for (const disc of media) {
    if (!Array.isArray(disc) || disc.length < 1 || disc.length > 200) return "invalid disc";
    for (const seconds of disc) {
      if (!Number.isInteger(seconds) || seconds < 1 || seconds > 36000) return "invalid duration";
    }
    total += disc.length;
  }
  if (total > MAX_TRACKS) return "too many tracks";
  return null;
}
