#!/bin/sh
set -eu

test_root=$(mktemp -d)

cleanup() {
  rm -rf "$test_root"
}
trap cleanup EXIT HUP INT TERM

expect_install_failure() {
  if "$@" >"$test_root/unexpected-success.out" 2>"$test_root/expected-failure.err"; then
    printf 'Command unexpectedly succeeded: %s\n' "$*" >&2
    exit 1
  fi
}

markdown_target=$test_root/markdown
no_agents_target=$test_root/no-agents
clean_target=$test_root/clean
python_target=$test_root/python-preflight
partial_target=$test_root/partial-target
symlink_target=$test_root/symlink-target
outside_target=$test_root/outside
escape_target=$test_root/escape-target
sqlite_target=$test_root/sqlite-custom
unhealthy_target=$test_root/sqlite-unhealthy
reserved_db_target=$test_root/sqlite-reserved-db
hardlink_db_target=$test_root/sqlite-hardlink-db
malformed_config_target=$test_root/sqlite-malformed-config
nested_database_target=$test_root/sqlite-nested-database
hardlink_ignore_target=$test_root/sqlite-hardlink-ignore
real_alias_target=$test_root/real-alias-target
mkdir -p \
  "$markdown_target" \
  "$no_agents_target" \
  "$clean_target" \
  "$python_target" \
  "$partial_target" \
  "$symlink_target" \
  "$outside_target" \
  "$escape_target/.coordination" \
  "$sqlite_target/.coordination" \
  "$unhealthy_target" \
  "$reserved_db_target/.coordination" \
  "$hardlink_db_target/.coordination" \
  "$malformed_config_target/.coordination" \
  "$nested_database_target/.coordination" \
  "$hardlink_ignore_target/.coordination" \
  "$real_alias_target"

# The filesystem root always contains the source checkout and is never a
# valid installation destination. This rejection occurs before any writes.
expect_install_failure ./scripts/install.sh --target / --adapter markdown
grep -Fq 'must not be the filesystem root' "$test_root/expected-failure.err"

# A legacy marker had no end delimiter. Reinstall must replace everything from
# that marker with the one canonical managed block while preserving host rules
# before it.
printf '%s\n' \
  '# Existing project rules' \
  '' \
  'Keep this line.' \
  '<!-- agentic-project-scaffold-lite -->' \
  'stale managed content' > "$markdown_target/AGENTS.md"

./scripts/install.sh --target "$markdown_target" --adapter markdown
./scripts/verify-install.sh "$markdown_target"
test "$(grep -Fxc '<!-- agentic-project-scaffold-lite:start -->' "$markdown_target/AGENTS.md")" -eq 1
test "$(grep -Fxc '<!-- agentic-project-scaffold-lite:end -->' "$markdown_target/AGENTS.md")" -eq 1
test "$(grep -Fc 'Keep this line.' "$markdown_target/AGENTS.md")" -eq 1
! grep -Fq 'stale managed content' "$markdown_target/AGENTS.md"
! grep -Fqx '<!-- agentic-project-scaffold-lite -->' "$markdown_target/AGENTS.md"

# Complete but damaged blocks are replaced, and content after the end marker is
# not swallowed.
printf '%s\n' \
  '# Existing project rules' \
  '' \
  'Keep this line.' \
  '<!-- agentic-project-scaffold-lite:start -->' \
  'damaged managed content' \
  '<!-- agentic-project-scaffold-lite:end -->' \
  '' \
  'Keep this suffix too.' > "$markdown_target/AGENTS.md"
./scripts/install.sh --target "$markdown_target" --adapter markdown
./scripts/verify-install.sh "$markdown_target"
grep -Fq 'Use `done` only when required review and evidence exist.' "$markdown_target/AGENTS.md"
grep -Fq 'Keep this suffix too.' "$markdown_target/AGENTS.md"
! grep -Fq 'damaged managed content' "$markdown_target/AGENTS.md"

cp "$markdown_target/AGENTS.md" "$test_root/AGENTS.before"
cp "$markdown_target/.coordination/config.yml" "$test_root/markdown-config.before"
./scripts/install.sh --target "$markdown_target" --adapter markdown
cmp -s "$test_root/AGENTS.before" "$markdown_target/AGENTS.md"
cmp -s "$test_root/markdown-config.before" "$markdown_target/.coordination/config.yml"

