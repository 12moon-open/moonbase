-- People and agents allowed to edit stations. Only a hash of each token is kept.
CREATE TABLE editors (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL,            -- maintainer, agent
  token_hash TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL,
  last_used_at INTEGER,
  revoked_at INTEGER
);

-- One edit of one station. The build applies every accepted edit, in order.
CREATE TABLE edits (
  id TEXT PRIMARY KEY,
  station TEXT NOT NULL,
  body TEXT NOT NULL,            -- the validated change, without note nor source
  note TEXT,
  source TEXT,
  editor_id TEXT NOT NULL REFERENCES editors(id),
  status TEXT NOT NULL,          -- pending, accepted, rejected, reverted
  decided_by TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX edits_status ON edits(status, created_at);
CREATE INDEX edits_station ON edits(station, created_at);
CREATE INDEX edits_updated ON edits(updated_at, id);
CREATE INDEX edits_editor ON edits(editor_id, created_at);

-- A searchable copy of the published stations, refreshed from data.12moon.app by the cron.
CREATE TABLE catalog (
  id TEXT PRIMARY KEY,
  shard TEXT NOT NULL,
  rev INTEGER NOT NULL,
  name_key TEXT NOT NULL,
  find TEXT NOT NULL,            -- name key, addresses and stream ids, lowercase
  country TEXT,
  status TEXT NOT NULL,
  record TEXT NOT NULL
);
CREATE INDEX catalog_shard ON catalog(shard);
CREATE INDEX catalog_country ON catalog(country);
CREATE TABLE catalog_shards (shard TEXT PRIMARY KEY, sha256 TEXT NOT NULL, version TEXT NOT NULL);
CREATE TABLE catalog_redirects (from_id TEXT PRIMARY KEY, to_id TEXT NOT NULL);

-- Stations added by an editor go through the same stream check as those from installations.
ALTER TABLE station_proposals ADD COLUMN editor_id TEXT;
