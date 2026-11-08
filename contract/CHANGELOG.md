# Contract changelog

## 1.1.0 (2026-11-08)

Additions only. A 1.0 client keeps working: it ignores the new dataset.

- Now-playing adapters: `now-playing-adapter`, `now-playing-template` and `now-playing-proposal` schemas, format `12moon.now_playing/1`. Strict: an unknown field invalidates an adapter.
- Shared executor cases in `cases/now-playing/`: an adapter, a recorded response, a time, and the expected result. Every executor (the API's, the clients') must give the same results.
- First service template, `now-playing/templates/creek.current-1.json`: the public data behind Creek's playlist widget (`terms.basis: public_page`).
- A future manifest dataset `now_playing` with `now-playing/adapters.ndjson.gz`, `now-playing/templates.ndjson.gz` and `now-playing/blocked-hosts.ndjson.gz`.

## 1.0.0 (unreleased)

First version: manifest, station, redirect.

Also in 1.0.0, for the contribution API: proposal (`release_match`), release match, stream measures (`stream_measures`), stream health, station proposal (`station_add`) and the closed list of tags. Stations may carry `wikipedia`. Station `ids` may carry `contributions`, and `sources` may list `contribution`. Stream codec values include `he-aac`.
