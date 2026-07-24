#!/bin/sh
set -eu

usage() {
  printf '%s\n' "Usage: scripts/verify-install.sh [--no-agents-file] [PATH]"
}

config_scalar() {
  awk -v requested_key="$2" '
    {
      line = $0
      sub(/^[[:space:]]+/, "", line)
      sub(/[[:space:]]+$/, "", line)
    }
    index(line, requested_key ":") == 1 {
      count += 1
      value = substr(line, length(requested_key) + 2)
      sub(/^[[:space:]]+/, "", value)
      sub(/[[:space:]]+$/, "", value)
    }
    END {
      if (count != 1 || value == "") {
        exit 1
      }
      print value
    }
  ' "$1"
}

target=.
target_seen=false
require_agents=true
failed=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-agents-file)
      require_agents=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [ "$target_seen" = true ]; then
        printf 'Only one installation path may be verified.\n' >&2
        usage >&2
        exit 2
      fi
      target=$1
      target_seen=true
      shift
      ;;
  esac
done

while [ "$target" != "/" ]; do
  case "$target" in
    */) target=${target%/} ;;
    */.) target=${target%/.} ;;
    *) break ;;
  esac
done
if [ -L "$target" ] || [ ! -d "$target" ]; then
  printf 'Installation target must be a real directory, not a symbolic link: %s\n' "$target" >&2
  exit 1
fi
target=$(CDPATH= cd -- "$target" && pwd -P)

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
source_dir=$(CDPATH= cd -- "$script_dir/.." && pwd -P)
bundle_dir=$target/.agents/agentic-project-scaffold-lite
config_file=$target/.coordination/config.yml

require_file() {
  relative_path=$1
  candidate=$target/$relative_path
  if [ -L "$candidate" ] || [ ! -s "$candidate" ] || [ ! -f "$candidate" ]; then
    printf 'Missing, empty, non-regular, or symbolic-link file: %s\n' "$relative_path" >&2
    failed=1
  elif [ -n "$(find "$candidate" -links +1 -print 2>/dev/null)" ]; then
    printf 'Hard-linked installation file is not supported: %s\n' "$relative_path" >&2
    failed=1
  fi
}

require_dir() {
  relative_path=$1
  candidate=$target/$relative_path
  if [ -L "$candidate" ] || [ ! -d "$candidate" ]; then
    printf 'Missing, non-directory, or symbolic-link directory: %s\n' "$relative_path" >&2
    failed=1
  fi
}

compare_canonical_file() {
  canonical_path=$1
  installed_path=$2
  description=$3
  if [ -L "$canonical_path" ] || [ ! -f "$canonical_path" ] || [ ! -s "$canonical_path" ]; then
    printf 'Canonical source is missing, empty, or a symbolic link: %s\n' "$canonical_path" >&2
    failed=1
  elif [ -L "$installed_path" ] || [ ! -f "$installed_path" ] ||
    ! cmp -s "$canonical_path" "$installed_path"; then
    printf 'Installed %s differs from the canonical source: %s\n' "$description" "$installed_path" >&2
    failed=1
  fi
}

if [ "$require_agents" = true ]; then
  require_file AGENTS.md
  if [ -f "$target/AGENTS.md" ] && [ ! -L "$target/AGENTS.md" ]; then
    start_marker='<!-- agentic-project-scaffold-lite:start -->'
    end_marker='<!-- agentic-project-scaffold-lite:end -->'
    if [ "$(grep -Fxc "$start_marker" "$target/AGENTS.md" || true)" -ne 1 ] ||
      [ "$(grep -Fxc "$end_marker" "$target/AGENTS.md" || true)" -ne 1 ] ||
      grep -Fqx '<!-- agentic-project-scaffold-lite -->' "$target/AGENTS.md"; then
      printf 'AGENTS.md does not contain one complete canonical managed block.\n' >&2
      failed=1
    fi
  fi
fi

