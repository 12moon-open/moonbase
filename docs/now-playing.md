# Now-playing adapters

Contract 1.1. An adapter says where a station publishes what it is playing and how to read it. It is data, never code, and it is executed by the listener's own server, never by an app. 12moon publishes adapters; it never fetches, stores or publishes the titles themselves.

Schemas: [`now-playing-adapter`](../contract/v1/schemas/now-playing-adapter.schema.json), [`now-playing-template`](../contract/v1/schemas/now-playing-template.schema.json), [`now-playing-proposal`](../contract/v1/schemas/now-playing-proposal.schema.json). Reference executor: [`api/src/nowplaying.js`](../api/src/nowplaying.js). Specification by example: [`cases/now-playing`](../contract/v1/cases/now-playing).

## Executing an adapter

1. **Resolve.** A template-based adapter takes its request and extraction from the template. Each param must match the template's pattern; it is URL-encoded into `{name}`. The URL must be HTTPS, port 443, without credentials or IP literal, and its host must be one of `request.hosts`.
2. **Fetch.** One `GET`, without cookies or headers chosen by the adapter. Redirects only to one of `hosts`, in HTTPS, two at most, each checked against private addresses after DNS resolution. Respect `robots.txt`, `poll.min_interval_s`, `Retry-After` and `Cache-Control`.
3. **Read.** The `Content-Type` must match `expect` (`wrong_type`), the body must fit `limits.max_bytes` (`too_large`). JSON uses a JSONPath subset: `$`, `.key`, `['key']`, `[n]`, `[-1]`, `[*]`. HTML and XML use a CSS subset: type, `.class`, `#id`, `[attr]`, `[attr=value]`, descendant, `>`, `:first-of-type`, `:nth-of-type(n)`. Text of `<script>` and `<style>` is never read; entities are decoded.
4. **Fields.** For each field: select, then `regex` (first capture, or the match), `split`, `html_unescape`, trim, then `time` or the value checks. A text value has its tags removed and spaces collapsed; it is refused when longer than 200 characters, when it holds an invisible character or a web address (`invalid_value`). `check: isrc` keeps a valid ISRC only.
5. **Times.** `iso8601`, `unix_s`, `unix_ms`, or `local_hm` / `local_hms` with an IANA `timezone`: attached to the local day, or the previous one when more than 5 minutes in the future.
6. **Pick** among items with an artist and a title: `first`, `last`, or `latest_started`. None: `no_item`.
7. **Result.**
   - `ignored` when the title is the station name (`equals_station_name`) or matches an `ignore.patterns` entry (case-insensitive, on `artist - title`);
   - `ended` when `ended_at` plus `grace_after_end_s` is past;
   - `stale` when `started_at`, or else `observed_at`, is older than `max_age_s`; a start more than 5 minutes in the future is `invalid_value`;
   - otherwise `current`, with `artist`, `title`, and when known `album`, `isrc`, `show`, `started_at`, `ended_at`.

Regular expressions are at most 200 characters, with no lookaround and no back-reference, so that .NET (`NonBacktracking`) and JavaScript agree.

## Publication

Adapters are proposed with `kind: "now_playing_adapter"` (signed, CC0, counters only in `checks`). 12moon checks the hosts, `robots.txt` and runs the adapter twice before publishing it in the `now_playing` dataset. A daily run marks a failing adapter `broken`, then `revoked` after 30 days. A station's request, a disallowing `robots.txt` or the maintainer revoke it at once, and its host joins the blocked list.

A service template is published only once the service's terms allow it, or the service agreed. Until then its status is `needs_permission`.
