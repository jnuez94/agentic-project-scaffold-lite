#!/bin/sh
set -eu

usage() {
  printf '%s\n' "Usage: scripts/install.sh [--target PATH] [--adapter markdown|sqlite] [--no-agents-file]"
}

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

ignore_install_signals() {
  trap '' HUP INT TERM
}

handle_install_signals() {
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
}

require_source_file() {
  source_path=$source_dir/$1
  if [ -L "$source_path" ] || [ ! -f "$source_path" ] || [ ! -s "$source_path" ]; then
    fail "Installer source is missing, empty, or a symbolic link: $1"
  fi
}

validate_directory_destination() {
  destination_path=$1
  destination_label=$2
  if [ -L "$destination_path" ]; then
    fail "$destination_label must not be a symbolic link: $destination_path"
  fi
  if [ -e "$destination_path" ] && [ ! -d "$destination_path" ]; then
    fail "$destination_label must be a directory: $destination_path"
  fi
}

validate_file_destination() {
  destination_path=$1
  destination_label=$2
  if [ -L "$destination_path" ]; then
    fail "$destination_label must not be a symbolic link: $destination_path"
  fi
  if [ -e "$destination_path" ] && [ ! -f "$destination_path" ]; then
    fail "$destination_label must be a regular file: $destination_path"
  fi
  if [ -f "$destination_path" ] &&
    [ -n "$(find "$destination_path" -links +1 -print 2>/dev/null)" ]; then
    fail "$destination_label must not have hard-link aliases: $destination_path"
  fi
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

atomic_copy() {
  copy_source=$1
  copy_destination=$2
  ignore_install_signals
  copy_temp=$(mktemp "$(dirname "$copy_destination")/.install.XXXXXX")
  handle_install_signals
  cp -p "$copy_source" "$copy_temp"
  mv "$copy_temp" "$copy_destination"
  copy_temp=
}

copy_if_absent() {
  if [ ! -f "$2" ]; then
    atomic_copy "$1" "$2"
  fi
}

target=.
adapter=markdown
write_agents=true

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target)
      [ "$#" -ge 2 ] || { usage >&2; exit 2; }
      target=$2
      shift 2
      ;;
    --adapter|--backend)
      [ "$#" -ge 2 ] || { usage >&2; exit 2; }
      adapter=$2
      shift 2
      ;;
    --no-agents-file)
      write_agents=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$adapter" in
  markdown|sqlite) ;;
  *)
    printf 'Unsupported adapter: %s. Available adapters: markdown, sqlite\n' "$adapter" >&2
    exit 2
    ;;
esac

# Python compatibility is a SQLite installation precondition, not a failure to
# discover after files have already been created in the target.
if [ "$adapter" = sqlite ]; then
  command -v python3 >/dev/null 2>&1 ||
    fail "SQLite installation requires Python 3.10 or newer."
  python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' ||
    fail "SQLite installation requires Python 3.10 or newer."
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
source_dir=$(CDPATH= cd -- "$script_dir/.." && pwd -P)

while [ "$target" != "/" ]; do
  case "$target" in
    */) target=${target%/} ;;
    */.) target=${target%/.} ;;
    *) break ;;
  esac
done
if [ -L "$target" ]; then
  fail "Target directory must not be a symbolic link: $target"
fi
[ -d "$target" ] || fail "Target directory does not exist or is not a directory: $target"
target=$(CDPATH= cd -- "$target" && pwd -P)
[ "$target" != "/" ] ||
  fail "Installation target must not be the filesystem root."

# Installing into the source checkout (or a parent that contains it) makes the
# source and destination roles ambiguous and can recursively copy managed
# output back into itself. Require two disjoint canonical directory trees.
if [ "$target" = "$source_dir" ]; then
  fail "Installation target must not overlap the scaffold source checkout: $target"
