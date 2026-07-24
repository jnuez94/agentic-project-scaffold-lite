# Releasing

This runbook qualifies and prepares Agentic Project Scaffold Lite releases.
Version 1.1.0 is the first stable release of the harness-neutral SQLite
coordination CLI.

## Preconditions

- Work from the intended release branch in a clean, complete checkout.
- Use Python 3.10 or newer.
- Resolve the release version and date before changing metadata.
- Keep the SQLite implementation only under repository root `coordination/`;
  the installer copies it into projects.
- Preserve one source of truth per installed project.
- Do not include secrets or private coordination state in fixtures, logs, or
  release artifacts.

For the 1.1.0 pull request, maintain exactly one commit. Amend it after every
update:

```sh
git add <reviewed-paths>
git commit --amend --no-edit
```

Do not push or change remote pull-request state without explicit approval.

## 1. Freeze The Contract

Review these files together:

- `VERSION`
- `CHANGELOG.md`
- `docs/cli-contract.md`
- `sqlite/schema.sql`
- `coordination/cli.py`
- `coordination/core.py`
- `coordination/entities/`

Confirm that command syntax, defaults, JSON results, errors, exit codes,
ordering, pagination, actor/session attribution, schema identity, and
operational behavior agree. `--help` output is supporting evidence, not a
substitute for the machine contract.

Schema version 1 is the first supported SQLite schema. Do not add or describe a
migration from pre-release databases.

## 2. Qualify The Repository

Run the complete suite:

```sh
make test
make validate-skill
python3 scripts/check-markdown-links.py
```

Record the output and map each
[release-readiness item](checklists/release_readiness_checklist.md) to a
specific test, command, or reviewed file. Pay particular attention to
multi-process races and failure-injection checks; one happy-path lifecycle is
not sufficient.

## 3. Verify A Clean SQLite Installation

Use a new temporary directory and remove it after recording sanitized evidence:

```sh
release_target=$(mktemp -d)
./scripts/install.sh --target "$release_target" --adapter sqlite
./scripts/verify-install.sh "$release_target"

release_tool="$release_target/.agents/agentic-project-scaffold-lite/bin/coordination"
"$release_tool" version
"$release_tool" doctor
```

Verify:

- the version is the intended stable release
- schema version is 1
- the installed launcher imports only its sibling bundled package
- the verifier uses the database configured in
  `.coordination/config.yml`
- the database is writable, healthy, WAL-backed, foreign-key enabled, and
  `FULL` synchronous
- reinstall preserves state and repairs managed installation content

Do not reuse a pre-release database for this qualification.

## 4. Exercise Backup And Restore

Create active actors and a small lifecycle fixture through the installed CLI,
then end all sessions. Back up to a new path:

```sh
release_backup="$release_target/.coordination/backups/release.sqlite3"
"$release_tool" backup --output "$release_backup"
```

Require:

- `verified: true`
- schema version 1
- a nonzero byte count
- mode `0600`
- no overwrite without `--force`

Mutate the fixture, end all sessions, and restore:

```sh
"$release_tool" restore \
  --input "$release_backup" \
  --actor release-owner \
  --force
"$release_tool" doctor
```

A successful restore result must contain:

```json
{
  "database": "absolute target path",
  "restored_from": "absolute input path",
  "safety_backup": "absolute backup path or null",
  "safety_backup_verified": true,
  "schema_version": 1,
  "verified": true,
  "publication": "atomic_replace",
  "audit_recorded": true,
  "rollback_performed": false
}
```

Verify that the restored content and restore audit exist, and that the safety
backup contains the immediately previous state.

## 5. Audit Release-Facing Text

Search the release metadata and SQLite documentation for stale pre-release
positioning:

```sh
rg -n 'alpha|beta|preview' \
  VERSION README.md QUICKSTART.md coordination/README.md \
  docs/cli-contract.md docs/adapters/sqlite.md \
  skills/agentic-project-scaffold-lite/references/sqlite.md \
  scaffold/coordination-readme-sqlite.md
```

Any hit in those current-positioning files requires review. Current SQLite
documentation must state:

- supported version 1.1.0
- Python 3.10 or newer
- canonical root runtime and strict installed launcher
- exact command and result contract
- bounded input and pagination behavior
- advisory locks and atomic no-clobber publication
- verified backup, staged restore audit, atomic publication, and rollback
  semantics
- schema version 1 as the first supported schema

## 6. Inspect The Release State

Before the release decision:

```sh
git status --short
git diff --check
git diff --stat
git log --oneline --decorate -n 3
```

Review the full diff. Confirm that generated test state, live databases,
sidecars, backups, temporary files, and local logs are absent.

For the one-commit 1.1.0 pull request, confirm that there is exactly one
pull-request commit and amend it if any qualification change was required.

## 7. Map The 1.1.0 Evidence

Use this matrix together with the detailed release-readiness checklist. A
successful aggregate command is evidence only for the rows whose named tests
it actually runs.

| Stability requirement | Primary evidence |
| --- | --- |
| Public commands, JSON shapes, errors, actor/session semantics, and bounds | `tests/cli-contract.sh`, `tests/sqlite-stability.sh`, `docs/cli-contract.md` |
| One harness-neutral implementation and strict installed imports | `tests/install.sh`, `tests/release-artifact.sh`, `coordination/`, `scripts/coordination.py` |
| Destination, configuration, managed-block, README, and reinstall integrity | `tests/install.sh`, `scripts/install.sh`, `scripts/verify-install.sh` |
| Exact v1 schema, constraints, revisions, claims, locks, and process races | `tests/cli-contract.sh`, `tests/sqlite-concurrency.sh`, `tests/sqlite-operations.sh`, `tests/sqlite-stability.sh` |
| Verified backup, staged restore audit, safety copy, rollback, and recovery | `tests/sqlite-operations.sh`, `tests/sqlite-restore-qualification.sh` |
| Safe Markdown, independent aggregates, pagination, and scale bounds | `tests/sqlite-stability.sh`, `coordination/entities/reports.py` |
| Interrupted export, backup, restore, publication, verification, and rollback | `tests/sqlite-stability.sh`, `tests/sqlite-restore-qualification.sh`, the failure-injection probe scripts under `tests/` |
| Clean committed-source installation and release identity | `tests/release-artifact.sh`, run through `make release-check` after the final amend |

## 8. Record The Decision

The release owner records:

- release version and date
- qualified commit ID
- Python versions used
- complete-suite result
- clean-install and reinstall result
- backup, restore, rollback-injection, and recovery evidence
- known limitations
- go/no-go decision

Publishing, tagging, pushing, and changing pull-request state are separate
remote actions. Perform them only when explicitly authorized.
