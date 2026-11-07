import { verifyRequest } from "./auth.js";
import { addMeasures, purgeMeasures, streamHealth, validateMeasures } from "./measures.js";
import { addProposal, addReport, contributor, eraseContributor, exportLinks, proposalStatus, useNonce } from "./store.js";
import { validateProposal } from "./validate.js";
import { verifyPending } from "./verify.js";

const MAX_BODY = 16 * 1024;
const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
};

function reply(status, body, headers = {}) {
  return new Response(JSON.stringify(body), { status, headers: { ...JSON_HEADERS, ...headers } });
}

async function readBody(request) {
  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > MAX_BODY) return null;
  const bytes = new Uint8Array(await request.arrayBuffer());
  return bytes.length > MAX_BODY ? null : bytes;
}

async function signed(request, env, now) {
  const bytes = await readBody(request);
  if (!bytes) return { response: reply(413, { error: "body too large" }) };
  const auth = await verifyRequest(request, bytes, now);
  if (auth.error) return { response: reply(401, { error: auth.error }) };
  if (!(await useNonce(env.DB, auth.nonce, now))) return { response: reply(401, { error: "replayed request" }) };
  return { auth, bytes };
}

function parseJson(bytes) {
  try {
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return undefined;
  }
}

export async function handle(request, env, now = Math.floor(Date.now() / 1000)) {
  const url = new URL(request.url);
  const path = url.pathname;
  const writing = request.method !== "GET" && request.method !== "HEAD";
  if (writing && env.READ_ONLY === "true") return reply(503, { error: "read only" }, { "retry-after": "3600" });

  if (request.method === "GET" && path === "/v1/health") return reply(200, { ok: true });

  if (request.method === "GET" && path === "/v1/links/release-matches") {
    const [updated, id] = (url.searchParams.get("after") || "0.").split(/\.(.*)/s);
    const limit = Math.min(Math.max(Number(url.searchParams.get("limit")) || 1000, 1), 1000);
    const links = await exportLinks(env.DB, Number(updated) || 0, id || "", limit);
    return reply(200, { links, next: links.length === limit ? links.at(-1).cursor : null }, { "cache-control": "public, max-age=60" });
  }

  const status = path.match(/^\/v1\/proposals\/(pr_[0-9a-z]{26})$/);
  if (request.method === "GET" && status) {
    const row = await proposalStatus(env.DB, status[1]);
    return row ? reply(200, row) : reply(404, { error: "not found" });
  }

  if (request.method === "POST" && path === "/v1/proposals") {
    const { auth, bytes, response } = await signed(request, env, now);
    if (response) return response;
    const body = parseJson(bytes);
    const invalid = validateProposal(body);
    if (invalid) return reply(422, { error: invalid });
    const id = await contributor(env.DB, auth.contributorId, auth.publicKey, now);
    if (!id) return reply(403, { error: "contributor blocked" });
    const result = await addProposal(env.DB, id, body, now);
    if (result.limited) return reply(429, { error: "daily limit reached" }, { "retry-after": "86400" });
    return reply(result.duplicate ? 200 : 202, { id: result.id, status: result.status });
  }

  if (request.method === "POST" && path === "/v1/reports") {
    const { auth, bytes, response } = await signed(request, env, now);
    if (response) return response;
    const id = await contributor(env.DB, auth.contributorId, auth.publicKey, now);
    if (!id) return reply(403, { error: "contributor blocked" });
    const result = await addReport(env.DB, id, parseJson(bytes), now);
    if (result.limited) return reply(429, { error: "daily limit reached" }, { "retry-after": "86400" });
    if (result.error) return reply(422, { error: result.error });
    return reply(202, { id: result.id });
  }

  if (request.method === "POST" && path === "/v1/measures") {
    // Not tied to a contributor: the key only signs the report and is never stored.
    const { auth, bytes, response } = await signed(request, env, now);
    if (response) return response;
    const body = parseJson(bytes);
    const invalid = validateMeasures(body);
    if (invalid) return reply(422, { error: invalid });
    const result = await addMeasures(env.DB, auth.publicKey, body, now);
    if (result.error) return reply(422, { error: result.error });
    if (result.duplicate) return reply(409, { error: "week already reported" });
    return reply(202, { accepted: result.accepted });
  }

  if (request.method === "GET" && path === "/v1/measures/streams") {
    const after = url.searchParams.get("after") || "";
    if (after && !/^sm_[0-9a-z]{26}$/.test(after)) return reply(400, { error: "invalid cursor" });
    const limit = Math.min(Math.max(Number(url.searchParams.get("limit")) || 1000, 1), 1000);
    const streams = await streamHealth(env.DB, now, after, limit);
    return reply(200, { streams, next: streams.length === limit ? streams.at(-1).id : null }, { "cache-control": "public, max-age=3600" });
  }

  if (request.method === "DELETE" && path === "/v1/contributors/me") {
    const { auth, response } = await signed(request, env, now);
    if (response) return response;
    await eraseContributor(env.DB, auth.contributorId);
    return reply(200, { erased: true });
  }

  return reply(404, { error: "not found" });
}

export default {
  fetch: (request, env) => handle(request, env),
  scheduled: (event, env, ctx) => {
    if (env.READ_ONLY === "true") return;
    const now = Math.floor(Date.now() / 1000);
    ctx.waitUntil(verifyPending(env.DB, { now }));
    if (event.cron === "17 3 * * *") ctx.waitUntil(purgeMeasures(env.DB, now));
  },
};
