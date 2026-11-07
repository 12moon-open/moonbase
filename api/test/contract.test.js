import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { compareRelease } from "../src/musicbrainz.js";
import { validateProposal } from "../src/validate.js";

const cases = (kind) => {
  const dir = new URL(`../../contract/v1/cases/${kind}/`, import.meta.url);
  return readdirSync(dir).filter((n) => n.endsWith(".json")).map((n) => [n, JSON.parse(readFileSync(new URL(n, dir), "utf8"))]);
};

test("valid proposals from the contract are accepted", () => {
  for (const [name, c] of cases("valid").filter(([, c]) => c.schema === "proposal")) {
    assert.equal(validateProposal(c.input), null, name);
  }
});

test("invalid proposals from the contract are refused", () => {
  const invalid = cases("invalid").filter(([, c]) => c.schema === "proposal");
  assert.ok(invalid.length >= 5);
  for (const [name, c] of invalid) assert.notEqual(validateProposal(c.input), null, name);
});

test("track list comparison follows the contract", () => {
  for (const [name, c] of cases("match")) {
    assert.equal(compareRelease(c.input.media, c.input.release), c.expected, name);
  }
});
