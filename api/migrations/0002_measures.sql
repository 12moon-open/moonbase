-- Stream measures. Nothing here identifies an installation, and nothing links the rows of one report.

-- One random secret per ISO week, deleted a few weeks after the week ends.
CREATE TABLE measure_weeks (
  week TEXT PRIMARY KEY,
  secret TEXT NOT NULL
);

-- HMAC(week secret, public key): refuses a second report from the same key for the same week.
-- Deleted with the week's secret, after which it can no longer be matched to any key.
CREATE TABLE measure_senders (
  marker TEXT PRIMARY KEY,
  week TEXT NOT NULL
);

-- One row per stream per report. Stored in stream order with a random tie-breaker,
-- so the rows of one report are not kept together.
CREATE TABLE stream_measures (
  stream TEXT NOT NULL,
  week TEXT NOT NULL,
  tie TEXT NOT NULL,
  success REAL,
  startup_ms INTEGER,
  stalls_per_play REAL NOT NULL,
  geo_blocked INTEGER NOT NULL,
  codec TEXT,
  bitrate_kbps INTEGER,
  PRIMARY KEY (stream, week, tie)
) WITHOUT ROWID;