./scripts/install.sh --target "$no_agents_target" --no-agents-file
./scripts/verify-install.sh --no-agents-file "$no_agents_target"
test ! -e "$no_agents_target/AGENTS.md"

./scripts/install.sh --target "$clean_target"
./scripts/install.sh --target "$clean_target"
./scripts/verify-install.sh "$clean_target"
test "$(grep -Fxc '<!-- agentic-project-scaffold-lite:start -->' "$clean_target/AGENTS.md")" -eq 1
test "$(grep -Fxc '<!-- agentic-project-scaffold-lite:end -->' "$clean_target/AGENTS.md")" -eq 1
grep -Fq 'Evidence-Based Completion' "$clean_target/.agents/agentic-project-scaffold-lite/SPEC.md"
grep -Fq 'actor_type: ai | human | service' "$clean_target/.agents/agentic-project-scaffold-lite/SPEC.md"
grep -Fq 'backend: markdown' "$clean_target/.coordination/config.yml"

expect_install_failure ./scripts/install.sh --target "$clean_target" --adapter sqlite

# Python compatibility is checked before even the target's managed parents are
# created.
fake_python_bin=$test_root/fake-python-bin
mkdir -p "$fake_python_bin"
printf '%s\n' '#!/bin/sh' 'exit 1' > "$fake_python_bin/python3"
chmod +x "$fake_python_bin/python3"
expect_install_failure env PATH="$fake_python_bin:/usr/bin:/bin" \
  ./scripts/install.sh --target "$python_target" --adapter sqlite
test -z "$(find "$python_target" -mindepth 1 -print -quit)"

# A partial source checkout must fail before touching the destination.
partial_source=$test_root/partial-source
mkdir -p "$partial_source/scripts"
cp ./scripts/install.sh "$partial_source/scripts/install.sh"
chmod +x "$partial_source/scripts/install.sh"

mkdir "$partial_source/nested-target"
expect_install_failure "$partial_source/scripts/install.sh" \
  --target "$partial_source/nested-target"
grep -Fqi 'inside the scaffold source checkout' "$test_root/expected-failure.err"
test -z "$(find "$partial_source/nested-target" -mindepth 1 -print -quit)"

source_inside_target=$test_root/source-inside-target
nested_source=$source_inside_target/scaffold
mkdir -p "$nested_source/scripts"
cp ./scripts/install.sh "$nested_source/scripts/install.sh"
chmod +x "$nested_source/scripts/install.sh"
expect_install_failure "$nested_source/scripts/install.sh" --target "$source_inside_target"
grep -Fqi 'source checkout must not be inside' "$test_root/expected-failure.err"

expect_install_failure "$partial_source/scripts/install.sh" --target "$partial_target"
test -z "$(find "$partial_target" -mindepth 1 -print -quit)"

# Managed destinations and configured databases cannot escape through symbolic
# links or parent-directory aliases.
ln -s "$outside_target" "$symlink_target/.agents"
expect_install_failure ./scripts/install.sh --target "$symlink_target" --adapter markdown
test -z "$(find "$outside_target" -mindepth 1 -print -quit)"

target_alias=$test_root/target-alias
ln -s "$real_alias_target" "$target_alias"
expect_install_failure ./scripts/install.sh \
  --target "$target_alias//" --adapter markdown
expect_install_failure ./scripts/install.sh \
  --target "$target_alias/./" --adapter markdown
expect_install_failure ./scripts/verify-install.sh "$target_alias//"
expect_install_failure ./scripts/verify-install.sh "$target_alias/."
test -z "$(find "$real_alias_target" -mindepth 1 -print -quit)"

printf '%s\n' \
  'version: 1' \
  'backend: sqlite' \
  'database: ../escaped.sqlite3' > "$escape_target/.coordination/config.yml"
expect_install_failure ./scripts/install.sh --target "$escape_target" --adapter sqlite
test ! -e "$escape_target/escaped.sqlite3"

