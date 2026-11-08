-- Stations added by installations. The body is what the installation sent, already validated.
CREATE TABLE station_proposals (
  id TEXT PRIMARY KEY,
  contributor_id TEXT REFERENCES contributors(id) ON DELETE SET NULL,
  fingerprint TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT NOT NULL,          -- pending, verifying, published, duplicate, rejected, hidden, revoked
  reason TEXT,
  station TEXT,                  -- st_… of an existing station, for a duplicate
  streams TEXT,                  -- streams as checked: url, protocol, codec, bitrate_kbps
  claimed_at INTEGER,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX station_proposals_status ON station_proposals(status, created_at);
CREATE INDEX station_proposals_contributor ON station_proposals(contributor_id, created_at);
CREATE INDEX station_proposals_updated ON station_proposals(updated_at, id);

CREATE TABLE station_reports (
  id TEXT PRIMARY KEY,
  station TEXT NOT NULL,
  contributor_id TEXT REFERENCES contributors(id) ON DELETE SET NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL,          -- open, accepted, dismissed
  created_at INTEGER NOT NULL
);
CREATE INDEX station_reports_status ON station_reports(status, created_at);