fi
case "$target" in
  "$source_dir"/*)
    fail "Installation target must not be inside the scaffold source checkout: $target"
    ;;
esac
case "$source_dir" in
  "$target"/*)
    fail "Scaffold source checkout must not be inside the installation target: $target"
    ;;
esac

# Validate the complete selected source before touching the target. A partial
# checkout must never replace a previously working managed bundle.
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
  checklists/release_readiness_checklist.md \
  scaffold/AGENTS.md \
  scaffold/AGENTS-sqlite.md \
  scaffold/coordination-config.yml \
  scaffold/coordination-config-sqlite.yml \
  scaffold/coordination-readme.md \
  scaffold/coordination-readme-sqlite.md
do
  require_source_file "$relative_path"
done

if [ "$adapter" = markdown ]; then
  for relative_path in \
    templates/agent_profile.md \
    templates/artifact_record.md \
    templates/decision_record.md \
    templates/dependency.md \
    templates/escalation.md \
    templates/message.md \
    templates/review.md \
    templates/task.md
  do
    require_source_file "$relative_path"
  done
else
  for relative_path in \
    scripts/coordination.py \
    sqlite/schema.sql \
    coordination/README.md \
    coordination/__init__.py \
    coordination/cli.py \
    coordination/core.py \
    coordination/errors.py \
    coordination/entities/__init__.py \
    coordination/entities/agents.py \
    coordination/entities/artifacts.py \
    coordination/entities/decisions.py \
    coordination/entities/dependencies.py \
    coordination/entities/diagnostics.py \
    coordination/entities/escalations.py \
    coordination/entities/evidence.py \
    coordination/entities/maintenance.py \
    coordination/entities/messages.py \
    coordination/entities/reports.py \
    coordination/entities/reviews.py \
    coordination/entities/sessions.py \
    coordination/entities/tasks.py
  do
    require_source_file "$relative_path"
  done
  if find "$source_dir/coordination" -type l -print -quit | grep -q .; then
    fail "The canonical coordination package must not contain symbolic links."
  fi
fi

if [ "$adapter" = markdown ]; then
  selected_agent_template=$source_dir/scaffold/AGENTS.md
else
  selected_agent_template=$source_dir/scaffold/AGENTS-sqlite.md
fi
managed_start='<!-- agentic-project-scaffold-lite:start -->'
managed_end='<!-- agentic-project-scaffold-lite:end -->'
[ "$(grep -Fxc "$managed_start" "$selected_agent_template")" -eq 1 ] &&
  [ "$(grep -Fxc "$managed_end" "$selected_agent_template")" -eq 1 ] &&
  awk -v start="$managed_start" -v finish="$managed_end" '
    $0 == start { start_line = NR }
    $0 == finish { finish_line = NR }
    END { exit !(start_line > 0 && finish_line > start_line) }
  ' "$selected_agent_template" ||
  fail "Selected AGENTS template does not contain one complete canonical managed block."

if [ "$adapter" = sqlite ]; then
  source_check_dir=$(mktemp -d "${TMPDIR:-/tmp}/coordination-source-check.XXXXXX")
  mkdir -p "$source_check_dir/.coordination"
  cp "$source_dir/scaffold/coordination-config-sqlite.yml" \
    "$source_check_dir/.coordination/config.yml"
  if ! (
    cd "$source_check_dir"
    "$source_dir/scripts/coordination.py" version >/dev/null
    "$source_dir/scripts/coordination.py" init >/dev/null
    "$source_dir/scripts/coordination.py" doctor >/dev/null
  ); then
    rm -rf "$source_check_dir"
    fail "Canonical SQLite launcher, package, or schema failed its preflight diagnostics."
  fi
  rm -rf "$source_check_dir"
fi

agents_root=$target/.agents
bundle_dir=$agents_root/agentic-project-scaffold-lite
install_lock=$agents_root/.agentic-project-scaffold-lite.install.lock
coordination_dir=$target/.coordination
config_file=$coordination_dir/config.yml
agents_file=$target/AGENTS.md
gitignore_file=$target/.gitignore

# Every path that will be written is checked before the first mkdir/cp/mv.
validate_directory_destination "$agents_root" "Managed bundle parent"
validate_directory_destination "$bundle_dir" "Managed bundle"
if [ -e "$install_lock" ] || [ -L "$install_lock" ]; then
  fail "Another installation is running or left a stale lock: $install_lock"
fi
validate_directory_destination "$coordination_dir" "Coordination state"
validate_file_destination "$config_file" "Coordination configuration"
validate_file_destination "$coordination_dir/README.md" "Coordination README"
if [ "$write_agents" = true ]; then
  validate_file_destination "$agents_file" "AGENTS.md"
fi
if [ "$adapter" = sqlite ]; then
  validate_directory_destination "$coordination_dir/backups" "Coordination backup directory"
  validate_file_destination "$gitignore_file" ".gitignore"
else
  for directory in agents tasks messages reviews decisions artifacts escalations indexes templates; do
    validate_directory_destination "$coordination_dir/$directory" "Markdown coordination directory"
  done
  for template in "$source_dir"/templates/*.md; do
    validate_file_destination "$coordination_dir/templates/$(basename "$template")" "Markdown template"
  done
fi

if [ -f "$config_file" ]; then
  if ! config_version=$(config_scalar "$config_file" version); then
    fail "Existing coordination configuration must contain exactly one non-empty version: $config_file"
  fi
  [ "$config_version" = 1 ] ||
    fail "Unsupported coordination configuration version $config_version: $config_file"
  if ! existing_backend=$(config_scalar "$config_file" backend); then
    fail "Existing coordination configuration must contain exactly one non-empty backend: $config_file"
  fi
  if [ "$existing_backend" != "$adapter" ]; then
    printf 'Existing coordination backend does not match requested adapter %s: %s\n' "$adapter" "$config_file" >&2
    printf 'Automatic backend switching is disabled; create a new installation instead.\n' >&2
    exit 1
  fi
  if [ "$adapter" = sqlite ] && ! python3 -I - \
    "$source_dir" "$config_file" <<'PY'
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])

from coordination.core import _project_database_from_config
from coordination.errors import CoordinationError

try:
    _project_database_from_config(Path(sys.argv[2]))
except CoordinationError as error:
    print(error.message, file=sys.stderr)
    raise SystemExit(error.exit_code)
PY
  then
    fail "Existing SQLite coordination configuration failed canonical validation: $config_file"
  fi
elif [ -d "$coordination_dir" ] &&
  [ -n "$(find "$coordination_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
  fail "Existing coordination state has no config.yml; refusing an ambiguous installation: $coordination_dir"
fi

database_path=
database_ignore_pattern=
if [ "$adapter" = sqlite ]; then
  if [ -f "$config_file" ]; then
    if ! configured_database=$(config_scalar "$config_file" database); then
      fail "SQLite configuration must contain exactly one non-empty database path: $config_file"
    fi
  else
    configured_database=coordination.sqlite3
  fi

  # The managed database must remain beneath .coordination, and neither it nor
  # an existing parent component may redirect writes through a symbolic link.
  if ! database_path=$(
    python3 - "$coordination_dir" "$configured_database" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
raw_value = sys.argv[2]
raw = Path(raw_value)

def reject(reason: str) -> None:
    print(f"Invalid configured database path {raw_value!r}: {reason}", file=sys.stderr)
    raise SystemExit(1)

if raw.is_absolute():
    reject("absolute paths are not allowed")
if not raw.parts or raw_value in {"", "."}:
    reject("a database filename is required")
if ".." in raw.parts:
    reject("parent-directory aliases are not allowed")
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
    exit 1
  fi
  database_relative=${database_path#"$target/"}
  database_ignore_pattern=$(
    python3 - "$database_relative" <<'PY'
import sys

value = "/" + sys.argv[1].replace("\\", "\\\\")
for character in ("*", "?", "[", "]"):
    value = value.replace(character, "\\" + character)
print(value + "*")
PY
  )
fi

stage_bundle=
rollback_bundle=$agents_root/.agentic-project-scaffold-lite.rollback.$$
package_manifest=
managed_block=
agents_temp=
copy_temp=
gitignore_temp=
had_old_bundle=false
publish_started=false
lock_acquired=false
install_complete=false

cleanup() {
  cleanup_status=$?
  trap - EXIT HUP INT TERM
  if [ "$install_complete" != true ]; then
    if [ "$had_old_bundle" = true ]; then
      if [ -d "$rollback_bundle" ] && [ ! -L "$rollback_bundle" ]; then
        if [ -e "$bundle_dir" ] && [ ! -L "$bundle_dir" ]; then
          rm -rf "$bundle_dir"
        fi
        mv "$rollback_bundle" "$bundle_dir"
      fi
    elif [ "$publish_started" = true ] &&
      [ -e "$bundle_dir" ] && [ ! -L "$bundle_dir" ]; then
      rm -rf "$bundle_dir"
    fi
  elif [ -d "$rollback_bundle" ] && [ ! -L "$rollback_bundle" ]; then
    rm -rf "$rollback_bundle"
  fi
  if [ -n "$stage_bundle" ] && [ -d "$stage_bundle" ] && [ ! -L "$stage_bundle" ]; then
    rm -rf "$stage_bundle"
  fi
  if [ -n "$package_manifest" ] && [ -f "$package_manifest" ] && [ ! -L "$package_manifest" ]; then
    rm -f "$package_manifest"
  fi
  if [ -n "$managed_block" ] && [ -f "$managed_block" ] && [ ! -L "$managed_block" ]; then
    rm -f "$managed_block"
  fi
  if [ -n "$agents_temp" ] && [ -f "$agents_temp" ] && [ ! -L "$agents_temp" ]; then
    rm -f "$agents_temp"
  fi
  if [ -n "$copy_temp" ] && [ -f "$copy_temp" ] && [ ! -L "$copy_temp" ]; then
    rm -f "$copy_temp"
  fi
  if [ -n "$gitignore_temp" ] && [ -f "$gitignore_temp" ] && [ ! -L "$gitignore_temp" ]; then
    rm -f "$gitignore_temp"
  fi
  if [ "$lock_acquired" = true ] && [ -d "$install_lock" ] && [ ! -L "$install_lock" ]; then
    rmdir "$install_lock" 2>/dev/null || true
  fi
  exit "$cleanup_status"
}
trap cleanup EXIT
handle_install_signals

mkdir -p "$agents_root" "$coordination_dir"
# Ignore handled signals across the external mkdir/built-in assignment pair so
# cleanup can never observe a lock we created before lock_acquired is true.
ignore_install_signals
if mkdir "$install_lock"; then
  lock_acquired=true
else
  handle_install_signals
  fail "Another installation acquired the managed-bundle lock: $install_lock"
fi
handle_install_signals
ignore_install_signals
stage_bundle=$(mktemp -d "$agents_root/.agentic-project-scaffold-lite.stage.XXXXXX")
handle_install_signals
mkdir -p "$stage_bundle/docs/adapters" "$stage_bundle/checklists"

cp "$source_dir/SPEC.md" "$stage_bundle/SPEC.md"
cp "$source_dir/VERSION" "$stage_bundle/VERSION"
cp "$source_dir/docs/decision-rights.md" "$stage_bundle/docs/decision-rights.md"
cp "$source_dir/docs/health-metrics.md" "$stage_bundle/docs/health-metrics.md"
cp "$source_dir/docs/cli-contract.md" "$stage_bundle/docs/cli-contract.md"
cp "$source_dir/docs/adapters/markdown.md" "$stage_bundle/docs/adapters/markdown.md"
cp "$source_dir/docs/adapters/sqlite.md" "$stage_bundle/docs/adapters/sqlite.md"
cp "$source_dir/docs/adapters/issue_tracker.md" "$stage_bundle/docs/adapters/issue_tracker.md"
cp "$source_dir/checklists/startup_checklist.md" "$stage_bundle/checklists/startup_checklist.md"
cp "$source_dir/checklists/conformance_checklist.md" "$stage_bundle/checklists/conformance_checklist.md"
cp "$source_dir/checklists/release_readiness_checklist.md" "$stage_bundle/checklists/release_readiness_checklist.md"

agent_template=$source_dir/scaffold/AGENTS.md
if [ "$adapter" = markdown ]; then
  mkdir -p "$coordination_dir/agents" "$coordination_dir/tasks" "$coordination_dir/messages"
  mkdir -p "$coordination_dir/reviews" "$coordination_dir/decisions" "$coordination_dir/artifacts"
  mkdir -p "$coordination_dir/escalations" "$coordination_dir/indexes" "$coordination_dir/templates"
  for template in "$source_dir"/templates/*.md; do
    atomic_copy "$template" "$coordination_dir/templates/$(basename "$template")"
  done
  atomic_copy "$source_dir/scaffold/coordination-readme.md" "$coordination_dir/README.md"
  copy_if_absent "$source_dir/scaffold/coordination-config.yml" "$config_file"
else
  mkdir -p "$stage_bundle/bin" "$stage_bundle/lib" "$stage_bundle/sqlite"
  cp "$source_dir/scripts/coordination.py" "$stage_bundle/bin/coordination"
  cp "$source_dir/sqlite/schema.sql" "$stage_bundle/sqlite/schema.sql"
  chmod +x "$stage_bundle/bin/coordination"

  ignore_install_signals
  package_manifest=$(mktemp "${TMPDIR:-/tmp}/coordination-package.XXXXXX")
  handle_install_signals
  (
    cd "$source_dir"
    find coordination -type f \
      ! -path '*/__pycache__/*' \
      ! -name '*.pyc' \
      ! -name '*.pyo' \
      -print | LC_ALL=C sort
  ) > "$package_manifest"
  [ -s "$package_manifest" ] || fail "The canonical coordination package is empty."
  while IFS= read -r relative_path; do
    mkdir -p "$stage_bundle/lib/$(dirname "$relative_path")"
    cp "$source_dir/$relative_path" "$stage_bundle/lib/$relative_path"
    cmp -s "$source_dir/$relative_path" "$stage_bundle/lib/$relative_path" ||
      fail "Staged coordination package differs from its canonical source: $relative_path"
  done < "$package_manifest"
  cmp -s "$source_dir/scripts/coordination.py" "$stage_bundle/bin/coordination" ||
    fail "Staged coordination launcher differs from its canonical source."
  cmp -s "$source_dir/sqlite/schema.sql" "$stage_bundle/sqlite/schema.sql" ||
    fail "Staged SQLite schema differs from its canonical source."
  cmp -s "$source_dir/VERSION" "$stage_bundle/VERSION" ||
    fail "Staged VERSION differs from its canonical source."
  "$stage_bundle/bin/coordination" version >/dev/null

  mkdir -p "$coordination_dir/backups"
  atomic_copy "$source_dir/scaffold/coordination-readme-sqlite.md" "$coordination_dir/README.md"
  copy_if_absent "$source_dir/scaffold/coordination-config-sqlite.yml" "$config_file"

  # Deliberately omit --db: installation and normal use must discover exactly
  # the database named by the target project's config.yml.
  (
    cd "$target"
    "$stage_bundle/bin/coordination" init >/dev/null
    "$stage_bundle/bin/coordination" doctor >/dev/null
  )
  agent_template=$selected_agent_template

  ignore_marker='# agentic-project-scaffold-lite sqlite state'
  ignore_end_marker='# /agentic-project-scaffold-lite sqlite state'
  ignore_install_signals
  gitignore_temp=$(mktemp "$target/.gitignore.install.XXXXXX")
  handle_install_signals
  if [ -f "$gitignore_file" ]; then
    cp -p "$gitignore_file" "$gitignore_temp"
    if awk -v start="$ignore_marker" -v finish="$ignore_end_marker" '
      $0 == start { in_block = 1 }
      in_block && $0 == finish { found = 1; exit }
      END { exit !found }
    ' "$gitignore_file"; then
      awk -v start="$ignore_marker" -v finish="$ignore_end_marker" '
        $0 == start { skipping = 1; next }
        skipping && $0 == finish { skipping = 0; next }
        !skipping && $0 != finish { print }
      ' "$gitignore_file" > "$gitignore_temp"
    else
      awk \
        -v start="$ignore_marker" \
        -v finish="$ignore_end_marker" \
        -v database="$database_ignore_pattern" '
        function uncommented(line) {
          sub(/^#[[:space:]]*/, "", line)
          return line
        }
        {
          normalized = uncommented($0)
          if ($0 == start || $0 == finish ||
              normalized == database ||
              normalized == ".coordination/*.sqlite3*" ||
              normalized == ".coordination/**/*.sqlite3*" ||
              normalized == ".coordination/backups/") {
            next
          }
          print
        }
      ' "$gitignore_file" > "$gitignore_temp"
    fi
  else
    : > "$gitignore_temp"
    chmod 0644 "$gitignore_temp"
  fi
  if [ -s "$gitignore_temp" ]; then
    printf '\n' >> "$gitignore_temp"
  fi
  printf '%s\n%s\n.coordination/*.sqlite3*\n.coordination/**/*.sqlite3*\n.coordination/backups/\n%s\n' \
    "$ignore_marker" "$database_ignore_pattern" "$ignore_end_marker" >> "$gitignore_temp"
  mv "$gitignore_temp" "$gitignore_file"
  gitignore_temp=
