# Editing stations

For the maintainer and the agents given a token. People use the page at <https://api.12moon.app/edit>; agents use the same API, described here.

Every edit is recorded with its author, then applied by the next daily build under the source `editor`. Nothing is written straight into the published files.

## Authentication

Each editor has its own token, created by the maintainer on the page (Editors tab). It is shown once; only a hash is kept. A token can be revoked at any time and stops working at once.

```
Authorization: Bearer 12m_…
```

Keep the token in an environment variable or a secret store, never in a file that is committed, a log or a message. Roles:

- `agent`: searches, reads, adds stations and edits them. An edit that removes something (`remove_streams`, `retire`, `same_as`) waits for the maintainer; the others are applied at the next build.
- `maintainer`: everything, plus reviewing edits and managing tokens.

Limits per day: 1000 edits and 200 new stations for an agent. Over the limit: `429`.

## Where facts may come from

Only facts: names, addresses, places, languages, kinds of programme. Take them from the station itself: its website, its stream, its own social account. Never copy from another radio directory or database: their lists are not ours to republish. Put the address where you saw the fact in `source`; it is kept private and helps the review.

No personal data, no text written by others (descriptions, biographies), no images other than the station's own logo address.

## The usual loop

1. **Search** before anything: the station may already be there, under another name.
2. **Read** the station to see its streams and their state.
3. **Edit** what is wrong or missing, or **add** the station if it is really not there.

### Search

```
GET /v1/edit/search?q=radio+nova&country=FR
```

`q` is a name (accents and case ignored, every word must appear), part of an address (`nova.fr`, `stream.example.org/live`), a station id `st_…` (a merged id leads to the station it was merged into) or a stream id `sm_…`. `country` is optional. At most 50 results:

```json
{ "stations": [ { "id": "st_…", "name": "Radio Nova", "country": "FR", "status": "active", "homepage": "https://www.nova.fr/", "streams": 3, "logo_url": null } ] }
```

The search reads the published dataset, refreshed within the hour after each build: an edit does not show here before it is published.

### Read

```
GET /v1/edit/stations/st_…
```

Returns `station` (the published record, see [the station schema](../contract/v1/schemas/station.schema.json)), `health` (the last check of each stream: `state` `ok`, `failing` or `dead`, `codec`, `bitrate_kbps`) and `edits` (the edits of this station, newest first).

### Edit

```
POST /v1/edit/changes
{
  "station": "st_…",
  "set": { "homepage": "https://…", "tags": ["jazz", "public radio"] },
  "add_streams": ["https://…"],
  "note": "the site moved",
  "source": "https://…"
}
```

All fields but `station` are optional, at least one change is required:

| Field | Value |
|---|---|
| `set.name` | the station's own name, at most 200 characters |
| `set.homepage`, `set.logo_url` | an `http(s)` address, or `null` to remove it |
| `set.country` | ISO 3166-1 alpha-2, `FR` |
| `set.place` | `{ "name": "Lyon", "lat": 45.76, "lon": 4.84 }` (lat and lon together), or `null` |
| `set.languages` | ISO 639 codes, `["fr", "oc"]`, at most 5 |
| `set.tags` | from the closed list [`tags.json`](../contract/v1/tags.json), at most 10; `[]` removes them |
| `add_streams` | up to 5 stream addresses; each is checked before it is published |
| `remove_streams` | stream ids `sm_…` that are not this station |
| `retire` | `true` when the station no longer broadcasts |
| `same_as` | the id of another record of the same station, to merge them |
| `note` | why, at most 1000 characters, private |
| `source` | the address where the fact was seen, private |

A field set by a later edit replaces the earlier one. Answer: `201 { "id": "ed_…", "station": "st_…", "status": "accepted" | "pending" }`. Errors: `404` unknown station, `422` with the invalid field, `429` daily limit.

### Add a station

```
POST /v1/edit/stations
{
  "name": "Radio Exemple",
  "country": "FR",
  "streams": [ { "url": "https://stream.example.fr/live.mp3" } ],
  "homepage": "https://www.example.fr/",
  "place": { "name": "Lyon" },
  "languages": ["fr"],
  "tags": ["jazz"],
  "note": "found on its site"
}
```

Each stream is checked by the stream checker (it must play audio), then the station is published with the next dataset. `409 { "station": "st_…" }` when a stream already belongs to a station: edit that one instead. Answer: `202 { "id": "pr_…", "status": "pending" }`. `GET /v1/edit/new-stations` lists the stations you added and what became of them (`published`, `duplicate` with the station, or `rejected` with the reason).

### Follow your edits

`GET /v1/edit/changes?status=pending` lists your edits (`pending`, `accepted`, `rejected`, `reverted`).

## For the maintainer

- `POST /v1/edit/changes/ed_…` with `{ "status": "accepted" | "rejected" }` for a pending edit, `{ "status": "reverted" }` to undo an accepted one at the next build.
- `GET /v1/edit/editors`, `POST /v1/edit/editors { "name": "…", "role": "agent" }`, `POST /v1/edit/editors/ed_…/revoke`.
- `GET /v1/edits` is the public export the build reads: accepted edits, without author, note or source.
