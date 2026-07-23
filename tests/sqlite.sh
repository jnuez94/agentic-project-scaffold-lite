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

"$tool" --db "$db" agent add --id product --name Product --role product
"$tool" --db "$db" agent add --id engineering --name Engineering --role engineering
"$tool" --db "$db" agent add --id security --name Security --role security

"$tool" --db "$db" task create \
  --id TASK-001 --title 'Implement local auth' --priority 1 \
  --acceptance 'Tests pass' --actor product --assignee engineering
"$tool" --db "$db" task create \
  --id TASK-002 --title 'Prepare rollout notes' --priority 2 \
  --acceptance 'Notes reviewed' --actor product --assignee product
"$tool" --db "$db" dependency add \
  --task TASK-002 --depends-on TASK-001 --type blocks --rationale 'Implementation must finish first' --actor product
"$tool" --db "$db" dependency resolve \
  --task TASK-002 --depends-on TASK-001 --type blocks --actor product

if "$tool" --db "$db" task status TASK-001 done --actor engineering >/dev/null 2>&1; then
  printf 'SQLite allowed done without evidence.\n' >&2
  exit 1
fi

"$tool" --db "$db" task claim TASK-001 --agent engineering
"$tool" --db "$db" task status TASK-001 review --actor engineering
"$tool" --db "$db" evidence add --task TASK-001 --uri 'test://auth-suite-passed' --type test --actor engineering
"$tool" --db "$db" review add \
  --id REV-001 --task TASK-001 --reviewer security --artifact 'src/auth' \
  --scope 'Authentication safety' --decision accepted \
  --blocked-claims 'Does not approve production deployment'
"$tool" --db "$db" task status TASK-001 done --actor product

"$tool" --db "$db" decision add \
  --id DEC-001 --title 'Use local authentication' --owner product --status accepted \
  --context 'Local-only project' --decision 'Use local authentication' \
  --blocked-claims 'No external identity claims'
"$tool" --db "$db" message send \
  --id MSG-001 --sender product --recipient team --task TASK-001 --body 'Task accepted'
"$tool" --db "$db" artifact add \
  --id ART-001 --uri 'src/auth' --owner engineering --type code --status review \
  --usage-boundaries 'Local use only' --task TASK-001 --reviewer security
"$tool" --db "$db" artifact status ART-001 accepted --actor security
"$tool" --db "$db" escalation add \
  --id ESC-001 --raised-by engineering --owner product --related-tasks TASK-002 \
  --issue 'Rollout owner unclear' --requested-decision 'Assign rollout owner'
"$tool" --db "$db" escalation resolve ESC-001 \
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

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["status"] == "done"; assert value["evidence_count"] == 1; assert len(value["reviews"]) == 1' "$test_dir/task.json"
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["healthy"] is True' "$test_dir/health.json"
python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"; assert db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] >= 18; assert db.execute("SELECT status FROM artifacts WHERE id=\"ART-001\"").fetchone()[0] == "accepted"; assert db.execute("SELECT status FROM escalations WHERE id=\"ESC-001\"").fetchone()[0] == "resolved"' "$db"
python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); assert db.execute("PRAGMA user_version").fetchone()[0] == 1' "$db"
python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"' "$test_dir/coordination-backup.sqlite3"
grep -Fq 'TASK-001: Implement local auth' "$test_dir/export.md"

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
