#!/bin/sh
set -eu

usage() {
  printf '%s\n' "Usage: tests/mcp-release-artifact.sh DIST_DIRECTORY"
}

[ "$#" -eq 1 ] || { usage >&2; exit 2; }
dist_dir=$1
repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/coordination-mcp-artifact.XXXXXX")

version=$(cat "$repo_root/VERSION")

# This suite installs the built wheel to prove the console script works from a
# real installation. Record whether the distribution was already present so the
# developer's environment is left exactly as it was found.
had_distribution=no
if python3 -m pip show agentic-project-scaffold-lite >/dev/null 2>&1; then
  had_distribution=yes
fi
installed_wheel=no

cleanup() {
  rm -rf "$test_dir"
  if [ "$installed_wheel" = yes ] && [ "$had_distribution" = no ]; then
    python3 -m pip uninstall --yes agentic-project-scaffold-lite >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT HUP INT TERM

sdist=$dist_dir/agentic_project_scaffold_lite-$version.tar.gz
wheel=$dist_dir/agentic_project_scaffold_lite-$version-py3-none-any.whl
[ -f "$sdist" ] && [ -f "$wheel" ] ||
  { printf '%s\n' "Expected $version sdist and wheel are missing from $dist_dir" >&2; exit 1; }

tar -xzf "$sdist" -C "$test_dir"
source_tree=$test_dir/agentic_project_scaffold_lite-$version
test "$(cat "$source_tree/VERSION")" = "$version"
test -f "$source_tree/coordination/service.py"
test -f "$source_tree/coordination/transports/mcp.py"
test -f "$source_tree/docs/mcp-contract.md"
test -f "$source_tree/docs/upgrade.md"
test -f "$source_tree/scripts/check-mcp-dependency.py"
test -f "$source_tree/scripts/coordination-mcp.py"

python3 -c \
  'import mcp; from importlib.metadata import version; assert version("mcp").split(".")[0] == "1"'
python3 -m pip install --no-deps --force-reinstall "$wheel" >/dev/null
installed_wheel=yes
command -v coordination-mcp >/dev/null

project=$test_dir/project
mkdir "$project"
"$source_tree/scripts/install.sh" \
    --target "$project" \
    --adapter sqlite \
    --with-mcp >/dev/null
"$source_tree/scripts/verify-install.sh" --with-mcp "$project" >/dev/null

mkdir -p "$project/nested/path"
(
  cd "$project/nested/path"
  coordination-mcp --help >/dev/null
)

python3 "$source_tree/tests/mcp-integration.py" >/dev/null

printf 'MCP built-artifact qualification passed.\n'
