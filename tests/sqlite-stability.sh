#!/bin/sh
set -eu

test_dir=$(mktemp -d)
interrupt_pid=

cleanup() {
  if [ -n "$interrupt_pid" ]; then
    kill "$interrupt_pid" 2>/dev/null || true
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
assert value["ok"] is False, value
assert value["error"]["code"] == sys.argv[2], value
' "$error_file" "$expected_code"
}

expect_error_in_dir() {
  expected_exit=$1
  expected_code=$2
  error_file=$3
  working_directory=$4
  shift 4
  set +e
  (
    cd "$working_directory"
    "$@"
  ) > "$error_file.stdout" 2> "$error_file"
  actual_exit=$?
  set -e
  [ "$actual_exit" -eq "$expected_exit" ] ||
    fail_test "Expected exit $expected_exit, got $actual_exit in $working_directory"
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
runtime=$test_dir/project/.agents/agentic-project-scaffold-lite
db=$test_dir/project/.coordination/coordination.sqlite3

# Bare init is idempotent even though it does not install project metadata.
# The current directory's incomplete boundary is valid only for init itself.
mkdir "$test_dir/bare-init"
(
  cd "$test_dir/bare-init"
  "$tool" init > "$test_dir/bare-init-first.json"
  "$tool" init > "$test_dir/bare-init-second.json"
)
python3 - "$test_dir/bare-init-first.json" \
  "$test_dir/bare-init-second.json" <<'PY'
import json
import sys

first = json.load(open(sys.argv[1], encoding="utf-8"))["data"]
second = json.load(open(sys.argv[2], encoding="utf-8"))["data"]
assert first["status"] == "initialized", first
assert second["status"] == "ready", second
assert first["database"] == second["database"], (first, second)
PY
expect_error_in_dir 5 configuration_error \
  "$test_dir/bare-init-doctor.json" \
  "$test_dir/bare-init" "$tool" doctor

"$tool" --db "$db" agent add --id actor --name Actor --role operations >/dev/null
"$tool" --db "$db" agent add --id alpha --name Alpha --role engineering >/dev/null
"$tool" --db "$db" agent add --id beta --name Beta --role review >/dev/null

# Public parser bounds are stable, reject abbreviations, and always emit the
# documented JSON error envelope.
expect_error 2 invalid_arguments "$test_dir/abbreviation.json" \
  "$tool" --db "$db" task create --id ABBREV --title value --act actor
expect_error 2 invalid_arguments "$test_dir/blank-title.json" \
  "$tool" --db "$db" task create --id BLANK --title '   ' --actor actor
expect_error 2 invalid_arguments "$test_dir/bad-id.json" \
  "$tool" --db "$db" task create --id 'bad/id' --title value --actor actor
long_id=$(python3 -c 'print("A" * 129)')
expect_error 2 invalid_arguments "$test_dir/long-id.json" \
  "$tool" --db "$db" task create --id "$long_id" --title value --actor actor
long_text=$(python3 -c 'print("x" * 65537)')
expect_error 2 invalid_arguments "$test_dir/long-text.json" \
  "$tool" --db "$db" task create \
  --id LONG-TEXT --title "$long_text" --actor actor
long_path=$(python3 -c 'print("p" * 4097)')
expect_error 2 invalid_arguments "$test_dir/long-path.json" \
  "$tool" --db "$db" backup --output "$long_path"
expect_error 2 invalid_arguments "$test_dir/zero-limit.json" \
  "$tool" --db "$db" task list --limit 0
expect_error 2 invalid_arguments "$test_dir/large-limit.json" \
  "$tool" --db "$db" task list --limit 501
expect_error 2 invalid_arguments "$test_dir/negative-offset.json" \
  "$tool" --db "$db" task list --offset -1
expect_error 2 invalid_arguments "$test_dir/stale-bound.json" \
  "$tool" --db "$db" health --stale-days 3651
expect_error 2 invalid_arguments "$test_dir/blank-db.json" \
  "$tool" --db '   ' doctor
expect_error 2 invalid_arguments "$test_dir/blank-output.json" \
  "$tool" --db "$db" export --output '   '
expect_error 2 invalid_arguments "$test_dir/duplicate-assignee.json" \
  "$tool" --db "$db" task create --id DUPLICATE --title value --actor actor \
  --assignee alpha --assignee alpha
expect_error 5 configuration_error "$test_dir/busy-bound.json" \
  env COORDINATION_BUSY_TIMEOUT_MS=60001 "$tool" --db "$db" doctor

# Database sidecars and the advisory lock are part of the operational
# identity: aliases and stale sidecars are rejected before SQLite opens them.
ln "$db.lock" "$test_dir/database-lock-alias"
expect_error 5 database_configuration_error \
  "$test_dir/hardlink-lock.json" "$tool" --db "$db" doctor
rm "$test_dir/database-lock-alias"
rm -f "$db-wal" "$db-shm"
ln -s "$test_dir/sidecar-target" "$db-wal"
expect_error 5 database_configuration_error \
  "$test_dir/symlink-sidecar.json" "$tool" --db "$db" doctor
rm "$db-wal"
stale_db=$test_dir/stale-sidecar.sqlite3
printf 'stale\n' > "$stale_db-wal"
expect_error 5 database_configuration_error \
  "$test_dir/stale-sidecar.json" "$tool" --db "$stale_db" init
test ! -e "$stale_db"
rm "$stale_db-wal"
"$tool" --db "$stale_db" init >/dev/null

# Unknown actors and referenced resources have the not-found class rather than
# leaking a lower-level foreign-key error.
expect_error 3 not_found "$test_dir/missing-actor.json" \
  "$tool" --db "$db" task create \
  --id UNKNOWN-ACTOR --title value --actor missing
expect_error 3 not_found "$test_dir/missing-assignee.json" \
  "$tool" --db "$db" task create \
  --id UNKNOWN-ASSIGNEE --title value --actor actor --assignee missing
expect_error 3 not_found "$test_dir/missing-message-task.json" \
  "$tool" --db "$db" message send \
  --id UNKNOWN-MESSAGE --sender actor --recipient team \
  --task missing --body value
expect_error 3 not_found "$test_dir/missing-reviewer.json" \
  "$tool" --db "$db" artifact add \
  --id UNKNOWN-REVIEWER --uri artifact://missing --owner actor --type code \
  --reviewer missing

"$tool" --db "$db" session start \
  --id recover-session --agent alpha --harness test >/dev/null
python3 -c '
import sqlite3
import sys
connection = sqlite3.connect(sys.argv[1])
connection.execute(
    "UPDATE agent_sessions SET last_seen_at = ? WHERE id = ?",
    ("2000-01-01T00:00:00+00:00", "recover-session"),
)
connection.commit()
' "$db"
expect_error 2 invalid_arguments "$test_dir/blank-reason.json" \
  "$tool" --db "$db" session recover recover-session \
  --actor actor --reason '   '

# Attribution is validated before claim-ownership comparisons, so unknown,
# inactive, mismatched, and ended identities retain their public error classes.
"$tool" --db "$db" session start \
  --id owner-session --agent alpha --harness test >/dev/null
"$tool" --db "$db" task create \
  --id ATTRIBUTION --title Attribution --actor actor >/dev/null
"$tool" --db "$db" --session owner-session task claim ATTRIBUTION \
  --agent alpha --if-revision 1 >/dev/null
expect_error 3 not_found "$test_dir/status-missing-actor.json" \
  "$tool" --db "$db" --session owner-session task status ATTRIBUTION review \
  --actor missing --if-revision 2
expect_error 3 not_found "$test_dir/status-missing-session.json" \
  "$tool" --db "$db" --session missing-session task status ATTRIBUTION review \
  --actor alpha --if-revision 2
expect_error 4 session_actor_mismatch "$test_dir/status-session-actor.json" \
  "$tool" --db "$db" --session owner-session task status ATTRIBUTION review \
  --actor beta --if-revision 2
"$tool" --db "$db" session start \
  --id ended-session --agent alpha --harness test >/dev/null
"$tool" --db "$db" session end ended-session >/dev/null
expect_error 4 inactive_session "$test_dir/heartbeat-ended-session.json" \
  "$tool" --db "$db" session heartbeat ended-session
expect_error 4 inactive_session "$test_dir/end-ended-session.json" \
  "$tool" --db "$db" session end ended-session
expect_error 4 inactive_session "$test_dir/status-ended-session.json" \
  "$tool" --db "$db" --session ended-session task status ATTRIBUTION review \
  --actor alpha --if-revision 2
"$tool" --db "$db" agent add \
  --id inactive --name Inactive --role test >/dev/null
"$tool" --db "$db" agent update inactive \
  --status inactive --actor inactive >/dev/null
expect_error 4 inactive_actor "$test_dir/status-inactive-actor.json" \
  "$tool" --db "$db" task status ATTRIBUTION review \
  --actor inactive --if-revision 2

# Aggregate fields are arrays, are independently aggregated, and have stable
# lexical order regardless of insertion order.
"$tool" --db "$db" task create \
  --id ARRAY-2 --title Second --actor actor \
  --assignee beta --assignee alpha > "$test_dir/task-create.json"
"$tool" --db "$db" task create \
  --id ARRAY-1 --title First --actor actor --assignee alpha >/dev/null
"$tool" --db "$db" artifact add \
  --id ART-ARRAY --uri artifact://array --owner actor --type code \
  --task ARRAY-2 --task ARRAY-1 --reviewer beta --reviewer alpha >/dev/null
"$tool" --db "$db" task show ARRAY-2 > "$test_dir/task-show.json"
"$tool" --db "$db" artifact list > "$test_dir/artifact-list.json"
python3 - "$test_dir/task-create.json" "$test_dir/task-show.json" \
  "$test_dir/artifact-list.json" <<'PY'
import json
import sys

created = json.load(open(sys.argv[1], encoding="utf-8"))["data"]
shown = json.load(open(sys.argv[2], encoding="utf-8"))["data"]
artifacts = json.load(open(sys.argv[3], encoding="utf-8"))["data"]
artifact = next(value for value in artifacts if value["id"] == "ART-ARRAY")
assert created["assignees"] == ["alpha", "beta"], created
assert shown["assignees"] == ["alpha", "beta"], shown
assert isinstance(shown["evidence"], list)
assert isinstance(shown["dependencies"], list)
assert isinstance(shown["reviews"], list)
assert artifact["related_tasks"] == ["ARRAY-1", "ARRAY-2"], artifact
assert artifact["reviewers"] == ["alpha", "beta"], artifact
PY

# Stored text cannot introduce Markdown structure or raw HTML in an export.
markdown_title='Danger
## injected | *bold* [link] <tag>'
"$tool" --db "$db" task create \
  --id MARKDOWN --title "$markdown_title" --actor actor >/dev/null
"$tool" --db "$db" export --output "$test_dir/export.md" >/dev/null
python3 - "$test_dir/export.md" <<'PY'
import sys

content = open(sys.argv[1], encoding="utf-8").read()
expected = (
    "### MARKDOWN: Danger ## injected \\| \\*bold\\* "
    "\\[link\\] &lt;tag&gt;"
)
assert expected in content, content
assert "\n## injected" not in content
assert "<tag>" not in content
PY

# Managed metadata names are reserved only within an actual .coordination
# root. A standalone explicit database may export to ordinary sibling files
# with those names.
mkdir "$test_dir/standalone"
standalone_db=$test_dir/standalone/state.sqlite3
"$tool" --db "$standalone_db" init >/dev/null
"$tool" --db "$standalone_db" agent add \
  --id standalone --name Standalone --role test >/dev/null
"$tool" --db "$standalone_db" export \
  --output "$test_dir/standalone/config.yml" >/dev/null
"$tool" --db "$standalone_db" export \
  --output "$test_dir/standalone/README.md" >/dev/null
grep -Fq '# Coordination Export' "$test_dir/standalone/config.yml"
grep -Fq '# Coordination Export' "$test_dir/standalone/README.md"

# A final symlink, non-regular file, hard-link alias, or protected operational
# path is never accepted for backup/export/restore.
ln -s "$test_dir/does-not-exist" "$test_dir/output-link"
mkdir "$test_dir/output-directory"
ln "$db" "$test_dir/database-alias.sqlite3"
expect_error 2 invalid_arguments "$test_dir/export-link.json" \
  "$tool" --db "$db" export --output "$test_dir/output-link"
expect_error 2 invalid_arguments "$test_dir/backup-directory.json" \
  "$tool" --db "$db" backup --output "$test_dir/output-directory"
expect_error 2 invalid_arguments "$test_dir/export-alias.json" \
  "$tool" --db "$db" export --output "$test_dir/database-alias.sqlite3"
rm "$test_dir/database-alias.sqlite3"
expect_error 2 invalid_arguments "$test_dir/backup-sidecar.json" \
  "$tool" --db "$db" backup --output "$db-wal"
case_variant_sidecar="$(dirname "$db")/COORDINATION.SQLITE3-WAL"
expect_error 2 invalid_arguments "$test_dir/backup-case-sidecar.json" \
  "$tool" --db "$db" backup --output "$case_variant_sidecar" --force
case_variant_lock="$(dirname "$db")/COORDINATION.SQLITE3.LOCK"
expect_error 2 invalid_arguments "$test_dir/export-case-lock.json" \
  "$tool" --db "$db" export --output "$case_variant_lock" --force
expect_error 2 invalid_arguments "$test_dir/export-config.json" \
  "$tool" --db "$db" export \
  --output "$test_dir/project/.coordination/config.yml" --force
expect_error 2 invalid_arguments "$test_dir/export-readme.json" \
  "$tool" --db "$db" export \
  --output "$test_dir/project/.coordination/README.md" --force
ln "$test_dir/project/.coordination/config.yml" \
  "$test_dir/config-hardlink.yml"
expect_error 2 invalid_arguments "$test_dir/export-config-hardlink.json" \
  "$tool" --db "$db" export \
  --output "$test_dir/config-hardlink.yml" --force
rm "$test_dir/config-hardlink.yml"

# An alternate explicitly selected database cannot publish over the live
# database namespace configured by the enclosing project. Only restore may
# replace the configured main database.
alternate_db=$test_dir/project/.coordination/alternate.sqlite3
"$tool" --db "$alternate_db" init >/dev/null
"$tool" --db "$alternate_db" agent add \
  --id alternate --name Alternate --role test >/dev/null
for configured_target in \
  "$db" \
  "$db-wal" \
  "$db-shm" \
  "$db-journal" \
  "$db.lock"
do
  configured_name=$(basename "$configured_target")
  expect_error 2 invalid_arguments \
    "$test_dir/configured-export-$configured_name.json" \
    "$tool" --db "$alternate_db" export \
    --output "$configured_target" --force
  expect_error 2 invalid_arguments \
    "$test_dir/configured-backup-$configured_name.json" \
    "$tool" --db "$alternate_db" backup \
    --output "$configured_target" --force
done
"$tool" --db "$db" doctor >/dev/null
"$tool" --db "$db" agent list > "$test_dir/configured-db-agents.json"
python3 -c 'import json,sys; assert "actor" in {row["id"] for row in json.load(open(sys.argv[1]))["data"]}' \
  "$test_dir/configured-db-agents.json"

# Explicit initialization may target the configured main database or a
# disjoint alternate database, but never one of the configured sidecar/lock
# roles.
for configured_sidecar in \
  "$test_dir/project/.coordination/config.yml" \
  "$test_dir/project/.coordination/README.md" \
  "$db-wal" \
  "$db-shm" \
  "$db-journal" \
  "$db.lock"
do
  configured_name=$(basename "$configured_sidecar")
  expect_error 2 invalid_arguments \
    "$test_dir/configured-init-$configured_name.json" \
    "$tool" --db "$configured_sidecar" init
done
"$tool" --db "$db" init >/dev/null
"$tool" --db "$db" doctor >/dev/null

# The complete future namespace of any explicit alternate database or output
# must be disjoint. This remains true when the configured database's own name
# looks like a sidecar or lock role.
suffix_index=0
for configured_suffix in .lock -wal -shm -journal; do
  suffix_index=$((suffix_index + 1))
  suffix_root=$test_dir/suffix-project-$suffix_index
  mkdir -p "$suffix_root/.coordination"
  printf 'version: 1\nbackend: sqlite\ndatabase: team%s\n' \
    "$configured_suffix" > "$suffix_root/.coordination/config.yml"
  suffix_configured_db=$suffix_root/.coordination/team$configured_suffix
  "$tool" --db "$suffix_configured_db" init >/dev/null
  suffix_alternate_db=$suffix_root/.coordination/team
  cp "$standalone_db" "$suffix_alternate_db"
  expect_error 2 invalid_arguments \
    "$test_dir/suffix-doctor-$suffix_index.json" \
    "$tool" --db "$suffix_alternate_db" doctor
  expect_error 2 invalid_arguments \
    "$test_dir/suffix-init-$suffix_index.json" \
    "$tool" --db "$suffix_alternate_db" init
  expect_error 2 invalid_arguments \
    "$test_dir/suffix-export-$suffix_index.json" \
    "$tool" --db "$standalone_db" export \
    --output "$suffix_configured_db" --force
  expect_error 2 invalid_arguments \
    "$test_dir/suffix-backup-$suffix_index.json" \
    "$tool" --db "$standalone_db" backup \
    --output "$suffix_alternate_db" --force
  "$tool" --db "$standalone_db" export \
    --output "$suffix_alternate_db" --force >/dev/null
  grep -Fq '# Coordination Export' "$suffix_alternate_db"
  "$tool" --db "$suffix_configured_db" doctor >/dev/null
done

expect_error 2 invalid_arguments "$test_dir/restore-link.json" \
  "$tool" --db "$db" restore --input "$test_dir/output-link" \
  --actor actor --force
ln "$db" "$test_dir/database-alias.sqlite3"
expect_error 2 invalid_arguments "$test_dir/restore-alias.json" \
  "$tool" --db "$db" restore --input "$test_dir/database-alias.sqlite3" \
  --actor actor --force
rm "$test_dir/database-alias.sqlite3"

# Restore input may be the configured main database, whose real advisory lock
# is used, but may never reinterpret one of its operational roles as another
# database or create a derived lock beside that role.
mkdir -p "$test_dir/restore-input-project/.coordination"
restore_input_main=$test_dir/restore-input-project/.coordination/live.sqlite3
printf 'version: 1\nbackend: sqlite\ndatabase: live.sqlite3\n' \
  > "$test_dir/restore-input-project/.coordination/config.yml"
"$tool" --db "$restore_input_main" init >/dev/null
"$tool" --db "$restore_input_main" agent add \
  --id input-actor --name Input --role operations >/dev/null
"$tool" --db "$test_dir/restore-from-main.sqlite3" restore \
  --input "$restore_input_main" --actor input-actor --force >/dev/null
"$tool" --db "$test_dir/restore-from-main.sqlite3" doctor >/dev/null
for restore_input_suffix in -wal -shm -journal .lock; do
  restore_input_role=$restore_input_main$restore_input_suffix
  cp "$restore_input_main" "$restore_input_role"
  expect_error 2 invalid_arguments \
    "$test_dir/restore-input-role-$restore_input_suffix.json" \
    "$tool" --db "$test_dir/restore-role-target-$restore_input_suffix.sqlite3" \
    restore --input "$restore_input_role" --actor actor --force
  test ! -e "$restore_input_role.lock"
done

# Restore rejects collisions between every source and target operational name,
# including the asymmetric source-lock-as-target-database case.
for namespace_suffix in .lock -wal -shm -journal; do
  expect_error 2 invalid_arguments \
    "$test_dir/restore-namespace-$namespace_suffix.json" \
    "$tool" --db "$db$namespace_suffix" restore --input "$db" \
    --actor actor --force
done
"$tool" --db "$db" doctor >/dev/null
expect_error 2 invalid_arguments "$test_dir/restore-safety-alias.json" \
  "$tool" --db "$test_dir/backups" restore --input "$db" \
  --actor actor --force
test ! -e "$test_dir/backups"

# An explicit restore target inside a project cannot reinterpret managed
# metadata or a configured database sidecar/lock as the replacement database.
managed_restore_source=$test_dir/managed-restore-source.sqlite3
"$tool" --db "$db" backup --output "$managed_restore_source" >/dev/null
cp "$test_dir/project/.coordination/config.yml" \
  "$test_dir/managed-config.before"
cp "$test_dir/project/.coordination/README.md" \
  "$test_dir/managed-readme.before"
for managed_target in \
  "$test_dir/project/.coordination/config.yml" \
  "$test_dir/project/.coordination/README.md" \
  "$db-wal" \
  "$db-shm" \
  "$db-journal" \
  "$db.lock"
do
  managed_name=$(basename "$managed_target")
  expect_error 2 invalid_arguments \
    "$test_dir/managed-restore-$managed_name.json" \
    "$tool" --db "$managed_target" restore \
    --input "$managed_restore_source" --actor actor --force
done
cmp -s "$test_dir/managed-config.before" \
  "$test_dir/project/.coordination/config.yml"
cmp -s "$test_dir/managed-readme.before" \
  "$test_dir/project/.coordination/README.md"
"$tool" --db "$db" doctor >/dev/null

# A backup output is itself a database namespace, so its future sidecar and
# lock names must also remain disjoint from the live source namespace.
for namespace_suffix in .lock -wal -shm -journal; do
  namespace_source=$test_dir/backup-namespace$namespace_suffix
  "$tool" --db "$namespace_source" init >/dev/null
  expect_error 2 invalid_arguments \
    "$test_dir/backup-namespace-$namespace_suffix.json" \
    "$tool" --db "$namespace_source" backup \
    --output "$test_dir/backup-namespace"
done
test ! -e "$test_dir/backup-namespace"

# A derived publication-lock filename cannot alias the database either.
lock_alias_db=$test_dir/.lock-output.publish.lock
"$tool" --db "$lock_alias_db" init >/dev/null
"$tool" --db "$lock_alias_db" agent add \
  --id lock-actor --name Lock --role test >/dev/null
expect_error 2 invalid_arguments "$test_dir/derived-lock-alias.json" \
  "$tool" --db "$lock_alias_db" export \
  --output "$test_dir/lock-output"

# Nested configured database paths still protect their root config, while
# discovery refuses symlinked coordination roots and config files.
mkdir -p "$test_dir/nested-project/.coordination/state" \
  "$test_dir/nested-project/child"
printf 'version: 1\nbackend: sqlite\ndatabase: state/nested.sqlite3\n' \
  > "$test_dir/nested-project/.coordination/config.yml"
"$tool" --db \
  "$test_dir/nested-project/.coordination/state/nested.sqlite3" init >/dev/null
expect_error_in_dir 2 invalid_arguments "$test_dir/nested-config.json" \
  "$test_dir/nested-project/child" \
  "$tool" export \
  --output "$test_dir/nested-project/.coordination/config.yml" --force

mkdir -p "$test_dir/nested-root-invalid/.coordination/state/.coordination"
printf 'version: 1\nbackend: sqlite\ndatabase: state/.coordination/team.sqlite3\n' \
  > "$test_dir/nested-root-invalid/.coordination/config.yml"
expect_error_in_dir 5 configuration_error \
  "$test_dir/nested-coordination-component.json" \
  "$test_dir/nested-root-invalid" "$tool" doctor

mkdir -p "$test_dir/casefold-config/.coordination"
for casefold_database in \
  'Backups/team.sqlite3' \
  'state/.Coordination/team.sqlite3'
do
  printf 'version: 1\nbackend: sqlite\ndatabase: %s\n' "$casefold_database" \
    > "$test_dir/casefold-config/.coordination/config.yml"
  casefold_name=$(printf '%s' "$casefold_database" | tr '/.' '__')
  expect_error_in_dir 5 configuration_error \
    "$test_dir/casefold-config-$casefold_name.json" \
    "$test_dir/casefold-config" "$tool" doctor
done

mkdir -p "$test_dir/non-directory-parent/.coordination"
printf 'not a directory\n' \
  > "$test_dir/non-directory-parent/.coordination/state"
printf 'version: 1\nbackend: sqlite\ndatabase: state/team.sqlite3\n' \
  > "$test_dir/non-directory-parent/.coordination/config.yml"
expect_error_in_dir 5 configuration_error \
  "$test_dir/non-directory-database-parent.json" \
  "$test_dir/non-directory-parent" "$tool" doctor

mkdir "$test_dir/symlink-root" "$test_dir/symlink-config"
ln -s "$test_dir/project/.coordination" \
  "$test_dir/symlink-root/.coordination"
mkdir "$test_dir/symlink-config/.coordination"
ln -s "$test_dir/project/.coordination/config.yml" \
  "$test_dir/symlink-config/.coordination/config.yml"
expect_error_in_dir 5 configuration_error "$test_dir/symlink-root.json" \
  "$test_dir/symlink-root" "$tool" doctor
expect_error_in_dir 5 configuration_error "$test_dir/symlink-config.json" \
  "$test_dir/symlink-config" "$tool" doctor

# A malformed nearer project boundary is an error; discovery never skips its
# directory or special-file config and silently mutates a parent database.
mkdir -p "$test_dir/project/missing-config/.coordination" \
  "$test_dir/project/directory-config/.coordination/config.yml" \
  "$test_dir/project/special-config/.coordination"
mkfifo "$test_dir/project/special-config/.coordination/config.yml"
expect_error_in_dir 5 configuration_error \
  "$test_dir/missing-config-boundary.json" \
  "$test_dir/project/missing-config" \
  "$tool" agent add --id wrong-project --name Wrong --role test
expect_error_in_dir 5 configuration_error \
  "$test_dir/directory-config-boundary.json" \
  "$test_dir/project/directory-config" \
  "$tool" agent add --id wrong-project --name Wrong --role test
expect_error_in_dir 5 configuration_error \
  "$test_dir/special-config-boundary.json" \
  "$test_dir/project/special-config" \
  "$tool" agent add --id wrong-project --name Wrong --role test
python3 - "$db" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
assert connection.execute(
    "SELECT COUNT(*) FROM agents WHERE id = 'wrong-project'"
).fetchone()[0] == 0
PY

# Concurrent no-clobber publication has one winner and one conflict, never two
# successful writers. The published artifacts remain complete and verifiable.
run_export() {
  output_file=$1
  code_file=$2
  set +e
  "$tool" --db "$db" export --output "$test_dir/concurrent.md" \
    > "$output_file" 2> "$output_file.error"
  code=$?
  set -e
  printf '%s\n' "$code" > "$code_file"
}

run_backup() {
  output_file=$1
  code_file=$2
  set +e
  "$tool" --db "$db" backup --output "$test_dir/concurrent.sqlite3" \
    > "$output_file" 2> "$output_file.error"
  code=$?
  set -e
  printf '%s\n' "$code" > "$code_file"
}

run_export "$test_dir/export-a.json" "$test_dir/export-a.code" &
export_a_pid=$!
run_export "$test_dir/export-b.json" "$test_dir/export-b.code" &
export_b_pid=$!
wait "$export_a_pid"
wait "$export_b_pid"
python3 -c '
import sys
codes = sorted(int(open(path, encoding="utf-8").read()) for path in sys.argv[1:])
assert codes == [0, 4], codes
' "$test_dir/export-a.code" "$test_dir/export-b.code"
grep -Fq '# Coordination Export' "$test_dir/concurrent.md"

run_backup "$test_dir/backup-a.json" "$test_dir/backup-a.code" &
backup_a_pid=$!
run_backup "$test_dir/backup-b.json" "$test_dir/backup-b.code" &
backup_b_pid=$!
wait "$backup_a_pid"
wait "$backup_b_pid"
python3 -c '
import sqlite3
import sys
codes = sorted(int(open(path, encoding="utf-8").read()) for path in sys.argv[1:3])
assert codes == [0, 4], codes
connection = sqlite3.connect(sys.argv[3])
assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
' "$test_dir/backup-a.code" "$test_dir/backup-b.code" \
  "$test_dir/concurrent.sqlite3"

printf 'old report\n' > "$test_dir/forced.md"
"$tool" --db "$db" export --output "$test_dir/forced.md" --force >/dev/null
grep -Fq '# Coordination Export' "$test_dir/forced.md"

# Output basenames are literal text, not glob patterns used to select cleanup
# candidates. Wildcards cannot delete unrelated sibling files.
for wildcard_name in '*' '?' '['; do
  wildcard_directory=$test_dir/wildcard-$wildcard_name
  mkdir "$wildcard_directory"
  printf 'keep\n' > "$wildcard_directory/.victim.value.tmp"
  "$tool" --db "$db" export \
    --output "$wildcard_directory/$wildcard_name" >/dev/null
  grep -Fq 'keep' "$wildcard_directory/.victim.value.tmp"
  test -f "$wildcard_directory/$wildcard_name"
done

# An interrupted publication emits a structured operational error, removes its
# private temporary, and permits an immediate clean retry.
PYTHONPATH=$runtime/lib python3 tests/backup_interrupt_probe.py \
  --tool-package "$runtime/lib/coordination" \
  --database "$db" \
  --output "$test_dir/interrupted.sqlite3" \
  --marker "$test_dir/backup-started" \
  > "$test_dir/interrupted.stdout" 2> "$test_dir/interrupted.json" &
interrupt_pid=$!
wait_count=0
while [ ! -f "$test_dir/backup-started" ]; do
  kill -0 "$interrupt_pid" 2>/dev/null ||
    fail_test "Interrupted backup probe exited before publication"
  wait_count=$((wait_count + 1))
  [ "$wait_count" -lt 500 ] ||
    fail_test "Interrupted backup probe did not enter publication"
  sleep 0.01
done
kill -TERM "$interrupt_pid"
set +e
wait "$interrupt_pid"
interrupt_exit=$?
set -e
interrupt_pid=
[ "$interrupt_exit" -eq 5 ] ||
  fail_test "Interrupted backup returned $interrupt_exit"
python3 -c '
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
assert value["error"]["code"] == "operation_interrupted", value
' "$test_dir/interrupted.json"
test ! -e "$test_dir/interrupted.sqlite3"
test -z "$(find "$test_dir" -name '.interrupted.sqlite3.*.tmp' -print)"
"$tool" --db "$db" backup --output "$test_dir/interrupted.sqlite3" >/dev/null

# Export has the same structured interruption and cleanup contract before its
# atomic publication step.
PYTHONPATH=$runtime/lib python3 tests/export_interrupt_probe.py \
  --tool-package "$runtime/lib/coordination" \
  --database "$db" \
  --output "$test_dir/interrupted.md" \
  --marker "$test_dir/export-started" \
  > "$test_dir/export-interrupted.stdout" \
  2> "$test_dir/export-interrupted.json" &
interrupt_pid=$!
wait_count=0
while [ ! -f "$test_dir/export-started" ]; do
  kill -0 "$interrupt_pid" 2>/dev/null ||
    fail_test "Interrupted export probe exited before publication"
  wait_count=$((wait_count + 1))
  [ "$wait_count" -lt 500 ] ||
    fail_test "Interrupted export probe did not enter publication"
  sleep 0.01
done
kill -TERM "$interrupt_pid"
set +e
wait "$interrupt_pid"
interrupt_exit=$?
set -e
interrupt_pid=
[ "$interrupt_exit" -eq 5 ] ||
  fail_test "Interrupted export returned $interrupt_exit"
python3 -c '
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
assert value["error"]["code"] == "operation_interrupted", value
' "$test_dir/export-interrupted.json"
test ! -e "$test_dir/interrupted.md"
test -z "$(find "$test_dir" -name '.interrupted.md.*.tmp' -print)"
"$tool" --db "$db" export --output "$test_dir/interrupted.md" >/dev/null

# Canonical object definitions are checked, not merely their names. Explicit
# NOT NULL text primary keys close SQLite's nullable PRIMARY KEY exception.
python3 - "$db" "$test_dir/wrong-definition.sqlite3" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(sys.argv[1])
destination = sqlite3.connect(sys.argv[2])
source.backup(destination)
source.close()
destination.executescript(
    """
    DROP INDEX idx_messages_recipient;
    CREATE INDEX idx_messages_recipient ON messages(body);
    DROP TRIGGER task_update_done_requires_evidence;
    CREATE TRIGGER task_update_done_requires_evidence
    BEFORE UPDATE OF status ON tasks
    BEGIN
      SELECT 1;
    END;
    """
)
destination.close()
PY
expect_error 5 schema_definition_mismatch "$test_dir/definition.json" \
  "$tool" --db "$test_dir/wrong-definition.sqlite3" doctor
python3 - "$db" "$test_dir/unexpected-object.sqlite3" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(sys.argv[1])
destination = sqlite3.connect(sys.argv[2])
source.backup(destination)
source.close()
destination.execute("CREATE VIEW unexpected_view AS SELECT 1 AS value")
destination.close()
PY
expect_error 5 schema_definition_mismatch "$test_dir/unexpected-object.json" \
  "$tool" --db "$test_dir/unexpected-object.sqlite3" doctor

python3 - "$test_dir/foreign-view.sqlite3" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
connection.execute("CREATE VIEW unexpected_view AS SELECT 1 AS value")
connection.close()
PY
expect_error 5 unsupported_schema "$test_dir/foreign-view-init.json" \
  "$tool" --db "$test_dir/foreign-view.sqlite3" init
python3 - "$test_dir/foreign-view.sqlite3" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
assert connection.execute(
    "SELECT sql FROM sqlite_master WHERE type = 'view' AND name = 'unexpected_view'"
).fetchone() is not None
assert connection.execute(
    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'agents'"
).fetchone()[0] == 0
PY

python3 - "$db" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
connection.execute("PRAGMA foreign_keys = ON")
tables = (
    "agents",
    "agent_sessions",
    "tasks",
    "messages",
    "reviews",
    "decisions",
    "artifacts",
    "escalations",
)
for table in tables:
    columns = {
        row[1]: row for row in connection.execute(f"PRAGMA table_info({table})")
    }
    assert columns["id"][3] == 1, (table, columns["id"])
claim_columns = {
    row[1]: row for row in connection.execute("PRAGMA table_info(task_claims)")
}
assert claim_columns["task_id"][3] == 1, claim_columns["task_id"]
try:
    connection.execute(
        """INSERT INTO agents(
             id, name, role, actor_type, status, created_at, updated_at
           ) VALUES (NULL, 'Null', 'test', 'ai', 'active', 'now', 'now')"""
    )
except sqlite3.IntegrityError:
    pass
else:
    raise AssertionError("agents.id accepted NULL")
PY

# Installed schema read/compile failures are installation errors, never
# internal failures, and validation happens before init creates a target.
cp "$runtime/sqlite/schema.sql" "$test_dir/schema-good.sql"
python3 - "$runtime/sqlite/schema.sql" <<'PY'
from pathlib import Path
import sys

Path(sys.argv[1]).write_bytes(b"\xff")
PY
expect_error 5 installation_error "$test_dir/schema-utf8-doctor.json" \
  "$tool" --db "$db" doctor
expect_error 5 installation_error "$test_dir/schema-utf8-init.json" \
  "$tool" --db "$test_dir/schema-utf8-init.sqlite3" init
test ! -e "$test_dir/schema-utf8-init.sqlite3"

printf 'THIS IS NOT SQL;\n' > "$runtime/sqlite/schema.sql"
expect_error 5 installation_error "$test_dir/schema-sql-doctor.json" \
  "$tool" --db "$db" doctor
expect_error 5 installation_error "$test_dir/schema-sql-init.json" \
  "$tool" --db "$test_dir/schema-sql-init.sqlite3" init
test ! -e "$test_dir/schema-sql-init.sqlite3"

python3 - "$test_dir/schema-good.sql" "$runtime/sqlite/schema.sql" <<'PY'
from pathlib import Path
import sys

schema = Path(sys.argv[1]).read_text(encoding="utf-8")
modified = schema.replace("  goal TEXT NOT NULL DEFAULT '',\n", "", 1)
assert modified != schema
Path(sys.argv[2]).write_text(modified, encoding="utf-8")
PY
expect_error 5 installation_error "$test_dir/schema-column-doctor.json" \
  "$tool" --db "$db" doctor
expect_error 5 installation_error "$test_dir/schema-column-init.json" \
  "$tool" --db "$test_dir/schema-column-init.sqlite3" init
test ! -e "$test_dir/schema-column-init.sqlite3"
cp "$test_dir/schema-good.sql" "$runtime/sqlite/schema.sql"

# A failure after the schema transaction starts leaves no partial v1 database,
# and an immediate retry with the canonical script succeeds.
expect_error 5 database_error "$test_dir/atomic-init.json" \
  env PYTHONPATH="$runtime/lib" python3 tests/init_failure_injection.py \
  --tool-package "$runtime/lib/coordination" \
  --database "$test_dir/atomic-init.sqlite3"
python3 - "$test_dir/atomic-init.sqlite3" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
assert connection.execute(
    "SELECT name FROM sqlite_master WHERE type = 'table'"
).fetchall() == []
PY
"$tool" --db "$test_dir/atomic-init.sqlite3" init >/dev/null
"$tool" --db "$test_dir/atomic-init.sqlite3" doctor >/dev/null

# More than one parameter batch exercises independent aggregates. Pagination
# remains bounded, deterministic, and complete at its boundaries.
scale_db=$test_dir/scale.sqlite3
"$tool" --db "$scale_db" init >/dev/null
"$tool" --db "$scale_db" agent add \
  --id scale --name Scale --role test >/dev/null
"$tool" --db "$scale_db" agent add \
  --id scale-a --name A --role test >/dev/null
"$tool" --db "$scale_db" agent add \
  --id scale-b --name B --role test >/dev/null
python3 - "$scale_db" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
stamp = "2026-01-01T00:00:00+00:00"
for index in range(510):
    task_id = f"SCALE-{index:04d}"
    connection.execute(
        """INSERT INTO tasks(
             id, title, priority, created_by, created_at, updated_at
           ) VALUES (?, ?, 3, 'scale', ?, ?)""",
        (task_id, f"Task {index}", stamp, stamp),
    )
    for agent in ("scale-b", "scale-a"):
        connection.execute(
            """INSERT INTO task_assignees(task_id, agent_id, assigned_at)
               VALUES (?, ?, ?)""",
            (task_id, agent, stamp),
        )
    connection.execute(
        """INSERT INTO task_evidence(
             task_id, uri, evidence_type, added_by, created_at
           ) VALUES (?, ?, 'test', 'scale', ?)""",
        (task_id, f"test://{index}", stamp),
    )
connection.execute(
    "DELETE FROM task_assignees WHERE task_id >= 'SCALE-0505'"
)
connection.commit()
PY
"$tool" --db "$scale_db" task list --limit 500 > "$test_dir/scale-first.json"
"$tool" --db "$scale_db" task list --limit 500 --offset 500 \
  > "$test_dir/scale-last.json"
"$tool" --db "$scale_db" task list > "$test_dir/scale-default.json"
"$tool" --db "$scale_db" health --limit 2 > "$test_dir/scale-health.json"
python3 - "$test_dir/scale-first.json" "$test_dir/scale-last.json" \
  "$test_dir/scale-default.json" "$test_dir/scale-health.json" <<'PY'
import json
import sys

first = json.load(open(sys.argv[1], encoding="utf-8"))["data"]
last = json.load(open(sys.argv[2], encoding="utf-8"))["data"]
default = json.load(open(sys.argv[3], encoding="utf-8"))["data"]
health = json.load(open(sys.argv[4], encoding="utf-8"))["data"]
assert len(first) == 500
assert len(last) == 10
assert len(default) == 100
assert first[0]["id"] == "SCALE-0000"
assert first[-1]["id"] == "SCALE-0499"
assert last[0]["id"] == "SCALE-0500"
assert last[-1]["id"] == "SCALE-0509"
assert all(value["assignees"] == ["scale-a", "scale-b"] for value in first)
assert all(value["evidence_count"] == 1 for value in first)
assert health["healthy"] is False
assert len(health["unowned_tasks"]) == 2
assert "unowned_tasks" in health["truncated_sections"]
PY

printf 'SQLite stability qualification tests passed.\n'
