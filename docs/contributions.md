# Contributions

Status: **live** at `https://api.12moon.app` since 2026-11-08.

## Links

For music, an anonymous installation can only propose a **link between identifiers**. It cannot add or edit music metadata. Anything that belongs in MusicBrainz goes to MusicBrainz, through its own editors. Stations, below, are the one exception: they are this project's own data.

The first and only kind of link today is `release_match`: "an album whose track durations are these is this MusicBrainz release". It lets other installations recognise the same album without asking anyone.

```json
{ "kind": "release_match", "media": [[215, 180, 302], [240]], "musicbrainz_release": "1b022e01-4da6-387b-8658-8678046e4cef" }
```

`media` holds track durations in whole seconds, one array per disc. Nothing else is accepted: see [`proposal.schema.json`](../contract/v1/schemas/proposal.schema.json).

## How a proposal is decided

Each proposal is checked against MusicBrainz, at most one request per second, with an identifiable User-Agent.

| MusicBrainz says | Decision |
|---|---|
| Same discs and tracks, durations within 3 seconds | Published, `verified_by: musicbrainz` |
| Different track list | Rejected |
| Release unknown | Rejected |
| Too few known durations to decide | Waits until a second, independent installation proposes the same link: then published, `verified_by: consensus` |
| Unavailable | Retried later |

A merged MusicBrainz release is linked under its current identifier. A link checked against MusicBrainz never depends on who proposed it. Blocking a contributor retracts only the links that depended on them alone.

## Identity

There are no accounts. Each installation creates an Ed25519 key pair and signs its requests. Its identifier is derived from the public key. No IP address, e-mail or name is stored. An installation can erase itself: `DELETE /v1/contributors/me`. Published links stay, without any trace of who proposed them.

Signed text, one field per line: `v1`, method, path, Unix timestamp, nonce, hex SHA-256 of the body. Headers: `x-12moon-key`, `x-12moon-timestamp`, `x-12moon-nonce`, `x-12moon-signature` (base64url).

## Endpoints

| Method and path | Use |
|---|---|
| `POST /v1/proposals` | Signed. Propose a link or a station. `202` queued, `200` already proposed |
| `GET /v1/proposals/{id}` | Status: `pending`, `accepted`, `rejected`, `revoked` |
| `POST /v1/reports` | Signed. Report a published link (`wrong_match`, `duplicate`, `other`) or a station |
| `DELETE /v1/contributors/me` | Signed. Erase this installation |
| `GET /v1/links/release-matches?after=` | Public export of published and retracted links |
| `POST /v1/measures` | Signed. One week of stream measures. `202` accepted, `409` week already reported |
| `GET /v1/measures/streams?after=` | Public stream scores |
| `GET /v1/contributions/stations?after=` | Public export of added stations |
| `/v1/admin/…` | Stream checker and maintainer only, with a secret token |

Limits: 200 proposals and 20 reports per installation per day, 16 KiB per request.

## Stations

An installation can add a station that the data does not have yet. It is published only after each of its streams has been checked.

```json
{ "kind": "station_add", "name": "Radio Exemple", "country": "FR",
  "streams": [{ "url": "https://stream.example.fr/live.mp3" }],
  "homepage": "https://www.example.fr/", "logo_url": "https://www.example.fr/logo.png",
  "place": { "name": "Bordeaux", "wikidata": "Q1479", "lat": 44.8378, "lon": -0.5792 },
  "languages": ["fr"], "tags": ["jazz"], "consent": "CC0-1.0" }
```

See [`station-proposal.schema.json`](../contract/v1/schemas/station-proposal.schema.json).

- **Consent.** `consent: "CC0-1.0"` states that the person accepted to place these facts in the public domain. The app shows the text before the first proposal.
- **Little free text.** Only the name and the place name, without addresses, e-mails or phone numbers. Tags come from a closed list, [`tags.json`](../contract/v1/tags.json). Coordinates are those of the station or its town, never of the device.
- **Addresses.** Public hosts only, no credentials, tracking parameters removed.
- **Checked before publication.** The stream checker plays a few seconds of each stream. A stream already published makes the proposal a `duplicate` of that station. Otherwise the station is `published` with the streams that play, measured codec and bitrate included, or `rejected` with a reason: `stream_unreachable`, `not_audio`, `private_address`.
- **Published by the daily build**, under the source `contribution`, in `ids.contributions`. The usual grouping rules apply.
- **Limits.** 10 stations per installation per day, 5 streams per station.
- **Reports.** `POST /v1/reports` with `{ "station": "st_…", "reason": "…" }`. Reasons: `dead_stream`, `wrong_info`, `inappropriate`, `not_a_station`, `duplicate`, `other`.
- **Withdrawal.** Blocking a contributor withdraws every station it added. The public export lists them as `withdrawn`, and the next build retires them.

`GET /v1/contributions/stations?after=` is the public export read by the build: published and withdrawn stations, never who proposed them.

## Stream measures

Separate from proposals: an installation can report what it saw when playing published streams, so that every stream gets a score. It needs the user's explicit consent, given apart from any other.

```json
{ "kind": "stream_measures", "week": "2026-W45", "streams": [
  { "stream": "sm_…", "attempts": 4, "failures": { "timeout": 1 }, "startup_ms": 1800, "stalls": 2, "codec": "aac", "bitrate_kbps": 192 } ] }
```

See [`stream-measures.schema.json`](../contract/v1/schemas/stream-measures.schema.json). What a report never holds: listening time, any time finer than the week, a user identifier, a local station.

- **One finished week** per report, among the last four. Clients send it at a random time, later.
- **Capped values**: 20 attempts, 50 stalls, startup delay rounded to 100 ms.
- **Signed but not linked.** The signature only proves integrity. The key is never stored and creates no contributor. Clients should use a key kept for measures only, and may change it every week.
- **One report per key and week.** The server keeps `HMAC(week secret, key)` for that, and deletes both once the week can no longer be reported.
- **Rows are not linked.** Each stream of a report is stored on its own, in stream order, without the report it came from.

### Scores

`GET /v1/measures/streams?after=` gives one score per stream over the last four finished weeks ([`stream-health.schema.json`](../contract/v1/schemas/stream-health.schema.json)).

- A week counts for a stream only when **at least three installations** measured it that week. One installation cannot make or break a score, and nobody's listening to a rare station is exposed.
- Each report is one voice. Success rate, startup delay and stalls per play are **medians** across reports, not sums of plays.
- A codec or bitrate appears only when three reports agree.
- `geo_blocked` is not a failure. It sets `geo_restricted` when three reports saw it.
- `reports` is a range (`3+`, `10+`, `100+`), never an exact count.
- Measures older than eight weeks are deleted.

## Not done yet

An administration page (the maintainer uses the admin routes for now), publication of the album links in `moondust`, and the terms of use shown by clients.
