import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { beforeEach, test } from "node:test";
import { validateEdit } from "../src/edits.js";
import { handle } from "../src/index.js";
import { makeDb } from "./d1.js";

const NOW = 1_794_000_000;
const ADMIN = "a".repeat(40);
const A = "st_" + "a".repeat(26);
const B = "st_" + "b".repeat(26);
const OLD = "st_" + "c".repeat(26);
let env;
const call = (method, path, body, token = ADMIN) => handle(new Request(`https://api.12moon.app${path}`, {
  method, headers: { ...(token ? { authorization: `Bearer ${token}` } : {}), ...(body ? { "content-type": "application/json" } : {}) },
  body: body === undefined ? undefined : JSON.stringify(body),
}), env, NOW);
const json = async (response) => ({ status: response.status, body: await response.json() });

beforeEach(async () => {
  env = { DB: makeDb(), READ_ONLY: "false", ADMIN_TOKEN: ADMIN, CHECKER_TOKEN: "c".repeat(40) };
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

test("an agent edits, and waits for review only to remove", async () => {
  const { body: agent } = await json(await call("POST", "/v1/edit/editors", { name: "agent", role: "agent" }));
  const t = agent.token;
  const set = await json(await call("POST", "/v1/edit/changes", { station: OLD, set: { homepage: "https://alpha.fr/", tags: ["jazz"] }, note: "from the site" }, t));
  assert.equal(set.status, 201);
  assert.equal(set.body.status, "accepted");
  const retire = await json(await call("POST", "/v1/edit/changes", { station: B, retire: true }, t));
  assert.equal(retire.body.status, "pending");
  assert.equal((await call("POST", `/v1/edit/changes/${retire.body.id}`, { status: "accepted" }, t)).status, 403);
  assert.equal((await call("GET", "/v1/edit/editors", undefined, t)).status, 403);
  assert.equal((await call("GET", "/v1/admin/station-reports", undefined, t)).status, 401);
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

  const mine = (await json(await call("GET", `/v1/edit/changes?station=${B}`, undefined, t))).body.edits;
  assert.deepEqual(mine.map((e) => [e.editor, e.status]), [["agent", "accepted"]]);
});

test("a token still works when its last use cannot be written", async () => {
  const { body } = await json(await call("POST", "/v1/edit/editors", { name: "reader", role: "agent" }));
  const db = env.DB;
  env.DB = { ...db, prepare: (sql) => (sql.startsWith("UPDATE editors") ? { bind: () => ({ run: async () => { throw new Error("D1 write limit"); } }) } : db.prepare(sql)) };
  assert.equal((await call("GET", "/v1/edit/me", undefined, body.token)).status, 200);
});

test("a new station from an editor goes to the stream check", async () => {
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
