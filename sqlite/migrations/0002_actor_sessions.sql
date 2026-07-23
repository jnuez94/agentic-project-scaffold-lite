BEGIN IMMEDIATE;

ALTER TABLE agents
  ADD COLUMN actor_type TEXT NOT NULL DEFAULT 'ai'
  CHECK (actor_type IN ('ai', 'human', 'service'));

CREATE TABLE agent_sessions (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES agents(id),
  harness TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'ended')),
  started_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  ended_at TEXT
);

ALTER TABLE audit_log
  ADD COLUMN session_id TEXT REFERENCES agent_sessions(id);

CREATE INDEX idx_agent_sessions_agent_status
  ON agent_sessions(agent_id, status, last_seen_at);
CREATE INDEX idx_audit_session ON audit_log(session_id, created_at);

INSERT OR IGNORE INTO metadata(key, value) VALUES ('schema_version', '2');
UPDATE metadata SET value = '2' WHERE key = 'schema_version';
PRAGMA user_version = 2;

COMMIT;
