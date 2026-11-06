# Contract

The contract is the promise made to every client of the dataset. It is dedicated to the public domain under CC0, so any client may copy it without obligation.

## Layout (planned)

```
contract/
  CHANGELOG.md
  v1/
    schemas/          JSON Schema 2020-12: manifest, station, health, redirect
    openapi.yaml      contribution API, added with the API
    cases/
      valid/          records every client must accept
      invalid/        records every client must reject
      normalize/      input and expected output: URLs, names, tags
      unknown/        records with future fields and values, to prove tolerance
```

Each case is a JSON file with a `description`, an `input` and an `expected` value. The same cases run in this repository and in each client.

## Versioning

- Releases are git tags: `contract-v1.0.0`.
- Clients copy a tagged version into their own repository and move to a new tag on purpose.
- Published paths and the API live under `/v1`.

## Compatibility rules

Inside `v1`, changes are additive only.

**Allowed:** a new optional field, a new value in an open list, a new dataset, a new key in `ids`, a new endpoint.

**Forbidden:** removing or renaming a field, changing its type or meaning, making an optional field required, tightening a rule so an old record fails.

**Clients must:**

- ignore unknown fields;
- handle unknown values in open lists as documented;
- ignore unknown datasets in the manifest;
- keep working on their local copy when the service is unreachable.

A check compares every change to the previous tag and fails if a rule is broken. A breaking change means a new `/v2`, published alongside `/v1`.
