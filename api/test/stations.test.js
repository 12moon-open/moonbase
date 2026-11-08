import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { beforeEach, test } from "node:test";
import { handle } from "../src/index.js";
import { DAILY_STATIONS, cleanText, publicHost, validateStationAdd } from "../src/stations.js";
import { makeDb } from "./d1.js";
import { NOW, newClient, signed } from "./helpers.js";

const TOKEN = "t".repeat(40);
const CHECKER = "c".repeat(40);
let env;
let client;
beforeEach(async () => {
  env = { DB: makeDb(), READ_ONLY: "false", ADMIN_TOKEN: TOKEN, CHECKER_TOKEN: CHECKER };
  client = await newClient();
});

const call = (request, now = NOW) => handle(request, env, now);
const station = (extra = {}) => ({
  kind: "station_add", name: "Radio Exemple", country: "FR",
  streams: [{ url: "https://stream.example.fr/live.mp3?utm_source=x" }], consent: "CC0-1.0", ...extra,
});
const propose = async (body = station(), who = client) => call(await signed(who, "POST", "/v1/proposals", body));
const adminCall = (method, path, body, token = TOKEN) =>
  call(new Request(`https://api.12moon.app${path}`, {
    method, headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }));
const exported = async () => (await (await call(new Request("https://api.12moon.app/v1/contributions/stations"))).json()).stations;

const cases = (kind) => {
  const dir = new URL(`../../contract/v1/cases/${kind}/`, import.meta.url);
  return readdirSync(dir).filter((n) => n.endsWith(".json")).map((n) => [n, JSON.parse(readFileSync(new URL(n, dir), "utf8"))])
    .filter(([, c]) => c.schema === "station-proposal");
};

test("contract cases for station proposals", () => {
  for (const [name, c] of cases("valid")) assert.equal(validateStationAdd(c.input).error, undefined, name);
  const invalid = cases("invalid");
  assert.ok(invalid.length >= 5);
  for (const [name, c] of invalid) assert.ok(validateStationAdd(c.input).error, name);
});

test("names and places carry no address, e-mail or phone number", () => {
  assert.equal(cleanText("  FIP   Jazz ", 100), "FIP Jazz");
  assert.equal(cleanText("Radio 107.7", 100), "Radio 107.7");
  for (const bad of ["Visit www.spam.example", "best radio.com", "call +33 6 12 34 56 78", "me@example.org", "a‮b"]) {
    assert.equal(cleanText(bad, 100), null, bad);
  }
});

test("private and local stream hosts are refused", () => {
  for (const host of ["127.0.0.1", "10.1.2.3", "192.168.1.10", "169.254.1.1", "localhost", "nas.local", "[::1]", "printer"]) {
    assert.equal(publicHost(host), false, host);
  }
  assert.equal(publicHost("stream.example.fr"), true);
  assert.equal(publicHost("93.184.216.34"), true);
  assert.ok(validateStationAdd(station({ streams: [{ url: "http://192.168.1.10:8000/live" }] })).error);
  assert.ok(validateStationAdd(station({ tags: ["not-a-known-tag"] })).error);
});

test("a station is queued, checked, then exported without its contributor", async () => {
  const sent = await propose();
  assert.equal(sent.status, 202);
  const { id } = await sent.json();
  assert.match(id, /^pr_/);

  assert.equal((await adminCall("POST", "/v1/admin/station-proposals/claim", undefined, "wrong")).status, 401);
  const claimed = (await (await adminCall("POST", "/v1/admin/station-proposals/claim")).json()).proposals;
  assert.equal(claimed.length, 1);
  assert.equal(claimed[0].streams[0], "https://stream.example.fr/live.mp3");
  assert.equal((await (await call(new Request(`https://api.12moon.app/v1/proposals/${id}`))).json()).status, "pending");

  const decided = await adminCall("POST", `/v1/admin/station-proposals/${id}`, {
    status: "published", streams: [{ url: "https://stream.example.fr/live.mp3", protocol: "http", codec: "mp3", bitrate_kbps: 128 }],
  });
  assert.equal(decided.status, 200);
  const [row] = await exported();
  assert.equal(row.id, id);
  assert.equal(row.name, "Radio Exemple");
  assert.deepEqual(row.streams, [{ url: "https://stream.example.fr/live.mp3", protocol: "http", codec: "mp3", bitrate_kbps: 128 }]);
  assert.ok(!JSON.stringify(row).includes("contributor"));
});

