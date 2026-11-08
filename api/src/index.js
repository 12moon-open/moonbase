import { verifyRequest } from "./auth.js";
import {
  addEdit, addStation, catalogState, createEditor, decideEdit, editorOf, exportEdits, listEditors, listEdits,
  refreshCatalog, revokeEditor, search, stationView,
} from "./edits.js";
import { EDIT_CSS, EDIT_HTML, EDIT_JS } from "./editpage.js";
import { addMeasures, purgeMeasures, streamHealth, validateMeasures } from "./measures.js";
import {
  addStationProposal, addStationReport, claimStationProposals, decideStationProposal, decideStationReport,
  exportStations, hideStationsOf, listStationProposals, listStationReports, stationProposalStatus, validateStationAdd,
} from "./stations.js";
import { TERMS_HTML } from "./terms.js";
import { revokeContributor } from "./verify.js";
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

  if ((request.method === "GET" || request.method === "HEAD") && path === "/terms") {
    return new Response(TERMS_HTML, { headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "public, max-age=3600",
      "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; frame-ancestors 'none'",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer",
    } });
  }

  if (request.method === "GET" && path === "/v1/links/release-matches") {
    const [updated, id] = (url.searchParams.get("after") || "0.").split(/\.(.*)/s);
    const limit = Math.min(Math.max(Number(url.searchParams.get("limit")) || 1000, 1), 1000);
    const links = await exportLinks(env.DB, Number(updated) || 0, id || "", limit);
    return reply(200, { links, next: links.length === limit ? links.at(-1).cursor : null }, { "cache-control": "public, max-age=60" });
  }

  const status = path.match(/^\/v1\/proposals\/(pr_[0-9a-z]{26})$/);
  if (request.method === "GET" && status) {
    const row = (await proposalStatus(env.DB, status[1])) || (await stationProposalStatus(env.DB, status[1]));
    return row ? reply(200, row) : reply(404, { error: "not found" });
  }

  if (request.method === "GET" && path === "/v1/contributions/stations") {
    const [updated, id] = (url.searchParams.get("after") || "0.").split(/\.(.*)/s);
    const limit = Math.min(Math.max(Number(url.searchParams.get("limit")) || 1000, 1), 1000);
    const stations = await exportStations(env.DB, Number(updated) || 0, id || "", limit);
    return reply(200, { stations, next: stations.length === limit ? stations.at(-1).cursor : null }, { "cache-control": "public, max-age=60" });
  }

  if (path.startsWith("/v1/admin/")) return admin(request, env, url, path, now);
  if (path.startsWith("/v1/edit/")) return edit(request, env, url, path, now);

  if (request.method === "GET" && path === "/v1/edits") {
    const [updated, id] = (url.searchParams.get("after") || "0.").split(/\.(.*)/s);
    const limit = Math.min(Math.max(Number(url.searchParams.get("limit")) || 1000, 1), 1000);
    const edits = await exportEdits(env.DB, Number(updated) || 0, id || "", limit);
    return reply(200, { edits, next: edits.length === limit ? edits.at(-1).cursor : null }, { "cache-control": "no-store" });
  }

  const page = { "/edit": [EDIT_HTML, "text/html"], "/edit/app.js": [EDIT_JS, "text/javascript"], "/edit/app.css": [EDIT_CSS, "text/css"] }[path];
  if (page && (request.method === "GET" || request.method === "HEAD")) {
    return new Response(page[0], { headers: {
      "content-type": `${page[1]}; charset=utf-8`,
      "cache-control": "no-cache",
      "content-security-policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src https:; connect-src 'self'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer",
      "cross-origin-opener-policy": "same-origin",
    } });
  }

  if (request.method === "POST" && path === "/v1/proposals") {
    const { auth, bytes, response } = await signed(request, env, now);
    if (response) return response;
    const body = parseJson(bytes);
    if (body && body.kind === "station_add") {
      const checked = validateStationAdd(body);
      if (checked.error) return reply(422, { error: checked.error });
      const id = await contributor(env.DB, auth.contributorId, auth.publicKey, now);
      if (!id) return reply(403, { error: "contributor blocked" });
      const result = await addStationProposal(env.DB, id, checked.value, now);
      if (result.limited) return reply(429, { error: "daily limit reached" }, { "retry-after": "86400" });
      return reply(result.duplicate ? 200 : 202, { id: result.id, status: result.status === "verifying" ? "pending" : result.status });
    }
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
    const body = parseJson(bytes);
    const result = body && body.station !== undefined
      ? await addStationReport(env.DB, id, body, now)
      : await addReport(env.DB, id, body, now);
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

async function sameToken(given, expected) {
  if (typeof expected !== "string" || expected.length < 32 || !given) return false;
  const [a, b] = await Promise.all([given, expected].map((t) => crypto.subtle.digest("SHA-256", new TextEncoder().encode(t))));
  const x = new Uint8Array(a), y = new Uint8Array(b);
  let diff = 0;
  for (let i = 0; i < x.length; i += 1) diff |= x[i] ^ y[i];
  return diff === 0;
}

/** "admin" for the maintainer, "checker" for the stream checker, or null. Constant-time comparisons. */
async function role(request, env) {
  const given = (request.headers.get("authorization") || "").replace(/^Bearer /, "");
  if (await sameToken(given, env.ADMIN_TOKEN)) return "admin";
  if (await sameToken(given, env.CHECKER_TOKEN)) return "checker";
  const editor = await editorOf(env.DB, given, Math.floor(Date.now() / 1000));
  return editor && editor.role === "maintainer" ? "admin" : null;
}

/** The editor behind the request: an editor token, or the admin token acting as the maintainer. */
async function editorFor(request, env, now) {
  const given = (request.headers.get("authorization") || "").replace(/^Bearer /, "");
  if (await sameToken(given, env.ADMIN_TOKEN)) {
    await env.DB.prepare("INSERT OR IGNORE INTO editors (id, name, role, token_hash, created_at) VALUES ('ed_admin', 'admin token', 'maintainer', 'admin-token', ?)").bind(now).run();
    return { id: "ed_admin", name: "admin token", role: "maintainer" };
  }
  return editorOf(env.DB, given, now);
}

/** Searching and editing stations, for editors. */
async function edit(request, env, url, path, now) {
  const editor = await editorFor(request, env, now);
  if (!editor) return reply(401, { error: "unauthorized" }, { "www-authenticate": "Bearer" });
  const body = async () => {
    const bytes = await readBody(request);
    return bytes ? parseJson(bytes) : undefined;
  };
  const answer = (result, created = 200) => {
    if (result.limited) return reply(429, { error: "daily limit reached" }, { "retry-after": "86400" });
    if (result.error) return reply(result.status || 422, { error: result.error, ...(result.station ? { station: result.station } : {}) });
    return reply(created, result);
  };
  if (request.method === "GET" && path === "/v1/edit/me") {
    return reply(200, { name: editor.name, role: editor.role, catalog: await catalogState(env.DB) });
  }
  if (request.method === "GET" && path === "/v1/edit/search") {
    const country = url.searchParams.get("country") || "";
    if (country && !/^[A-Z]{2}$/.test(country)) return reply(400, { error: "invalid country" });
    return reply(200, { stations: await search(env.DB, url.searchParams.get("q") || "", country, Number(url.searchParams.get("limit")) || 50) });
  }
  const one = path.match(/^\/v1\/edit\/stations\/(st_[0-9a-z]{26})$/);
  if (request.method === "GET" && one) {
    const view = await stationView(env.DB, one[1]);
    return view ? reply(200, view) : reply(404, { error: "unknown station" });
  }
  if (request.method === "POST" && path === "/v1/edit/stations") return answer(await addStation(env.DB, editor, await body(), now), 202);
  if (request.method === "POST" && path === "/v1/edit/changes") return answer(await addEdit(env.DB, editor, await body(), now), 201);
  if (request.method === "GET" && path === "/v1/edit/changes") {
    const status = url.searchParams.get("status") || "";
    if (status && !["pending", "accepted", "rejected", "reverted"].includes(status)) return reply(400, { error: "invalid status" });
    const mine = editor.role === "maintainer" ? {} : { editor: editor.id };
    return reply(200, { edits: await listEdits(env.DB, { status, ...mine }) });
  }
  if (request.method === "GET" && path === "/v1/edit/new-stations") {
    const { results } = await env.DB.prepare(
      "SELECT id, status, reason, station, body, created_at FROM station_proposals WHERE editor_id = ? ORDER BY created_at DESC LIMIT 200",
    ).bind(editor.id).all();
    return reply(200, { stations: results.map((r) => ({ ...r, body: JSON.parse(r.body) })) });
  }
  // Below: the maintainer only.
  if (editor.role !== "maintainer") return reply(403, { error: "forbidden" });
  const decision = path.match(/^\/v1\/edit\/changes\/(ed_[0-9a-z]{26})$/);
  if (request.method === "POST" && decision) {
    const given = await body();
    return answer(await decideEdit(env.DB, editor, decision[1], given && given.status, now));
  }
  if (request.method === "GET" && path === "/v1/edit/editors") return reply(200, { editors: await listEditors(env.DB) });
  if (request.method === "POST" && path === "/v1/edit/editors") return answer(await createEditor(env.DB, await body(), now), 201);
  const revoke = path.match(/^\/v1\/edit\/editors\/(ed_[0-9a-z]{26})\/revoke$/);
  if (request.method === "POST" && revoke) return answer(await revokeEditor(env.DB, revoke[1], now));
  if (request.method === "POST" && path === "/v1/edit/catalog/refresh") return reply(200, await refreshCatalog(env.DB));
  return reply(404, { error: "not found" });
}

const CHECKER_DECISIONS = new Set(["published", "duplicate", "rejected", "pending"]);

/** For the stream checker and the maintainer only. */
async function admin(request, env, url, path, now) {
  const who = await role(request, env);
  if (!who) return reply(401, { error: "unauthorized" });
  if (request.method === "POST" && path === "/v1/admin/station-proposals/claim") {
    return reply(200, { proposals: await claimStationProposals(env.DB, now) });
  }
  const decision = path.match(/^\/v1\/admin\/station-proposals\/(pr_[0-9a-z]{26})$/);
  if (request.method === "POST" && decision) {
    const bytes = await readBody(request);
    const body = bytes && parseJson(bytes);
    if (who === "checker" && !CHECKER_DECISIONS.has(body && body.status)) return reply(403, { error: "forbidden" });
    const result = await decideStationProposal(env.DB, decision[1], body, now);
    return result.error ? reply(422, result) : reply(200, result);
  }
  // Everything below is for the maintainer only.
  if (who !== "admin") return reply(403, { error: "forbidden" });
  if (request.method === "GET" && path === "/v1/admin/station-proposals") {
    return reply(200, { proposals: await listStationProposals(env.DB, url.searchParams.get("status") || "published") });
  }
  if (request.method === "GET" && path === "/v1/admin/station-reports") {
    return reply(200, { reports: await listStationReports(env.DB, url.searchParams.get("status") || "open") });
  }
  const report = path.match(/^\/v1\/admin\/station-reports\/(rp_[0-9a-z]{26})$/);
  if (request.method === "POST" && report) {
    const bytes = await readBody(request);
    const result = await decideStationReport(env.DB, report[1], (bytes && parseJson(bytes) || {}).status);
    return result.error ? reply(422, result) : reply(200, result);
  }
  const block = path.match(/^\/v1\/admin\/contributors\/([A-Za-z0-9_-]{16,64})\/block$/);
  if (request.method === "POST" && block) {
    await env.DB.prepare("UPDATE contributors SET blocked_at = ? WHERE id = ? AND blocked_at IS NULL").bind(now, block[1]).run();
    await hideStationsOf(env.DB, block[1], now);
    await revokeContributor(env.DB, block[1], now);
    return reply(200, { blocked: true });
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
    else ctx.waitUntil(refreshCatalog(env.DB).catch((error) => console.error("catalog", String(error))));
  },
};
