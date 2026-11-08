# Data model: stations

Contract version 1.0.0, not yet released. The schemas in [`contract/v1/schemas`](../contract/v1/schemas) are authoritative.

## Principles

- One record per **station**, with one or more **streams**.
- Stable facts and volatile health are stored apart, so a daily check does not rewrite every record.
- Every record states where it comes from. Only sources on the allowlist are accepted.
- Identifiers are never reused. Merged records leave a redirect.
- No personal data, ever: no contributor identifier appears in any published file.

## Files

```
v1/
  manifest.json
  stations/FR.ndjson.gz      stable records, one JSON object per line, sorted by id
  redirects.ndjson.gz        old id -> new id
  health/FR.ndjson.gz        volatile state, CDN only (planned, not in the first release)
```

Sharding by ISO 3166-1 country code. `XX.ndjson.gz` holds stations with no known country.

## Manifest

```json
{
  "contract": "1.0.0",
  "dataset_version": "2026-11-20.1",
  "generated_at": "2026-11-20T04:00:00Z",
  "license": "CC0-1.0",
  "datasets": {
    "stations": [
      { "shard": "FR", "path": "stations/FR.ndjson.gz", "sha256": "…", "bytes": 182044, "count": 3120 }
    ],
    "redirects": [
      { "shard": "all", "path": "redirects.ndjson.gz", "sha256": "…", "bytes": 310, "count": 4 }
    ]
  }
}
```

A client downloads the manifest, compares each `sha256` with its local copy, and fetches only what changed.

## Station

```json
{
  "id": "st_01jc8w5k3v9q2m7xr4tn6ydbfa",
  "rev": 3,
  "status": "active",
  "name": "FIP",
  "alt_names": [{ "name": "France Inter Paris", "lang": "fr" }],
  "country": "FR",
  "subdivision": "FR-75",
  "place": { "name": "Paris", "wikidata": "Q90", "lat": 48.8567, "lon": 2.3508, "scope": "city" },
  "languages": ["fr"],
  "tags": ["eclectic", "jazz"],
  "homepage": "https://www.radiofrance.fr/fip",
  "logo_url": "https://example.org/logo.png",
  "streams": [
    {
      "id": "sm_01jc8w5m2c4t8h1p9e3rkvz7qd",
      "url": "https://stream.radiofrance.fr/fip/fip_hifi.m3u8",
      "protocol": "hls",
      "codec": "aac",
      "bitrate_kbps": 192,
      "role": "primary"
    }
  ],
  "ids": {
    "wikidata": "Q1435613",
    "radio_browser": ["00000000-0000-0000-0000-000000000000"]
  },
  "sources": [
    { "source": "radio-browser", "retrieved_at": "2026-11-20" }
  ],
  "updated_at": "2026-11-20T04:00:00Z"
}
```

The values above are illustrative.

| Field | Required | Rule |
|---|---|---|
| `id` | yes | `st_` + 26 lowercase characters, opaque, permanent. Never parse it |
| `rev` | yes | Integer, increases on every published change |
| `status` | yes | `active`, `retired`. Open list: unknown values are treated as `retired` |
| `name` | yes | 1 to 200 characters, as used by the station |
| `alt_names` | no | Other names, with optional BCP 47 `lang` |
| `country` | no | ISO 3166-1 alpha-2 |
| `subdivision` | no | ISO 3166-2 |
| `place` | no | `scope` is `city`, `region`, `country` or `reported` (coordinates as given by the source, unverified). Open list. Coordinates are not a transmitter position |
| `languages` | no | BCP 47 |
| `tags` | no | Lowercase, normalised |
| `homepage` | no | `http` or `https` |
| `logo_url` | no | Address of the image at its origin, never hosted here. For a station matched with Wikidata, a PNG thumbnail of its logo on Wikimedia Commons, whose page states the licence |
| `streams` | yes | At least one when `status` is `active` |
| `wikipedia` | no | Article titles by language, from Wikidata: `{"fr": "FIP"}` gives `https://fr.wikipedia.org/wiki/FIP` |
| `ids` | no | External identifiers. New keys may be added, such as `musicbrainz`. `contributions` lists the proposals a station comes from |
| `sources` | yes | At least one, from the allowlist |
| `updated_at` | yes | UTC, RFC 3339 |

## Stream

| Field | Required | Rule |
|---|---|---|
| `id` | yes | `sm_` + 26 lowercase characters, opaque, permanent |
| `url` | yes | `http` or `https`, public host only, no credentials, no session or tracking parameters |
| `protocol` | yes | `http`, `hls`, `dash`, or an unknown value to ignore |
| `codec` | no | `mp3`, `aac`, `he-aac`, `flac`, `opus`, `vorbis`, … Open list. Measured, not declared: see below |
| `bitrate_kbps` | no | Integer |
| `role` | no | `primary`, `alternate`, `low-bandwidth` |

`codec` and `bitrate_kbps` come from the last successful check of the Radio Browser checker. A failed check publishes nothing. A codec the checker cannot name (an Ogg container, a video stream) is left out. When the measures cannot be fetched, a build keeps the last known values. A protocol measured as HLS is published as `hls`, even without `.m3u8` in the address.

**Clients must treat every URL as untrusted.** They must refuse private, loopback and link-local addresses, including after DNS resolution and redirects.

## Health (planned)

```json
{ "id": "sm_01jc8w5m2c4t8h1p9e3rkvz7qd", "state": "ok", "checked_at": "2026-11-20T03:12:00Z", "last_ok_at": "2026-11-20T03:12:00Z", "codec": "aac", "bitrate_kbps": 192, "failures": 0 }
```

`state` is `ok`, `failing` or `unknown`. A failure means "unreachable from the checker". It may be a geographic restriction.

## Wikidata

A station is matched with a Wikidata item only when the match is sure: same country and same name, and either a shared domain between the item's official website and the station's addresses, or a name unique on both sides with no contradicting website. A matched station gets `ids.wikidata`, `wikipedia`, the item's logo, and its website when it had none. Its `sources` then list `wikidata`.

## Grouping

Source rows describe one stream each. Two rows become one station when:

- they share a stream address, ignoring http or https; or
- they have the same name in the same country, and the same channel in their path, such as `fip` in `fip_hifi.m3u8`; or
- they have the same name in the same country, no channel in their path, and a domain that is not shared hosting.

A name alone is never enough. Source rows are sometimes mislabelled, and a duplicate record does less harm than a wrong stream in a record. Identifiers stay stable because each build reads the previous one. A station gone from its source becomes `retired`: it is not deleted.

## Redirect

```json
{ "from": "st_01jc8w5k3v9q2m7xr4tn6ydbfb", "to": "st_01jc8w5k3v9q2m7xr4tn6ydbfa", "at": "2026-11-20" }
```

Clients follow redirects until they reach a live id. Chains are collapsed at build time.

## Allowed sources

| `source` | Licence |
|---|---|
| `radio-browser` | Public domain dedication |
| `wikidata` | CC0 |
| `contribution` | CC0, accepted by the contributor |
| `editor` | CC0 |

A test rejects any other value. Adding a source requires a documented licence check.
