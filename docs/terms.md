# Terms of contribution

12moon commons is an open database of internet radio stations, published in the public domain. These terms apply when an app sends something to `api.12moon.app`. Reading the data needs no account and has no conditions: it is released under CC0 1.0.

## What you can send

- **A station** that the data does not have: its name, country, stream addresses, and optionally its website, logo address, town, coordinates, languages and genres.
- **A report** on a published station: dead stream, wrong information, inappropriate, not a station, duplicate.
- **Stream measures**, only if you turn them on in your app: whether streams started, how fast, how often they stopped, their codec and bitrate. Once a week at most, without listening time or any time finer than the week.
- **Album links** between your files and MusicBrainz releases, made of track durations only.

## What you agree to

- **Public domain.** What you send is placed in the public domain under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). You waive any right you may have on it. Anyone may copy and reuse it, for any purpose.
- **Facts only.** You send public facts about a station: its official name and the addresses it publishes itself. No text written by you, no copied description, no stream you are not allowed to share.
- **Good faith.** No false stations, no advertising, no content that is illegal or hateful. Abuse leads to every contribution from your installation being withdrawn.

## What is collected

- **No account, no name, no e-mail.** Your app signs its requests with a key it creates. The service keeps an identifier derived from that key, to apply limits and to withdraw contributions if needed.
- **No IP address is stored.**
- **Stream measures are not linked to you.** The key that signs them is never stored, and the server keeps only counters, without the report they came from. A score is published only when at least three installations measured a stream in the same week.
- **Erasure.** Your app can erase its identifier at any time (`DELETE /v1/contributors/me`). What was already published stays, without any link to you.

## How contributions are handled

- **Automatic checks.** Every station is checked before publication: each stream must play. A stream already known links your proposal to the existing station.
- **Publication.** Accepted stations appear in the next daily release of the data, at `data.12moon.app` and in the [`moondust`](https://github.com/12moon-open/moondust) repository.
- **Reports and removal.** Reports are reviewed by the maintainer, who can withdraw a station and every contribution of an installation. A broadcaster may ask for its station to be removed.
- **No warranty.** The service and the data are provided as they are, without warranty. Stream addresses point to third parties: 12moon does not host any audio, image or text of a station.

## Contact

To report illegal content, ask for a removal or ask a question: see the contact on [the published terms](https://api.12moon.app/terms).

The full technical description is in [contributions](contributions.md).
