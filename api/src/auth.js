import { base64urlToBytes, bytesToBase64url, bytesToHex, sha256 } from "./encoding.js";

export const MAX_SKEW_SECONDS = 300;

/**
 * Requests are signed with an Ed25519 key that each installation creates. The
 * contributor identifier is derived from the public key: no account, no secret on
 * the server. Signed text: v1, method, path, timestamp, nonce, SHA-256 of the body.
 */
export async function verifyRequest(request, bodyBytes, nowSeconds) {
  const key = base64urlToBytes(request.headers.get("x-12moon-key"));
  const signature = base64urlToBytes(request.headers.get("x-12moon-signature"));
  const nonce = request.headers.get("x-12moon-nonce") || "";
  const timestamp = Number(request.headers.get("x-12moon-timestamp"));
  if (!key || key.length !== 32 || !signature || signature.length !== 64) return { error: "missing or malformed signature" };
  if (!/^[A-Za-z0-9_-]{16,64}$/.test(nonce)) return { error: "invalid nonce" };
  if (!Number.isInteger(timestamp) || Math.abs(nowSeconds - timestamp) > MAX_SKEW_SECONDS) return { error: "stale timestamp" };
  const url = new URL(request.url);
  const text = ["v1", request.method, url.pathname, String(timestamp), nonce, bytesToHex(await sha256(bodyBytes))].join("\n");
  let valid = false;
  try {
    const publicKey = await crypto.subtle.importKey("raw", key, { name: "Ed25519" }, false, ["verify"]);
    valid = await crypto.subtle.verify({ name: "Ed25519" }, publicKey, signature, new TextEncoder().encode(text));
  } catch {
    valid = false;
  }
  if (!valid) return { error: "bad signature" };
  const contributorId = bytesToBase64url((await sha256(key)).slice(0, 16));
  return { contributorId, publicKey: bytesToBase64url(key), nonce };
}

/** Helper for clients and tests: sign a request the way verifyRequest expects. */
export async function signRequest({ privateKey, publicKeyBytes, method, path, body = "", timestamp, nonce }) {
  const bodyBytes = new TextEncoder().encode(body);
  const text = ["v1", method, path, String(timestamp), nonce, bytesToHex(await sha256(bodyBytes))].join("\n");
  const signature = new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, privateKey, new TextEncoder().encode(text)));
  return {
    "x-12moon-key": bytesToBase64url(publicKeyBytes),
    "x-12moon-timestamp": String(timestamp),
    "x-12moon-nonce": nonce,
    "x-12moon-signature": bytesToBase64url(signature),
  };
}