require_dir .agents
require_dir .agents/agentic-project-scaffold-lite
require_dir .coordination
require_file .agents/agentic-project-scaffold-lite/SPEC.md
require_file .agents/agentic-project-scaffold-lite/VERSION
require_file .agents/agentic-project-scaffold-lite/docs/decision-rights.md
require_file .agents/agentic-project-scaffold-lite/docs/health-metrics.md
require_file .agents/agentic-project-scaffold-lite/docs/cli-contract.md
require_file .agents/agentic-project-scaffold-lite/checklists/startup_checklist.md
require_file .agents/agentic-project-scaffold-lite/checklists/conformance_checklist.md
require_file .agents/agentic-project-scaffold-lite/checklists/release_readiness_checklist.md
require_file .coordination/README.md
require_file .coordination/config.yml

backend=
config_version=
if [ -f "$config_file" ] && [ ! -L "$config_file" ]; then
  if ! config_version=$(config_scalar "$config_file" version); then
    printf 'Coordination configuration must contain exactly one non-empty version.\n' >&2
    failed=1
  elif [ "$config_version" != 1 ]; then
    printf 'Unsupported coordination configuration version: %s\n' "$config_version" >&2
    failed=1
  fi
  if ! backend=$(config_scalar "$config_file" backend); then
    printf 'Coordination configuration must contain exactly one non-empty backend.\n' >&2
    failed=1
  fi
fi

verify_temp=$(mktemp -d "${TMPDIR:-/tmp}/coordination-verify.XXXXXX")
trap 'rm -rf "$verify_temp"' EXIT HUP INT TERM
expected_bundle_manifest=$verify_temp/expected-bundle.txt
installed_bundle_manifest=$verify_temp/installed-bundle.txt
: > "$expected_bundle_manifest"

for relative_path in \
  SPEC.md \
  VERSION \
  docs/decision-rights.md \
  docs/health-metrics.md \
  docs/cli-contract.md \
  docs/adapters/markdown.md \
  docs/adapters/sqlite.md \
  docs/adapters/issue_tracker.md \
  checklists/startup_checklist.md \
  checklists/conformance_checklist.md \
  checklists/release_readiness_checklist.md
do
  printf '%s\n' "$relative_path" >> "$expected_bundle_manifest"
  compare_canonical_file \
    "$source_dir/$relative_path" \
    "$bundle_dir/$relative_path" \
    "managed bundle file $relative_path"
done

case "$backend" in
  sqlite)
    printf '%s\n' bin/coordination sqlite/schema.sql >> "$expected_bundle_manifest"
    (
      cd "$source_dir"
      find coordination -type f \
        ! -path '*/__pycache__/*' \
        ! -name '*.pyc' \
        ! -name '*.pyo' \
        -print | sed 's|^|lib/|'
    ) >> "$expected_bundle_manifest"
    ;;
  markdown) ;;
esac
LC_ALL=C sort -o "$expected_bundle_manifest" "$expected_bundle_manifest"
if [ -d "$bundle_dir" ] && [ ! -L "$bundle_dir" ]; then
  (
    cd "$bundle_dir"
    find . -type f -print | sed 's|^\./||' | LC_ALL=C sort
  ) > "$installed_bundle_manifest"
  if ! cmp -s "$expected_bundle_manifest" "$installed_bundle_manifest"; then
    printf 'Installed managed-bundle file set differs from the selected canonical bundle.\n' >&2
    failed=1
  fi
  if find "$bundle_dir" -type l -print -quit | grep -q .; then
    printf 'Installed managed bundle must not contain symbolic links.\n' >&2
    failed=1
  fi
  if find "$bundle_dir" ! -type d ! -type f -print -quit | grep -q .; then
    printf 'Installed managed bundle must contain only directories and regular files.\n' >&2
    failed=1
  fi
  if find "$bundle_dir" -type f -links +1 -print -quit | grep -q .; then
    printf 'Installed managed bundle files must not have hard-link aliases.\n' >&2
    failed=1
  fi
fi

