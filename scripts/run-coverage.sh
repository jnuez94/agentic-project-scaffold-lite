#!/bin/sh
# Measure line and branch coverage across the unit tests and the qualification
# suites, including the CLI and MCP subprocesses those suites launch.
#
# The installed launcher re-executes itself under `python -I` and builds its own
# import path at runtime, so coverage cannot be started with `--source` from the
# parent process. Instead this script installs a temporary `.pth` file into the
# active environment's site-packages, which calls `coverage.process_startup()`
# in every interpreter started while COVERAGE_PROCESS_START is exported. The
# `.pth` is removed on exit, including on failure or interrupt.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
cd "$repo_root"

if ! python3 -c 'import coverage' 2>/dev/null; then
  printf '%s\n' "coverage is not installed. Run: python3 -m pip install '.[dev]'" >&2
  exit 1
fi
if ! python3 -c 'import pytest' 2>/dev/null; then
  printf '%s\n' "pytest is not installed. Run: python3 -m pip install '.[dev]'" >&2
  exit 1
fi

site_packages=$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
if [ ! -w "$site_packages" ]; then
  printf '%s\n' "Cannot write to $site_packages." >&2
  printf '%s\n' "Run coverage from a virtual environment you own." >&2
  exit 1
fi

startup_pth=$site_packages/zz-coordination-coverage-subprocess.pth

cleanup() {
  rm -f "$startup_pth"
}
trap cleanup EXIT HUP INT TERM

printf 'import coverage; coverage.process_startup()\n' > "$startup_pth"
COVERAGE_PROCESS_START=$repo_root/pyproject.toml
export COVERAGE_PROCESS_START

rm -f .coverage
rm -f .coverage.*

python3 -m coverage run -m pytest
sh tests/install.sh
sh tests/sqlite.sh
sh tests/cli-contract.sh
sh tests/sqlite-concurrency.sh
sh tests/sqlite-operations.sh

# Instrumenting every subprocess makes the two scale suites dominate the run.
# COVERAGE_QUICK=1 skips them for a fast local signal; the reported percentage
# is then a floor, not the full measurement.
if [ "${COVERAGE_QUICK:-0}" = "1" ]; then
  printf '%s\n' "COVERAGE_QUICK=1: skipping the stability and restore suites." >&2
else
  sh tests/sqlite-stability.sh
  sh tests/sqlite-restore-qualification.sh
fi

python3 tests/service-parity.py
python3 tests/connection_lifecycle.py
python3 tests/claim_ownership.py
python3 tests/task_inspect_bounds.py
python3 tests/trust_model.py
python3 tests/console_features.py
python3 tests/write_features.py
python3 tests/observability.py
python3 tests/record_integrity.py
python3 tests/causality.py
python3 tests/inbox.py

if python3 -c 'import mcp' 2>/dev/null; then
  python3 tests/mcp-security.py
  python3 tests/mcp-integration.py
else
  printf '%s\n' "Skipping MCP suites: the optional 'mcp' extra is not installed." >&2
fi

python3 -m coverage combine
python3 -m coverage report --precision=1
python3 -m coverage html --precision=1 >/dev/null

printf '\nHTML report: %s\n' "$repo_root/htmlcov/index.html"
