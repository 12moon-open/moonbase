# Now-playing adapters

Contract 1.1. An adapter says where a station publishes what it is playing and how to read it. It is data, never code, and it is executed by the listener's own server, never by an app. 12moon publishes adapters; it never fetches, stores or publishes the titles themselves.

Schemas: [`now-playing-adapter`](../contract/v1/schemas/now-playing-adapter.schema.json), [`now-playing-template`](../contract/v1/schemas/now-playing-template.schema.json), [`now-playing-proposal`](../contract/v1/schemas/now-playing-proposal.schema.json). Reference executor: [`api/src/nowplaying.js`](../api/src/nowplaying.js). Specification by example: [`cases/now-playing`](../contract/v1/cases/now-playing).

## Executing an adapter

1. **Resolve.** A template-based adapter takes its request and extraction from the template. Each param must match the template's pattern; it is URL-encoded into `{name}`. The URL must be HTTPS, port 443, without credentials or IP literal, and its host must be one of `request.hosts`.
2. **Fetch.** One `GET`, without cookies or headers chosen by the adapter. Redirects only to one of `hosts`, in HTTPS, two at most, each checked against private addresses after DNS resolution. Respect `poll.min_interval_s`, `Retry-After`, `Cache-Control` and 429. Since 1.6, `robots.txt` is recorded, not obeyed (see below).
3. **Read.** The `Content-Type` must match `expect` (`wrong_type`), the body must fit `limits.max_bytes` (`too_large`). JSON uses a JSONPath subset: `$`, `.key`, `['key']`, `[n]`, `[-1]`, `[*]`. HTML and XML use a CSS subset: type, `.class`, `#id`, `[attr]`, `[attr=value]`, descendant, `>`, `:first-of-type`, `:nth-of-type(n)`. Text of `<script>` and `<style>` is never read; entities are decoded.
4. **Fields.** For each field: select, then `regex` (first capture, or the match), `split`, `html_unescape`, trim, then `time` or the value checks. A text value has its tags removed and spaces collapsed; it is refused when longer than 200 characters, when it holds an invisible character or a web address (`invalid_value`). `check: isrc` keeps a valid ISRC only.
5. **Times.** `iso8601`, `unix_s`, `unix_ms`, or `local_hm` / `local_hms` with an IANA `timezone`: attached to the local day, or the previous one when more than 5 minutes in the future.
6. **Pick** among items with an artist and a title: `first`, `last`, or `latest_started`. None: `no_item`.
7. **Result.**
   - `ignored` when the title is the station name (`equals_station_name`) or matches an `ignore.patterns` entry (case-insensitive, on `artist - title`);
   - `ended` when `ended_at` plus `grace_after_end_s` is past;
   - `stale` when `started_at`, or else `observed_at`, is older than `max_age_s`; a start more than 5 minutes in the future is `invalid_value`;
   - otherwise `current`, with `artist`, `title`, and when known `album`, `isrc`, `show`, `started_at`, `ended_at`.

## Since 1.2

- **Scheme and port.** `request.scheme` and `request.port` (or template params). https on 443 by default. Other ports, only: 2199 (Centova), 8000-8999, 10443, 18000-18999 (Icecast, Shoutcast, AzuraCast). http only towards the host of one of the station's own streams, which the listener's server already reaches in clear for the audio.
- **Formats.** `request.unwrap: "jsonp"` removes a `callback(...)` envelope. `request.accept_types` accepts JSON served as `application/javascript`, `text/javascript`, `text/plain` or octet-stream.
- **Choosing an item.** `extract.match` keeps the items whose value at `path` equals, or ends with, a text: an Icecast status lists every mount, and the station's own is chosen by the end of `listenurl`. `extract.wrap_single` reads a single object where a list was expected.
- **Times.** `datetime_offset`: `2026-11-08 10:54:45 +0100`.
- **Audio.** Any `audio/*`, `video/*` or `application/ogg` answer is cut before its body is read (`audio_response`). Some pages redirect robots to the stream itself.

## Since 1.3

