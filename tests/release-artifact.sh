#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
test_dir=$(mktemp -d)

cleanup() {
  rm -rf "$test_dir"
}
trap cleanup EXIT HUP INT TERM

artifact=$test_dir/project-scaffold-lite.tar
source_tree=$test_dir/source
target="$test_dir/clean install/project"

git -C "$repo_root" archive --format=tar --output="$artifact" HEAD
mkdir "$source_tree"
tar -xf "$artifact" -C "$source_tree"
mkdir -p "$target"

test ! -e "$source_tree/.git"
test "$(cat "$source_tree/VERSION")" = 1.1.0

"$source_tree/scripts/install.sh" --target "$target" --adapter sqlite >/dev/null
"$source_tree/scripts/verify-install.sh" "$target" >/dev/null

tool=$target/.agents/agentic-project-scaffold-lite/bin/coordination
db=$target/.coordination/coordination.sqlite3

"$tool" version > "$test_dir/version.json"
mkdir -p "$target/nested/path"
(
  cd "$target/nested/path"
  "$tool" doctor > "$test_dir/doctor.json"
  "$tool" agent add --id packaged --name Packaged --role test >/dev/null
  "$tool" backup --output "$target/.coordination/backups/packaged.sqlite3" \
    > "$test_dir/backup.json"
)

python3 - "$test_dir/version.json" "$test_dir/doctor.json" \
  "$test_dir/backup.json" "$db" <<'PY'
import json
import sqlite3
import sys

version = json.load(open(sys.argv[1], encoding="utf-8"))
doctor = json.load(open(sys.argv[2], encoding="utf-8"))
backup = json.load(open(sys.argv[3], encoding="utf-8"))
assert version == {
    "ok": True,
    "data": {"cli_version": "1.1.0", "schema_version": 1},
}
assert doctor["data"]["healthy"] is True
assert backup["data"]["verified"] is True
connection = sqlite3.connect(sys.argv[4])
assert connection.execute(
    "SELECT COUNT(*) FROM agents WHERE id = 'packaged'"
).fetchone()[0] == 1
PY

cmp "$source_tree/sqlite/schema.sql" \
  "$target/.agents/agentic-project-scaffold-lite/sqlite/schema.sql"
cmp "$source_tree/scripts/coordination.py" \
  "$target/.agents/agentic-project-scaffold-lite/bin/coordination"
cmp "$source_tree/VERSION" \
  "$target/.agents/agentic-project-scaffold-lite/VERSION"

printf 'Release artifact clean-install tests passed.\n'
