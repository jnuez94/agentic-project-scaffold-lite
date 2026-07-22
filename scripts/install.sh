#!/bin/sh
set -eu

usage() {
  printf '%s\n' "Usage: scripts/install.sh [--target PATH] [--no-agents-file]"
}

target=.
write_agents=true

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target)
      [ "$#" -ge 2 ] || { usage >&2; exit 2; }
      target=$2
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

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)

[ -d "$target" ] || { printf 'Target directory does not exist: %s\n' "$target" >&2; exit 1; }
[ -f "$source_dir/SPEC.md" ] || { printf 'Installer must run from a complete scaffold checkout.\n' >&2; exit 1; }

bundle_dir=$target/.agents/agentic-project-scaffold-lite
coordination_dir=$target/.coordination

mkdir -p "$bundle_dir/docs/adapters" "$bundle_dir/checklists"
mkdir -p "$coordination_dir/agents" "$coordination_dir/tasks" "$coordination_dir/messages"
mkdir -p "$coordination_dir/reviews" "$coordination_dir/decisions" "$coordination_dir/artifacts"
mkdir -p "$coordination_dir/escalations" "$coordination_dir/indexes" "$coordination_dir/templates"

cp "$source_dir/SPEC.md" "$bundle_dir/SPEC.md"
cp "$source_dir/docs/decision-rights.md" "$bundle_dir/docs/decision-rights.md"
cp "$source_dir/docs/health-metrics.md" "$bundle_dir/docs/health-metrics.md"
cp "$source_dir/docs/adapters/markdown.md" "$bundle_dir/docs/adapters/markdown.md"
cp "$source_dir/docs/adapters/sqlite.md" "$bundle_dir/docs/adapters/sqlite.md"
cp "$source_dir/docs/adapters/issue_tracker.md" "$bundle_dir/docs/adapters/issue_tracker.md"
cp "$source_dir/checklists/startup_checklist.md" "$bundle_dir/checklists/startup_checklist.md"
cp "$source_dir/checklists/conformance_checklist.md" "$bundle_dir/checklists/conformance_checklist.md"
cp "$source_dir/checklists/release_readiness_checklist.md" "$bundle_dir/checklists/release_readiness_checklist.md"
cp "$source_dir"/templates/*.md "$coordination_dir/templates/"

if [ ! -f "$coordination_dir/README.md" ]; then
  cp "$source_dir/scaffold/coordination-readme.md" "$coordination_dir/README.md"
fi

agents_file=$target/AGENTS.md
marker='<!-- agentic-project-scaffold-lite -->'
if [ "$write_agents" = true ]; then
  if [ ! -f "$agents_file" ]; then
    cp "$source_dir/scaffold/AGENTS.md" "$agents_file"
  elif ! grep -Fq "$marker" "$agents_file"; then
    {
      printf '\n'
      sed '1d' "$source_dir/scaffold/AGENTS.md"
    } >> "$agents_file"
  fi
fi

printf 'Installed Agentic Project Scaffold Lite into %s\n' "$target"
printf 'Next: complete %s and create initial records in %s\n' \
  "$bundle_dir/checklists/startup_checklist.md" "$coordination_dir"