fi

# Publish the complete managed bundle as one directory rename. Preserve the
# previous bundle until all post-publication checks and instruction updates
# succeed so any failure can restore the known prior installation.
[ ! -e "$rollback_bundle" ] && [ ! -L "$rollback_bundle" ] ||
  fail "Rollback staging path already exists: $rollback_bundle"
if [ -d "$bundle_dir" ]; then
  had_old_bundle=true
  mv "$bundle_dir" "$rollback_bundle"
fi
[ ! -e "$bundle_dir" ] && [ ! -L "$bundle_dir" ] ||
  fail "Managed bundle destination changed during installation: $bundle_dir"
publish_started=true
mv "$stage_bundle" "$bundle_dir"
stage_bundle=

if [ "$adapter" = sqlite ]; then
  (
    cd "$target"
    "$bundle_dir/bin/coordination" version >/dev/null
    "$bundle_dir/bin/coordination" doctor >/dev/null
  )
fi

if [ "$write_agents" = true ]; then
  legacy_marker='<!-- agentic-project-scaffold-lite -->'

  ignore_install_signals
  managed_block=$(mktemp "${TMPDIR:-/tmp}/coordination-agents-block.XXXXXX")
  handle_install_signals
  sed -n "/^$managed_start\$/,/^$managed_end\$/p" "$agent_template" > "$managed_block"

  if [ ! -f "$agents_file" ]; then
    cp "$agent_template" "$agents_file"
  else
    ignore_install_signals
    agents_temp=$(mktemp "$target/.AGENTS.md.install.XXXXXX")
    handle_install_signals
    cp -p "$agents_file" "$agents_temp"
    awk \
      -v start="$managed_start" \
      -v finish="$managed_end" \
      -v legacy="$legacy_marker" \
      -v block="$managed_block" '
      function write_block(line) {
        while ((getline line < block) > 0) {
          print line
        }
        close(block)
      }
      {
        if (!skipping && ($0 == start || $0 == legacy)) {
          if (!inserted) {
            write_block()
            inserted = 1
          }
          skipping = 1
          next
        }
        if (skipping) {
          if ($0 == finish) {
            skipping = 0
          }
          next
        }
        if ($0 == finish) {
          next
        }
        print
      }
      END {
        if (!inserted) {
          if (NR > 0) {
            print ""
          }
          write_block()
        }
      }
    ' "$agents_file" > "$agents_temp"
    mv "$agents_temp" "$agents_file"
    agents_temp=
  fi

  [ "$(grep -Fxc "$managed_start" "$agents_file")" -eq 1 ] &&
    [ "$(grep -Fxc "$managed_end" "$agents_file")" -eq 1 ] &&
    ! grep -Fqx "$legacy_marker" "$agents_file" ||
    fail "Failed to publish the canonical AGENTS.md managed block."
fi

install_complete=true
if [ "$had_old_bundle" = true ]; then
  rm -rf "$rollback_bundle"
fi

printf 'Installed Agentic Project Scaffold Lite into %s\n' "$target"
printf 'Coordination adapter: %s\n' "$adapter"
printf 'Next: complete %s and initialize project coordination in %s\n' \
  "$bundle_dir/checklists/startup_checklist.md" "$coordination_dir"
