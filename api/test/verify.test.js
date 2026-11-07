import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import { handle } from "../src/index.js";
import { revokeContributor, verifyPending } from "../src/verify.js";
import { makeDb } from "./d1.js";
import { MBID, NOW, fakeMusicBrainz, mbRelease, newClient, proposal, signed } from "./helpers.js";

let env;
beforeEach(() => {
  env = { DB: makeDb(), READ_ONLY: "false" };
});

async function propose(media = [[215, 180, 302]], mbid = MBID, client) {
  const who = client ?? (await newClient());
  const response = await handle(await signed(who, "POST", "/v1/proposals", proposal(media, mbid)), env, NOW);
  return { id: (await response.json()).id, client: who };
}

const run = (table, now = NOW) =>
  verifyPending(env.DB, { now, fetchImpl: fakeMusicBrainz(table).fetchImpl, sleep: async () => {} });

const status = (id) => env.DB.raw.prepare("SELECT status, reason, link_id FROM proposals WHERE id = ?").get(id);
const links = () => env.DB.raw.prepare("SELECT * FROM links").all();

test("a track list that matches MusicBrainz is published", async () => {
  const { id } = await propose();
  const summary = await run({ [MBID]: mbRelease([[215400, 179600, 301000]]) });
  assert.equal(summary.accepted, 1);
  assert.equal(status(id).status, "accepted");
  assert.equal(links()[0].verified_by, "musicbrainz");
});

test("a track list that disagrees is rejected", async () => {
  const { id } = await propose();
  await run({ [MBID]: mbRelease([[215000, 180000, 330000]]) });
  assert.deepEqual([status(id).status, status(id).reason], ["rejected", "tracklist_mismatch"]);
  assert.equal(links().length, 0);
});

test("an unknown release is rejected", async () => {
  const { id } = await propose();
  await run({});
  assert.equal(status(id).reason, "unknown_release");
});

test("a merged release is linked to its current identifier", async () => {
  const merged = "2c022e01-4da6-387b-8658-8678046e4cef";
  await propose();
  await run({ [MBID]: mbRelease([[215000, 180000, 302000]], merged) });
  assert.equal(links()[0].musicbrainz_release, merged);
});

test("MusicBrainz down: the proposal waits and is retried", async () => {
  const { id } = await propose();
  const summary = await run({ [MBID]: 503 });
  assert.equal(summary.retried, 1);
  assert.equal(status(id).status, "pending");
  assert.equal((await run({ [MBID]: mbRelease([[215000, 180000, 302000]]) }, NOW + 3600)).accepted, 1);
});

test("without lengths, two contributors are needed", async () => {
  const noLengths = { [MBID]: mbRelease([[null, null, null]]) };
  const first = await propose();
  await run(noLengths);
  assert.equal(status(first.id).status, "pending");
  const second = await propose();
  await run(noLengths, NOW + 2 * 86400);
  assert.equal(status(first.id).status, "accepted");
  assert.equal(status(second.id).status, "accepted");
  assert.equal(links()[0].verified_by, "consensus");
});

test("one contributor proposing twice is not a consensus", async () => {
  const noLengths = { [MBID]: mbRelease([[null, null, null]]) };
  const first = await propose();
  await propose([[215, 180, 302]], MBID, first.client);
  await run(noLengths);
  assert.equal(status(first.id).status, "pending");
});

test("revoking a contributor retracts what depended only on them", async () => {
  const noLengths = { [MBID]: mbRelease([[null, null, null]]) };
  const a = await propose();
  const b = await propose();
  await run(noLengths);
  const checked = await propose([[100, 200]], "3c022e01-4da6-387b-8658-8678046e4cef", a.client);
  await run({ "3c022e01-4da6-387b-8658-8678046e4cef": mbRelease([[100000, 200000]], "3c022e01-4da6-387b-8658-8678046e4cef") }, NOW + 10);
  const contributorA = env.DB.raw.prepare("SELECT contributor_id FROM proposals WHERE id = ?").get(a.id).contributor_id;
  const result = await revokeContributor(env.DB, contributorA, NOW + 20);
  assert.equal(result.retracted, 1);
  const byVerification = Object.fromEntries(links().map((l) => [l.verified_by, l.status]));
  assert.deepEqual(byVerification, { consensus: "retracted", musicbrainz: "active" });
  assert.equal(status(b.id).status, "accepted");
  assert.equal(status(checked.id).status, "revoked");
});

test("MusicBrainz is called once per release, with an identifiable User-Agent", async () => {
  await propose();
  await propose();
  const mb = fakeMusicBrainz({ [MBID]: mbRelease([[215000, 180000, 302000]]) });
  await verifyPending(env.DB, { now: NOW, fetchImpl: mb.fetchImpl, sleep: async () => {} });
  assert.equal(mb.calls.length, 1);
  assert.match(mb.calls[0].userAgent, /^12moon-commons\/\d/);
});

test("published links are exported without any contributor", async () => {
  await propose();
  await run({ [MBID]: mbRelease([[215000, 180000, 302000]]) });
  const response = await handle(new Request("https://api.12moon.app/v1/links/release-matches"), env, NOW);
  const body = await response.json();
  assert.equal(body.links.length, 1);
  assert.deepEqual(Object.keys(body.links[0]).sort(), ["cursor", "id", "media", "musicbrainz_release", "status", "updated_at", "verified_by"]);
  assert.ok(!JSON.stringify(body).includes("contributor"));
});
