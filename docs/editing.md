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

### Search and read

Search the published files, not the API: they are public, static and cached.

1. `GET https://data.12moon.app/v1/manifest.json` lists the files with their sha256. Download again only when `dataset_version` changed (once a day at most).
2. Each `datasets.stations[].path` (`stations/FR.ndjson.gz`, one file per country) holds one station per line, see [the station schema](../contract/v1/schemas/station.schema.json). `redirects.ndjson.gz` maps a merged id (`from`) to the station it went into (`to`).
3. `health/FR.ndjson.gz` holds the last check of each stream of that country, by stream id: `state` (`ok`, `failing`, `dead`), `codec`, `bitrate_kbps`.

Keep them in a local index and match on the name (ignore accents and case), the site, the stream addresses and the ids. A station may be listed under another name, or twice: look at its streams and site before deciding it is missing.

`GET /v1/edit/changes?station=st_…` lists the edits already made to a station, `?status=pending` yours waiting for review. An edit shows in the files only after the next build.

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
| `set.place` | `{ "name": "Lyon", "wikidata": "Q456", "lat": 45.76, "lon": 4.84 }` (lat and lon together), or `null`. It replaces the whole place: send the town with its coordinates, or the ones already there are lost |
| `set.languages` | ISO 639 codes, `["fr", "oc"]`, at most 5 |
| `set.tags` | from the closed list [`tags.json`](../contract/v1/tags.json), at most 10; `[]` removes them |
| `add_streams` | up to 5 stream addresses; each is checked before it is published |
| `remove_streams` | stream ids `sm_…` that are not this station |
| `retire` | `true` when the station no longer broadcasts |
| `same_as` | the id of another record of the same station, to merge them |
| `note` | why, at most 1000 characters, private |
| `source` | the address where the fact was seen, private |

A field set by a later edit replaces the earlier one. Answer: `201 { "id": "ed_…", "station": "st_…", "status": "accepted" | "pending" }`. Errors: `422` with the invalid field, `429` daily limit. An unknown station id is accepted but does nothing: check it in the files first.

### Add a station

```
POST /v1/edit/stations
{
  "name": "Radio Exemple",
  "country": "FR",
  "streams": [ { "url": "https://stream.example.fr/live.mp3" } ],
  "homepage": "https://www.example.fr/",
  "place": { "name": "Lyon", "wikidata": "Q456", "lat": 45.76, "lon": 4.84 },
  "languages": ["fr"],
  "tags": ["jazz"],
  "note": "found on its site"
}
```

Each stream is checked by the stream checker (it must play audio), then the station is published with the next dataset; a stream already in a station makes it a `duplicate` of that station. Answer: `202 { "id": "pr_…", "status": "pending" }`. `GET /v1/edit/new-stations` lists the stations you added and what became of them (`published`, `duplicate` with the station, or `rejected` with the reason).

### Follow your edits

`GET /v1/edit/changes` lists your edits; filter with `status` (`pending`, `accepted`, `rejected`, `reverted`) or `station`.

## For the maintainer

- `POST /v1/edit/changes/ed_…` with `{ "status": "accepted" | "rejected" }` for a pending edit, `{ "status": "reverted" }` to undo an accepted one at the next build.
- `GET /v1/edit/editors`, `POST /v1/edit/editors { "name": "…", "role": "agent" }`, `POST /v1/edit/editors/ed_…/revoke`.
- `GET /v1/edits` is the public export the build reads: accepted edits, without author, note or source.
