import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import { handle } from "../src/index.js";
import { DAILY_PROPOSALS } from "../src/store.js";
import { makeDb } from "./d1.js";
import { NOW, newClient, proposal, signed } from "./helpers.js";

let env;
let client;
beforeEach(async () => {
  env = { DB: makeDb(), READ_ONLY: "false" };
  client = await newClient();
});

const call = (request, now = NOW) => handle(request, env, now);

test("a signed proposal is queued", async () => {
  const response = await call(await signed(client, "POST", "/v1/proposals", proposal()));
  assert.equal(response.status, 202);
  const body = await response.json();
  assert.match(body.id, /^pr_[0-9a-z]{26}$/);
  const status = await call(new Request(`https://api.12moon.app/v1/proposals/${body.id}`));
  assert.equal((await status.json()).status, "pending");
});

test("no IP address or personal field is stored", async () => {
  const request = await signed(client, "POST", "/v1/proposals", proposal());
  request.headers.set("cf-connecting-ip", "203.0.113.9");
  await call(request);
  const dump = JSON.stringify(env.DB.raw.prepare("SELECT * FROM proposals").all()) +
    JSON.stringify(env.DB.raw.prepare("SELECT * FROM contributors").all());
  assert.ok(!dump.includes("203.0.113.9"));
  const columns = env.DB.raw.prepare("SELECT name FROM pragma_table_info('contributors')").all().map((c) => c.name);
  assert.deepEqual(columns, ["id", "public_key", "created_at", "blocked_at"]);
});

test("the same proposal twice is not duplicated", async () => {
  const first = await (await call(await signed(client, "POST", "/v1/proposals", proposal()))).json();
  const again = await call(await signed(client, "POST", "/v1/proposals", proposal()));
  assert.equal(again.status, 200);
  assert.equal((await again.json()).id, first.id);
});

test("unsigned, tampered, stale and replayed requests are refused", async () => {
  const unsigned = new Request("https://api.12moon.app/v1/proposals", { method: "POST", body: JSON.stringify(proposal()) });
  assert.equal((await call(unsigned)).status, 401);

  const good = await signed(client, "POST", "/v1/proposals", proposal());
  const tampered = new Request(good.url, { method: "POST", headers: good.headers, body: JSON.stringify(proposal([[1]])) });
  assert.equal((await call(tampered)).status, 401);

  const otherPath = await signed(client, "POST", "/v1/reports", proposal());
  assert.equal((await call(new Request("https://api.12moon.app/v1/proposals", { method: "POST", headers: otherPath.headers, body: JSON.stringify(proposal()) }))).status, 401);

  const stale = await signed(client, "POST", "/v1/proposals", proposal(), { now: NOW - 3600 });
  assert.equal((await call(stale)).status, 401);

  const once = await signed(client, "POST", "/v1/proposals", proposal(), { nonce: "replay-nonce-000001" });
  const copy = once.clone();
  assert.equal((await call(once)).status, 202);
  assert.equal((await call(copy)).status, 401);
});

test("free text and URLs are refused", async () => {
  const response = await call(await signed(client, "POST", "/v1/proposals", { ...proposal(), comment: "hello" }));
  assert.equal(response.status, 422);
});

test("oversized bodies are refused", async () => {
  const huge = proposal(Array.from({ length: 20 }, () => Array.from({ length: 200 }, () => 36000)));
  assert.equal((await call(await signed(client, "POST", "/v1/proposals", huge))).status, 413);
});

test("a blocked contributor cannot propose", async () => {
  await call(await signed(client, "POST", "/v1/proposals", proposal()));
  env.DB.raw.exec("UPDATE contributors SET blocked_at = 1");
  assert.equal((await call(await signed(client, "POST", "/v1/proposals", proposal([[100]])))).status, 403);
});

test("the daily limit applies", async () => {
  const insert = env.DB.raw.prepare(
    "INSERT INTO proposals (id, contributor_id, kind, fingerprint, media, musicbrainz_release, status, next_attempt_at, created_at) VALUES (?, ?, 'release_match', ?, '[[1]]', 'x', 'pending', 0, ?)",
  );
  await call(await signed(client, "POST", "/v1/proposals", proposal()));
  const id = env.DB.raw.prepare("SELECT id FROM contributors").get().id;
  for (let i = 0; i < DAILY_PROPOSALS; i += 1) insert.run(`pr_fill${i}`, id, `f${i}`, NOW);
  assert.equal((await call(await signed(client, "POST", "/v1/proposals", proposal([[99]])))).status, 429);
});

test("read-only mode refuses writes but serves reads", async () => {
  env.READ_ONLY = "true";
  assert.equal((await call(await signed(client, "POST", "/v1/proposals", proposal()))).status, 503);
  assert.equal((await call(new Request("https://api.12moon.app/v1/health"))).status, 200);
});

test("a contributor can erase itself", async () => {
  await call(await signed(client, "POST", "/v1/proposals", proposal()));
  const response = await call(await signed(client, "DELETE", "/v1/contributors/me"));
  assert.equal(response.status, 200);
  assert.equal(env.DB.raw.prepare("SELECT COUNT(*) AS n FROM contributors").get().n, 0);
  assert.equal(env.DB.raw.prepare("SELECT contributor_id FROM proposals").get().contributor_id, null);
});
