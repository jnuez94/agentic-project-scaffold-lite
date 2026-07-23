#!/bin/sh
set -eu

test_dir=$(mktemp -d)
unknown_dir=$(mktemp -d)

cleanup() {
  rm -rf "$test_dir" "$unknown_dir"
}
trap cleanup EXIT HUP INT TERM

./scripts/install.sh --target "$test_dir" --adapter sqlite >/dev/null

tool=$test_dir/.agents/agentic-project-scaffold-lite/bin/coordination
db=$test_dir/.coordination/coordination.sqlite3

"$tool" version > "$test_dir/version.json"
"$tool" --db "$db" doctor > "$test_dir/doctor.json"
"$tool" --db "$db" init > "$test_dir/init.json"

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); expected=open(sys.argv[2]).read().strip(); assert value == {"ok": True, "data": {"cli_version": expected, "schema_version": 1}}' "$test_dir/version.json" VERSION
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); data=value["data"]; assert value["ok"] is True; assert data["healthy"] is True; assert data["schema_version"] == 1; assert data["metadata_schema_version"] == 1; assert data["integrity_check"] == "ok"; assert data["foreign_key_check"] == "ok"; assert data["journal_mode"] == "wal"; assert data["foreign_keys"] is True' "$test_dir/doctor.json"
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["ok"] is True; assert value["data"]["status"] == "ready"; assert value["data"]["schema_version"] == 1' "$test_dir/init.json"

if "$tool" --db "$db" bogus 2> "$test_dir/usage.json"; then
  printf 'Invalid arguments unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 2
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["ok"] is False; assert value["error"]["code"] == "invalid_arguments"' "$test_dir/usage.json"

if "$tool" --db "$db" task show MISSING 2> "$test_dir/not-found.json"; then
  printf 'Missing task unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 3
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "not_found"; assert value["error"]["details"]["resource"] == "task MISSING"' "$test_dir/not-found.json"

python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.execute("PRAGMA user_version = 2"); db.commit(); db.close()' "$unknown_dir/newer.sqlite3"
if "$tool" --db "$unknown_dir/newer.sqlite3" init 2> "$test_dir/schema.json"; then
  printf 'Newer schema unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 5
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "unsupported_schema"; assert value["error"]["details"] == {"database_schema": 2, "supported_schema": 1}' "$test_dir/schema.json"
python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); assert db.execute("PRAGMA user_version").fetchone()[0] == 2' "$unknown_dir/newer.sqlite3"

python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.execute("CREATE TABLE unrelated(id INTEGER)"); db.commit(); db.close()' "$unknown_dir/unknown.sqlite3"
if "$tool" --db "$unknown_dir/unknown.sqlite3" init 2> "$test_dir/unknown.json"; then
  printf 'Unknown nonempty schema unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 5
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "unsupported_schema"' "$test_dir/unknown.json"

python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.executescript("""PRAGMA user_version = 1; CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL); INSERT INTO metadata VALUES (\"schema_version\", \"1\");"""); db.close()' "$unknown_dir/incomplete.sqlite3"
if "$tool" --db "$unknown_dir/incomplete.sqlite3" doctor 2> "$test_dir/incomplete.json"; then
  printf 'Incomplete schema unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 5
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "incomplete_schema"; assert "agents" in value["error"]["details"]["missing_tables"]' "$test_dir/incomplete.json"

python3 -c 'import sqlite3,sys; source=sqlite3.connect(sys.argv[1]); destination=sqlite3.connect(sys.argv[2]); source.backup(destination); source.close(); destination.close()' "$db" "$unknown_dir/missing-column.sqlite3"
python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.execute("ALTER TABLE audit_log DROP COLUMN detail"); db.commit(); db.close()' "$unknown_dir/missing-column.sqlite3"
if "$tool" --db "$unknown_dir/missing-column.sqlite3" doctor 2> "$test_dir/missing-column.json"; then
  printf 'Schema with a missing column unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 5
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "incomplete_schema"; assert value["error"]["details"]["missing_columns"] == {"audit_log": ["detail"]}' "$test_dir/missing-column.json"

python3 -c 'import sqlite3,sys; source=sqlite3.connect(sys.argv[1]); destination=sqlite3.connect(sys.argv[2]); source.backup(destination); source.close(); destination.close()' "$db" "$unknown_dir/missing-objects.sqlite3"
python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.executescript("DROP INDEX idx_audit_session; DROP TRIGGER task_update_done_requires_evidence;"); db.close()' "$unknown_dir/missing-objects.sqlite3"
if "$tool" --db "$unknown_dir/missing-objects.sqlite3" doctor 2> "$test_dir/missing-objects.json"; then
  printf 'Schema with missing index and trigger unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 5
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); details=value["error"]["details"]; assert value["error"]["code"] == "incomplete_schema"; assert details["missing_indexes"] == ["idx_audit_session"]; assert details["missing_triggers"] == ["task_update_done_requires_evidence"]' "$test_dir/missing-objects.json"

python3 -c 'import sqlite3,sys; source=sqlite3.connect(sys.argv[1]); destination=sqlite3.connect(sys.argv[2]); source.backup(destination); source.close(); destination.close()' "$db" "$unknown_dir/mismatch.sqlite3"
python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.execute("UPDATE metadata SET value=\"2\" WHERE key=\"schema_version\""); db.commit(); db.close()' "$unknown_dir/mismatch.sqlite3"
if "$tool" --db "$unknown_dir/mismatch.sqlite3" doctor 2> "$test_dir/mismatch.json"; then
  printf 'Mismatched schema metadata unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 5
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "schema_mismatch"; assert value["error"]["details"]["database_schema"] == 1; assert value["error"]["details"]["metadata_schema"] == "2"' "$test_dir/mismatch.json"

python3 -c 'import sqlite3,sys; source=sqlite3.connect(sys.argv[1]); destination=sqlite3.connect(sys.argv[2]); source.backup(destination); source.close(); destination.close()' "$db" "$unknown_dir/foreign-key.sqlite3"
python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.execute("PRAGMA foreign_keys = OFF"); db.execute("INSERT INTO task_assignees(task_id, agent_id, assigned_at) VALUES (\"missing-task\", \"missing-agent\", \"now\")"); db.commit(); db.close()' "$unknown_dir/foreign-key.sqlite3"
if "$tool" --db "$unknown_dir/foreign-key.sqlite3" doctor 2> "$test_dir/foreign-key.json"; then
  printf 'Foreign-key violation unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 5
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); details=value["error"]["details"]; assert value["error"]["code"] == "foreign_key_violation"; assert details["violation_count"] == 2; assert len(details["violations"]) == 2' "$test_dir/foreign-key.json"

"$tool" --db "$db" agent add --id actor --name Actor --role engineering >/dev/null
if "$tool" --db "$db" agent add --id actor --name Duplicate --role engineering 2> "$test_dir/conflict.json"; then
  printf 'Duplicate agent unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 4
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "constraint_violation"' "$test_dir/conflict.json"

"$tool" --db "$db" task create --id TASK-STATE --title State --actor actor >/dev/null
if "$tool" --db "$db" task status TASK-STATE review --actor actor 2> "$test_dir/transition.json"; then
  printf 'Invalid task transition unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 4
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "invalid_task_transition"; assert value["error"]["details"]["from"] == "todo"; assert value["error"]["details"]["to"] == "review"' "$test_dir/transition.json"

printf 'CLI contract tests passed.\n'