if [ "$require_agents" = true ] &&
  [ -f "$target/AGENTS.md" ] && [ ! -L "$target/AGENTS.md" ]; then
  case "$backend" in
    sqlite) canonical_agents=$source_dir/scaffold/AGENTS-sqlite.md ;;
    markdown) canonical_agents=$source_dir/scaffold/AGENTS.md ;;
    *) canonical_agents= ;;
  esac
  if [ -n "$canonical_agents" ]; then
    canonical_agents_block=$verify_temp/canonical-agents-block.md
    installed_agents_block=$verify_temp/installed-agents-block.md
    sed -n "/^$start_marker\$/,/^$end_marker\$/p" \
      "$canonical_agents" > "$canonical_agents_block"
    sed -n "/^$start_marker\$/,/^$end_marker\$/p" \
      "$target/AGENTS.md" > "$installed_agents_block"
    if ! cmp -s "$canonical_agents_block" "$installed_agents_block"; then
      printf 'AGENTS.md managed block differs from the selected canonical adapter instructions.\n' >&2
      failed=1
    fi
  fi
fi

case "$backend" in
  markdown)
    compare_canonical_file \
      "$source_dir/scaffold/coordination-readme.md" \
      "$target/.coordination/README.md" \
      "coordination README"
    require_file .coordination/templates/task.md
    require_file .coordination/templates/review.md
    require_file .coordination/templates/decision_record.md
    require_file .coordination/templates/dependency.md
    for directory in agents tasks messages reviews decisions artifacts escalations indexes templates; do
      require_dir ".coordination/$directory"
    done
    ;;
  sqlite)
    compare_canonical_file \
      "$source_dir/scaffold/coordination-readme-sqlite.md" \
      "$target/.coordination/README.md" \
      "coordination README"
    sqlite_ready=true
    if ! command -v python3 >/dev/null 2>&1 ||
      ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
      printf 'SQLite verification requires Python 3.10 or newer.\n' >&2
      failed=1
      sqlite_ready=false
    fi

    require_dir .coordination/backups
    require_file .gitignore
    require_file .agents/agentic-project-scaffold-lite/bin/coordination
    require_dir .agents/agentic-project-scaffold-lite/lib
    require_dir .agents/agentic-project-scaffold-lite/lib/coordination
    require_file .agents/agentic-project-scaffold-lite/lib/coordination/README.md
    require_file .agents/agentic-project-scaffold-lite/lib/coordination/cli.py
    require_file .agents/agentic-project-scaffold-lite/lib/coordination/entities/tasks.py
    require_file .agents/agentic-project-scaffold-lite/lib/coordination/entities/sessions.py
    require_file .agents/agentic-project-scaffold-lite/lib/coordination/entities/diagnostics.py
    require_file .agents/agentic-project-scaffold-lite/lib/coordination/entities/maintenance.py
    require_file .agents/agentic-project-scaffold-lite/sqlite/schema.sql

    tool=$bundle_dir/bin/coordination
    if [ ! -x "$tool" ]; then
      printf 'Coordination CLI is not executable.\n' >&2
      failed=1
      sqlite_ready=false
    fi

    configured_database=
    if ! configured_database=$(config_scalar "$config_file" database); then
      printf 'SQLite configuration must contain exactly one non-empty database path.\n' >&2
      failed=1
      sqlite_ready=false
    fi

    database_path=
    if [ "$sqlite_ready" = true ]; then
      if ! database_path=$(
        python3 - "$target/.coordination" "$configured_database" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
raw_value = sys.argv[2]
raw = Path(raw_value)

def reject(reason: str) -> None:
    print(f"Invalid configured database path {raw_value!r}: {reason}", file=sys.stderr)
    raise SystemExit(1)

if raw.is_absolute() or not raw.parts or raw_value in {"", "."} or ".." in raw.parts:
    reject("the database must be a contained relative file")
if any(part.casefold() == ".coordination" for part in raw.parts):
    reject("nested .coordination path components are not allowed")
if raw.parts and raw.parts[0].casefold() in {"config.yml", "readme.md", "backups"}:
    reject("the database path conflicts with managed coordination state")
candidate = root.joinpath(*raw.parts)
resolved = candidate.resolve()
try:
    resolved.relative_to(root)
except ValueError:
    reject("the database must remain inside .coordination")
if resolved == root:
    reject("the database path resolves to the coordination directory")

probe = root
for index, part in enumerate(raw.parts):
    if part in {"", "."}:
        continue
    probe = probe / part
    if probe.is_symlink():
        reject(f"symbolic links are not allowed ({probe})")
    if probe.exists():
        is_last = index == len(raw.parts) - 1
        if is_last and not probe.is_file():
            reject(f"database destination is not a regular file ({probe})")
        if not is_last and not probe.is_dir():
            reject(f"database parent is not a directory ({probe})")

for suffix in ("-wal", "-shm", "-journal"):
    sidecar = Path(f"{candidate}{suffix}")
    if sidecar.is_symlink():
        reject(f"symbolic-link sidecars are not allowed ({sidecar})")
    if sidecar.exists() and not sidecar.is_file():
        reject(f"database sidecar is not a regular file ({sidecar})")
    if sidecar.is_file():
        if not candidate.is_file():
            reject(f"stale sidecar exists for an absent database ({sidecar})")
        if sidecar.stat().st_nlink != 1:
            reject(f"hard-linked sidecars are not supported ({sidecar})")

lock = Path(f"{candidate}.lock")
if lock.is_symlink() or (lock.exists() and not lock.is_file()):
    reject(f"database lock must be a regular file ({lock})")
if lock.is_file() and lock.stat().st_nlink != 1:
    reject(f"hard-linked database locks are not supported ({lock})")

for reserved_name in ("config.yml", "README.md"):
    reserved = root / reserved_name
    if resolved == reserved.resolve():
        reject(f"the database must not alias {reserved_name}")
    if candidate.exists() and reserved.exists() and candidate.samefile(reserved):
        reject(f"the database must not hard-link {reserved_name}")
if candidate.is_file() and candidate.stat().st_nlink != 1:
    reject("hard-linked databases are not supported")
print(candidate)
PY
      ); then
        failed=1
        sqlite_ready=false
      fi
    fi
    if [ -n "$database_path" ]; then
      database_relative=${database_path#"$target/"}
      require_file "$database_relative"
      database_ignore_pattern=$(
        python3 - "$database_relative" <<'PY'
import sys

value = "/" + sys.argv[1].replace("\\", "\\\\")
for character in ("*", "?", "[", "]"):
    value = value.replace(character, "\\" + character)
print(value + "*")
PY
      )
      ignore_marker='# agentic-project-scaffold-lite sqlite state'
      ignore_end_marker='# /agentic-project-scaffold-lite sqlite state'
      expected_ignore_block=$verify_temp/expected-gitignore-block
      installed_ignore_block=$verify_temp/installed-gitignore-block
      printf '%s\n%s\n.coordination/*.sqlite3*\n.coordination/**/*.sqlite3*\n.coordination/backups/\n%s\n' \
        "$ignore_marker" "$database_ignore_pattern" "$ignore_end_marker" \
        > "$expected_ignore_block"
      awk -v start="$ignore_marker" -v finish="$ignore_end_marker" '
        $0 == start { copying = 1 }
        copying { print }
        $0 == finish { copying = 0 }
      ' "$target/.gitignore" > "$installed_ignore_block"
      if [ "$(grep -Fxc "$ignore_marker" "$target/.gitignore" || true)" -ne 1 ] ||
        [ "$(grep -Fxc "$ignore_end_marker" "$target/.gitignore" || true)" -ne 1 ] ||
        ! cmp -s "$expected_ignore_block" "$installed_ignore_block"; then
        printf 'The managed SQLite .gitignore block is incomplete or noncanonical.\n' >&2
        failed=1
        sqlite_ready=false
      fi
    fi

    temp_dir=$verify_temp/sqlite
    mkdir "$temp_dir"
    source_manifest=$temp_dir/source-package.txt
    installed_manifest=$temp_dir/installed-package.txt

    if find "$source_dir/coordination" -type l -print -quit | grep -q .; then
      printf 'Canonical coordination source contains a symbolic link.\n' >&2
      failed=1
      sqlite_ready=false
    fi
    if find "$bundle_dir/lib/coordination" -type l -print -quit | grep -q .; then
      printf 'Installed coordination package contains a symbolic link.\n' >&2
      failed=1
      sqlite_ready=false
    fi
    (
      cd "$source_dir"
      find coordination -type f \
        ! -path '*/__pycache__/*' \
        ! -name '*.pyc' \
        ! -name '*.pyo' \
        -print | LC_ALL=C sort
    ) > "$source_manifest"
    (
      cd "$bundle_dir/lib"
      find coordination -type f -print | LC_ALL=C sort
    ) > "$installed_manifest"
    if ! cmp -s "$source_manifest" "$installed_manifest"; then
      printf 'Installed coordination package file set differs from the canonical source.\n' >&2
      failed=1
      sqlite_ready=false
    else
      while IFS= read -r relative_path; do
        if ! cmp -s "$source_dir/$relative_path" "$bundle_dir/lib/$relative_path"; then
          printf 'Installed coordination package file differs from canonical source: %s\n' "$relative_path" >&2
          failed=1
          sqlite_ready=false
        fi
      done < "$source_manifest"
    fi
    compare_canonical_file "$source_dir/scripts/coordination.py" "$tool" "coordination launcher"
    compare_canonical_file "$source_dir/sqlite/schema.sql" "$bundle_dir/sqlite/schema.sql" "SQLite schema"
    compare_canonical_file "$source_dir/VERSION" "$bundle_dir/VERSION" "VERSION"

    if [ "$failed" -ne 0 ]; then
      sqlite_ready=false
    fi

    if [ "$sqlite_ready" = true ]; then
      version_json=$temp_dir/version.json
      doctor_json=$temp_dir/doctor.json
      # Deliberately omit --db so both diagnostics exercise cwd-based config
      # discovery exactly as project users do.
      if ! (
        cd "$target"
        "$tool" version > "$version_json"
      ); then
        printf 'Coordination CLI version diagnostic failed.\n' >&2
        failed=1
        sqlite_ready=false
      fi
      if ! (
        cd "$target"
        "$tool" doctor > "$doctor_json"
      ); then
        printf 'Coordination CLI doctor diagnostic failed.\n' >&2
        failed=1
        sqlite_ready=false
      fi
      if [ "$sqlite_ready" = true ] && ! python3 - \
        "$version_json" "$doctor_json" "$bundle_dir/VERSION" "$database_path" <<'PY'
import json
from pathlib import Path
import sys

version_result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
doctor_result = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
expected_version = Path(sys.argv[3]).read_text(encoding="utf-8").strip()
expected_database = Path(sys.argv[4]).resolve()

if version_result != {
    "ok": True,
    "data": {"cli_version": expected_version, "schema_version": 1},
}:
    raise SystemExit("version returned an unexpected result")
if doctor_result.get("ok") is not True:
    raise SystemExit("doctor did not return a successful result")
doctor = doctor_result.get("data", {})
if doctor.get("healthy") is not True:
    raise SystemExit("doctor reported an unhealthy installation")
if doctor.get("cli_version") != expected_version:
    raise SystemExit("doctor and installed VERSION disagree")
if doctor.get("schema_version") != 1 or doctor.get("metadata_schema_version") != 1:
    raise SystemExit("doctor reported an unsupported schema")
if Path(doctor.get("database", "")).resolve() != expected_database:
    raise SystemExit("doctor inspected a database other than config.yml selects")
PY
      then
        printf 'Coordination CLI diagnostics did not verify a healthy configured installation.\n' >&2
        failed=1
      fi
    fi

    ;;
  *)
    printf 'Unknown or missing coordination backend: %s\n' "$backend" >&2
    failed=1
    ;;
esac

rm -rf "$verify_temp"
trap - EXIT HUP INT TERM

if [ "$failed" -ne 0 ]; then
  exit 1
fi

printf 'Installation verified: %s (%s)\n' "$target" "$backend"
