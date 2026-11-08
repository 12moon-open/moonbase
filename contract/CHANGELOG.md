# Contract changelog

## 1.6.0 (2026-11-08)

A rule change, set by the maintainer as permanent. No schema field changes.

- Terms, robots.txt and reservations of text and data mining never block a now-playing adapter or template, whatever its `terms.basis`. They are still recorded in `terms`. `needs_review` and `needs_permission` are no longer used for these reasons alone.
- The technical limits stay mandatory: one read per station and per minute, only while someone listens, shared; `Retry-After`, `Cache-Control` and 429; back-off; an identifiable User-Agent, a 403 stops; `GET` only, no cookie, no credentials, no consent wall; no title stored or republished.
- Blocked-host reason `robots_disallow` is no longer given; it stays valid for older lists.
- Template `bbc.rms/1` (BBC services, `terms.basis: user_created`), with 2 more shared cases.
- The manifest says `contract: "1.6.0"`.

## 1.5.0 (2026-11-08)

Additions only.

- The manifest's `now_playing` dataset is published, with three shards: `adapters` (`now-playing/adapters.ndjson.gz`, one adapter per line), `templates` (`now-playing/templates.ndjson.gz`, one service template per line) and `blocked-hosts` (`now-playing/blocked-hosts.ndjson.gz`). A client reads it as the stations: the sha256 of each file, then an atomic switch.
- Schema `now-playing-blocked-host`: `host`, `subdomains`, `reason` (`station_request`, `service_request`, `robots_disallow`, `refuses_user_agent`, `maintainer`), `since`. No now-playing request, nor a redirect, may reach a listed host, whatever the adapter or template. A client adds these hosts to its own list and never drops one of its own because it is missing here.
- Published adapters always carry `id`, `rev`, `status` and `updated_at`. An adapter whose station was merged points to the station it was merged into; one whose station is gone is left out.
- The manifest says `contract: "1.5.0"`.

## 1.4.0 (2026-11-08)

Additions only, for now-playing adapters.

- `extract.subitems`: a JSONPath read in each item kept after `match`; its elements become the items (a station's playlist inside a list of stations).
- `pick: "first_not_ended"`: the first item whose `ended_at` plus `grace_after_end_s` is not past; when every one has ended, `ended`.
- Template `nrj.livemeta/1` (NRJ and Nostalgie, `terms.basis: user_created`, `terms.robots: disallowed`), a connector made by a user and reviewed by the maintainer, with 4 more shared cases.

## 1.3.1 (2026-11-08)

- `terms.basis: "user_created"` for a connector made by a user and shared, and `terms.robots` (`allowed`, `disallowed`, `absent`) recording what robots.txt said. For a user-created connector, robots.txt is read and recorded but does not stop it; the other safeguards stay.

## 1.3.0 (2026-11-08)

Additions only, for now-playing adapters, from a reading of 28 stations' players. A 1.2 client refuses an adapter or template that uses them and keeps the others.

- Template param `kind: "path"`: inserted as it is after its pattern check (no `..`), for status pages at a custom path.
- With a template, an adapter may replace some `fields` and the `match`.
- Fields: `or_paths` (paths tried in order), `list: "first"` (first element of a list), `root` (read from the document root, such as a show name).
- `match.ends_with_any`: ends in order of preference (`/live`, then `/autodj`).
- Time `local_datetime` (`yyyy-MM-dd HH:mm:ss`, with `timezone`).
- `request.no_item_status`: HTTP statuses meaning nothing is playing (iHeart answers 410).
- Templates `icecast.status/2` (custom path; `icecast.status/1` is unchanged for 1.2 clients), `npr.cadence/1`, `iheart.livemeta/1` (the public data behind iHeart's own players, `terms.basis: public_page`), `dpg.qmusic/1`, `eurozet.rds/1`, `tuba.onstation/1`, with 10 more shared cases.
- Fetching rule: a `Cache-Control: max-age` longer than `poll.interval_s` is capped to it.

## 1.2.1 (2026-11-08)

- Station `sources` may list `radioarg`, and `ids` may carry `radioarg` (`ra:<page>`).

## 1.2.0 (2026-11-08)

Additions only, for now-playing adapters. A 1.1 client refuses an adapter that uses them, as its strict reading requires, and keeps the others.

- `request.scheme` and `request.port`: https on 443 by default; another port from a closed list (2199, 8000-8999, 10443, 18000-18999); http only towards the host of one of the station's own streams.
- `request.unwrap: "jsonp"` and `request.accept_types` (JSON served as JavaScript, text or octet-stream).
- `extract.match` (keep the item whose value equals, or ends with, a text, such as an Icecast mount) and `extract.wrap_single` (a single object where a list was expected).
- `time: "datetime_offset"` for `2026-11-08 10:54:45 +0100`.
- An audio or video answer fails with `audio_response`, before its body is read.
- Templates `centova.streaminfo/1`, `icecast.status/1`, `corus.fmplaylist/1`, `lautfm.current/1`, `radiocult.live/1`, with 12 more shared cases.

## 1.1.0 (2026-11-08)

Additions only. A 1.0 client keeps working: it ignores the new dataset.

- Now-playing adapters: `now-playing-adapter`, `now-playing-template` and `now-playing-proposal` schemas, format `12moon.now_playing/1`. Strict: an unknown field invalidates an adapter.
- Shared executor cases in `cases/now-playing/`: an adapter, a recorded response, a time, and the expected result. Every executor (the API's, the clients') must give the same results.
- First service template, `now-playing/templates/creek.current-1.json`: the public data behind Creek's playlist widget (`terms.basis: public_page`).
- A future manifest dataset `now_playing` with `now-playing/adapters.ndjson.gz`, `now-playing/templates.ndjson.gz` and `now-playing/blocked-hosts.ndjson.gz`.

## 1.0.0 (unreleased)

First version: manifest, station, redirect.

Also in 1.0.0, for the contribution API: proposal (`release_match`), release match, stream measures (`stream_measures`), stream health, station proposal (`station_add`) and the closed list of tags. Stations may carry `wikipedia`. Station `ids` may carry `contributions`, and `sources` may list `contribution`. Stream codec values include `he-aac`.
