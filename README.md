# 12moon commons

An open metadata commons for music software, starting with internet radio stations. It complements [MusicBrainz](https://musicbrainz.org/) and does not copy it.

> **Status:** early. The first dataset is in [`moondust`](https://github.com/12moon-open/moondust). `data.12moon.app` is not live yet, and streams have not been checked for playback.

## What it is

- **Stations first.** One clean record per station, with verified streams, a place and links to other open databases.
- **Open.** The dataset is dedicated to the public domain under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). Anyone may reuse it, for any purpose, with no obligation.
- **Built to outlive the service.** Reads are static files. A full dated export lives in the public [`moondust`](https://github.com/12moon-open/moondust) repository.
- **Linked, not duplicated.** Records point to Wikidata, Radio Browser and, later, MusicBrainz identifiers. Anything without a home elsewhere gets a 12moon identifier.

## What it is not

No audio, cover art, lyrics, reviews or biographies. No personal data of any kind: no listening history, ratings, file paths or server addresses.

## Using the data

Planned address:

```
https://data.12moon.app/v1/manifest.json
```

Until then, use the files in [`moondust`](https://github.com/12moon-open/moondust).

The manifest lists every file with its checksum. Fetch only what changed. See [the data model](docs/data-model.md) and [the contract](contract/README.md).

Please cache locally and treat every URL as untrusted.

## Building the dataset

Python 3, standard library only. Tests also use `jsonschema` for the contract.

```bash
python -m pipeline.build --input radiobrowser_stations_YYYYMMDD_HHMMSS.json.gz --out ../moondust --dist ../dist
python -m unittest discover -s tests -t .
```

The build refuses to publish a truncated source or a large drop in stations.

## Contributing

A contribution API is planned. Every contribution will be a proposal, checked before publication. Until then, please report errors, including rights issues or a request to remove a station, in the [issues](https://github.com/12moon-open/moonbase/issues).

If a correction belongs in Radio Browser, Wikidata or MusicBrainz, it should go there first.

## Sources and thanks

- [Radio Browser](https://www.radio-browser.info/), a community directory whose data is dedicated to the public domain.
- [Wikidata](https://www.wikidata.org/), CC0.

## Licences

- Data and contract: [CC0 1.0](contract/LICENSE).
- Code: [MIT](LICENSE).

## En français

12moon commons est une base de métadonnées ouverte, en complément de MusicBrainz, qui commence par les radios. Les données sont sous CC0. Aucune donnée personnelle, aucun fichier audio, aucune pochette, aucun texte d'auteur.
