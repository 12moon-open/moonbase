const TOLERANCE_SECONDS = 3;
const MIN_KNOWN = 0.8;
export const USER_AGENT = "12moon-commons/1.0 ( https://github.com/12moon-open/moonbase )";

/**
 * Compare proposed durations with a MusicBrainz release.
 * "match": same discs and tracks, enough known lengths, all within tolerance.
 * "mismatch": the track lists disagree. "insufficient": too few lengths to decide.
 */
export function compareRelease(media, release) {
  const discs = Array.isArray(release?.media) ? release.media : [];
  if (discs.length !== media.length) return "mismatch";
  let known = 0;
  let total = 0;
  for (let d = 0; d < media.length; d += 1) {
    const tracks = Array.isArray(discs[d]?.tracks) ? discs[d].tracks : [];
    if (tracks.length !== media[d].length) return "mismatch";
    for (let t = 0; t < tracks.length; t += 1) {
      total += 1;
      const length = tracks[t]?.length;
      if (typeof length !== "number") continue;
      known += 1;
      if (Math.abs(length / 1000 - media[d][t]) > TOLERANCE_SECONDS) return "mismatch";
    }
  }
  return known >= total * MIN_KNOWN ? "match" : "insufficient";
}

/** Fetch a release. Returns {status, release}. Follows MusicBrainz merges: release.id is canonical. */
export async function fetchRelease(mbid, fetchImpl = fetch) {
  const url = `https://musicbrainz.org/ws/2/release/${mbid}?inc=recordings&fmt=json`;
  const response = await fetchImpl(url, { headers: { "User-Agent": USER_AGENT, Accept: "application/json" } });
  if (response.status === 404) return { status: "not_found" };
  if (!response.ok) return { status: "unavailable" };
  return { status: "ok", release: await response.json() };
}
