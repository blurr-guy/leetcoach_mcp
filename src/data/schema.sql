-- LeetCoach SQLite schema.
--
-- Applied automatically on first connect by src/data/db.py. Everything is local:
-- one file, no server, no network, no accounts. Single-user by design, so there
-- are no RLS policies and no auth columns beyond the user_id scoping key.

CREATE TABLE IF NOT EXISTS problems (
    id               INTEGER PRIMARY KEY,          -- LeetCode's problem number
    title            TEXT    NOT NULL,
    slug             TEXT    NOT NULL UNIQUE,
    difficulty       TEXT    NOT NULL CHECK (difficulty IN ('Easy', 'Medium', 'Hard')),
    topics           TEXT    NOT NULL DEFAULT '[]', -- JSON array of strings
    leetcode_url     TEXT    NOT NULL,
    acceptance_rate  REAL    NOT NULL DEFAULT 0,
    frequency        REAL    NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_problems_difficulty ON problems (difficulty);
CREATE INDEX IF NOT EXISTS idx_problems_slug ON problems (slug);

CREATE TABLE IF NOT EXISTS attempts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             TEXT    NOT NULL,
    problem_id          INTEGER NOT NULL REFERENCES problems (id) ON DELETE CASCADE,
    status              TEXT    NOT NULL CHECK (status IN ('solved', 'attempted', 'skipped')),
    time_taken_minutes  INTEGER CHECK (time_taken_minutes IS NULL OR time_taken_minutes >= 0),
    timestamp           TEXT    NOT NULL DEFAULT (datetime('now')),
    notes               TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_attempts_user_time ON attempts (user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_attempts_problem ON attempts (problem_id);

CREATE TABLE IF NOT EXISTS user_profile (
    user_id           TEXT    PRIMARY KEY,
    weak_topics       TEXT    NOT NULL DEFAULT '[]', -- JSON array of strings
    target_companies  TEXT    NOT NULL DEFAULT '[]', -- JSON array of strings
    streak            INTEGER NOT NULL DEFAULT 0,
    last_active       TEXT,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);
