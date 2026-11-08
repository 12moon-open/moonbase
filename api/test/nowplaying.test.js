import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { AdapterError, cssSelect, parseMarkup, resolve, run } from "../src/nowplaying.js";

const contract = new URL("../../contract/v1/", import.meta.url);
const read = (dir) => readdirSync(new URL(dir, contract)).filter((n) => n.endsWith(".json"))
  .map((n) => [n, JSON.parse(readFileSync(new URL(dir + n, contract), "utf8"))]);
const templates = Object.fromEntries(read("now-playing/templates/").map(([, t]) => [t.id, t]));

for (const [name, c] of read("cases/now-playing/")) {
  test(`now playing: ${name}`, () => {
    let got;
    try {
      got = run(resolve(c.adapter, templates), c.response, c.now, c.station_name);
    } catch (error) {
      if (!(error instanceof AdapterError)) throw error;
      got = { error: error.reason };
    }
    assert.deepEqual(got, c.expected, c.description);
  });
}

test("css subset: child, nth-of-type, attribute", () => {
  const root = parseMarkup('<ul><li class="a">1</li><li class="a b">2<span x="y">s</span></li></ul><p><li>3</li></p>', false);
  assert.deepEqual(cssSelect(root, "ul > li.a", false).length, 2);
  assert.equal(cssSelect(root, "li:nth-of-type(2) span[x=y]", false).length, 1);
  assert.equal(cssSelect(root, "ul li", false).length, 2);
  assert.throws(() => cssSelect(root, "li:has(span)", false), AdapterError);
});
