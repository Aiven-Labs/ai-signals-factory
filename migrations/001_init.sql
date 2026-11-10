-- Meetup factory core schema. Apply with: psql "$DATABASE_URL" -f migrations/001_init.sql
CREATE TABLE IF NOT EXISTS organisers (
  id            SERIAL PRIMARY KEY,
  name          TEXT NOT NULL,
  email         TEXT UNIQUE,
  slack_id      TEXT UNIQUE,
  telegram_id   TEXT UNIQUE,
  role          TEXT NOT NULL DEFAULT 'volunteer'
                CHECK (role IN ('admin','organiser','volunteer','observer')),
  active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS events (
  id            SERIAL PRIMARY KEY,
  number        INTEGER UNIQUE,
  title         TEXT NOT NULL,
  event_date    DATE NOT NULL,
  venue         TEXT,
  host_id       INTEGER REFERENCES organisers(id),
  github_issue  TEXT,
  status        TEXT NOT NULL DEFAULT 'planning'
                CHECK (status IN ('planning','confirmed','done','cancelled'))
);

CREATE TABLE IF NOT EXISTS speakers (
  id            SERIAL PRIMARY KEY,
  name          TEXT NOT NULL,
  email         TEXT UNIQUE,
  source_row    TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- speaker pipeline: pitched -> invited -> confirmed -> declined / spoke
CREATE TABLE IF NOT EXISTS event_speakers (
  event_id      INTEGER REFERENCES events(id) ON DELETE CASCADE,
  speaker_id    INTEGER REFERENCES speakers(id) ON DELETE CASCADE,
  talk_title    TEXT,
  state         TEXT NOT NULL DEFAULT 'pitched'
                CHECK (state IN ('pitched','invited','confirmed','declined','spoke')),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (event_id, speaker_id)
);

-- every outward action is a proposal first; nothing is sent without a decision
CREATE TABLE IF NOT EXISTS proposed_actions (
  id            SERIAL PRIMARY KEY,
  idem_key      TEXT UNIQUE NOT NULL,
  kind          TEXT NOT NULL,
  payload       JSONB NOT NULL DEFAULT '{}',
  requested_by  TEXT NOT NULL DEFAULT 'system',
  status        TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','approved','rejected','done','failed')),
  decided_by    INTEGER REFERENCES organisers(id),
  decided_at    TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inbound_messages (
  id            SERIAL PRIMARY KEY,
  channel       TEXT NOT NULL,
  sender        TEXT NOT NULL,
  body          TEXT NOT NULL,
  intent        TEXT,
  handled_by    TEXT,          -- 'rule' | 'model' | 'human'
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS access_grants (
  id            SERIAL PRIMARY KEY,
  organiser_id  INTEGER NOT NULL REFERENCES organisers(id),
  system        TEXT NOT NULL,   -- github, slack, drive, squarespace, luma, meetup, youtube, linkedin
  automated     BOOLEAN NOT NULL DEFAULT FALSE,
  status        TEXT NOT NULL DEFAULT 'requested'
                CHECK (status IN ('requested','granted','revoked')),
  proposal_id   INTEGER REFERENCES proposed_actions(id),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (organiser_id, system)
);

CREATE TABLE IF NOT EXISTS audit_log (
  id            BIGSERIAL PRIMARY KEY,
  at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor         TEXT NOT NULL,
  action        TEXT NOT NULL,
  detail        JSONB NOT NULL DEFAULT '{}'
);

-- every model call is logged so the zero-token share is measurable
CREATE TABLE IF NOT EXISTS llm_calls (
  id            BIGSERIAL PRIMARY KEY,
  at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  purpose       TEXT NOT NULL,
  model         TEXT NOT NULL,
  tokens_in     INTEGER,
  tokens_out    INTEGER
);
