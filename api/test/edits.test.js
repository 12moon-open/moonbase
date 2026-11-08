import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { beforeEach, test } from "node:test";
import { refreshCatalog, validateEdit } from "../src/edits.js";
import { handle } from "../src/index.js";
import { makeDb } from "./d1.js";

const NOW = 1_794_000_000;
const ADMIN = "a".repeat(40);
const A = "st_" + "a".repeat(26);
const B = "st_" + "b".repeat(26);
const OLD = "st_" + "c".repeat(26);
const station = (id, name, extra = {}) => ({ id, rev: 1, status: "active", name, country: "FR", sources: ["radio-browser"],
  updated_at: "2026-11-08T00:00:00Z", streams: [{ id: "sm_" + id.slice(3), url: `https://stream.example.fr/${name.toLowerCase().replace(/ /g, "")}.mp3`, protocol: "http" }], ...extra });

function dataset(stations, redirects = [], version = "2026-11-08.1") {
  const gz = (rows) => gzipSync(rows.map((r) => JSON.stringify(r) + "\n").join(""));
  const files = { "stations/FR.ndjson.gz": gz(stations), "redirects.ndjson.gz": gz(redirects),
    "health/FR.ndjson.gz": gz(stations.map((s) => ({ id: s.streams[0].id, state: "ok", codec: "mp3" }))) };
  const sha = (b) => String(b.length) + "0".repeat(64 - String(b.length).length);
  const manifest = { dataset_version: version, datasets: {
    stations: [{ shard: "FR", path: "stations/FR.ndjson.gz", sha256: sha(files["stations/FR.ndjson.gz"]) + version.at(-1) }],
    redirects: [{ shard: "all", path: "redirects.ndjson.gz", sha256: sha(files["redirects.ndjson.gz"]) }] } };
  return async (url) => {
    const path = url.replace("https://data.12moon.app/v1/", "");
    if (path === "manifest.json") return new Response(JSON.stringify(manifest));
    return files[path] ? new Response(files[path]) : new Response("", { status: 404 });
  };
}

let env;
const call = (method, path, body, token = ADMIN) => handle(new Request(`https://api.12moon.app${path}`, {
  method, headers: { ...(token ? { authorization: `Bearer ${token}` } : {}), ...(body ? { "content-type": "application/json" } : {}) },
  body: body === undefined ? undefined : JSON.stringify(body),
}), env, NOW);
const json = async (response) => ({ status: response.status, body: await response.json() });

beforeEach(async () => {
  env = { DB: makeDb(), READ_ONLY: "false", ADMIN_TOKEN: ADMIN, CHECKER_TOKEN: "c".repeat(40) };
  globalThis.fetch = dataset([station(A, "Radio Alpha", { homepage: "https://alpha.example.fr/" }), station(B, "Radio Béta", { alt_names: [{ name: "Beta FM", lang: "fr" }] })],
    [{ from: OLD, to: A, at: "2026-11-08" }]);
  await refreshCatalog(env.DB);
});

test("the catalog follows the manifest and only rereads changed shards", async () => {
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM catalog").first()).n, 2);
  assert.deepEqual((await refreshCatalog(env.DB)).done, []);
  globalThis.fetch = dataset([station(A, "Radio Alpha", { rev: 2, name: "Radio Alpha FM" })], [], "2026-11-08.2");
  const second = await refreshCatalog(env.DB);
  assert.equal(second.done[0].changed, 2); // one updated, one deleted
  const row = await env.DB.prepare("SELECT name_key FROM catalog WHERE id = ?").bind(A).first();
  assert.equal(row.name_key, "radio alpha fm");
});

test("no token, a wrong token or a revoked one is refused", async () => {
  assert.equal((await call("GET", "/v1/edit/me", undefined, null)).status, 401);
  assert.equal((await call("GET", "/v1/edit/me", undefined, "12m_" + "x".repeat(43))).status, 401);
  const { body } = await json(await call("POST", "/v1/edit/editors", { name: "agent one", role: "agent" }));
  assert.match(body.token, /^12m_[A-Za-z0-9_-]{43}$/);
  assert.equal((await call("GET", "/v1/edit/me", undefined, body.token)).status, 200);
  await call("POST", `/v1/edit/editors/${body.id}/revoke`);
  assert.equal((await call("GET", "/v1/edit/me", undefined, body.token)).status, 401);
  const stored = await env.DB.prepare("SELECT token_hash FROM editors WHERE id = ?").bind(body.id).first();
  assert.ok(!stored.token_hash.includes(body.token.slice(4, 20)));
});

