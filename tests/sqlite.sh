#!/bin/sh
set -eu

test_dir=$(mktemp -d)

cleanup() {
  rm -rf "$test_dir"
}
trap cleanup EXIT HUP INT TERM

printf 'keep-this-ignore\n' > "$test_dir/.gitignore"
./scripts/install.sh --target "$test_dir" --adapter sqlite
./scripts/verify-install.sh "$test_dir"

tool=$test_dir/.agents/agentic-project-scaffold-lite/bin/coordination
db=$test_dir/.coordination/coordination.sqlite3

grep -Fq 'keep-this-ignore' "$test_dir/.gitignore"
test "$(grep -c '# agentic-project-scaffold-lite sqlite state' "$test_dir/.gitignore")" -eq 1
grep -Fq 'Use the deterministic coordination CLI' "$test_dir/AGENTS.md"
test -f "$test_dir/.agents/agentic-project-scaffold-lite/lib/coordination/entities/tasks.py"
test -f "$test_dir/.agents/agentic-project-scaffold-lite/lib/coordination/entities/agents.py"
test -f "$test_dir/.agents/agentic-project-scaffold-lite/lib/coordination/entities/sessions.py"
test -f "$test_dir/.agents/agentic-project-scaffold-lite/lib/coordination/entities/maintenance.py"

"$tool" --db "$db" agent add --id product --name Product --role product --actor-type human
"$tool" --db "$db" agent add --id engineering --name Engineering --role engineering --actor-type ai
"$tool" --db "$db" agent add --id security --name Security --role security --actor-type ai
"$tool" --db "$db" agent add --id automation --name Automation --role operations --actor-type service

"$tool" --db "$db" session start \
  --id product-cli-001 --agent product --harness cli --model human
"$tool" --db "$db" session start \
  --id engineering-codex-001 --agent engineering --harness codex --model gpt-test
"$tool" --db "$db" session start \
  --id security-claude-001 --agent security --harness claude --model claude-test
"$tool" --db "$db" session heartbeat engineering-codex-001

"$tool" --db "$db" --session product-cli-001 task create \
  --id TASK-001 --title 'Implement local auth' --priority 1 \
  --acceptance 'Tests pass' --actor product --assignee engineering
"$tool" --db "$db" --session product-cli-001 task create \
  --id TASK-002 --title 'Prepare rollout notes' --priority 2 \
  --acceptance 'Notes reviewed' --actor product --assignee product
"$tool" --db "$db" --session product-cli-001 dependency add \
  --task TASK-002 --depends-on TASK-001 --type blocks --rationale 'Implementation must finish first' --actor product
"$tool" --db "$db" --session product-cli-001 dependency resolve \
  --task TASK-002 --depends-on TASK-001 --type blocks --actor product

if "$tool" --db "$db" --session product-cli-001 task status TASK-001 blocked \
  --actor engineering --if-revision 1 >/dev/null 2>&1; then
  printf 'SQLite accepted an actor/session mismatch.\n' >&2
  exit 1
fi

"$tool" --db "$db" --session engineering-codex-001 task claim TASK-001 \
  --agent engineering --if-revision 1
"$tool" --db "$db" --session engineering-codex-001 task status TASK-001 review \
  --actor engineering --if-revision 2
"$tool" --db "$db" --session engineering-codex-001 evidence add --task TASK-001 --uri 'test://auth-suite-passed' --type test --actor engineering
"$tool" --db "$db" --session security-claude-001 review add \
  --id REV-001 --task TASK-001 --reviewer security --artifact 'src/auth' \
  --scope 'Authentication safety' --decision accepted \
  --blocked-claims 'Does not approve production deployment'
"$tool" --db "$db" --session product-cli-001 task status TASK-001 done \
  --actor product --if-revision 3

"$tool" --db "$db" --session product-cli-001 task create \
  --id TASK-003 --title 'Exercise evidence gate' --actor product --assignee engineering
"$tool" --db "$db" --session engineering-codex-001 task claim TASK-003 \
  --agent engineering --if-revision 1
"$tool" --db "$db" --session engineering-codex-001 task status TASK-003 review \
  --actor engineering --if-revision 2
if "$tool" --db "$db" --session engineering-codex-001 task status TASK-003 done \
  --actor engineering --if-revision 3 >/dev/null 2>&1; then
  printf 'SQLite allowed done without evidence.\n' >&2
  exit 1
