// Reference executor for now-playing adapters (contract 1.1, format 12moon.now_playing/1).
// It reads one response already fetched and returns what is playing, or why not.
// The cases in contract/v1/cases/now-playing are its specification, shared with Moon.

const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f​-‏‪-‮⁠-⁩﻿]/;
const URLISH = /https?:\/\/|www\.[a-z0-9-]+\.[a-z]/i;
const ISRC = /^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$/;
const MAX_VALUE = 200;
const VOID = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
const RAW_TEXT = new Set(["script", "style"]);

export class AdapterError extends Error {
  constructor(reason) {
    super(reason);
    this.reason = reason;
  }
}

// ---------- Templates ----------

/** Ports allowed besides 443 (https) and 80 (http): Centova, Icecast and Shoutcast status pages. */
export function allowedPort(port) {
  return port === 2199 || port === 10443 || (port >= 8000 && port <= 8999) || (port >= 18000 && port <= 18999);
}

/**
 * A full adapter from a template-based one. Each param must match its pattern; hosts must cover the URL.
 * context.stream_hosts: hosts of the station's own streams. http is allowed only towards them (1.2).
 */
export function resolve(adapter, templates, context = {}) {
  let full = adapter;
  if (adapter.template) {
    const template = templates[adapter.template];
    if (!template || template.status === "revoked") throw new AdapterError("unknown_template");
    const params = adapter.params || {};
    const names = Object.keys(template.params);
    if (Object.keys(params).some((k) => !names.includes(k)) || names.some((k) => typeof params[k] !== "string")) {
      throw new AdapterError("invalid_adapter");
    }
    for (const name of names) {
      if (!new RegExp(template.params[name].pattern).test(params[name])) throw new AdapterError("invalid_adapter");
    }
    const fill = (text) => text.replace(/\{([a-z_]+)\}/g, (_, n) => encodeURIComponent(params[n]));
    const request = { ...template.request, url: fill(template.request.url), hosts: template.request.hosts.map(fill) };
    if (typeof request.scheme === "string") request.scheme = fill(request.scheme);
    if (typeof request.port === "string") request.port = Number(fill(request.port));
    const extract = { ...template.extract };
    if (extract.match) {
      // Compared as text, not sent in a URL: the param goes in as it is.
      const raw = (text) => text.replace(/\{([a-z_]+)\}/g, (_, n) => params[n]);
      extract.match = Object.fromEntries(Object.entries(extract.match).map(([k, v]) => [k, k === "path" ? v : raw(v)]));
    }
    full = {
      ...template,
      ...Object.fromEntries(Object.entries(adapter).filter(([k]) => !["template", "params"].includes(k))),
      request, extract,
      ignore: adapter.ignore || template.ignore,
    };
  }
  let url;
  try {
    url = new URL(full.request.url);
  } catch {
    throw new AdapterError("invalid_adapter");
  }
  if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== "443")) throw new AdapterError("invalid_adapter");
  if (/^[0-9.]+$/.test(url.hostname) || url.hostname.includes(":")) throw new AdapterError("invalid_adapter");
  if (!full.request.hosts.includes(url.hostname)) throw new AdapterError("invalid_adapter");
  const placeholder = /\{[a-z_]{1,30}\}/;
  const values = [full.request.url, ...full.request.hosts, full.request.scheme, full.request.port,
    ...Object.values(full.extract.match || {})].filter((v) => v !== undefined);
  if (values.some((v) => placeholder.test(String(v)))) {
    throw new AdapterError("invalid_adapter");
  }
  const scheme = full.request.scheme || "https";
  if (scheme !== "https" && scheme !== "http") throw new AdapterError("invalid_adapter");
  if (scheme === "http" && !(context.stream_hosts || []).includes(url.hostname)) throw new AdapterError("invalid_adapter");
  const port = full.request.port ?? (scheme === "https" ? 443 : 80);
  if (!Number.isInteger(port) || !(port === (scheme === "https" ? 443 : 80) || allowedPort(port))) throw new AdapterError("invalid_adapter");
  url.protocol = `${scheme}:`;
  url.port = String(port);
  full.request = { ...full.request, effective_url: url.toString() };
  return full;
}