# Full configuration grammar and nested coordination roots are validated before
# any managed destination is created.
printf '%s\n' \
  'version: 1' \
  'backend: sqlite' \
  'database: state.sqlite3' \
  'this is not configuration' \
  > "$malformed_config_target/.coordination/config.yml"
expect_install_failure ./scripts/install.sh \
  --target "$malformed_config_target" --adapter sqlite
test ! -e "$malformed_config_target/.agents"
test ! -e "$malformed_config_target/.coordination/README.md"
test ! -e "$malformed_config_target/.coordination/backups"
test ! -e "$malformed_config_target/.coordination/state.sqlite3"

printf '%s\n' \
  'version: 1' \
  'backend: sqlite' \
  'database: state/.coordination/team.sqlite3' \
  > "$nested_database_target/.coordination/config.yml"
expect_install_failure ./scripts/install.sh \
  --target "$nested_database_target" --adapter sqlite
test ! -e "$nested_database_target/.agents"

printf '%s\n' \
  'version: 1' \
  'backend: sqlite' \
  'database: Backups/team.sqlite3' \
  > "$nested_database_target/.coordination/config.yml"
expect_install_failure ./scripts/install.sh \
  --target "$nested_database_target" --adapter sqlite
test ! -e "$nested_database_target/.agents"

printf '%s\n' \
  'version: 1' \
  'backend: sqlite' \
  'database: state/.Coordination/team.sqlite3' \
  > "$nested_database_target/.coordination/config.yml"
expect_install_failure ./scripts/install.sh \
  --target "$nested_database_target" --adapter sqlite
test ! -e "$nested_database_target/.agents"

# Existing files with outside hard-link aliases are rejected before writes.
printf 'outside ignore\n' > "$test_root/outside-ignore"
ln "$test_root/outside-ignore" "$hardlink_ignore_target/.gitignore"
printf '%s\n' \
  'version: 1' \
  'backend: sqlite' \
  'database: coordination.sqlite3' \
  > "$hardlink_ignore_target/.coordination/config.yml"
cp "$test_root/outside-ignore" "$test_root/outside-ignore.before"
expect_install_failure ./scripts/install.sh \
  --target "$hardlink_ignore_target" --adapter sqlite
cmp -s "$test_root/outside-ignore.before" "$test_root/outside-ignore"
test ! -e "$hardlink_ignore_target/.agents"

# Custom configuration is authoritative for installation, verification, and
# cwd discovery. Reinstall preserves both its bytes and its database contents.
printf '%s\n' \
  '  version: 1' \
  '  backend: sqlite' \
  '  database: state/team.db' > "$sqlite_target/.coordination/config.yml"
cp "$sqlite_target/.coordination/config.yml" "$test_root/sqlite-config.before"

./scripts/install.sh --target "$sqlite_target" --adapter sqlite
./scripts/verify-install.sh "$sqlite_target"
sqlite_tool=$sqlite_target/.agents/agentic-project-scaffold-lite/bin/coordination
sqlite_db=$sqlite_target/.coordination/state/team.db
test -f "$sqlite_db"
test ! -e "$sqlite_target/.coordination/coordination.sqlite3"
(
  cd "$sqlite_target"
  "$sqlite_tool" agent add --id persistent --name Persistent --role test >/dev/null
  "$sqlite_tool" doctor > "$test_root/custom-doctor.json"
)
python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["data"]["database"].endswith("/.coordination/state/team.db")' "$test_root/custom-doctor.json"
grep -Fqx '/.coordination/state/team.db*' "$sqlite_target/.gitignore"

./scripts/install.sh --target "$sqlite_target" --adapter sqlite
./scripts/verify-install.sh "$sqlite_target"
cmp -s "$test_root/sqlite-config.before" "$sqlite_target/.coordination/config.yml"
(
  cd "$sqlite_target"
  "$sqlite_tool" agent list > "$test_root/agents-after-reinstall.json"
)
python3 -c 'import json,sys; rows=json.load(open(sys.argv[1]))["data"]; assert [row["id"] for row in rows] == ["persistent"]' "$test_root/agents-after-reinstall.json"

