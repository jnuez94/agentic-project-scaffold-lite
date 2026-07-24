#!/bin/sh
set -eu

test_dir=$(mktemp -d)
restore_pid=

cleanup() {
  if [ -n "$restore_pid" ]; then
    kill "$restore_pid" 2>/dev/null || true
  fi
  rm -rf "$test_dir"
}
trap cleanup EXIT HUP INT TERM

fail_test() {
  printf '%s\n' "$1" >&2
  exit 1
}

expect_error() {
  expected_exit=$1
  expected_code=$2
  error_file=$3
  shift 3
  set +e
  "$@" > "$error_file.stdout" 2> "$error_file"
  actual_exit=$?
  set -e
  [ "$actual_exit" -eq "$expected_exit" ] ||
    fail_test "Expected exit $expected_exit, got $actual_exit: $*"
  python3 -c '
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
assert value["error"]["code"] == sys.argv[2], value
' "$error_file" "$expected_code"
}

mkdir "$test_dir/project"
./scripts/install.sh --target "$test_dir/project" --adapter sqlite >/dev/null
tool=$test_dir/project/.agents/agentic-project-scaffold-lite/bin/coordination
package=$test_dir/project/.agents/agentic-project-scaffold-lite/lib/coordination
installed_lib=$test_dir/project/.agents/agentic-project-scaffold-lite/lib
target=$test_dir/project/.coordination/coordination.sqlite3
source=$test_dir/source.sqlite3

"$tool" --db "$target" agent add \
  --id operator --name Operator --role operations >/dev/null
"$tool" --db "$target" backup --output "$source" >/dev/null
"$tool" --db "$target" agent add \
  --id target-only --name Target --role test >/dev/null

# An audit insertion failure happens before publication and leaves the target
# byte-for-byte state and its audit history unchanged.
python3 - "$source" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
connection.execute(
    "UPDATE sqlite_sequence SET seq = ? WHERE name = 'audit_log'",
    (9223372036854775807,),
)
connection.commit()
PY
before_state=$(python3 - "$target" <<'PY'
import hashlib
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
rows = connection.execute(
    "SELECT id, name, role FROM agents ORDER BY id"
).fetchall()
audits = connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
print(hashlib.sha256(repr((rows, audits)).encode()).hexdigest())
PY
)
set +e
"$tool" --db "$target" restore --input "$source" \
  --actor operator --force > "$test_dir/audit-failure.stdout" \
  2> "$test_dir/audit-failure.json"
audit_failure_exit=$?
set -e
[ "$audit_failure_exit" -eq 5 ] ||
  fail_test "Restore audit failure returned $audit_failure_exit"
python3 - "$test_dir/audit-failure.json" "$target" "$source" <<'PY'
import json
from pathlib import Path
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
error = value["error"]
assert error["code"] == "restore_audit_failed", value
details = error["details"]
assert Path(details["database"]) == Path(sys.argv[2]).resolve(), details
assert Path(details["restored_from"]) == Path(sys.argv[3]).resolve(), details
assert details["target_unchanged"] is True, details
assert details["reason"], details
PY
after_state=$(python3 - "$target" <<'PY'
import hashlib
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
rows = connection.execute(
    "SELECT id, name, role FROM agents ORDER BY id"
).fetchall()
audits = connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
print(hashlib.sha256(repr((rows, audits)).encode()).hexdigest())
PY
)
[ "$before_state" = "$after_state" ] ||
  fail_test "Restore audit failure changed the target"

# Recreate a normal verified source for publication and locking tests.
"$tool" --db "$target" backup --output "$test_dir/normal-source.sqlite3" >/dev/null
normal_source=$test_dir/normal-source.sqlite3

# Existing restore targets must be regular files; a FIFO is rejected without
# replacing or consuming it.
mkfifo "$test_dir/special-target"
expect_error 2 invalid_arguments "$test_dir/special-target.json" \
  "$tool" --db "$test_dir/special-target" restore \
  --input "$normal_source" --actor operator --force
test -p "$test_dir/special-target"