fi
"$tool" --db "$db" --session engineering-codex-001 evidence add \
  --task TASK-003 --uri 'test://evidence-gate-passed' --type test --actor engineering
"$tool" --db "$db" --session engineering-codex-001 task status TASK-003 done \
  --actor engineering --if-revision 3

"$tool" --db "$db" --session product-cli-001 decision add \
  --id DEC-001 --title 'Use local authentication' --owner product --status accepted \
  --context 'Local-only project' --decision 'Use local authentication' \
  --blocked-claims 'No external identity claims'
"$tool" --db "$db" --session product-cli-001 message send \
  --id MSG-001 --sender product --recipient team --task TASK-001 --body 'Task accepted'
"$tool" --db "$db" --session engineering-codex-001 artifact add \
  --id ART-001 --uri 'src/auth' --owner engineering --type code --status review \
  --usage-boundaries 'Local use only' --task TASK-001 --reviewer security
"$tool" --db "$db" --session security-claude-001 artifact status ART-001 accepted --actor security
"$tool" --db "$db" --session engineering-codex-001 escalation add \
  --id ESC-001 --raised-by engineering --owner product --related-tasks TASK-002 \
  --issue 'Rollout owner unclear' --requested-decision 'Assign rollout owner'
"$tool" --db "$db" --session product-cli-001 escalation resolve ESC-001 \
  --resolution 'Product owns rollout' --actor product

"$tool" --db "$db" task show TASK-001 > "$test_dir/task.json"
"$tool" --db "$db" health > "$test_dir/health.json"
"$tool" --db "$db" export --output "$test_dir/export.md"
"$tool" --db "$db" backup --output "$test_dir/coordination-backup.sqlite3"

if "$tool" --db "$db" export --output "$test_dir/export.md" >/dev/null 2>&1; then
  printf 'Export unexpectedly overwrote an existing report.\n' >&2
  exit 1
fi
if "$tool" --db "$db" backup --output "$test_dir/coordination-backup.sqlite3" >/dev/null 2>&1; then
  printf 'Backup unexpectedly overwrote an existing database.\n' >&2
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["ok"] is True; data=value["data"]; assert data["status"] == "done"; assert data["evidence_count"] == 1; assert len(data["reviews"]) == 1' "$test_dir/task.json"
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["ok"] is True; assert value["data"]["healthy"] is True' "$test_dir/health.json"
python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"; assert db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] >= 27; assert db.execute("SELECT COUNT(*) FROM audit_log WHERE session_id IS NOT NULL").fetchone()[0] >= 24; assert db.execute("SELECT status FROM artifacts WHERE id=\"ART-001\"").fetchone()[0] == "accepted"; assert db.execute("SELECT status FROM escalations WHERE id=\"ESC-001\"").fetchone()[0] == "resolved"' "$db"
python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); assert db.execute("PRAGMA user_version").fetchone()[0] == 1; assert db.execute("SELECT actor_type FROM agents WHERE id=\"product\"").fetchone()[0] == "human"; assert db.execute("SELECT actor_type FROM agents WHERE id=\"automation\"").fetchone()[0] == "service"; assert db.execute("SELECT harness FROM agent_sessions WHERE id=\"engineering-codex-001\"").fetchone()[0] == "codex"' "$db"
python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"' "$test_dir/coordination-backup.sqlite3"
grep -Fq 'TASK-001: Implement local auth' "$test_dir/export.md"

"$tool" --db "$db" session end engineering-codex-001
if "$tool" --db "$db" --session engineering-codex-001 message send \
  --id MSG-ENDED --sender engineering --recipient team --body 'Should fail' >/dev/null 2>&1; then
  printf 'SQLite accepted a mutation from an ended session.\n' >&2
  exit 1
fi

./scripts/install.sh --target "$test_dir" --adapter sqlite
./scripts/verify-install.sh "$test_dir"
test "$(grep -c '# agentic-project-scaffold-lite sqlite state' "$test_dir/.gitignore")" -eq 1
"$tool" --db "$db" task show TASK-001 >/dev/null
(cd "$test_dir" && "$tool" task list >/dev/null)

if ./scripts/install.sh --target "$test_dir" --adapter markdown >/dev/null 2>&1; then
  printf 'Installer silently switched an existing SQLite project to Markdown.\n' >&2
  exit 1
fi

printf 'SQLite tests passed.\n'
