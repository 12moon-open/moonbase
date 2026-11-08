# Contract changelog

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
