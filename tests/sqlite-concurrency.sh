#!/bin/sh
set -eu

test_dir=$(mktemp -d)
lock_pid=

cleanup() {
  if [ -n "$lock_pid" ]; then
    kill "$lock_pid" 2>/dev/null || true
  fi
  rm -rf "$test_dir"
}
trap cleanup EXIT HUP INT TERM

./scripts/install.sh --target "$test_dir" --adapter sqlite >/dev/null

tool=$test_dir/.agents/agentic-project-scaffold-lite/bin/coordination
db=$test_dir/.coordination/coordination.sqlite3

"$tool" --db "$db" agent add --id alpha --name Alpha --role engineering >/dev/null
"$tool" --db "$db" agent add --id beta --name Beta --role review >/dev/null
"$tool" --db "$db" session start --id alpha-session --agent alpha --harness codex >/dev/null
"$tool" --db "$db" session start --id beta-session --agent beta --harness claude >/dev/null
"$tool" --db "$db" --session alpha-session task create \
  --id RACE --title 'Concurrent claim' --actor alpha >/dev/null

run_claim() {
  agent=$1
  session=$2
  output=$3
  error=$4
  code_file=$5
  set +e
  "$tool" --db "$db" --session "$session" task claim RACE \
    --agent "$agent" --if-revision 1 > "$output" 2> "$error"
  code=$?
  set -e
  printf '%s\n' "$code" > "$code_file"
}

run_claim alpha alpha-session "$test_dir/alpha.json" "$test_dir/alpha-error.json" "$test_dir/alpha.code" &
alpha_pid=$!
run_claim beta beta-session "$test_dir/beta.json" "$test_dir/beta-error.json" "$test_dir/beta.code" &
beta_pid=$!
wait "$alpha_pid"
wait "$beta_pid"

python3 -c 'import sys; codes=sorted(int(open(path).read()) for path in sys.argv[1:]); assert codes == [0, 4], codes' \
  "$test_dir/alpha.code" "$test_dir/beta.code"
python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); task=db.execute("SELECT status, revision FROM tasks WHERE id=\"RACE\"").fetchone(); claims=db.execute("SELECT agent_id, session_id FROM task_claims WHERE task_id=\"RACE\"").fetchall(); assert task == ("in_progress", 2); assert len(claims) == 1; assert claims[0] in (("alpha", "alpha-session"), ("beta", "beta-session"))' "$db"

winner=$(python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); print(db.execute("SELECT agent_id FROM task_claims WHERE task_id=\"RACE\"").fetchone()[0])' "$db")
if [ "$winner" = alpha ]; then
  winner_session=alpha-session
  loser=beta
  loser_session=beta-session
else
  winner_session=beta-session
  loser=alpha
  loser_session=alpha-session
fi

"$tool" --db "$db" --session "$winner_session" task claim RACE \
  --agent "$winner" --if-revision 1 > "$test_dir/replay.json"
python3 -c 'import json,sys; data=json.load(open(sys.argv[1]))["data"]; assert data["revision"] == 2; assert data["claimed"] is False; assert data["idempotent_replay"] is True' "$test_dir/replay.json"

if "$tool" --db "$db" session end "$winner_session" 2> "$test_dir/active-claim.json"; then
  printf 'Session with an active claim unexpectedly ended.\n' >&2
  exit 1
else
  test "$?" -eq 4
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "session_has_active_claims"; assert value["error"]["details"]["tasks"] == ["RACE"]' "$test_dir/active-claim.json"

if "$tool" --db "$db" agent update "$winner" --status inactive \
  2> "$test_dir/active-session.json"; then
  printf 'Agent with an active session unexpectedly deactivated.\n' >&2
  exit 1
else
  test "$?" -eq 4
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "agent_has_active_sessions"' "$test_dir/active-session.json"

if "$tool" --db "$db" --session "$loser_session" task status RACE review \
  --actor "$loser" --if-revision 2 2> "$test_dir/not-owner.json"; then
  printf 'Non-owner unexpectedly changed a claimed task.\n' >&2
  exit 1
else
  test "$?" -eq 4
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "task_claim_owner_mismatch"' "$test_dir/not-owner.json"

if "$tool" --db "$db" --session "$winner_session" task status RACE review \
  --actor "$winner" --if-revision 1 2> "$test_dir/stale.json"; then
  printf 'Stale task update unexpectedly succeeded.\n' >&2
  exit 1
else
  test "$?" -eq 4
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); details=value["error"]["details"]; assert value["error"]["code"] == "stale_task_revision"; assert details["expected_revision"] == 1; assert details["actual_revision"] == 2' "$test_dir/stale.json"

"$tool" --db "$db" --session "$winner_session" task status RACE review \
  --actor "$winner" --if-revision 2 > "$test_dir/review.json"
python3 -c 'import json,sqlite3,sys; value=json.load(open(sys.argv[1])); assert value["data"]["revision"] == 3; db=sqlite3.connect(sys.argv[2]); assert db.execute("SELECT COUNT(*) FROM task_claims WHERE task_id=\"RACE\"").fetchone()[0] == 0' "$test_dir/review.json" "$db"
"$tool" --db "$db" session end "$winner_session" >/dev/null

python3 -c 'import sqlite3,sys,time; db=sqlite3.connect(sys.argv[1]); db.execute("BEGIN IMMEDIATE"); open(sys.argv[2], "w").close(); time.sleep(1); db.rollback()' \
  "$db" "$test_dir/locked" &
lock_pid=$!
while [ ! -f "$test_dir/locked" ]; do
  sleep 0.01
done

if COORDINATION_BUSY_TIMEOUT_MS=50 "$tool" --db "$db" agent add \
  --id locked --name Locked --role test 2> "$test_dir/busy.json"; then
  printf 'Write unexpectedly succeeded while the database was locked.\n' >&2
  exit 1
else
  test "$?" -eq 6
fi
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["error"]["code"] == "database_busy"' "$test_dir/busy.json"
wait "$lock_pid"
lock_pid=
python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); assert db.execute("SELECT COUNT(*) FROM agents WHERE id=\"locked\"").fetchone()[0] == 0' "$db"

printf 'SQLite concurrency tests passed.\n'