// ---------- JSONPath subset: $ .key ['key'] [n] [-1] [*] ----------

function parsePath(path) {
  if (!path.startsWith("$")) throw new AdapterError("invalid_adapter");
  const steps = [];
  const re = /\.([A-Za-z_][A-Za-z0-9_-]*)|\['([^'\]]{1,60})'\]|\[(-?\d{1,3})\]|\[\*\]/y;
  re.lastIndex = 1;
  while (re.lastIndex < path.length) {
    const start = re.lastIndex;
    const m = re.exec(path);
    if (!m || m.index !== start) throw new AdapterError("invalid_adapter");
    if (m[1] !== undefined || m[2] !== undefined) steps.push({ key: m[1] ?? m[2] });
    else if (m[3] !== undefined) steps.push({ index: Number(m[3]) });
    else steps.push({ all: true });
  }
  return steps;
}

function jsonSelect(root, path) {
  let nodes = [root];
  for (const step of parsePath(path)) {
    const next = [];
    for (const node of nodes) {
      if (step.all) {
        if (Array.isArray(node)) next.push(...node);
      } else if (step.index !== undefined) {
        if (Array.isArray(node)) {
          const value = node[step.index < 0 ? node.length + step.index : step.index];
          if (value !== undefined) next.push(value);
        }
      } else if (node && typeof node === "object" && !Array.isArray(node) && Object.hasOwn(node, step.key)) {
        next.push(node[step.key]);
      }
    }
    nodes = next;
  }
  return nodes;
}

// ---------- A small HTML and XML reader ----------

const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };

export function unescapeHtml(text) {
  return text.replace(/&(#x[0-9a-f]{1,6}|#[0-9]{1,7}|[a-z]{2,6});/gi, (all, code) => {
    if (code[0] === "#") {
      const n = code[1] === "x" || code[1] === "X" ? parseInt(code.slice(2), 16) : parseInt(code.slice(1), 10);
      return n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : all;
    }
    return ENTITIES[code.toLowerCase()] ?? all;
  });
}

