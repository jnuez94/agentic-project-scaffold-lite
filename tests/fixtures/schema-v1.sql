PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
BEGIN IMMEDIATE;
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS metadata (
  key TEXT NOT NULL PRIMARY KEY CHECK (length(trim(key)) BETWEEN 1 AND 128),
  value TEXT NOT NULL
);

INSERT OR IGNORE INTO metadata(key, value) VALUES ('schema_version', '1');

CREATE TABLE IF NOT EXISTS agents (
  id TEXT NOT NULL PRIMARY KEY
    CHECK (
      length(id) BETWEEN 1 AND 128
      AND substr(id, 1, 1) GLOB '[A-Za-z0-9]'
      AND id NOT GLOB '*[^A-Za-z0-9._:@+-]*'
    ),
  name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 65536),
  role TEXT NOT NULL CHECK (length(trim(role)) BETWEEN 1 AND 65536),
  actor_type TEXT NOT NULL DEFAULT 'ai' CHECK (actor_type IN ('ai', 'human', 'service')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
  responsibilities TEXT NOT NULL DEFAULT '',
  goal TEXT NOT NULL DEFAULT '',
  operating_style TEXT NOT NULL DEFAULT '',
  decision_authority TEXT NOT NULL DEFAULT '',
  review_authority TEXT NOT NULL DEFAULT '',
  escalation_rules TEXT NOT NULL DEFAULT '',
  unavailable_for TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_sessions (
  id TEXT NOT NULL PRIMARY KEY
    CHECK (
      length(id) BETWEEN 1 AND 128
      AND substr(id, 1, 1) GLOB '[A-Za-z0-9]'
      AND id NOT GLOB '*[^A-Za-z0-9._:@+-]*'
    ),
  agent_id TEXT NOT NULL REFERENCES agents(id),
  harness TEXT NOT NULL CHECK (length(trim(harness)) BETWEEN 1 AND 65536),
  model TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'ended')),
  started_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  ended_at TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT NOT NULL PRIMARY KEY
    CHECK (
      length(id) BETWEEN 1 AND 128
      AND substr(id, 1, 1) GLOB '[A-Za-z0-9]'
      AND id NOT GLOB '*[^A-Za-z0-9._:@+-]*'
    ),
  title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 65536),
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'in_progress', 'review', 'blocked', 'done')),
  priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
  tags TEXT NOT NULL DEFAULT '',
  acceptance_criteria TEXT NOT NULL DEFAULT '',
  next_steps TEXT NOT NULL DEFAULT '',
  blocked_claims TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL REFERENCES agents(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_assignees (
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  agent_id TEXT NOT NULL REFERENCES agents(id),
  assigned_at TEXT NOT NULL,
  PRIMARY KEY (task_id, agent_id)
);

CREATE TABLE IF NOT EXISTS task_claims (
  task_id TEXT NOT NULL PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
  agent_id TEXT NOT NULL REFERENCES agents(id),
  session_id TEXT NOT NULL REFERENCES agent_sessions(id),
  claimed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_dependencies (
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  depends_on_task_id TEXT NOT NULL REFERENCES tasks(id),
  dependency_type TEXT NOT NULL CHECK (dependency_type IN ('blocks', 'informs', 'review_required', 'evidence_required')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'resolved')),
  rationale TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  PRIMARY KEY (task_id, depends_on_task_id, dependency_type),
  CHECK (task_id <> depends_on_task_id)
);

CREATE TABLE IF NOT EXISTS task_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  uri TEXT NOT NULL CHECK (length(trim(uri)) BETWEEN 1 AND 65536),
  evidence_type TEXT NOT NULL DEFAULT 'artifact'
    CHECK (length(trim(evidence_type)) BETWEEN 1 AND 65536),
  added_by TEXT NOT NULL REFERENCES agents(id),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT NOT NULL PRIMARY KEY
    CHECK (
      length(id) BETWEEN 1 AND 128
      AND substr(id, 1, 1) GLOB '[A-Za-z0-9]'
      AND id NOT GLOB '*[^A-Za-z0-9._:@+-]*'
    ),
  sender_id TEXT NOT NULL REFERENCES agents(id),
  recipient TEXT NOT NULL CHECK (length(trim(recipient)) BETWEEN 1 AND 65536),
  task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
  body TEXT NOT NULL CHECK (length(trim(body)) BETWEEN 1 AND 65536),
  tags TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
  id TEXT NOT NULL PRIMARY KEY
    CHECK (
      length(id) BETWEEN 1 AND 128
      AND substr(id, 1, 1) GLOB '[A-Za-z0-9]'
      AND id NOT GLOB '*[^A-Za-z0-9._:@+-]*'
    ),
  task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
  reviewer_id TEXT NOT NULL REFERENCES agents(id),
  artifact_uri TEXT NOT NULL CHECK (length(trim(artifact_uri)) BETWEEN 1 AND 65536),
  scope TEXT NOT NULL CHECK (length(trim(scope)) BETWEEN 1 AND 65536),
  decision TEXT NOT NULL CHECK (decision IN ('accepted', 'conditionally_accepted', 'changes_requested', 'rejected')),
  accepted_items TEXT NOT NULL DEFAULT '',
  required_changes TEXT NOT NULL DEFAULT '',
  remaining_risks TEXT NOT NULL DEFAULT '',
  blocked_claims TEXT NOT NULL DEFAULT '',
  follow_up_tasks TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
  id TEXT NOT NULL PRIMARY KEY
    CHECK (
      length(id) BETWEEN 1 AND 128
      AND substr(id, 1, 1) GLOB '[A-Za-z0-9]'
      AND id NOT GLOB '*[^A-Za-z0-9._:@+-]*'
    ),
  title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 65536),
  owner_id TEXT NOT NULL REFERENCES agents(id),
  status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'accepted', 'superseded', 'rejected')),
  context TEXT NOT NULL CHECK (length(trim(context)) BETWEEN 1 AND 65536),
  decision TEXT NOT NULL CHECK (length(trim(decision)) BETWEEN 1 AND 65536),
  options_considered TEXT NOT NULL DEFAULT '',
  implications TEXT NOT NULL DEFAULT '',
  evidence TEXT NOT NULL DEFAULT '',
  blocked_claims TEXT NOT NULL DEFAULT '',
  review_required TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT NOT NULL PRIMARY KEY
    CHECK (
      length(id) BETWEEN 1 AND 128
      AND substr(id, 1, 1) GLOB '[A-Za-z0-9]'
      AND id NOT GLOB '*[^A-Za-z0-9._:@+-]*'
    ),
  uri TEXT NOT NULL UNIQUE CHECK (length(trim(uri)) BETWEEN 1 AND 65536),
  owner_id TEXT NOT NULL REFERENCES agents(id),
  type TEXT NOT NULL CHECK (length(trim(type)) BETWEEN 1 AND 65536),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'review', 'accepted', 'superseded')),
  usage_boundaries TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifact_tasks (
  artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  PRIMARY KEY (artifact_id, task_id)
);