# The installed runtime is copied byte-for-byte, and PYTHONPATH cannot replace
# its coordination package with an unrelated one.
cmp -s scripts/coordination.py "$sqlite_tool"
cmp -s sqlite/schema.sql "$sqlite_target/.agents/agentic-project-scaffold-lite/sqlite/schema.sql"
cmp -s VERSION "$sqlite_target/.agents/agentic-project-scaffold-lite/VERSION"
poison_root=$test_root/poison
mkdir -p "$poison_root/coordination"
printf '%s\n' 'raise RuntimeError("unintended coordination package imported")' > "$poison_root/coordination/__init__.py"
(
  cd "$sqlite_target"
  PYTHONPATH="$poison_root" "$sqlite_tool" version >/dev/null
)

# Import-time corruption is an installation error with the public JSON
# envelope, never an uncaught Python traceback.
installed_cli=$sqlite_target/.agents/agentic-project-scaffold-lite/lib/coordination/cli.py
printf 'this is invalid Python !!!\n' > "$installed_cli"
set +e
"$sqlite_tool" version > "$test_root/corrupt-cli.stdout" \
  2> "$test_root/corrupt-cli.json"
corrupt_cli_exit=$?
set -e
[ "$corrupt_cli_exit" -eq 5 ]
python3 - "$test_root/corrupt-cli.json" <<'PY'
import json
from pathlib import Path
import sys

content = Path(sys.argv[1]).read_text(encoding="utf-8")
assert "Traceback" not in content
value = json.loads(content)
assert value["ok"] is False, value
assert value["error"]["code"] == "installation_error", value
PY
expect_install_failure ./scripts/verify-install.sh "$sqlite_target"
./scripts/install.sh --target "$sqlite_target" --adapter sqlite
./scripts/verify-install.sh "$sqlite_target"

# Verifier rejects bundle drift; same-backend reinstall repairs it without
# replacing configuration or data.
printf '\n# local tamper\n' >> "$sqlite_target/.agents/agentic-project-scaffold-lite/lib/coordination/core.py"
expect_install_failure ./scripts/verify-install.sh "$sqlite_target"
./scripts/install.sh --target "$sqlite_target" --adapter sqlite
./scripts/verify-install.sh "$sqlite_target"
(
  cd "$sqlite_target"
  "$sqlite_tool" agent list > "$test_root/agents-after-repair.json"
)
python3 -c 'import json,sys; rows=json.load(open(sys.argv[1]))["data"]; assert [row["id"] for row in rows] == ["persistent"]' "$test_root/agents-after-repair.json"

# The project coordination README is managed content. A binary or otherwise
# stale pre-existing file is rejected by verification and repaired on
# same-backend reinstall.
cp "$sqlite_db" "$sqlite_target/.coordination/README.md"
expect_install_failure ./scripts/verify-install.sh "$sqlite_target"
./scripts/install.sh --target "$sqlite_target" --adapter sqlite
cmp -s scaffold/coordination-readme-sqlite.md \
  "$sqlite_target/.coordination/README.md"
./scripts/verify-install.sh "$sqlite_target"

# Byte-equal hard-link aliases are still an installation-integrity failure,
# because later writes through the outside name could alter imported code.
installed_core=$sqlite_target/.agents/agentic-project-scaffold-lite/lib/coordination/core.py
cp "$installed_core" "$test_root/outside-core.py"
rm "$installed_core"
ln "$test_root/outside-core.py" "$installed_core"
expect_install_failure ./scripts/verify-install.sh "$sqlite_target"
./scripts/install.sh --target "$sqlite_target" --adapter sqlite
./scripts/verify-install.sh "$sqlite_target"

# Verification covers every managed bundle file and the adapter-selected
# instruction block, rather than checking only marker presence.
cp LICENSE "$sqlite_target/.agents/agentic-project-scaffold-lite/docs/cli-contract.md"
expect_install_failure ./scripts/verify-install.sh "$sqlite_target"
./scripts/install.sh --target "$sqlite_target" --adapter sqlite
./scripts/verify-install.sh "$sqlite_target"
cmp -s docs/cli-contract.md \
  "$sqlite_target/.agents/agentic-project-scaffold-lite/docs/cli-contract.md"