# The managed recovery directory itself must be a real directory, not an
# alias chosen by another process or a pre-existing project.
mkdir "$test_dir/alias-parent" "$test_dir/external-backups"
cp "$target" "$test_dir/alias-parent/target.sqlite3"
ln -s "$test_dir/external-backups" "$test_dir/alias-parent/backups"
expect_error 5 environment_error "$test_dir/safety-directory.json" \
  "$tool" --db "$test_dir/alias-parent/target.sqlite3" restore \
  --input "$normal_source" --actor operator --force

# A nested configured database still publishes safety copies to the one
# project-level .coordination/backups directory.
mkdir -p "$test_dir/nested/.coordination/state" \
  "$test_dir/nested/.coordination/backups"
nested_target=$test_dir/nested/.coordination/state/team.db
nested_source=$test_dir/nested-source.sqlite3
"$tool" --db "$nested_target" init >/dev/null
"$tool" --db "$nested_target" agent add \
  --id operator --name Operator --role operations >/dev/null
"$tool" --db "$nested_target" backup --output "$nested_source" >/dev/null
"$tool" --db "$nested_target" agent add \
  --id nested-only --name Nested --role test >/dev/null
"$tool" --db "$nested_target" restore --input "$nested_source" \
  --actor operator --force > "$test_dir/nested-restore.json"
python3 - "$test_dir/nested-restore.json" \
  "$test_dir/nested/.coordination/backups" <<'PY'
import json
from pathlib import Path
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))["data"]
assert Path(data["safety_backup"]).parent == Path(sys.argv[2]).resolve(), data
assert data["safety_backup_verified"] is True, data
PY

# A deterministic post-publication failure restores the verified recovery copy
# and does not leak the replacement's restore audit into the rolled-back target.
PYTHONPATH=$installed_lib python3 tests/restore_failure_injection.py \
  --target "$target" \
  --source "$normal_source" \
  --actor operator \
  --expected-package "$package" > "$test_dir/rollback.json"
python3 -c '
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))["data"]
assert data == {
    "error_code": "restore_verification_failed",
    "rollback_performed": True,
    "rollback_succeeded": True,
    "rollback_verified": True,
}
' "$test_dir/rollback.json"

# Atomic replacement failure is reported as pre-publication and preserves the
# old target. A failed rollback is never described as successful or verified.
publication_target=$test_dir/publication-target.sqlite3
postrename_target=$test_dir/postrename-target.sqlite3
rollback_failure_target=$test_dir/rollback-failure-target.sqlite3
"$tool" --db "$target" backup --output "$publication_target" >/dev/null
"$tool" --db "$target" backup --output "$postrename_target" >/dev/null
"$tool" --db "$target" backup --output "$rollback_failure_target" >/dev/null
for failure_mode in publication postrename rollback; do
  case "$failure_mode" in
    publication) failure_target=$publication_target ;;
    postrename) failure_target=$postrename_target ;;
    rollback) failure_target=$rollback_failure_target ;;
  esac
  PYTHONPATH=$installed_lib python3 tests/restore_failure_matrix.py \
    --mode "$failure_mode" \
    --target "$failure_target" \
    --source "$normal_source" \
    --actor operator \
    --expected-package "$package" \
    > "$test_dir/$failure_mode-failure.json"
done
python3 - "$test_dir/publication-failure.json" \
  "$test_dir/postrename-failure.json" \
  "$test_dir/rollback-failure.json" <<'PY'
import json
import sys

publication = json.load(open(sys.argv[1], encoding="utf-8"))["data"]
postrename = json.load(open(sys.argv[2], encoding="utf-8"))["data"]
rollback = json.load(open(sys.argv[3], encoding="utf-8"))["data"]
assert publication["error_code"] == "restore_publication_failed", publication
assert publication["target_unchanged"] is True, publication
assert postrename == {
    "error_code": "restore_verification_failed",
    "target_unchanged": None,
    "rollback_performed": True,
    "rollback_succeeded": True,
    "rollback_verified": True,
}, postrename
assert rollback == {
    "error_code": "restore_verification_failed",
    "target_unchanged": None,
    "rollback_performed": True,
    "rollback_succeeded": False,
    "rollback_verified": False,
}, rollback
PY