test("the checker cannot publish a stream that was not proposed", async () => {
  const { id } = await (await propose()).json();
  const bad = await adminCall("POST", `/v1/admin/station-proposals/${id}`, { status: "published", streams: [{ url: "https://evil.example/x" }] });
  assert.equal(bad.status, 422);
});

test("a duplicate points to the existing station", async () => {
  const { id } = await (await propose()).json();
  await adminCall("POST", `/v1/admin/station-proposals/${id}`, { status: "duplicate", station: "st_ov2zc5iv2saqhv4kvf4uf7p5le" });
  const status = await (await call(new Request(`https://api.12moon.app/v1/proposals/${id}`))).json();
  assert.deepEqual(status, { id, status: "duplicate", station: "st_ov2zc5iv2saqhv4kvf4uf7p5le" });
});

test("same station twice from one installation is not duplicated, and there is a daily limit", async () => {
  const first = await (await propose()).json();
  const again = await propose();
  assert.equal(again.status, 200);
  assert.equal((await again.json()).id, first.id);
  for (let i = 1; i < DAILY_STATIONS; i += 1) {
    assert.equal((await propose(station({ streams: [{ url: `https://s${i}.example.fr/live` }] }))).status, 202);
  }
  assert.equal((await propose(station({ streams: [{ url: "https://last.example.fr/live" }] }))).status, 429);
});

test("blocking a contributor withdraws its stations from the export", async () => {
  const { id } = await (await propose()).json();
  await adminCall("POST", `/v1/admin/station-proposals/${id}`, { status: "published", streams: [{ url: "https://stream.example.fr/live.mp3" }] });
  const [listed] = (await (await adminCall("GET", "/v1/admin/station-proposals?status=published")).json()).proposals;
  await adminCall("POST", `/v1/admin/contributors/${listed.contributor_id}/block`);
  const rows = await exported();
  assert.deepEqual(rows.map((r) => [r.id, r.status, r.name]), [[id, "withdrawn", undefined]]);
  assert.equal((await propose(station({ streams: [{ url: "https://other.example.fr/x" }] }))).status, 403);
});

test("a station report is recorded and listed for the maintainer", async () => {
  const sent = await call(await signed(client, "POST", "/v1/reports", { station: "st_ov2zc5iv2saqhv4kvf4uf7p5le", reason: "dead_stream" }));
  assert.equal(sent.status, 202);
  const reports = (await (await adminCall("GET", "/v1/admin/station-reports")).json()).reports;
  assert.equal(reports[0].reason, "dead_stream");
  assert.ok(!("contributor_id" in reports[0]));
  const bad = await call(await signed(client, "POST", "/v1/reports", { station: "st_ov2zc5iv2saqhv4kvf4uf7p5le", reason: "i hate it" }));
  assert.equal(bad.status, 422);
});

test("erasing a contributor keeps its published stations without it", async () => {
  const { id } = await (await propose()).json();
  await adminCall("POST", `/v1/admin/station-proposals/${id}`, { status: "published", streams: [{ url: "https://stream.example.fr/live.mp3" }] });
  await call(await signed(client, "DELETE", "/v1/contributors/me"));
  const row = env.DB.raw.prepare("SELECT contributor_id, status FROM station_proposals").get();
  assert.deepEqual({ ...row }, { contributor_id: null, status: "published" });
});

test("the checker token can only claim and decide, never block or hide", async () => {
  const { id } = await (await propose()).json();
  assert.equal((await adminCall("POST", "/v1/admin/station-proposals/claim", undefined, CHECKER)).status, 200);
  assert.equal((await adminCall("POST", `/v1/admin/station-proposals/${id}`, { status: "hidden" }, CHECKER)).status, 403);
  assert.equal((await adminCall("POST", `/v1/admin/station-proposals/${id}`, { status: "rejected", reason: "not_audio" }, CHECKER)).status, 200);
  assert.equal((await adminCall("GET", "/v1/admin/station-proposals?status=published", undefined, CHECKER)).status, 403);
  assert.equal((await adminCall("GET", "/v1/admin/station-reports", undefined, CHECKER)).status, 403);
  assert.equal((await adminCall("POST", "/v1/admin/contributors/abcdefghijklmnopqrstuv/block", undefined, CHECKER)).status, 403);
});