cp scaffold/AGENTS.md "$sqlite_target/AGENTS.md"
expect_install_failure ./scripts/verify-install.sh "$sqlite_target"
./scripts/install.sh --target "$sqlite_target" --adapter sqlite
./scripts/verify-install.sh "$sqlite_target"
grep -Fq 'uses the SQLite backend' "$sqlite_target/AGENTS.md"

# Reinstall repairs an incomplete/commented managed ignore block atomically and
# preserves the mode of a pre-existing host file.
chmod 0640 "$sqlite_target/.gitignore"
python3 - "$sqlite_target/.gitignore" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
content = path.read_text(encoding="utf-8")
content = content.replace(
    "\n.coordination/backups/\n",
    "\n# .coordination/backups/\n",
)
path.write_text(content, encoding="utf-8")
PY
expect_install_failure ./scripts/verify-install.sh "$sqlite_target"
./scripts/install.sh --target "$sqlite_target" --adapter sqlite
./scripts/verify-install.sh "$sqlite_target"
python3 - "$sqlite_target/.gitignore" <<'PY'
from pathlib import Path
import stat
import sys

path = Path(sys.argv[1])
assert stat.S_IMODE(path.stat().st_mode) == 0o640
content = path.read_text(encoding="utf-8")
assert content.count("# agentic-project-scaffold-lite sqlite state\n") == 1
assert content.count("# /agentic-project-scaffold-lite sqlite state\n") == 1
assert "\n.coordination/backups/\n" in content
assert "\n# .coordination/backups/\n" not in content
PY

# Database configuration cannot select a managed metadata file or a hard-link
# alias of another live database.
printf '%s\n' \
  'version: 1' \
  'backend: sqlite' \
  'database: config.yml' > "$reserved_db_target/.coordination/config.yml"
expect_install_failure ./scripts/install.sh \
  --target "$reserved_db_target" --adapter sqlite
grep -Fq 'database: config.yml' \
  "$reserved_db_target/.coordination/config.yml"
test ! -e "$reserved_db_target/.agents"

printf '%s\n' \
  'version: 1' \
  'backend: sqlite' \
  'database: backups' > "$reserved_db_target/.coordination/config.yml"
expect_install_failure ./scripts/install.sh \
  --target "$reserved_db_target" --adapter sqlite
test ! -e "$reserved_db_target/.agents"
test ! -e "$reserved_db_target/.coordination/backups"

printf '%s\n' \
  'version: 1' \
  'backend: sqlite' \
  'database: README.md/team.db' > "$reserved_db_target/.coordination/config.yml"
expect_install_failure ./scripts/install.sh \
  --target "$reserved_db_target" --adapter sqlite
test ! -e "$reserved_db_target/.agents"
test ! -e "$reserved_db_target/.coordination/README.md"

printf '%s\n' \
  'version: 1' \
  'backend: sqlite' \
  'database: state.db' > "$hardlink_db_target/.coordination/config.yml"
ln "$sqlite_db" "$hardlink_db_target/.coordination/state.db"
expect_install_failure ./scripts/install.sh \
  --target "$hardlink_db_target" --adapter sqlite
rm "$hardlink_db_target/.coordination/state.db"
test ! -e "$hardlink_db_target/.agents"

# A successful command is not enough: verification runs doctor and rejects an
# unhealthy configured database.
./scripts/install.sh --target "$unhealthy_target" --adapter sqlite
python3 -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.execute("PRAGMA user_version = 2"); db.commit(); db.close()' \
  "$unhealthy_target/.coordination/coordination.sqlite3"
expect_install_failure ./scripts/verify-install.sh "$unhealthy_target"

# Failure between moving the prior bundle aside and publishing the staged
# bundle restores the original managed directory.
printf '%s\n' 'rollback sentinel' > "$markdown_target/.agents/agentic-project-scaffold-lite/rollback-sentinel"
fake_mv_bin=$test_root/fake-mv-bin
mkdir -p "$fake_mv_bin"
printf '%s\n' \
  '#!/bin/sh' \
  'last=' \
  'for argument in "$@"; do' \
  '  last=$argument' \
  'done' \
  'if [ "${last##*/}" = agentic-project-scaffold-lite ] && [ ! -e "$FAIL_ONCE_MARKER" ]; then' \
  '  : > "$FAIL_ONCE_MARKER"' \
  '  exit 1' \
  'fi' \
  'exec /bin/mv "$@"' > "$fake_mv_bin/mv"
