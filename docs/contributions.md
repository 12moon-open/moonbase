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

Limits: 200 proposals and 20 reports per installation per day, 16 KiB per request.

## Not done yet

Deployment, the administration page, publication of the links in `moondust`, and the client in the Moon plugin.
