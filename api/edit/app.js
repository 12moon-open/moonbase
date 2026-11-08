"use strict";
// The edit page. Every value from the data is put in the page as text, never as HTML.

const $ = (id) => document.getElementById(id);
const DATA = "https://data.12moon.app/v1/";
let me = null;
// The published dataset, read once per session: id → { record, shard, find }.
const stations = new Map();
const redirects = new Map();
let dataVersion = null;

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}

const token = () => sessionStorage.getItem("token");

async function api(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: { authorization: `Bearer ${token()}`, ...(body ? { "content-type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
    credentials: "omit",
  });
  if (response.status === 401) {
    sessionStorage.removeItem("token");
    showLogin("Token refused.");
    throw new Error("unauthorized");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error ? `${data.error}${data.station ? " (" + data.station + ")" : ""}` : `HTTP ${response.status}`);
  return data;
}

const date = (s) => new Date(s * 1000).toISOString().slice(0, 16).replace("T", " ");
const list = (text) => text.split(",").map((s) => s.trim()).filter(Boolean);
const link = (url) => (!url ? "" : /^https?:\/\//i.test(url)
  ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer", class: "url" }, url) : h("span", { class: "url" }, url));

function showLogin(message = "") {
  $("app").hidden = true;
  $("logout").hidden = true;
  $("who").textContent = "";
  $("login").hidden = false;
  $("login-error").textContent = message;
}

async function start() {
  try {
    me = await api("GET", "/v1/edit/me");
  } catch (e) {
    if (e.message !== "unauthorized") showLogin(e.message);
    return;
  }
  $("login").hidden = true;
  $("app").hidden = false;
  $("logout").hidden = false;
  $("who").textContent = `· ${me.name} (${me.role})`;
  for (const b of document.querySelectorAll("[data-role]")) b.hidden = b.dataset.role !== me.role;
  tab("search");
  if (!dataVersion) loadData();
}

// --- The published dataset ---

async function readGzip(url) {
  const response = await fetch(url, { cache: "no-cache", credentials: "omit" });
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  const text = await new Response(response.body.pipeThrough(new DecompressionStream("gzip"))).text();
  return text.split("\n").filter(Boolean).map((line) => JSON.parse(line));
}

function nameKey(text) {
  return (typeof text === "string" ? text : "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

function findText(r) {
  const parts = [nameKey(r.name), ...(r.alt_names || []).map((n) => nameKey(n.name || n)), r.id];
  if (r.homepage) parts.push(r.homepage.toLowerCase().replace(/^https?:\/\//, ""));
  for (const m of r.streams || []) parts.push(m.id, m.url.toLowerCase().replace(/^https?:\/\//, ""));
  return parts.join(" | ");
}

async function loadData() {
  const label = $("catalog");
  try {
    const manifest = await (await fetch(DATA + "manifest.json", { cache: "no-cache", credentials: "omit" })).json();
    const entries = manifest.datasets.stations;
    let done = 0;
    label.textContent = `Loading stations 0/${entries.length}…`;
    const queue = [...entries];
    const worker = async () => {
      for (let entry = queue.shift(); entry; entry = queue.shift()) {
        for (const r of await readGzip(DATA + entry.path)) stations.set(r.id, { record: r, shard: entry.shard, find: findText(r),
          name: " " + [r.name, ...(r.alt_names || []).map((n) => n.name || n)].map(nameKey).join(" ") });
        label.textContent = `Loading stations ${++done}/${entries.length}…`;
      }
    };
    await Promise.all([1, 2, 3, 4, 5, 6].map(worker));
    for (const r of await readGzip(DATA + manifest.datasets.redirects[0].path)) redirects.set(r.from, r.to);
    dataVersion = manifest.dataset_version;
    label.textContent = `${stations.size} stations, dataset ${dataVersion}`;
  } catch (e) {
    label.className = "error";
    label.textContent = `Could not load the dataset: ${e.message}`;
  }
}

const resolve = (id) => (stations.has(id) ? id : redirects.get(id) || id);
const healthCache = new Map();
function healthOf(shard) {
  if (!healthCache.has(shard)) healthCache.set(shard, readGzip(`${DATA}health/${shard}.ndjson.gz`).catch(() => []));
  return healthCache.get(shard);
}

/** Station ids already holding one of these stream addresses. */
function holders(urls) {
  const keys = urls.map((u) => u.toLowerCase().replace(/^https?:\/\//, "").replace(/\/+$/, "")).filter((k) => k.length >= 8);
  return [...stations.values()].filter((s) => keys.some((k) => s.find.includes(k))).map((s) => s.record);
}

function tab(name) {
  for (const b of document.querySelectorAll("nav button")) b.classList.toggle("on", b.dataset.tab === name);
  for (const s of document.querySelectorAll("main section")) s.hidden = s.id !== name;
  ({ review: showReview, add: showAdd, editors: showEditors })[name]?.();
}

// --- Search and station ---

function runSearch(event) {
  event?.preventDefault();
  const table = $("results");
  if (!dataVersion) {
    table.replaceChildren(h("tr", {}, h("td", { class: "muted" }, "The dataset is still loading.")));
    return;
  }
  const q = $("q").value.trim();
  const country = $("country").value.trim().toUpperCase();
  const id = q.match(/^st_[0-9a-z]{26}$/) ? resolve(q) : null;
  const words = id ? [id] : /[./:_]/.test(q) ? [q.toLowerCase().replace(/^https?:\/\//, "")] : nameKey(q).split(" ").filter(Boolean);
  if (!words.length && !country) return;
  const key = nameKey(q);
  // 0: every word starts a word of the name, 1: every word is in the name, 2: in an address or an id.
  const tier = (s) => (words.every((w) => s.name.includes(" " + w)) ? 0 : words.every((w) => s.name.includes(w)) ? 1
    : words.every((w) => s.find.includes(w)) ? 2 : 3);
  const found = [...stations.values()]
    .filter((s) => !country || s.record.country === country)
    .map((s) => ({ ...s, tier: tier(s) }))
    .filter((s) => s.tier < 3)
    .sort((a, b) => a.tier - b.tier || (b.record.status === "active") - (a.record.status === "active")
      || (nameKey(b.record.name) === key) - (nameKey(a.record.name) === key)
      || nameKey(b.record.name).startsWith(key) - nameKey(a.record.name).startsWith(key)
      || a.record.name.length - b.record.name.length)
    .slice(0, 100).map((s) => s.record);
  table.replaceChildren(
    h("tr", {}, h("th", {}, "Name"), h("th", {}, "Country"), h("th", {}, "Streams"), h("th", {}, "Status"), h("th", {}, "Site")),
    ...found.map((s) => h("tr", { class: "click", onclick: () => openStation(s.id) },
      h("td", {}, s.name), h("td", {}, s.country || ""), h("td", {}, (s.streams || []).length), h("td", {}, s.status), h("td", { class: "url muted" }, s.homepage || ""))),
  );
  if (!found.length) table.replaceChildren(h("tr", {}, h("td", { class: "muted" }, "Nothing found.")));
}

async function openStation(id) {
  const box = $("station");
  box.replaceChildren(h("p", { class: "muted" }, "Loading…"));
  const target = resolve(id);
  const entry = stations.get(target);
  if (!entry) {
    box.replaceChildren(h("p", { class: "error" }, `${id} is not in the published dataset.`));
    return;
  }
  let view;
  try {
    const [{ edits }, health] = await Promise.all([api("GET", `/v1/edit/changes?station=${target}`), healthOf(entry.shard)]);
    const ids = new Set((entry.record.streams || []).map((m) => m.id));
    view = { station: entry.record, edits, health: Object.fromEntries(health.filter((r) => ids.has(r.id)).map((r) => [r.id, r])),
      redirected_from: target !== id ? id : undefined };
  } catch (e) {
    box.replaceChildren(h("p", { class: "error" }, e.message));
    return;
  }
  const s = view.station;
  const place = s.place || {};
  const f = {
    name: h("input", { value: s.name }),
    homepage: h("input", { value: s.homepage || "" }),
    logo_url: h("input", { value: s.logo_url || "" }),
    country: h("input", { value: s.country || "", maxlength: 2, size: 3 }),
    city: h("input", { value: place.name || "" }),
    lat: h("input", { value: place.lat ?? "", size: 10 }),
    lon: h("input", { value: place.lon ?? "", size: 10 }),
    languages: h("input", { value: (s.languages || []).join(", ") }),
    tags: h("input", { value: (s.tags || []).join(", "), list: "tags" }),
    add: h("textarea", { rows: 2, placeholder: "one stream address per line" }),
    same: h("input", { placeholder: "st_… of the same station, to merge" }),
    retire: h("input", { type: "checkbox" }),
    note: h("input", { placeholder: "why (kept private)" }),
  };
  const remove = new Map();
  const rows = (s.streams || []).map((m) => {
    const health = view.health[m.id] || {};
    const box = h("input", { type: "checkbox" });
    remove.set(m.id, box);
    return h("tr", {},
      h("td", {}, box),
      h("td", {}, link(m.url), h("div", { class: "muted" }, m.id)),
      h("td", {}, [health.codec || m.codec, health.bitrate_kbps || m.bitrate_kbps].filter(Boolean).join(" ")),
      h("td", { class: health.state === "ok" ? "ok" : health.state ? "error" : "muted" }, health.state || "?", health.error ? ` (${health.error})` : ""));
  });
  const status = h("span");
  const save = async (event) => {
    event.preventDefault();
    const set = {};
    const text = (input, old) => (input.value.trim() === (old || "") ? undefined : input.value.trim() || null);
    for (const key of ["name", "homepage", "logo_url"]) {
      const v = text(f[key], s[key]);
      if (v !== undefined) set[key] = v;
    }
    if (set.name === null) delete set.name;
    const country = f.country.value.trim().toUpperCase();
    if (country && country !== (s.country || "")) set.country = country;
    const newPlace = {};
    if (f.city.value.trim()) newPlace.name = f.city.value.trim();
    if (f.lat.value.trim() || f.lon.value.trim()) {
      newPlace.lat = Number(f.lat.value);
      newPlace.lon = Number(f.lon.value);
    }
    if (JSON.stringify(newPlace) !== JSON.stringify(place)) set.place = Object.keys(newPlace).length ? newPlace : null;
    for (const key of ["languages", "tags"]) {
      const v = list(f[key].value);
      if (v.join(",") !== (s[key] || []).join(",")) set[key] = v;
    }
    const change = { station: s.id };
    if (Object.keys(set).length) change.set = set;
    const add = f.add.value.split("\n").map((u) => u.trim()).filter(Boolean);
    if (add.length) change.add_streams = add;
    const gone = [...remove].filter(([, b]) => b.checked).map(([id]) => id);
    if (gone.length) change.remove_streams = gone;
    if (f.same.value.trim()) change.same_as = f.same.value.trim();
    if (f.retire.checked) change.retire = true;
    if (f.note.value.trim()) change.note = f.note.value.trim();
    status.className = "muted";
    status.textContent = "Saving…";
    try {
      const result = await api("POST", "/v1/edit/changes", change);
      status.className = "ok";
      status.textContent = result.status === "pending" ? "Saved, waiting for the maintainer." : "Saved. Published with the next dataset.";
      setTimeout(() => openStation(s.id), 800);
    } catch (e) {
      status.className = "error";
      status.textContent = e.message;
    }
  };
  box.replaceChildren(
    h("h2", {}, s.name, " ", h("span", { class: "muted" }, `${s.id} · ${s.status} · rev ${s.rev}`)),
    view.redirected_from ? h("p", { class: "muted" }, `${view.redirected_from} was merged into this station.`) : "",
    h("form", { onsubmit: save },
      h("div", { class: "grid" },
        h("label", {}, "Name"), f.name,
        h("label", {}, "Site"), f.homepage,
        h("label", {}, "Logo"), f.logo_url,
        h("label", {}, "Country"), h("div", {}, f.country),
        h("label", {}, "Town"), f.city,
        h("label", {}, "Lat, lon"), h("div", {}, f.lat, " ", f.lon),
        h("label", {}, "Languages"), f.languages,
        h("label", {}, "Tags"), f.tags),
      h("h2", {}, "Streams"),
      h("table", {}, h("tr", {}, h("th", {}, "Remove"), h("th", {}, "Address"), h("th", {}, "Format"), h("th", {}, "State")), ...rows),
      h("div", { class: "grid" },
        h("label", {}, "Add streams"), f.add,
        h("label", {}, "Same station as"), f.same,
        h("label", {}, "Retire"), h("label", {}, f.retire, " no longer broadcasts"),
        h("label", {}, "Note"), f.note),
      h("p", {}, h("button", {}, "Save"), " ", status)),
    h("h2", {}, "Edits"),
    editTable(view.edits, () => openStation(s.id)),
    h("details", {}, h("summary", { class: "muted" }, "Published record"), h("pre", {}, JSON.stringify(s, null, 2))),
  );
  box.scrollIntoView({ behavior: "smooth" });
}

function editTable(edits, refresh) {
  if (!edits.length) return h("p", { class: "muted" }, "None.");
  const act = (id, status) => async () => {
    try {
      await api("POST", `/v1/edit/changes/${id}`, { status });
      refresh();
    } catch (e) {
      alert(e.message);
    }
  };
  return h("table", {}, ...edits.map((e) => h("tr", {},
    h("td", {}, date(e.created_at), h("div", { class: "muted" }, e.editor)),
    h("td", {}, stations.has(e.station) ? h("a", { href: "#", onclick: (ev) => { ev.preventDefault(); tab("search"); openStation(e.station); } }, stations.get(e.station).record.name) : e.station,
      h("pre", {}, JSON.stringify(e.change, null, 1)), e.note ? h("div", { class: "muted" }, e.note) : "", e.source ? link(e.source) : ""),
    h("td", {}, e.status),
    h("td", {}, me.role !== "maintainer" ? "" : e.status === "pending"
      ? [h("button", { onclick: act(e.id, "accepted") }, "Accept"), " ", h("button", { onclick: act(e.id, "rejected") }, "Reject")]
      : e.status === "accepted" ? h("button", { onclick: act(e.id, "reverted") }, "Revert") : ""))));
}

// --- To review ---

async function showReview() {
  const box = $("review");
  box.replaceChildren(h("p", { class: "muted" }, "Loading…"));
  try {
    const [{ edits }, { reports }, { proposals }] = await Promise.all([
      api("GET", "/v1/edit/changes?status=pending"),
      api("GET", "/v1/admin/station-reports?status=open"),
      api("GET", "/v1/admin/station-proposals?status=published"),
    ]);
    const decide = (id, status) => async () => {
      await api("POST", `/v1/admin/station-reports/${id}`, { status });
      showReview();
    };
    box.replaceChildren(
      h("h2", {}, `Edits waiting (${edits.length})`), editTable(edits, showReview),
      h("h2", {}, `Reports from listeners (${reports.length})`),
      reports.length ? h("table", {}, ...reports.map((r) => h("tr", {},
        h("td", {}, date(r.created_at)),
        h("td", {}, h("a", { href: "#", onclick: (ev) => { ev.preventDefault(); tab("search"); openStation(r.station); } }, r.station)),
        h("td", {}, r.reason),
        h("td", {}, h("button", { onclick: decide(r.id, "accepted") }, "Fixed"), " ", h("button", { onclick: decide(r.id, "dismissed") }, "Dismiss"))))) : h("p", { class: "muted" }, "None."),
      h("h2", {}, `Stations added from Moon, published (${proposals.length})`),
      proposals.length ? h("table", {}, ...proposals.slice(0, 100).map((p) => h("tr", {},
        h("td", {}, date(p.created_at)), h("td", {}, p.body.name), h("td", {}, p.body.country),
        h("td", { class: "url muted" }, p.body.streams.join(" "))))) : h("p", { class: "muted" }, "None."),
    );
  } catch (e) {
    box.replaceChildren(h("p", { class: "error" }, e.message));
  }
}

// --- Add a station ---

async function showAdd() {
  const box = $("add");
  const f = {
    name: h("input", { required: true }), country: h("input", { maxlength: 2, size: 3, required: true }),
    streams: h("textarea", { rows: 3, required: true, placeholder: "one stream address per line, at most 5" }),
    homepage: h("input"), logo_url: h("input"), city: h("input"), lat: h("input", { size: 10 }), lon: h("input", { size: 10 }),
    languages: h("input", { placeholder: "fr, en" }), tags: h("input", { list: "tags", placeholder: "jazz, news" }), note: h("input"),
  };
  const status = h("span");
  const send = async (event) => {
    event.preventDefault();
    const body = { name: f.name.value.trim(), country: f.country.value.trim().toUpperCase(),
      streams: f.streams.value.split("\n").map((u) => u.trim()).filter(Boolean).map((url) => ({ url })) };
    for (const key of ["homepage", "logo_url", "note"]) if (f[key].value.trim()) body[key] = f[key].value.trim();
    const place = {};
    if (f.city.value.trim()) place.name = f.city.value.trim();
    if (f.lat.value.trim()) Object.assign(place, { lat: Number(f.lat.value), lon: Number(f.lon.value) });
    if (Object.keys(place).length) body.place = place;
    if (list(f.languages.value).length) body.languages = list(f.languages.value);
    if (list(f.tags.value).length) body.tags = list(f.tags.value);
    const already = holders(body.streams.map((m) => m.url));
    if (already.length) {
      status.className = "error";
      status.replaceChildren("A stream already belongs to ", ...already.slice(0, 3).map((r) =>
        h("a", { href: "#", onclick: (ev) => { ev.preventDefault(); tab("search"); openStation(r.id); } }, `${r.name} `)), ": edit it instead.");
      return;
    }
    try {
      const result = await api("POST", "/v1/edit/stations", body);
      status.className = "ok";
      status.textContent = `Sent (${result.id}). Each stream is checked, then the station is published with the next dataset.`;
      showMine();
    } catch (e) {
      status.className = "error";
      status.textContent = e.message;
    }
  };
  const mine = h("div");
  const showMine = async () => {
    const { stations } = await api("GET", "/v1/edit/new-stations");
    mine.replaceChildren(stations.length ? h("table", {}, ...stations.map((p) => h("tr", {},
      h("td", {}, date(p.created_at)), h("td", {}, p.body.name), h("td", {}, p.body.country),
      h("td", {}, p.status, p.reason ? ` (${p.reason})` : ""), h("td", {}, p.station || "")))) : h("p", { class: "muted" }, "None yet."));
  };
  box.replaceChildren(
    h("p", { class: "muted" }, "Search first. A station whose stream is already in the dataset is not added."),
    h("form", { onsubmit: send }, h("div", { class: "grid" },
      h("label", {}, "Name"), f.name, h("label", {}, "Country"), h("div", {}, f.country), h("label", {}, "Streams"), f.streams,
      h("label", {}, "Site"), f.homepage, h("label", {}, "Logo"), f.logo_url, h("label", {}, "Town"), f.city,
      h("label", {}, "Lat, lon"), h("div", {}, f.lat, " ", f.lon), h("label", {}, "Languages"), f.languages,
      h("label", {}, "Tags"), f.tags, h("label", {}, "Note"), f.note),
    h("p", {}, h("button", {}, "Add"), " ", status)),
    h("h2", {}, "Stations I added"), mine,
  );
  showMine().catch((e) => mine.replaceChildren(h("p", { class: "error" }, e.message)));
}

// --- Editors ---

async function showEditors() {
  const box = $("editors");
  const name = h("input", { placeholder: "name, e.g. radio-agent", required: true });
  const role = h("select", {}, h("option", { value: "agent" }, "agent"), h("option", { value: "maintainer" }, "maintainer"));
  const shown = h("div");
  const create = async (event) => {
    event.preventDefault();
    try {
      const result = await api("POST", "/v1/edit/editors", { name: name.value.trim(), role: role.value });
      shown.replaceChildren(h("p", {}, `Token for ${result.name}, shown once:`), h("div", { class: "token" }, result.token));
      load();
    } catch (e) {
      shown.replaceChildren(h("p", { class: "error" }, e.message));
    }
  };
  const table = h("table");
  const load = async () => {
    const { editors } = await api("GET", "/v1/edit/editors");
    table.replaceChildren(h("tr", {}, h("th", {}, "Name"), h("th", {}, "Role"), h("th", {}, "Created"), h("th", {}, "Last used"), h("th", {})),
      ...editors.filter((e) => e.id !== "ed_admin").map((e) => h("tr", {}, h("td", {}, e.name), h("td", {}, e.role), h("td", {}, date(e.created_at)),
        h("td", {}, e.last_used_at ? date(e.last_used_at) : ""),
        h("td", {}, e.revoked_at ? `revoked ${date(e.revoked_at)}` : h("button", { onclick: async () => {
          if (confirm(`Revoke ${e.name}? Its token stops working at once.`)) {
            await api("POST", `/v1/edit/editors/${e.id}/revoke`);
            load();
          }
        } }, "Revoke")))));
  };
  box.replaceChildren(h("form", { onsubmit: create }, name, " ", role, " ", h("button", {}, "Create a token")), shown, table);
  load().catch((e) => table.replaceChildren(h("tr", {}, h("td", { class: "error" }, e.message))));
}

// --- Start ---

$("login").addEventListener("submit", (event) => {
  event.preventDefault();
  sessionStorage.setItem("token", $("token").value.trim());
  $("token").value = "";
  start();
});
$("logout").addEventListener("click", () => {
  sessionStorage.removeItem("token");
  showLogin();
});
$("search-form").addEventListener("submit", runSearch);
for (const b of document.querySelectorAll("nav button")) b.addEventListener("click", () => tab(b.dataset.tab));
for (const t of TAGS) $("tags").append(h("option", { value: t }));
if (token()) start();
else showLogin();
