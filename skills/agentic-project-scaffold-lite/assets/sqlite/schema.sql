PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT OR IGNORE INTO metadata(key, value) VALUES ('schema_version', '1');

CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  role TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'in_progress', 'review', 'blocked', 'done')),
  priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
  tags TEXT NOT NULL DEFAULT '',
  acceptance_criteria TEXT NOT NULL DEFAULT '',
  next_steps TEXT NOT NULL DEFAULT '',
  blocked_claims TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  created_by TEXT REFERENCES agents(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_assignees (
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  agent_id TEXT NOT NULL REFERENCES agents(id),
  assigned_at TEXT NOT NULL,
  PRIMARY KEY (task_id, agent_id)
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
  uri TEXT NOT NULL,
  evidence_type TEXT NOT NULL DEFAULT 'artifact',
  added_by TEXT REFERENCES agents(id),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  sender_id TEXT REFERENCES agents(id),
  recipient TEXT NOT NULL,
  task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
  body TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY,
  task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
  reviewer_id TEXT NOT NULL REFERENCES agents(id),
  artifact_uri TEXT NOT NULL,
  scope TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('accepted', 'conditionally_accepted', 'changes_requested', 'rejected')),
  accepted_items TEXT NOT NULL DEFAULT '',
  required_changes TEXT NOT NULL DEFAULT '',
  remaining_risks TEXT NOT NULL DEFAULT '',
  blocked_claims TEXT NOT NULL DEFAULT '',
  follow_up_tasks TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  owner_id TEXT NOT NULL REFERENCES agents(id),
  status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'accepted', 'superseded', 'rejected')),
  context TEXT NOT NULL,
  decision TEXT NOT NULL,
  options_considered TEXT NOT NULL DEFAULT '',
  implications TEXT NOT NULL DEFAULT '',
  evidence TEXT NOT NULL DEFAULT '',
  blocked_claims TEXT NOT NULL DEFAULT '',
  review_required TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY,
  uri TEXT NOT NULL UNIQUE,
  owner_id TEXT NOT NULL REFERENCES agents(id),
  type TEXT NOT NULL,
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
  id TEXT PRIMARY KEY,
  raised_by TEXT NOT NULL REFERENCES agents(id),
  owner TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_review', 'resolved', 'closed_no_action')),
  related_tasks TEXT NOT NULL DEFAULT '',
  needed_by TEXT,
  issue TEXT NOT NULL,
  requested_decision TEXT NOT NULL,
  resolution TEXT NOT NULL DEFAULT '',
  follow_up_tasks TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT,
  action TEXT NOT NULL,
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status_priority ON tasks(status, priority, updated_at);
CREATE INDEX IF NOT EXISTS idx_task_assignees_agent ON task_assignees(agent_id, task_id);
CREATE INDEX IF NOT EXISTS idx_evidence_task ON task_evidence(task_id);
CREATE INDEX IF NOT EXISTS idx_reviews_task ON reviews(task_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient, created_at);
CREATE INDEX IF NOT EXISTS idx_escalations_status ON escalations(status, created_at);

CREATE TRIGGER IF NOT EXISTS task_insert_done_requires_evidence
BEFORE INSERT ON tasks
WHEN NEW.status = 'done'
BEGIN
  SELECT RAISE(ABORT, 'a task cannot be created as done');
END;

CREATE TRIGGER IF NOT EXISTS task_update_done_requires_evidence
BEFORE UPDATE OF status ON tasks
WHEN NEW.status = 'done'
  AND NOT EXISTS (SELECT 1 FROM task_evidence WHERE task_id = NEW.id)
BEGIN
  SELECT RAISE(ABORT, 'done requires at least one evidence record');
END;
