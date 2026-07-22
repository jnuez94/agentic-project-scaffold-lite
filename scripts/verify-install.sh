#!/bin/sh
set -eu

target=.
require_agents=true
failed=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-agents-file)
      require_agents=false
      shift
      ;;
    -h|--help)
      printf '%s\n' "Usage: scripts/verify-install.sh [--no-agents-file] [PATH]"
      exit 0
      ;;
    *)
      target=$1
      shift
      ;;
  esac
done

require_file() {
  if [ ! -s "$target/$1" ]; then
    printf 'Missing or empty: %s\n' "$1" >&2
    failed=1
  fi
}

require_dir() {
  if [ ! -d "$target/$1" ]; then
    printf 'Missing directory: %s\n' "$1" >&2
    failed=1
  fi
}

if [ "$require_agents" = true ]; then
  require_file AGENTS.md
fi
require_file .agents/agentic-project-scaffold-lite/SPEC.md
require_file .agents/agentic-project-scaffold-lite/docs/decision-rights.md
require_file .agents/agentic-project-scaffold-lite/checklists/startup_checklist.md
require_file .coordination/README.md
require_file .coordination/templates/task.md
require_file .coordination/templates/review.md
require_file .coordination/templates/decision_record.md

for directory in agents tasks messages reviews decisions artifacts escalations indexes templates; do
  require_dir ".coordination/$directory"
done

if [ "$failed" -ne 0 ]; then
  exit 1
fi

printf 'Installation verified: %s\n' "$target"