test("an agent searches, edits, and waits for review only to remove", async () => {
  const { body: agent } = await json(await call("POST", "/v1/edit/editors", { name: "agent", role: "agent" }));
  const t = agent.token;
  const found = await json(await call("GET", "/v1/edit/search?q=beta", undefined, t));
  assert.deepEqual(found.body.stations.map((s) => s.id), [B]);
  assert.equal((await json(await call("GET", "/v1/edit/search?q=beta+fm", undefined, t))).body.stations[0].id, B);
  assert.equal((await json(await call("GET", "/v1/edit/search?q=alpha.example.fr", undefined, t))).body.stations[0].id, A);
  assert.equal((await json(await call("GET", `/v1/edit/search?q=${OLD}`, undefined, t))).body.stations[0].id, A);
  const set = await json(await call("POST", "/v1/edit/changes", { station: OLD, set: { homepage: "https://alpha.fr/", tags: ["jazz"] }, note: "from the site" }, t));
  assert.equal(set.status, 201);
  assert.equal(set.body.station, A);
  assert.equal(set.body.status, "accepted");
  const retire = await json(await call("POST", "/v1/edit/changes", { station: B, retire: true }, t));
  assert.equal(retire.body.status, "pending");
  assert.equal((await call("POST", `/v1/edit/changes/${retire.body.id}`, { status: "accepted" }, t)).status, 403);
  assert.equal((await call("GET", "/v1/edit/editors", undefined, t)).status, 403);
  assert.equal((await call("GET", "/v1/admin/station-reports", undefined, t)).status, 401);
  assert.equal((await call("POST", "/v1/edit/changes", { station: "st_" + "z".repeat(26), retire: true }, t)).status, 404);
  assert.equal((await call("POST", "/v1/edit/changes", { station: A, set: { tags: ["not-a-tag"] } }, t)).status, 422);
  assert.equal((await call("POST", "/v1/edit/changes", { station: A, set: { homepage: "http://192.168.1.1/" } }, t)).status, 422);

  let exported = (await json(await call("GET", "/v1/edits", undefined, null))).body.edits;
  assert.deepEqual(exported.map((e) => e.id), [set.body.id]);
  assert.equal(exported[0].note, undefined);
  assert.equal(JSON.stringify(exported).includes("agent"), false);

  assert.equal((await call("POST", `/v1/edit/changes/${retire.body.id}`, { status: "accepted" })).status, 200);
  assert.equal((await call("POST", `/v1/edit/changes/${set.body.id}`, { status: "reverted" })).status, 200);
  exported = (await json(await call("GET", "/v1/edits", undefined, null))).body.edits;
  assert.deepEqual(Object.fromEntries(exported.map((e) => [e.id, e.status])), { [set.body.id]: "withdrawn", [retire.body.id]: "accepted" });

  const view = await json(await call("GET", `/v1/edit/stations/${A}`, undefined, t));
  assert.equal(view.body.station.id, A);
  assert.equal(view.body.health[`sm_${"a".repeat(26)}`].state, "ok");
  assert.equal(view.body.edits[0].editor, "agent");
});

test("a new station from an editor goes to the stream check, an existing stream is refused", async () => {
  const known = await json(await call("POST", "/v1/edit/stations", { name: "Copy", country: "FR", streams: [{ url: "https://stream.example.fr/radioalpha.mp3" }] }));
  assert.equal(known.status, 409);
  assert.equal(known.body.station, A);
  const added = await json(await call("POST", "/v1/edit/stations", { name: "Radio Gamma", country: "BE", streams: [{ url: "https://gamma.example.be/live" }], note: "found on its site" }));
  assert.equal(added.status, 202);
  const claimed = await json(await call("POST", "/v1/admin/station-proposals/claim", undefined, "c".repeat(40)));
  assert.equal(claimed.body.proposals[0].name, "Radio Gamma");
  assert.equal((await json(await call("GET", "/v1/edit/new-stations"))).body.stations.length, 1);
});

test("validation keeps only known fields", () => {
  assert.equal(validateEdit({ station: A, set: { status: "active" } }, "agent").error, "cannot set: status");
  assert.equal(validateEdit({ station: A }, "agent").error, "nothing to change");
  assert.equal(validateEdit({ station: A, same_as: A }, "agent").error, "invalid same_as");
  assert.deepEqual(validateEdit({ station: A, set: { place: { name: "Lyon", lat: 45.76, lon: 4.84 } } }, "maintainer").value,
    { set: { place: { name: "Lyon", lat: 45.76, lon: 4.84 } } });
});

test("the page is served with a strict policy, and its module is up to date", async () => {
  const page = await call("GET", "/edit", undefined, null);
  assert.equal(page.status, 200);
  assert.match(page.headers.get("content-security-policy"), /script-src 'self'/);
  assert.doesNotMatch(readFileSync(new URL("../edit/app.js", import.meta.url), "utf8"), /innerHTML|insertAdjacentHTML|eval\(/);
  const before = readFileSync(new URL("../src/editpage.js", import.meta.url), "utf8");
  execFileSync(process.execPath, [new URL("../edit/build.mjs", import.meta.url).pathname]);
  assert.equal(readFileSync(new URL("../src/editpage.js", import.meta.url), "utf8"), before, "run node edit/build.mjs");
});