CREATE TABLE IF NOT EXISTS artifact_reviewers (
  artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
  reviewer_id TEXT NOT NULL REFERENCES agents(id),
  PRIMARY KEY (artifact_id, reviewer_id)
);

CREATE TABLE IF NOT EXISTS escalations (
  id TEXT NOT NULL PRIMARY KEY
    CHECK (
      length(id) BETWEEN 1 AND 128
      AND substr(id, 1, 1) GLOB '[A-Za-z0-9]'
      AND id NOT GLOB '*[^A-Za-z0-9._:@+-]*'
    ),
  raised_by TEXT NOT NULL REFERENCES agents(id),
  owner TEXT NOT NULL CHECK (length(trim(owner)) BETWEEN 1 AND 65536),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_review', 'resolved', 'closed_no_action')),
  related_tasks TEXT NOT NULL DEFAULT '',
  needed_by TEXT,
  issue TEXT NOT NULL CHECK (length(trim(issue)) BETWEEN 1 AND 65536),
  requested_decision TEXT NOT NULL
    CHECK (length(trim(requested_decision)) BETWEEN 1 AND 65536),
  resolution TEXT NOT NULL DEFAULT '',
  follow_up_tasks TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT NOT NULL REFERENCES agents(id),
  session_id TEXT REFERENCES agent_sessions(id),
  action TEXT NOT NULL,
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status_priority ON tasks(status, priority, updated_at);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent_status
  ON agent_sessions(agent_id, status, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_task_assignees_agent ON task_assignees(agent_id, task_id);
CREATE INDEX IF NOT EXISTS idx_task_claims_agent ON task_claims(agent_id, claimed_at);
CREATE INDEX IF NOT EXISTS idx_evidence_task ON task_evidence(task_id);
CREATE INDEX IF NOT EXISTS idx_reviews_task ON reviews(task_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient, created_at);
CREATE INDEX IF NOT EXISTS idx_escalations_status ON escalations(status, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_log(session_id, created_at);

CREATE TRIGGER IF NOT EXISTS task_insert_done_requires_evidence
BEFORE INSERT ON tasks
WHEN NEW.status = 'done'
BEGIN
  SELECT RAISE(ABORT, 'a task cannot be created as done');
END;

CREATE TRIGGER IF NOT EXISTS task_claim_requires_active_session
BEFORE INSERT ON task_claims
WHEN NOT EXISTS (
  SELECT 1
  FROM agent_sessions s
  JOIN agents a ON a.id = s.agent_id
  WHERE s.id = NEW.session_id
    AND s.agent_id = NEW.agent_id
    AND s.status = 'active'
    AND a.status = 'active'
)
BEGIN
  SELECT RAISE(ABORT, 'task claim requires a matching active session');
END;

CREATE TRIGGER IF NOT EXISTS task_claim_requires_claimable_state
BEFORE INSERT ON task_claims
WHEN (SELECT status FROM tasks WHERE id = NEW.task_id)
  NOT IN ('todo', 'review', 'blocked')
BEGIN
  SELECT RAISE(ABORT, 'task is not in a claimable state');
END;

CREATE TRIGGER IF NOT EXISTS task_enter_in_progress_requires_claim
BEFORE UPDATE OF status ON tasks
WHEN NEW.status = 'in_progress'
  AND OLD.status <> 'in_progress'
  AND NOT EXISTS (SELECT 1 FROM task_claims WHERE task_id = NEW.id)
BEGIN
  SELECT RAISE(ABORT, 'in_progress requires an active task claim');
END;

CREATE TRIGGER IF NOT EXISTS task_status_requires_next_revision
BEFORE UPDATE OF status ON tasks
WHEN NEW.status <> OLD.status
  AND NEW.revision <> OLD.revision + 1
BEGIN
  SELECT RAISE(ABORT, 'task status change requires the next revision');
END;

CREATE TRIGGER IF NOT EXISTS task_update_done_requires_evidence
BEFORE UPDATE OF status ON tasks
WHEN NEW.status = 'done'
  AND NOT EXISTS (SELECT 1 FROM task_evidence WHERE task_id = NEW.id)
BEGIN
  SELECT RAISE(ABORT, 'done requires at least one evidence record');
END;

COMMIT;
