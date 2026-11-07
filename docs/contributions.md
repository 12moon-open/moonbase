# Contributions

Status: written and tested, **not deployed**. The planned address is `api.12moon.app`.

## Links only

An anonymous installation can only propose a **link between identifiers**. It cannot add or edit metadata: no titles, no names, no free text, no URLs. Anything that belongs in MusicBrainz goes to MusicBrainz, through its own editors.

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
| `POST /v1/proposals` | Signed. Propose a link. `202` queued, `200` already proposed |
| `GET /v1/proposals/{id}` | Status: `pending`, `accepted`, `rejected`, `revoked` |
| `POST /v1/reports` | Signed. Report a published link: `wrong_match`, `duplicate`, `other` |
| `DELETE /v1/contributors/me` | Signed. Erase this installation |
| `GET /v1/links/release-matches?after=` | Public export of published and retracted links |
| `POST /v1/measures` | Signed. One week of stream measures. `202` accepted, `409` week already reported |
| `GET /v1/measures/streams?after=` | Public stream scores |

Limits: 200 proposals and 20 reports per installation per day, 16 KiB per request.

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

Deployment, the administration page, publication of the links in `moondust`, and the client in the Moon plugin.
