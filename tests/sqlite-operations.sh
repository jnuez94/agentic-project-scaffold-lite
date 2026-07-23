#!/bin/sh
set -eu

test_dir=$(mktemp -d)

cleanup() {
  rm -rf "$test_dir"
}
trap cleanup EXIT HUP INT TERM

./scripts/install.sh --target "$test_dir" --adapter sqlite >/dev/null

tool=$test_dir/.agents/agentic-project-scaffold-lite/bin/coordination
db=$test_dir/.coordination/coordination.sqlite3
backup=$test_dir/.coordination/backups/recovery.sqlite3

"$tool" --db "$db" agent add --id operator --name Operator --role operations >/dev/null
"$tool" --db "$db" agent add --id worker --name Worker --role engineering >/dev/null
"$tool" --db "$db" session start \
  --id operator-session --agent operator --harness cli >/dev/null
"$tool" --db "$db" session start \
  --id worker-session --agent worker --harness codex >/dev/null
"$tool" --db "$db" --session operator-session task create \
  --id RECOVER --title 'Recover interrupted work' --actor operator >/dev/null
"$tool" --db "$db" --session worker-session task claim RECOVER \
  --agent worker --if-revision 1 >/dev/null

python3 -c 'import sqlite3,sys; source=sqlite3.connect(sys.argv[1]); destination=sqlite3.connect(sys.argv[2]); source.backup(destination); source.close(); destination.execute("UPDATE agent_sessions SET status=\"ended\" WHERE id=\"worker-session\""); destination.commit(); destination.close()' \
  "$db" "$test_dir/invalid-claim.sqlite3"
if "$tool" --db "$test_dir/invalid-claim.sqlite3" doctor \
  2> "$test_dir/invariant.json"; then
  printf 'Doctor unexpectedly accepted an invalid active claim.\n' >&2
  exit 1
else
  test "$?" -eq 5
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "coordination_invariant_violation"' "$test_dir/invariant.json"

if "$tool" --db "$db" session recover worker-session \
  --actor operator --reason 'Worker stopped unexpectedly' \
  2> "$test_dir/not-stale.json"; then
  printf 'Fresh session unexpectedly recovered.\n' >&2
  exit 1
else
  test "$?" -eq 4
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "session_not_stale"' "$test_dir/not-stale.json"

python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.execute("UPDATE agent_sessions SET last_seen_at=\"2000-01-01T00:00:00+00:00\" WHERE id=\"worker-session\""); db.commit(); db.close()' "$db"
"$tool" --db "$db" session recover worker-session \
  --actor operator --reason 'Worker stopped unexpectedly' \
  > "$test_dir/recovered.json"
python3 -c 'import json,sqlite3,sys; value=json.load(open(sys.argv[1])); tasks=value["data"]["recovered_tasks"]; assert tasks == [{"id":"RECOVER","revision":3,"status":"blocked"}]; db=sqlite3.connect(sys.argv[2]); assert db.execute("SELECT status FROM agent_sessions WHERE id=\"worker-session\"").fetchone()[0] == "ended"; assert db.execute("SELECT status,revision,notes FROM tasks WHERE id=\"RECOVER\"").fetchone() == ("blocked",3,"Worker stopped unexpectedly"); assert db.execute("SELECT COUNT(*) FROM task_claims").fetchone()[0] == 0' "$test_dir/recovered.json" "$db"

"$tool" --db "$db" health --stale-session-minutes 0 > "$test_dir/health.json"
python3 -c 'import json,sys; data=json.load(open(sys.argv[1]))["data"]; assert any(row["id"] == "operator-session" for row in data["stale_sessions"]); assert data["unclaimed_in_progress_tasks"] == []; assert data["invalid_active_claims"] == []' "$test_dir/health.json"

"$tool" --db "$db" session end operator-session >/dev/null
"$tool" --db "$db" backup --output "$backup" > "$test_dir/backup.json"
python3 -c 'import json,os,stat,sys; data=json.load(open(sys.argv[1]))["data"]; assert data["verified"] is True; assert data["schema_version"] == 1; assert data["bytes"] > 0; assert stat.S_IMODE(os.stat(data["backup"]).st_mode) == 0o600' "$test_dir/backup.json"

"$tool" --db "$db" agent add --id post-backup --name Later --role test >/dev/null
"$tool" --db "$db" session start \
  --id post-backup-session --agent post-backup --harness test >/dev/null
if "$tool" --db "$db" restore --input "$backup" --actor operator \
  2> "$test_dir/confirmation.json"; then
  printf 'Restore without confirmation unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 2
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "confirmation_required"' "$test_dir/confirmation.json"

if "$tool" --db "$db" restore --input "$backup" --actor operator --force \
  2> "$test_dir/active-restore.json"; then
  printf 'Restore with an active target session unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 4
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "restore_active_sessions"; assert value["error"]["details"]["sessions"] == ["post-backup-session"]' "$test_dir/active-restore.json"
"$tool" --db "$db" session end post-backup-session >/dev/null

"$tool" --db "$db" restore --input "$backup" --actor operator --force \
  > "$test_dir/restore.json"
python3 -c 'import json,os,sqlite3,sys; data=json.load(open(sys.argv[1]))["data"]; assert data["verified"] is True; assert os.path.isfile(data["safety_backup"]); db=sqlite3.connect(sys.argv[2]); assert db.execute("SELECT COUNT(*) FROM agents WHERE id=\"post-backup\"").fetchone()[0] == 0; assert db.execute("SELECT COUNT(*) FROM audit_log WHERE action=\"restore\"").fetchone()[0] == 1; safety=sqlite3.connect(data["safety_backup"]); assert safety.execute("SELECT COUNT(*) FROM agents WHERE id=\"post-backup\"").fetchone()[0] == 1' "$test_dir/restore.json" "$db"

printf 'not a database\n' > "$test_dir/corrupt.sqlite3"
if "$tool" --db "$db" restore --input "$test_dir/corrupt.sqlite3" \
  --actor operator --force 2> "$test_dir/corrupt.json"; then
  printf 'Corrupt restore input unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 5
fi
python3 -c 'import json,sqlite3,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] in ("database_error","environment_error"); db=sqlite3.connect(sys.argv[2]); assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"' "$test_dir/corrupt.json" "$db"

printf 'not a database\n' > "$test_dir/corrupt-target.sqlite3"
"$tool" --db "$test_dir/corrupt-target.sqlite3" restore --input "$backup" \
  --actor operator --force > "$test_dir/corrupt-target.json"
python3 -c 'import json,os,sqlite3,sys; data=json.load(open(sys.argv[1]))["data"]; assert data["verified"] is True; assert data["safety_backup_verified"] is False; assert os.path.isfile(data["safety_backup"]); assert open(data["safety_backup"]).read() == "not a database\n"; db=sqlite3.connect(sys.argv[2]); assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"; assert db.execute("SELECT COUNT(*) FROM agents WHERE id=\"operator\"").fetchone()[0] == 1' "$test_dir/corrupt-target.json" "$test_dir/corrupt-target.sqlite3"

test -z "$(find "$test_dir/.coordination/backups" -name '*.tmp' -print)"
test -z "$(find "$test_dir" -name '*.restore.*' -print)"
"$tool" --db "$db" doctor > "$test_dir/doctor.json"
python3 -c 'import json,sys; data=json.load(open(sys.argv[1]))["data"]; assert data["coordination_invariants"] == "ok"; assert data["integrity_check"] == "ok"; assert data["foreign_key_check"] == "ok"' "$test_dir/doctor.json"

printf 'SQLite operational reliability tests passed.\n'
