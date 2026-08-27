# ADR 0004 — Schema Version 2: Append-Only Ledger, Change Log, and Migration

Status: Proposed.

## Context

Schema version 1 is frozen: it is the current state, and any schema change is
a version upgrade (that is why it is frozen). The 2.0 roadmap item (#24)
collects every capability that requires such a change. Three gaps motivate
it, all continuations of the audit-first boundary in ADR 0002:

1. **The ledger is not tamper-evident at the storage layer.** The runtime
   only appends to `audit_log`, but nothing in the database enforces that.
   An out-of-band `UPDATE` or `DELETE` of audit rows is silent; `doctor`
   detects some out-of-band edits, but the ledger itself accepts them.
2. **Audit records what happened, not what changed.** Free-text fields
   (descriptions, acceptance criteria, decision rationale) stay free — that
   is deliberate — so a mutation's audit row cannot answer "what did the
   text say before?". The agreed resolution is a diff capability for
   security and behavior audit only; the console deliberately does not
   surface diffs.
3. **Nothing ever leaves the live database.** Done tasks, ended sessions,
   and read messages accumulate forever in the working set.

## Decision

### Schema version 2 objects

Version 2 is version 1 plus, with no column changes to existing tables:

- **`change_log`** — `(id, audit_id → audit_log.id, object_type, object_id,
  field, old_value, new_value)`, indexed by `audit_id` and by
  `(object_type, object_id)`. The service layer writes one row per changed
  field inside the same transaction as the mutation and its audit row.
  Values are bounded by the existing text limits. Reads are exposed as an
  audit surface only: `audit changes --id <audit-id>` and
  `audit changes --object <type> <id>` on the CLI, and one read-only MCP
  tool mirroring them. No console report renders diffs.
- **Append-only `audit_log` triggers.** `DELETE` on `audit_log` always
  raises. `UPDATE` raises unless it is a redaction: only the `detail` column
  changes, and its new value is the fixed redaction sentinel naming the
  redaction event. Redaction itself is an audited operation
  (`audit redact --id <id> --actor A --because ...`): it appends an audit
  row (`action = 'redact'`, `object_type = 'audit'`) and rewrites the
  original row's `detail` to `[redacted:<redaction-audit-id>]` in the same
  transaction. `change_log` rows are redactable the same way. Nothing else
  in the ledger is ever mutable.
- **Archival of records, never of the ledger.** A new maintenance operation
  `archive` moves closed records older than an explicit cutoff — done tasks
  with their satellite rows, ended sessions, read messages — into a separate
  verified archive database under `.coordination/archive/`, using the
  backup engine's staged-copy/verify/atomic-publish machinery, and deletes
  them from the live database in the same audited operation. `audit_log`
  and `change_log` are excluded by design: the ledger is never archived,
  never rewritten, and at personal single-operator scale (ADR 0001) its
  growth is acceptable. Archive files are read with the existing tooling by
  pointing `--db` at them (read-only operations only).

### Migration

- **`migrate` is an explicit, audited, operator-initiated operation.** The
  installer never migrates: installing 2.0 over a 1.x project preserves the
  v1 database untouched, and every 2.0 operation except `migrate` refuses a
  v1 database with a clear "run migrate" error. 1.x runtimes already refuse
  anything but v1, so a migrated database cannot be opened by an old
  runtime by accident.
- **Migration reuses the restore engine's guarantees**: take a verified
  pre-migration backup automatically; stage a copy; apply the v2 DDL to the
  staged copy; verify it against the canonical v2 inventory (integrity,
  invariants, schema identity); publish atomically under the exclusive
  advisory lock; write the `action = 'migrate'` audit row recording
  from/to versions. Failure at any phase leaves the v1 database untouched;
  failure after publication is rolled back exactly like a failed restore.
- **There is no downgrade migration.** Rollback is restoring the
  pre-migration backup with the existing restore procedure.
- **Existing rows are not backfilled.** `change_log` starts at migration;
  history before it remains audit-rows-only. The migration audit row
  records that boundary.

### Versioning and contracts

- Version 2 ships as release **2.0.0**. Schema version 2 is then frozen on
  the same terms as version 1: it is the current state, and the next schema
  change is version 3.
- Every 1.x operation keeps its syntax, envelope, and `data` shape.
  Additions are new operations (`migrate`, `archive`, `audit changes`,
  `audit redact`) and ledger enforcement underneath existing ones. The
  frozen-contract suites from 1.x run unchanged against 2.0.
- `doctor` gains ledger checks: trigger presence, `change_log` referential
  integrity, and redaction-sentinel consistency.

## Non-Goals

- Shared hosts and second operators (ADR 0001; unchanged).
- Console or report diff surfaces — diffs are for security and behavior
  audit only.
- Automatic or implicit migration, and downgrade migration.
- External audit sinks and log shipping (separate ADR 0002 roadmap item).
- Archiving or compacting the ledger.

## Consequences

- The ledger becomes tamper-evident at the storage layer: any out-of-band
  edit of audit history now fails at the database, not merely at detection
  time, and the only mutation the schema admits is an attributable,
  audited redaction that leaves a permanent tombstone.
- Free text stays free; reviewers get field-level before/after for every
  mutation after migration day.
- Mutating operations pay one `change_log` write per changed field in the
  same transaction — negligible at this deployment scale.
- The migration path concentrates the risk. It must ship with its own
  qualification suite mirroring the restore matrix: fault injection and
  interrupt probes at staging, publication, and verification phases, plus
  a 1.x-refusal and 2.0-refusal cross-version matrix.
- `sqlite/schema.sql`, the canonical inventory in `_schema_objects.py`, the
  contracts, and the upgrade guide all change together in the 2.0 release;
  mcp-security gains coverage for the new read surface and redaction.

## Roadmap

1. v2 DDL + canonical inventory + frozen-contract suite extension.
2. `change_log` writes at the service boundary; `audit changes` read
   surface (CLI, then MCP).
3. Append-only triggers + `audit redact`.
4. `migrate` with its qualification matrix.
5. `archive` with its qualification matrix.
6. Release 2.0.0 per the house release procedure.