# SIGTERM during source preparation is a pre-publication interruption with a
# structured error, an unchanged target, and no leaked staging file.
interrupt_target=$test_dir/interrupted-target.sqlite3
"$tool" --db "$target" backup --output "$interrupt_target" >/dev/null
interrupt_before=$(python3 - "$interrupt_target" <<'PY'
import hashlib
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
state = (
    connection.execute("SELECT id, name, role FROM agents ORDER BY id").fetchall(),
    connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
)
print(hashlib.sha256(repr(state).encode()).hexdigest())
PY
)
interrupt_marker=$test_dir/restore-interrupt-started
PYTHONPATH=$installed_lib python3 tests/restore_interrupt_probe.py \
  --tool-package "$package" \
  --target "$interrupt_target" \
  --source "$normal_source" \
  --actor operator \
  --marker "$interrupt_marker" \
  > "$test_dir/restore-interrupted.stdout" \
  2> "$test_dir/restore-interrupted.json" &
restore_pid=$!
wait_count=0
while [ ! -f "$interrupt_marker" ]; do
  kill -0 "$restore_pid" 2>/dev/null ||
    fail_test "Interrupted restore probe exited before preparation"
  wait_count=$((wait_count + 1))
  [ "$wait_count" -lt 500 ] ||
    fail_test "Interrupted restore probe did not enter preparation"
  sleep 0.01
done
kill -TERM "$restore_pid"
set +e
wait "$restore_pid"
interrupt_exit=$?
set -e
restore_pid=
[ "$interrupt_exit" -eq 5 ] ||
  fail_test "Interrupted restore returned $interrupt_exit"
python3 -c '
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
assert value["error"]["code"] == "operation_interrupted", value
' "$test_dir/restore-interrupted.json"
interrupt_after=$(python3 - "$interrupt_target" <<'PY'
import hashlib
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
state = (
    connection.execute("SELECT id, name, role FROM agents ORDER BY id").fetchall(),
    connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
)
print(hashlib.sha256(repr(state).encode()).hexdigest())
PY
)
[ "$interrupt_before" = "$interrupt_after" ] ||
  fail_test "Interrupted restore changed its target"
test -z "$(find "$test_dir" -name '.interrupted-target.sqlite3.restore.*')"

# Restore intent owns the target operational lock before source preparation.
# A mutation started after that intent is visible times out instead of slipping
# into state that the restore would silently replace.
marker=$test_dir/restore-preparing
PYTHONPATH=$installed_lib COORDINATION_BUSY_TIMEOUT_MS=5000 \
  python3 tests/restore_lock_probe.py \
  --target "$target" \
  --source "$normal_source" \
  --actor operator \
  --marker "$marker" \
  --expected-package "$package" \
  > "$test_dir/restore-lock.json" 2> "$test_dir/restore-lock.error" &
restore_pid=$!
wait_count=0
while [ ! -f "$marker" ]; do
  kill -0 "$restore_pid" 2>/dev/null ||
    fail_test "Restore lock probe exited before preparation"
  wait_count=$((wait_count + 1))
  [ "$wait_count" -lt 500 ] ||
    fail_test "Restore lock probe did not enter preparation"
  sleep 0.01
done
expect_error 6 database_busy "$test_dir/restore-busy.json" \
  env COORDINATION_BUSY_TIMEOUT_MS=50 "$tool" --db "$target" \
  agent add --id during-restore --name During --role test
wait "$restore_pid"
restore_pid=
python3 - "$target" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
assert connection.execute(
    "SELECT COUNT(*) FROM agents WHERE id = 'during-restore'"
).fetchone()[0] == 0
assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
assert connection.execute(
    "SELECT COUNT(*) FROM audit_log WHERE action = 'restore'"
).fetchone()[0] == 1
PY

test -z "$(find "$test_dir" -name '*.restore.*' -o -name '*.rollback.*')"

printf 'SQLite restore qualification tests passed.\n'
