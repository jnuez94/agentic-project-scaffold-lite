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
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); data=value["data"]; assert value["ok"] is True; assert data["healthy"] is True; assert data["schema_version"] == 1; assert data["metadata_schema_version"] == 1; assert data["integrity_check"] == "ok"; assert data["foreign_key_check"] == "ok"; assert data["coordination_invariants"] == "ok"; assert data["journal_mode"] == "wal"; assert data["synchronous"] == "full"; assert data["foreign_keys"] is True; assert data["busy_timeout_ms"] == 5000' "$test_dir/doctor.json"
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["ok"] is True; assert value["data"]["status"] == "ready"; assert value["data"]["schema_version"] == 1' "$test_dir/init.json"

if "$tool" --db "$db" bogus 2> "$test_dir/usage.json"; then
  printf 'Invalid arguments unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 2
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["ok"] is False; assert value["error"]["code"] == "invalid_arguments"' "$test_dir/usage.json"

if COORDINATION_BUSY_TIMEOUT_MS=invalid "$tool" --db "$db" doctor \
  2> "$test_dir/configuration.json"; then
  printf 'Invalid busy timeout unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 5
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "configuration_error"' "$test_dir/configuration.json"

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
if "$tool" --db "$db" task claim TASK-STATE --agent actor \
  --if-revision 1 2> "$test_dir/session-required.json"; then
  printf 'Sessionless claim unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 2
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "session_required"' "$test_dir/session-required.json"

if "$tool" --db "$db" task status TASK-STATE review \
  --actor actor --if-revision 1 2> "$test_dir/transition.json"; then
  printf 'Invalid task transition unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 4
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "invalid_task_transition"; assert value["error"]["details"]["from"] == "todo"; assert value["error"]["details"]["to"] == "review"' "$test_dir/transition.json"

# Freeze the exact row contracts for every public list command. Create
# reverse-lexical IDs, normalize their ordering timestamps, then assert
# envelopes, field sets, types, nullability, filters, and pagination.
"$tool" --db "$db" agent add \
  --id list-b --name 'List B' --role test >/dev/null
"$tool" --db "$db" session start \
  --id S-B --agent list-b --harness claude --model m \
  > "$test_dir/session-start-b.json"
"$tool" --db "$db" session start \
  --id S-A --agent actor --harness codex \
  > "$test_dir/session-start-a.json"
"$tool" --db "$db" session end S-A > "$test_dir/session-end-a.json"

"$tool" --db "$db" task create \
  --id LIST-T --title 'List contract task' --actor actor >/dev/null
"$tool" --db "$db" evidence add \
  --task LIST-T --uri urn:evidence:first --type test --actor actor \
  > "$test_dir/evidence-add-1.json"
"$tool" --db "$db" evidence add \
  --task LIST-T --uri urn:evidence:second --actor actor \
  > "$test_dir/evidence-add-2.json"

"$tool" --db "$db" review add \
  --id R-B --task LIST-T --reviewer actor --artifact urn:review:b \
  --scope full --decision accepted \
  > "$test_dir/review-add-b.json"
"$tool" --db "$db" review add \
  --id R-A --reviewer actor --artifact urn:review:a \
  --scope partial --decision changes_requested \
  > "$test_dir/review-add-a.json"

"$tool" --db "$db" decision add \
  --id D-B --title 'Decision B' --owner actor \
  --context context-b --decision decision-b \
  > "$test_dir/decision-add-b.json"
"$tool" --db "$db" decision add \
  --id D-A --title 'Decision A' --owner actor \
  --context context-a --decision decision-a \
  > "$test_dir/decision-add-a.json"

"$tool" --db "$db" message send \
  --id M-C --sender actor --recipient alice --body message-c \
  > "$test_dir/message-send-c.json"
"$tool" --db "$db" message send \
  --id M-B --sender actor --recipient team --task LIST-T --body message-b \
  > "$test_dir/message-send-b.json"
"$tool" --db "$db" message send \
  --id M-A --sender actor --recipient bob --body message-a \
  > "$test_dir/message-send-a.json"

"$tool" --db "$db" escalation add \
  --id E-B --raised-by actor --owner owner-b \
  --issue issue-b --requested-decision request-b \
  > "$test_dir/escalation-add-b.json"
"$tool" --db "$db" escalation add \
  --id E-A --raised-by actor --owner owner-a --needed-by 2026-08-01 \
  --issue issue-a --requested-decision request-a \
  > "$test_dir/escalation-add-a.json"
