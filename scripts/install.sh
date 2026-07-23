#!/bin/sh
set -eu

usage() {
  printf '%s\n' "Usage: scripts/install.sh [--target PATH] [--adapter markdown|sqlite] [--no-agents-file]"
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

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)

[ -d "$target" ] || { printf 'Target directory does not exist: %s\n' "$target" >&2; exit 1; }
[ -f "$source_dir/SPEC.md" ] || { printf 'Installer must run from a complete scaffold checkout.\n' >&2; exit 1; }

bundle_dir=$target/.agents/agentic-project-scaffold-lite
coordination_dir=$target/.coordination
config_file=$coordination_dir/config.yml

if [ -f "$config_file" ] && ! grep -Eq "^backend:[[:space:]]*$adapter[[:space:]]*$" "$config_file"; then
  printf 'Existing coordination backend does not match requested adapter %s: %s\n' "$adapter" "$config_file" >&2
  printf 'Automatic backend switching is disabled; create a new installation instead.\n' >&2
  exit 1
fi

mkdir -p "$bundle_dir/docs/adapters" "$bundle_dir/checklists" "$coordination_dir"

cp "$source_dir/SPEC.md" "$bundle_dir/SPEC.md"
cp "$source_dir/VERSION" "$bundle_dir/VERSION"
cp "$source_dir/docs/decision-rights.md" "$bundle_dir/docs/decision-rights.md"
cp "$source_dir/docs/health-metrics.md" "$bundle_dir/docs/health-metrics.md"
cp "$source_dir/docs/adapters/markdown.md" "$bundle_dir/docs/adapters/markdown.md"
cp "$source_dir/docs/adapters/sqlite.md" "$bundle_dir/docs/adapters/sqlite.md"
cp "$source_dir/docs/adapters/issue_tracker.md" "$bundle_dir/docs/adapters/issue_tracker.md"
cp "$source_dir/checklists/startup_checklist.md" "$bundle_dir/checklists/startup_checklist.md"
cp "$source_dir/checklists/conformance_checklist.md" "$bundle_dir/checklists/conformance_checklist.md"
cp "$source_dir/checklists/release_readiness_checklist.md" "$bundle_dir/checklists/release_readiness_checklist.md"
agent_template=$source_dir/scaffold/AGENTS.md
if [ "$adapter" = markdown ]; then
  mkdir -p "$coordination_dir/agents" "$coordination_dir/tasks" "$coordination_dir/messages"
  mkdir -p "$coordination_dir/reviews" "$coordination_dir/decisions" "$coordination_dir/artifacts"
  mkdir -p "$coordination_dir/escalations" "$coordination_dir/indexes" "$coordination_dir/templates"
  cp "$source_dir"/templates/*.md "$coordination_dir/templates/"
  if [ ! -f "$coordination_dir/README.md" ]; then
    cp "$source_dir/scaffold/coordination-readme.md" "$coordination_dir/README.md"
  fi
  if [ ! -f "$config_file" ]; then
    cp "$source_dir/scaffold/coordination-config.yml" "$config_file"
  fi
else
  command -v python3 >/dev/null 2>&1 || { printf 'SQLite installation requires python3.\n' >&2; exit 1; }
  mkdir -p "$bundle_dir/bin" "$bundle_dir/lib/coordination/entities"
  mkdir -p "$bundle_dir/sqlite" "$coordination_dir/backups"
  cp "$source_dir/scripts/coordination.py" "$bundle_dir/bin/coordination"
  cp "$source_dir"/coordination/*.py "$bundle_dir/lib/coordination/"
  cp "$source_dir"/coordination/entities/*.py "$bundle_dir/lib/coordination/entities/"
  cp "$source_dir/sqlite/schema.sql" "$bundle_dir/sqlite/schema.sql"
  chmod +x "$bundle_dir/bin/coordination"
  if [ ! -f "$coordination_dir/README.md" ]; then
    cp "$source_dir/scaffold/coordination-readme-sqlite.md" "$coordination_dir/README.md"
  fi
  if [ ! -f "$config_file" ]; then
    cp "$source_dir/scaffold/coordination-config-sqlite.yml" "$config_file"
  fi
  "$bundle_dir/bin/coordination" --db "$coordination_dir/coordination.sqlite3" init >/dev/null
  agent_template=$source_dir/scaffold/AGENTS-sqlite.md

  gitignore_file=$target/.gitignore
  ignore_marker='# agentic-project-scaffold-lite sqlite state'
  if [ ! -f "$gitignore_file" ]; then
    printf '%s\n.coordination/*.sqlite3*\n.coordination/backups/\n' "$ignore_marker" > "$gitignore_file"
  elif ! grep -Fq "$ignore_marker" "$gitignore_file"; then
    printf '\n%s\n.coordination/*.sqlite3*\n.coordination/backups/\n' "$ignore_marker" >> "$gitignore_file"
  fi
fi

agents_file=$target/AGENTS.md
marker='<!-- agentic-project-scaffold-lite -->'
if [ "$write_agents" = true ]; then
  if [ ! -f "$agents_file" ]; then
    cp "$agent_template" "$agents_file"
  elif ! grep -Fq "$marker" "$agents_file"; then
    {
      printf '\n'
      sed '1d' "$agent_template"
    } >> "$agents_file"
  fi
fi

printf 'Installed Agentic Project Scaffold Lite into %s\n' "$target"
printf 'Coordination adapter: %s\n' "$adapter"
printf 'Next: complete %s and initialize project coordination in %s\n' \
  "$bundle_dir/checklists/startup_checklist.md" "$coordination_dir"