- **Path params.** A template param with `kind: "path"` is inserted as it is, after its pattern check, instead of URL-encoded. Patterns refuse `..`.
- **Adapter overrides.** With a template, an adapter may bring `fields` (each replaces the template's field of the same name) and `match`.
- **Fields.** `or_paths` are tried in order when `path` gives nothing; `list: "first"` reads the first element of a list; `root: true` reads from the document root rather than the item.
- **Preferred mounts.** `match.ends_with_any` keeps the items matching the earliest end found.
- **Times.** `local_datetime`: `2026-11-08 09:41:40` in the adapter's `timezone`.
- **Nothing playing.** A status in `request.no_item_status` (204, 404 or 410) is `no_item`, not a failure. Any other status than 200 is `http_error`.
- **Cache.** Respect `Cache-Control: max-age`, but never wait longer than `poll.interval_s`: some services announce a cache of a month on what changes every few minutes.
- **Reservations.** Some sites state in their robots.txt a reservation of text and data mining (EU directive 2019/790, art. 4). Reading the title playing now to show it to a listener is not mining, so such a reservation does not stop an adapter. Since 1.6, a robots.txt `Disallow` does not either.

## Since 1.4

- **Nested items.** `extract.subitems` turns each item kept after `match` into the elements of a list inside it: a group's file lists every webradio, and each one its playlist.
- **First not ended.** `pick: "first_not_ended"` takes the first item whose `ended_at` (plus the grace) is not past, so a song change does not show `ended` while the next song is already listed.

## Since 1.6: terms never block, limits always apply

A standing rule set by the maintainer. The title playing now is what any player shows while listening; a station's or a service's terms, its robots.txt and a reservation of text and data mining never stop an adapter or a template, whatever its `terms.basis`. They are still read and recorded in `terms`, for information. No adapter or template is put in `needs_review` or `needs_permission` for these reasons alone.

What protects the stations' servers stays mandatory, for every adapter:

- one read per station and per minute at most, only while someone listens, shared by all the devices of a server;
- `Retry-After`, `Cache-Control` (capped as above) and 429 respected; back-off, then suspension, after repeated failures;
- an identifiable User-Agent, never disguised: a 403 stops the adapter, with no workaround;
- `GET` only: no `POST`, no login, no cookie, no credentials, no consent wall accepted on the user's behalf;
- no title stored or republished.

Review stays for other reasons: abuse, a wrong station, the content read. A station's or a service's request to stop still turns the adapter `revoked` and blocks its host at once.

- **A webradio is not its parent station.** The page of titles played by a group's main station says nothing about its theme webradios. An adapter is checked against the stream's ICY title when it has one. 12moon puts in `needs_review` an adapter whose request is the same as another station's, unless both records are the same station.
- **No endless response.** One request, one answer: a server-sent events stream (Zeno) is out of scope.

Regular expressions are at most 200 characters, with no lookaround and no back-reference, so that .NET (`NonBacktracking`) and JavaScript agree.

## The `now_playing` dataset

Since 1.5. The manifest lists it next to the stations, in three shards, each checked by its sha256 like the stations:

| Shard | File | One line is |
|---|---|---|
| `adapters` | `now-playing/adapters.ndjson.gz` | a [`now-playing-adapter`](../contract/v1/schemas/now-playing-adapter.schema.json), with `id`, `rev`, `status`, `updated_at` |
| `templates` | `now-playing/templates.ndjson.gz` | a [`now-playing-template`](../contract/v1/schemas/now-playing-template.schema.json) |
| `blocked-hosts` | `now-playing/blocked-hosts.ndjson.gz` | a [`now-playing-blocked-host`](../contract/v1/schemas/now-playing-blocked-host.schema.json) |

An adapter that is not `active`, or whose template is not `active`, is not executed. A blocked host is never reached by a now-playing request or a redirect: `subdomains: true` blocks every name ending in `.host` too. A client adds these hosts to its own list; it never removes one of its own because it is missing here.

```json
{"host":"example.org","subdomains":true,"reason":"station_request","since":"2026-11-08"}
```

## Publication

Adapters are proposed with `kind: "now_playing_adapter"` (signed, CC0, counters only in `checks`). 12moon checks the hosts, records `robots.txt` and runs the adapter twice before publishing it in the `now_playing` dataset. A daily run marks a failing adapter `broken`, then `revoked` after 30 days. A station's request or the maintainer revoke it at once, and its host joins the blocked list.

A service template is published once the maintainer has checked that it reads only the title playing now and respects the limits above. Its `terms.basis` records on what ground it was written: `public_api` for a documented API, `public_page` for data the station already shows publicly through the service, `user_created` for a connector made by a user, `station_permission` or `provider_permission` for a written agreement. The basis is information, never a condition. Only the title playing now is read, at most once a minute per listening server, and nothing is stored or republished.
