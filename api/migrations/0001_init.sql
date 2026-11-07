-- Contributors are anonymous: an identifier derived from a public key. No IP address,
-- no e-mail, no name is ever stored.
CREATE TABLE contributors (
  id TEXT PRIMARY KEY,
  public_key TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL,
  blocked_at INTEGER
);

CREATE TABLE nonces (
  nonce TEXT PRIMARY KEY,
  expires_at INTEGER NOT NULL
);

CREATE TABLE proposals (
  id TEXT PRIMARY KEY,
  contributor_id TEXT REFERENCES contributors(id) ON DELETE SET NULL,
  kind TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  media TEXT NOT NULL,
  musicbrainz_release TEXT NOT NULL,
  status TEXT NOT NULL,
  reason TEXT,
  link_id TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  decided_at INTEGER
);
CREATE INDEX proposals_queue ON proposals(status, next_attempt_at);
CREATE INDEX proposals_contributor ON proposals(contributor_id, created_at);
CREATE INDEX proposals_subject ON proposals(fingerprint, musicbrainz_release);

CREATE TABLE links (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  media TEXT NOT NULL,
  musicbrainz_release TEXT NOT NULL,
  verified_by TEXT NOT NULL,
  status TEXT NOT NULL,
  updated_at INTEGER NOT NULL,
  UNIQUE (fingerprint, musicbrainz_release)
);
CREATE INDEX links_updated ON links(updated_at, id);

CREATE TABLE reports (
  id TEXT PRIMARY KEY,
  link_id TEXT NOT NULL,
  contributor_id TEXT REFERENCES contributors(id) ON DELETE SET NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