"$tool" --db "$db" escalation resolve E-A \
  --resolution resolved-a --follow-up-tasks LIST-T --actor actor \
  > "$test_dir/escalation-resolve-a.json"

python3 - "$db" <<'PY'
import sqlite3
import sys

stamp = "2026-01-01T00:00:00+00:00"
with sqlite3.connect(sys.argv[1]) as connection:
    connection.execute(
        "UPDATE agent_sessions SET started_at = ? WHERE id IN ('S-A', 'S-B')",
        (stamp,),
    )
    for table in ("task_evidence", "reviews", "decisions", "messages", "escalations"):
        connection.execute(f"UPDATE {table} SET created_at = ?", (stamp,))
PY

"$tool" --db "$db" session list > "$test_dir/session-list.json"
"$tool" --db "$db" session list --limit 1 --offset 1 \
  > "$test_dir/session-page.json"
"$tool" --db "$db" session list --offset 99 \
  > "$test_dir/session-empty.json"
"$tool" --db "$db" session list --agent actor \
  > "$test_dir/session-agent.json"
"$tool" --db "$db" session list --status ended \
  > "$test_dir/session-status.json"
"$tool" --db "$db" session list --harness codex \
  > "$test_dir/session-harness.json"

"$tool" --db "$db" evidence list --task LIST-T \
  > "$test_dir/evidence-list.json"
"$tool" --db "$db" evidence list --task LIST-T --limit 1 --offset 1 \
  > "$test_dir/evidence-page.json"
"$tool" --db "$db" evidence list --task LIST-T --offset 99 \
  > "$test_dir/evidence-empty.json"

"$tool" --db "$db" review list > "$test_dir/review-list.json"
"$tool" --db "$db" review list --task LIST-T \
  > "$test_dir/review-task.json"
"$tool" --db "$db" review list --limit 1 --offset 1 \
  > "$test_dir/review-page.json"
"$tool" --db "$db" review list --offset 99 \
  > "$test_dir/review-empty.json"

"$tool" --db "$db" decision list > "$test_dir/decision-list.json"
"$tool" --db "$db" decision list --limit 1 --offset 1 \
  > "$test_dir/decision-page.json"
"$tool" --db "$db" decision list --offset 99 \
  > "$test_dir/decision-empty.json"

"$tool" --db "$db" message list > "$test_dir/message-list.json"
"$tool" --db "$db" message list --recipient alice \
  > "$test_dir/message-recipient.json"
"$tool" --db "$db" message list --limit 1 --offset 1 \
  > "$test_dir/message-page.json"
"$tool" --db "$db" message list --offset 99 \
  > "$test_dir/message-empty.json"

"$tool" --db "$db" escalation list > "$test_dir/escalation-list.json"
"$tool" --db "$db" escalation list --status resolved \
  > "$test_dir/escalation-resolved.json"
"$tool" --db "$db" escalation list --status open \
  > "$test_dir/escalation-open.json"
"$tool" --db "$db" escalation list --limit 1 --offset 1 \
  > "$test_dir/escalation-page.json"
"$tool" --db "$db" escalation list --offset 99 \
  > "$test_dir/escalation-empty.json"

python3 - "$test_dir" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])


def result(name):
    value = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
    assert set(value) == {"ok", "data"}, (name, value)
    assert value["ok"] is True, (name, value)
    return value["data"]


def ids(name):
    return [row["id"] for row in result(name)]


def exact_keys(row, expected, name):
    assert set(row) == expected, (name, row)


def strings(row, names, label):
    for name in names:
        assert type(row[name]) is str, (label, name, row[name])


assert result("session-start-a") == {
    "id": "S-A",
    "agent_id": "actor",
    "harness": "codex",
    "model": "",
    "status": "active",
}
assert result("session-start-b") == {
    "id": "S-B",
    "agent_id": "list-b",
    "harness": "claude",
    "model": "m",
    "status": "active",
}
assert result("session-end-a") == {"id": "S-A", "status": "ended"}

for name in ("evidence-add-1", "evidence-add-2"):
    mutation = result(name)
    assert set(mutation) == {"id", "task_id", "status"}, mutation
    assert type(mutation["id"]) is int, mutation
    assert mutation["task_id"] == "LIST-T"
    assert mutation["status"] == "created"
assert result("review-add-a") == {
    "id": "R-A",
    "decision": "changes_requested",
    "status": "created",
}
assert result("review-add-b") == {
    "id": "R-B",
    "decision": "accepted",
    "status": "created",
}
assert result("decision-add-a") == {"id": "D-A", "status": "proposed"}
assert result("decision-add-b") == {"id": "D-B", "status": "proposed"}
for message_id in ("M-A", "M-B", "M-C"):
    assert result(f"message-send-{message_id[-1].lower()}") == {
        "id": message_id,
        "status": "sent",
    }
