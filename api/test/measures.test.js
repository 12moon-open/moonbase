import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { beforeEach, test } from "node:test";
import { handle } from "../src/index.js";
import { MIN_REPORTS, acceptedWeeks, isoWeek, purgeMeasures, validateMeasures } from "../src/measures.js";
import { makeDb } from "./d1.js";
import { NOW, newClient, signed } from "./helpers.js";

const FIP = "sm_feoydw2o5i6hhry4gvnoppdbv6";
const OTHER = "sm_01jc8w5m2c4t8h1p9e3rkvz7qd";
const LAST_WEEK = acceptedWeeks(NOW)[0];

let env;
beforeEach(() => {
  env = { DB: makeDb(), READ_ONLY: "false" };
});

const call = (request, now = NOW) => handle(request, env, now);
const report = (streams, week = LAST_WEEK) => ({ kind: "stream_measures", week, streams });
const send = async (body, client) => call(await signed(client ?? (await newClient()), "POST", "/v1/measures", body));
const health = async (now = NOW) => (await (await call(new Request("https://api.12moon.app/v1/measures/streams"), now)).json()).streams;

const cases = (kind) => {
  const dir = new URL(`../../contract/v1/cases/${kind}/`, import.meta.url);
  return readdirSync(dir).filter((n) => n.endsWith(".json")).map((n) => [n, JSON.parse(readFileSync(new URL(n, dir), "utf8"))])
    .filter(([, c]) => c.schema === "stream-measures");
};

test("contract cases for stream measures", () => {
  for (const [name, c] of cases("valid")) assert.equal(validateMeasures(c.input), null, name);
  const invalid = cases("invalid");
  assert.ok(invalid.length >= 5);
  for (const [name, c] of invalid) assert.notEqual(validateMeasures(c.input), null, name);
});

test("more failures than attempts is refused", () => {
  assert.equal(validateMeasures(report([{ stream: FIP, attempts: 2, failures: { timeout: 2, dns: 1 } }])), "more failures than attempts");
});

test("a report is accepted once per key and week", async () => {
  const client = await newClient();
  const first = await send(report([{ stream: FIP, attempts: 3 }]), client);
  assert.equal(first.status, 202);
  assert.equal((await send(report([{ stream: OTHER, attempts: 1 }]), client)).status, 409);
  assert.equal((await send(report([{ stream: FIP, attempts: 1 }]))).status, 202);
});

test("only finished recent weeks are accepted", async () => {
  assert.equal((await send(report([{ stream: FIP, attempts: 1 }], isoWeek(NOW * 1000)))).status, 422);
  assert.equal((await send(report([{ stream: FIP, attempts: 1 }], "2020-W10"))).status, 422);
});

test("nothing stored identifies the sender or links one report's rows", async () => {
  const client = await newClient();
  const request = await signed(client, "POST", "/v1/measures", report([{ stream: FIP, attempts: 1 }, { stream: OTHER, attempts: 2 }]));
  request.headers.set("cf-connecting-ip", "203.0.113.9");
  const key = request.headers.get("x-12moon-key");
  await call(request);
  const dump = JSON.stringify(
    ["stream_measures", "measure_senders", "measure_weeks", "contributors"].map((t) => env.DB.raw.prepare(`SELECT * FROM ${t}`).all()),
  );
  assert.ok(!dump.includes("203.0.113.9"));
  assert.ok(!dump.includes(key));
  assert.equal(env.DB.raw.prepare("SELECT COUNT(*) AS n FROM contributors").get().n, 0);
  const columns = env.DB.raw.prepare("SELECT name FROM pragma_table_info('stream_measures')").all().map((c) => c.name);
  assert.deepEqual(columns, ["stream", "week", "tie", "success", "startup_ms", "stalls_per_play", "geo_blocked", "codec", "bitrate_kbps"]);
});

test("a score needs three installations in the same week", async () => {
  for (let i = 0; i < MIN_REPORTS - 1; i += 1) await send(report([{ stream: FIP, attempts: 4 }]));
  assert.deepEqual(await health(), []);
  await send(report([{ stream: FIP, attempts: 4 }]));
  assert.equal((await health()).length, 1);
});

test("one installation counts once, and the score is a median", async () => {
  await send(report([{ stream: FIP, attempts: 20, failures: { timeout: 20 }, startup_ms: 9000, stalls: 50 }]));
  for (let i = 0; i < 3; i += 1) {
    await send(report([{ stream: FIP, attempts: 2, startup_ms: 1500, stalls: 0, codec: "aac", bitrate_kbps: 192 }]));
  }
  const [score] = await health();
  assert.equal(score.id, FIP);
  assert.equal(score.success_rate, 1);
  assert.equal(score.startup_ms_p50, 1500);
  assert.equal(score.stalls_per_play, 0);
  assert.equal(score.codec, "aac");
  assert.equal(score.bitrate_kbps, 192);
  assert.equal(score.reports, "3+");
  assert.equal(score.geo_restricted, false);
});

test("codec needs three agreeing reports, geo blocking is not a failure", async () => {
  await send(report([{ stream: FIP, attempts: 2, codec: "mp3" }]));
  for (let i = 0; i < 3; i += 1) await send(report([{ stream: FIP, attempts: 2, failures: { geo_blocked: 2 } }]));
  const [score] = await health();
  assert.equal(score.codec, undefined);
  assert.equal(score.geo_restricted, true);
  assert.equal(score.success_rate, 1);
});

test("old measures and week secrets are purged", async () => {
  for (let i = 0; i < 3; i += 1) await send(report([{ stream: FIP, attempts: 1 }]));
  const later = NOW + 10 * 7 * 86400;
  await purgeMeasures(env.DB, later);
  for (const table of ["stream_measures", "measure_senders", "measure_weeks"]) {
    assert.equal(env.DB.raw.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n, 0, table);
  }
});
