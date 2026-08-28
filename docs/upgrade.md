# Upgrade Existing Installations

This guide upgrades an existing Agentic Project Scaffold Lite project to
version 2.0.0. The installer replaces only managed scaffold/runtime content
and preserves project content and coordination configuration. Version 2.0.0
introduces SQLite schema version 2; upgrading a SQLite database is a separate,
explicit `migrate` step that the installer never performs for you.

Use the 2.0.0 source release for the `scripts/install.sh` and
`scripts/verify-install.sh` commands below. Do not copy `coordination/` into a
project by hand.

## 1. Identify The Existing Backend And Version

From the project:

```sh
project=/path/to/project
cat "$project/.coordination/config.yml"
cat "$project/.agents/agentic-project-scaffold-lite/VERSION"
```

The existing `backend:` value is authoritative. The installer rejects an
implicit Markdown-to-SQLite or SQLite-to-Markdown switch.

## 2. Back Up SQLite State

For an existing SQLite project, create a verified backup with its currently
installed CLI before upgrading:

```sh
project=/path/to/project
tool="$project/.agents/agentic-project-scaffold-lite/bin/coordination"
"$tool" backup \
  --output "$project/.coordination/backups/pre-2.0.0.sqlite3"
```

`migrate` also takes its own verified backup automatically, but the
pre-upgrade backup above is made with the old runtime and should be kept
until the upgraded installation passes verification. Markdown projects should
commit or otherwise back up their `.coordination/` records before
reinstalling.

## 3. Upgrade A Markdown Installation

Run the 2.0.0 installer with the existing backend:

```sh
./scripts/install.sh \
  --target /path/to/project \
  --adapter markdown
./scripts/verify-install.sh /path/to/project
```

This repairs the managed bundle and instruction block while preserving
unmanaged project content and existing Markdown coordination records. MCP is
not available for the Markdown backend.

## 4. Upgrade A 1.1.0 Through 1.4.0 SQLite Installation

End or recover every active session first, then reinstall the same backend
from the 2.0.0 source release and migrate the database explicitly:

```sh
./scripts/install.sh \
  --target /path/to/project \
  --adapter sqlite

tool=/path/to/project/.agents/agentic-project-scaffold-lite/bin/coordination
"$tool" migrate --actor your-actor-id
"$tool" doctor
./scripts/verify-install.sh /path/to/project
```

Versions 1.1.0 through 1.4.0 all use frozen schema version 1, so the same
single migration applies to any of them. Until `migrate` runs, every other
2.0.0 operation refuses the version-1 database with a
`run 'coordination migrate'` hint; 1.x runtimes refuse a migrated database,
so the two runtimes can never write the same file. Migration validates the
version-1 database (integrity, invariants, no active sessions), publishes a
verified version-1 backup under `.coordination/backups/`, stages the upgrade,
verifies record preservation, publishes atomically, and records the
`migrate` audit event. Reinstall itself preserves
`.coordination/config.yml`, the database, backups, and every record.

Databases created by pre-release builds remain unsupported. Export or back up
needed data, install into a clean project, and recreate approved records
through the stable CLI.

### Behavior To Expect After Upgrading To 2.0.0

Every 1.1.0 through 1.4.0 command keeps its syntax, envelope, and `data`
shape. Check scripts and agent instructions against these:

- The audit ledger is append-only at the storage layer: out-of-band `UPDATE`
  or `DELETE` of `audit_log` rows now fails in SQLite itself. The only
  admitted mutation is `audit redact`, which appends a redaction event and
  tombstones the target's free text as `[redacted:<audit-id>]`.
- Field-bearing mutations record before/after values in `change_log`,
  starting at migration day; earlier history remains audit-rows-only. The
  diff surface is audit-only: `audit changes` on the CLI and the read-only
  `coordination_audit_changes` MCP tool. Console reports render no diffs.
- `migrate` and `archive` are new commands; `archive --older-than-days N`
  moves fully closed, fully read records into an immutable archive database
  under `.coordination/archive/` and deletes them from the live database in
  one audited operation. The ledger and session rows are never archived.
- `doctor` gains `change_log_orphan_count` and
  `audit_redaction_dangling_count`, folded into `record_consistency`.
- New stable error codes: `already_current`, `migrate_active_sessions`,
  `migration_blocked`, `migration_publication_failed`, and
  `migration_verification_failed`; `confirmation_required` now also covers
  `archive`.

## 5. Enable Or Upgrade Optional MCP

Install the 2.0.0 optional dependency and generic console bootstrap in the
Python environment used by the MCP client:

```sh
python3 -m pip install --upgrade \
  'agentic-project-scaffold-lite[mcp]==2.0.0'
python3 -I -c \
  'import importlib.metadata as m; print(m.version("mcp"))'
```

Then reinstall the existing SQLite project with the explicit MCP option:

```sh
./scripts/install.sh \
  --target /path/to/project \
  --adapter sqlite \
  --with-mcp
./scripts/verify-install.sh \
  --with-mcp \
  /path/to/project
```

The supported SDK range is `mcp>=1.28.1,<2`. Installation and verification both
reject missing or unsupported versions. Verification compares the installed
launcher with trusted canonical source and never executes a launcher that
fails that integrity check.

If the MCP client uses a virtual environment, configure its command as that
environment's absolute `coordination-mcp` path, or ensure the same environment
is active when it starts the project-installed launcher:

```json
{
  "command": "/absolute/path/to/venv/bin/coordination-mcp",
  "args": []
}
```

Restart the MCP client after upgrading so it starts the new bootstrap and
managed runtime. Codex, Claude, and other clients continue to use the same
generic command and project database.

## 6. Verify Preserved State

Run:

```sh
project=/path/to/project
tool="$project/.agents/agentic-project-scaffold-lite/bin/coordination"

./scripts/verify-install.sh --with-mcp "$project"
"$tool" doctor
"$tool" agent list
"$tool" task list
```

Omit `--with-mcp` when MCP is intentionally not installed. Verification must
fail if managed files differ, the database is unhealthy, or the optional SDK
is outside its supported range.

## Rollback

Stop MCP clients and other coordination writers first. There is no downgrade
migration: to return to 1.4.0, reinstall the same backend from the 1.4.0
source release, run that release's verifier, and restore the version-1
database from the pre-migration backup that `migrate` published (or the
pre-upgrade backup from step 2) using that release's explicit restore
confirmation and recovery procedure. Do not overwrite the live database
manually.