assert result("escalation-add-a") == {"id": "E-A", "status": "open"}
assert result("escalation-add-b") == {"id": "E-B", "status": "open"}
assert result("escalation-resolve-a") == {"id": "E-A", "status": "resolved"}

session_keys = {
    "id", "agent_id", "harness", "model", "status",
    "started_at", "last_seen_at", "ended_at",
}
sessions = result("session-list")
assert ids("session-list") == ["S-A", "S-B"], sessions
for row in sessions:
    exact_keys(row, session_keys, "session")
    strings(
        row,
        {"id", "agent_id", "harness", "model", "status",
         "started_at", "last_seen_at"},
        "session",
    )
assert sessions[0]["ended_at"] is not None
assert type(sessions[0]["ended_at"]) is str
assert sessions[1]["ended_at"] is None
assert ids("session-page") == ["S-B"]
assert result("session-empty") == []
assert ids("session-agent") == ["S-A"]
assert ids("session-status") == ["S-A"]
assert ids("session-harness") == ["S-A"]

evidence_keys = {
    "id", "task_id", "uri", "evidence_type", "added_by", "created_at",
}
evidence = result("evidence-list")
assert len(evidence) == 2
evidence_ids = [
    result("evidence-add-1")["id"],
    result("evidence-add-2")["id"],
]
assert ids("evidence-list") == evidence_ids, evidence
assert [row["uri"] for row in evidence] == [
    "urn:evidence:first",
    "urn:evidence:second",
], evidence
assert [row["evidence_type"] for row in evidence] == ["test", "artifact"], evidence
for row in evidence:
    exact_keys(row, evidence_keys, "evidence")
    assert type(row["id"]) is int
    strings(row, evidence_keys - {"id"}, "evidence")
assert result("evidence-page") == [evidence[1]]
assert result("evidence-empty") == []

review_keys = {
    "id", "task_id", "reviewer_id", "artifact_uri", "scope", "decision",
    "accepted_items", "required_changes", "remaining_risks",
    "blocked_claims", "follow_up_tasks", "created_at",
}
reviews = result("review-list")
assert ids("review-list") == ["R-A", "R-B"], reviews
for row in reviews:
    exact_keys(row, review_keys, "review")
    strings(row, review_keys - {"task_id"}, "review")
assert reviews[0]["task_id"] is None
assert reviews[1]["task_id"] == "LIST-T"
assert ids("review-task") == ["R-B"]
assert ids("review-page") == ["R-B"]
assert result("review-empty") == []

decision_keys = {
    "id", "title", "owner_id", "status", "context", "decision",
    "options_considered", "implications", "evidence", "blocked_claims",
    "review_required", "created_at", "updated_at",
}
decisions = result("decision-list")
assert ids("decision-list") == ["D-A", "D-B"], decisions
for row in decisions:
    exact_keys(row, decision_keys, "decision")
    strings(row, decision_keys, "decision")
assert ids("decision-page") == ["D-B"]
assert result("decision-empty") == []

message_keys = {
    "id", "sender_id", "recipient", "task_id", "body", "tags", "created_at",
}
messages = result("message-list")
assert ids("message-list") == ["M-A", "M-B", "M-C"], messages
for row in messages:
    exact_keys(row, message_keys, "message")
    strings(row, message_keys - {"task_id"}, "message")
assert messages[0]["task_id"] is None
assert messages[1]["task_id"] == "LIST-T"
assert messages[2]["task_id"] is None
assert ids("message-recipient") == ["M-B", "M-C"]
assert ids("message-page") == ["M-B"]
assert result("message-empty") == []

escalation_keys = {
    "id", "raised_by", "owner", "status", "related_tasks", "needed_by",
    "issue", "requested_decision", "resolution", "follow_up_tasks",
    "created_at", "updated_at",
}
escalations = result("escalation-list")
assert ids("escalation-list") == ["E-A", "E-B"], escalations
for row in escalations:
    exact_keys(row, escalation_keys, "escalation")
    strings(row, escalation_keys - {"needed_by"}, "escalation")
assert escalations[0]["needed_by"] == "2026-08-01"
assert escalations[1]["needed_by"] is None
assert ids("escalation-resolved") == ["E-A"]
assert ids("escalation-open") == ["E-B"]
assert ids("escalation-page") == ["E-B"]
assert result("escalation-empty") == []
PY

printf 'CLI contract tests passed.\n'