chmod +x "$fake_mv_bin/mv"
expect_install_failure env \
  PATH="$fake_mv_bin:/usr/bin:/bin" \
  FAIL_ONCE_MARKER="$test_root/mv-failed-once" \
  ./scripts/install.sh --target "$markdown_target" --adapter markdown
grep -Fq 'rollback sentinel' "$markdown_target/.agents/agentic-project-scaffold-lite/rollback-sentinel"
test -z "$(find "$markdown_target/.agents" -maxdepth 1 \
  \( -name '.agentic-project-scaffold-lite.stage.*' -o \
     -name '.agentic-project-scaffold-lite.rollback.*' \) -print -quit)"

# Signal delivery immediately after either directory rename restores the old
# bundle. State intent is recorded before the move, so cleanup does not depend
# on a post-command flag assignment.
signal_mv_bin=$test_root/signal-mv-bin
mkdir "$signal_mv_bin"
printf '%s\n' \
  '#!/bin/sh' \
  'last=' \
  'for argument in "$@"; do last=$argument; done' \
  'case "$SIGNAL_MOVE_PHASE:$last" in' \
  '  old:*.rollback.*|publish:*/agentic-project-scaffold-lite)' \
  '    if [ ! -e "$SIGNAL_ONCE_MARKER" ]; then' \
  '      /bin/mv "$@"' \
  '      : > "$SIGNAL_ONCE_MARKER"' \
  '      kill -TERM "$PPID"' \
  '      exit 0' \
  '    fi' \
  '    ;;' \
  'esac' \
  'exec /bin/mv "$@"' > "$signal_mv_bin/mv"
chmod +x "$signal_mv_bin/mv"

for signal_phase in old publish; do
  expect_install_failure env \
    PATH="$signal_mv_bin:/usr/bin:/bin" \
    SIGNAL_MOVE_PHASE="$signal_phase" \
    SIGNAL_ONCE_MARKER="$test_root/signal-$signal_phase-once" \
    ./scripts/install.sh --target "$markdown_target" --adapter markdown
  grep -Fq 'rollback sentinel' \
    "$markdown_target/.agents/agentic-project-scaffold-lite/rollback-sentinel"
  test -z "$(find "$markdown_target/.agents" -maxdepth 1 \
    \( -name '.agentic-project-scaffold-lite.stage.*' -o \
       -name '.agentic-project-scaffold-lite.rollback.*' \) -print -quit)"
done

# Once post-publication checks have completed, a signal during disposal of the
# rollback copy preserves the verified new bundle and leaves no stale staging.
signal_rm_bin=$test_root/signal-rm-bin
mkdir "$signal_rm_bin"
printf '%s\n' \
  '#!/bin/sh' \
  'case "$*" in' \
  '  *".agentic-project-scaffold-lite.rollback."*)' \
  '    if [ ! -e "$SIGNAL_ONCE_MARKER" ]; then' \
  '      /bin/rm "$@"' \
  '      : > "$SIGNAL_ONCE_MARKER"' \
  '      kill -TERM "$PPID"' \
  '      exit 0' \
  '    fi' \
  '    ;;' \
  'esac' \
  'exec /bin/rm "$@"' > "$signal_rm_bin/rm"
chmod +x "$signal_rm_bin/rm"
expect_install_failure env \
  PATH="$signal_rm_bin:/usr/bin:/bin" \
  SIGNAL_ONCE_MARKER="$test_root/signal-rm-once" \
  ./scripts/install.sh --target "$markdown_target" --adapter markdown
./scripts/verify-install.sh "$markdown_target"
test ! -e "$markdown_target/.agents/agentic-project-scaffold-lite/rollback-sentinel"
test -z "$(find "$markdown_target/.agents" -maxdepth 1 \
  \( -name '.agentic-project-scaffold-lite.stage.*' -o \
     -name '.agentic-project-scaffold-lite.rollback.*' \) -print -quit)"

printf 'Installer tests passed.\n'