/** A tree of { name, attrs, children } and strings. Lenient: unclosed tags close with their parent. */
export function parseMarkup(text, xml) {
  const root = { name: "#root", attrs: {}, children: [] };
  const stack = [root];
  const re = /<!--[\s\S]*?-->|<!\[CDATA\[([\s\S]*?)\]\]>|<![^>]*>|<\?[\s\S]*?\?>|<\/\s*([A-Za-z][\w:.-]*)\s*>|<([A-Za-z][\w:.-]*)((?:\s+[^\s=>/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*(\/?)>/g;
  let last = 0;
  let m;
  const text_ = (s) => {
    if (s) stack.at(-1).children.push(xml ? unescapeHtml(s) : unescapeHtml(s));
  };
  while ((m = re.exec(text))) {
    text_(text.slice(last, m.index));
    last = re.lastIndex;
    if (m[1] !== undefined) {
      stack.at(-1).children.push(m[1]);
    } else if (m[2]) {
      const name = xml ? m[2] : m[2].toLowerCase();
      const at = stack.map((n) => n.name).lastIndexOf(name);
      if (at > 0) stack.length = at;
    } else if (m[3]) {
      const name = xml ? m[3] : m[3].toLowerCase();
      const attrs = {};
      for (const a of m[4].matchAll(/([^\s=>/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) {
        attrs[xml ? a[1] : a[1].toLowerCase()] = unescapeHtml(a[2] ?? a[3] ?? a[4] ?? "");
      }
      const node = { name, attrs, children: [] };
      stack.at(-1).children.push(node);
      if (!xml && RAW_TEXT.has(name)) {
        const end = text.toLowerCase().indexOf(`</${name}`, re.lastIndex);
        re.lastIndex = last = end < 0 ? text.length : end;
        continue;
      }
      if (!m[5] && !(!xml && VOID.has(name))) stack.push(node);
    }
  }
  text_(text.slice(last));
  return root;
}

function textOf(node) {
  if (typeof node === "string") return node;
  return node.children.map(textOf).join("");
}

// ---------- CSS subset: type .class #id [attr] [attr=value] :first-of-type :nth-of-type(n), descendant and > ----------

function parseSelector(css, xml) {
  const parts = css.trim().split(/\s*(>)\s*|\s+/).filter((p) => p !== undefined && p !== "");
  const chain = [];
  let combinator = " ";
  for (const part of parts) {
    if (part === ">") {
      combinator = ">";
      continue;
    }
    const m = /^([A-Za-z][\w:-]*|\*)?((?:\.[\w-]+|#[\w-]+|\[[\w:-]+(?:=(?:"[^"]*"|'[^']*'|[^\]]+))?\]|:first-of-type|:nth-of-type\(\d{1,3}\))*)$/.exec(part);
    if (!m) throw new AdapterError("invalid_adapter");
    const compound = { combinator, name: m[1] && m[1] !== "*" ? (xml ? m[1] : m[1].toLowerCase()) : null, tests: [] };
    for (const t of m[2].matchAll(/\.([\w-]+)|#([\w-]+)|\[([\w:-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\]]+)))?\]|:first-of-type|:nth-of-type\((\d{1,3})\)/g)) {
      if (t[1]) compound.tests.push((n) => (n.attrs.class || "").split(/\s+/).includes(t[1]));
      else if (t[2]) compound.tests.push((n) => n.attrs.id === t[2]);
      else if (t[3]) {
        const value = t[4] ?? t[5] ?? t[6];
        const attr = xml ? t[3] : t[3].toLowerCase();
        compound.tests.push((n) => Object.hasOwn(n.attrs, attr) && (value === undefined || n.attrs[attr] === value));
      } else {
        const nth = t[7] ? Number(t[7]) : 1;
        compound.tests.push((n, parent) => parent.children.filter((c) => typeof c !== "string" && c.name === n.name).indexOf(n) === nth - 1);
      }
    }
    chain.push(compound);
    combinator = " ";
  }
  if (!chain.length) throw new AdapterError("invalid_adapter");
  return chain;
}

function matches(compound, node, parent) {
  return (!compound.name || node.name === compound.name) && compound.tests.every((t) => t(node, parent));
}

/** Every element under scope matching the selector, in document order. */
export function cssSelect(scope, css, xml) {
  const chain = parseSelector(css, xml);
  const out = [];
  const walk = (node, ancestors) => {
    for (const child of node.children) {
      if (typeof child === "string") continue;
      const path = [...ancestors, { node: child, parent: node }];
      if (matchChain(chain, path)) out.push(child);
      walk(child, path);
    }
  };
  walk(scope, []);
  return out;
}

function matchChain(chain, path) {
  // path: [{node, parent}, ...] from just under the scope to the candidate.
  const step = (ci, pi) => {
    const { node, parent } = path[pi];
    if (!matches(chain[ci], node, parent)) return false;
    if (ci === 0) return true;
    if (chain[ci].combinator === ">") return pi > 0 && step(ci - 1, pi - 1);
    for (let p = pi - 1; p >= 0; p -= 1) if (step(ci - 1, p)) return true;
    return false;
  };
  return step(chain.length - 1, path.length - 1);
}

// ---------- Values ----------

function offsetMinutes(timeZone, ms) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", { timeZone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })
      .formatToParts(new Date(ms)).map((p) => [p.type, p.value]),
  );
  const local = Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute, +parts.second);
  return Math.round((local - Math.floor(ms / 1000) * 1000) / 60000);
}

function localTime(text, timeZone, now, withSeconds) {
  const m = (withSeconds ? /^(\d{1,2}):(\d{2}):(\d{2})$/ : /^(\d{1,2}):(\d{2})$/).exec(text);
  if (!m) return null;
  let tz;
  try {
    tz = new Intl.DateTimeFormat("en-US", { timeZone }).resolvedOptions().timeZone;
  } catch {
    throw new AdapterError("invalid_adapter");
  }
  const [h, mi, s] = [Number(m[1]), Number(m[2]), Number(m[3] || 0)];
  if (h > 23 || mi > 59 || s > 59) return null;
  const today = new Date(now + offsetMinutes(tz, now) * 60000);
  const build = (dayShift) => {
    const guess = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() + dayShift, h, mi, s);
    return guess - offsetMinutes(tz, guess - offsetMinutes(tz, guess) * 60000) * 60000;
  };
  let at = build(0);
  if (at > now + 5 * 60000) at = build(-1); // Just before midnight, seen just after.
  return at;
}

function toTime(value, kind, timeZone, now) {
  if (kind === "unix_s" || kind === "unix_ms") {
    const n = typeof value === "number" ? value : /^\d{9,13}$/.test(value) ? Number(value) : NaN;
    return Number.isFinite(n) ? (kind === "unix_s" ? n * 1000 : n) : null;
  }
  const text = String(value).trim();
  if (kind === "datetime_offset") {
    const m = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) ([+-]\d{2}):?(\d{2})$/.exec(text);
    if (!m) return null;
    const ms = Date.parse(`${m[1]}T${m[2]}${m[3]}:${m[4]}`);
    return Number.isFinite(ms) ? ms : null;
  }
  if (kind === "iso8601") {
    if (!/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})$/.test(text)) return null;
    const ms = Date.parse(text.replace(" ", "T"));
    return Number.isFinite(ms) ? ms : null;
  }
  return localTime(text, timeZone, now, kind === "local_hms");
}

function clean(text) {
  const value = text.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
  if (!value) return null;
  if (value.length > MAX_VALUE || INVISIBLE.test(value) || URLISH.test(value)) throw new AdapterError("invalid_value");
  return value;
}

function fieldValue(spec, item, mode, now) {
  let raw;
  if (spec.path) {
    const found = jsonSelect(item, spec.path)[0];
    if (found === undefined || found === null || typeof found === "object") return null;
    raw = found;
  } else {
    const found = item.name === "#root" || item.children ? cssSelect(item, spec.css, mode === "xml")[0] : undefined;
    if (!found) return null;
    raw = textOf(found);
  }
  if (spec.time && typeof raw === "number") return toTime(raw, spec.time, spec.timezone, now);
  let text = String(raw);
  if (spec.regex) {
    const m = new RegExp(spec.regex).exec(text);
    if (!m) return null;
    text = m[1] ?? m[0];
  }
  if (spec.split) {
    const at = text.indexOf(spec.split.sep);
    if (at < 0) return null;
    text = spec.split.part === 0 ? text.slice(0, at) : text.slice(at + spec.split.sep.length);
  }
  if (spec.html_unescape) text = unescapeHtml(text);
  if (spec.trim !== false) text = text.trim();
  if (spec.time) return toTime(text, spec.time, spec.timezone, now);
  const value = clean(text);
  if (value && spec.check === "isrc") return ISRC.test(value.replace(/-/g, "").toUpperCase()) ? value.replace(/-/g, "").toUpperCase() : null;
  return value;
}

function nameKey(text) {
  return (text || "").normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
}

const iso = (ms) => new Date(ms).toISOString().replace(/\.000Z$/, "Z");

/**
 * Reads one response with a full adapter (see resolve).
 * response: { content_type, body } ; now: ISO time ; stationName: for ignore.equals_station_name.
 * Returns { status: "current", artist, title, ... } or { status: "ended" | "stale" | "ignored" }.
 * Throws AdapterError(reason) for wrong_type, too_large, no_item, invalid_value, invalid_adapter.
 */
export function run(adapter, response, nowText, stationName = "") {
  const now = Date.parse(nowText);
  const mode = adapter.request.expect;
  const type = String(response.content_type || "").split(";")[0].trim().toLowerCase();
  // Never read a stream by mistake: an audio or video answer is cut before its body is read.
  if (/^(?:audio|video)\//.test(type) || type === "application/ogg") throw new AdapterError("audio_response");
  const extra = adapter.request.accept_types || [];
  const typeOk = extra.includes(type) || (mode === "json" ? /^application\/(?:[\w.+-]*\+)?json$/.test(type)
    : mode === "html" ? type === "text/html" || type === "application/xhtml+xml"
    : /^(?:application|text)\/(?:[\w.+-]*\+)?xml$/.test(type));
  if (!typeOk) throw new AdapterError("wrong_type");
  const body = response.body;
  if (new TextEncoder().encode(body).length > adapter.limits.max_bytes) throw new AdapterError("too_large");
  let root;
  if (mode === "json") {
    let text = body;
    if (adapter.request.unwrap === "jsonp") {
      const m = /^\s*[A-Za-z_$][\w$.]{0,60}\s*\(([\s\S]*)\)\s*;?\s*$/.exec(text);
      if (!m) throw new AdapterError("wrong_type");
      text = m[1];
    }
    try {
      root = JSON.parse(text);
    } catch {
      throw new AdapterError("wrong_type");
    }
  } else {
    root = parseMarkup(body, mode === "xml");
  }
  const ex = adapter.extract;
  let items;
  if (mode === "json") {
    items = jsonSelect(root, ex.items);
    if (!items.length && ex.wrap_single && ex.items.endsWith("[*]")) {
      items = jsonSelect(root, ex.items.slice(0, -3)).filter((i) => i && typeof i === "object" && !Array.isArray(i));
    }
    items = items.filter((i) => i && typeof i === "object");
  } else {
    items = cssSelect(root, ex.items, mode === "xml");
  }
  if (ex.match) {
    items = items.filter((item) => {
      const found = mode === "json" ? jsonSelect(item, ex.match.path)[0] : undefined;
      if (found === undefined || found === null || typeof found === "object") return false;
      const text = String(found);
      return ex.match.equals !== undefined ? text === ex.match.equals : text.endsWith(ex.match.ends_with);
    });
  }
  const read = (item) => {
    const out = {};
    for (const [name, spec] of Object.entries(ex.fields)) {
      const value = fieldValue(spec, item, mode, now);
      if (value !== null && value !== undefined) out[name] = value;
    }
    return out;
  };
  const rows = items.map(read).filter((r) => r.artist && r.title);
  if (!rows.length) throw new AdapterError("no_item");
  let row;
  if (ex.pick === "first") row = rows[0];
  else if (ex.pick === "last") row = rows.at(-1);
  else {
    const dated = rows.filter((r) => typeof r.started_at === "number");
    row = dated.length ? dated.reduce((a, b) => (b.started_at > a.started_at ? b : a)) : rows[0];
  }
  const ignore = adapter.ignore || {};
  if (ignore.equals_station_name && stationName) {
    const station = nameKey(stationName);
    if ([row.title, `${row.artist}${row.title}`].some((t) => nameKey(t) === station)) return { status: "ignored" };
  }
  for (const pattern of ignore.patterns || []) {
    if (new RegExp(pattern, "i").test(`${row.artist} - ${row.title}`)) return { status: "ignored" };
  }
  const fresh = adapter.freshness;
  if (typeof row.ended_at === "number" && now > row.ended_at + (fresh.grace_after_end_s || 0) * 1000) return { status: "ended" };
  if (typeof row.started_at === "number") {
    if (row.started_at > now + 5 * 60000) throw new AdapterError("invalid_value");
    if (now - row.started_at > fresh.max_age_s * 1000) return { status: "stale" };
  } else if (ex.observed_at) {
    const observed = fieldValue(ex.observed_at, root, mode, now);
    if (typeof observed === "number" && now - observed > fresh.max_age_s * 1000) return { status: "stale" };
  }
  const out = { status: "current", artist: row.artist, title: row.title };
  for (const key of ["album", "isrc", "show"]) if (row[key]) out[key] = row[key];
  for (const key of ["started_at", "ended_at"]) if (typeof row[key] === "number") out[key] = iso(row[key]);
  return out;
}
