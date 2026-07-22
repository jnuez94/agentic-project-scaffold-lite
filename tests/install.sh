#!/bin/sh
set -eu

test_dir=$(mktemp -d)
test_no_agents=$(mktemp -d)
test_clean=$(mktemp -d)

cleanup() {
  rm -rf "$test_dir" "$test_no_agents" "$test_clean"
}
trap cleanup EXIT HUP INT TERM

printf '# Existing project rules\n\nKeep this line.\n' > "$test_dir/AGENTS.md"

./scripts/install.sh --target "$test_dir"
./scripts/verify-install.sh "$test_dir"
./scripts/install.sh --target "$test_dir"

test "$(grep -c '<!-- agentic-project-scaffold-lite -->' "$test_dir/AGENTS.md")" -eq 1
test "$(grep -c 'Keep this line.' "$test_dir/AGENTS.md")" -eq 1

./scripts/install.sh --target "$test_no_agents" --no-agents-file
./scripts/verify-install.sh --no-agents-file "$test_no_agents"
test ! -e "$test_no_agents/AGENTS.md"

./scripts/install.sh --target "$test_clean"
./scripts/install.sh --target "$test_clean"
./scripts/verify-install.sh "$test_clean"
test "$(grep -c '<!-- agentic-project-scaffold-lite -->' "$test_clean/AGENTS.md")" -eq 1
grep -Fq 'Use `done` only when required review and evidence exist.' "$test_clean/AGENTS.md"
grep -Fq 'Evidence-Based Completion' "$test_clean/.agents/agentic-project-scaffold-lite/SPEC.md"

printf 'Installer tests passed.\n'
