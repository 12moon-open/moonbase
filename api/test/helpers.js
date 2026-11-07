import { signRequest } from "../src/auth.js";

export const MBID = "1b022e01-4da6-387b-8658-8678046e4cef";
export const NOW = 1_800_000_000;
let counter = 0;

export async function newClient() {
  const keys = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
  const raw = new Uint8Array(await crypto.subtle.exportKey("raw", keys.publicKey));
  return { privateKey: keys.privateKey, publicKeyBytes: raw };
}

export async function signed(client, method, path, bodyObject, { now = NOW, nonce } = {}) {
  const body = bodyObject === undefined ? "" : JSON.stringify(bodyObject);
  counter += 1;
  const headers = await signRequest({
    ...client,
    method,
    path,
    body,
    timestamp: now,
    nonce: nonce ?? `nonce-${String(counter).padStart(12, "0")}`,
  });
  return new Request(`https://api.12moon.app${path}`, {
    method,
    headers: { ...headers, "content-type": "application/json" },
    body: method === "GET" ? undefined : body,
  });
}

export function proposal(media = [[215, 180, 302]], mbid = MBID) {
  return { kind: "release_match", media, musicbrainz_release: mbid };
}

export function mbRelease(lengthsMs, id = MBID) {
  return { id, media: lengthsMs.map((disc) => ({ tracks: disc.map((length) => ({ length })) })) };
}

export function fakeMusicBrainz(table) {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, userAgent: options.headers["User-Agent"] });
    const mbid = url.match(/release\/([0-9a-f-]{36})/)[1];
    const entry = table[mbid];
    if (entry === undefined) return new Response("{}", { status: 404 });
    if (typeof entry === "number") return new Response("{}", { status: entry });
    return new Response(JSON.stringify(entry), { status: 200 });
  };
  return { fetchImpl, calls };
}
