# ADR 0002 — Audit-First Service Boundary And The Observability Roadmap

Status: Accepted, 2026-08-23. Depends on [ADR 0001](0001-personal-single-operator-deployment.md).

## Context

Observability and auditability are as central to this coordination layer as
coordination itself: the record is how agents and the operator know what
happened, why, and who did it. The 1.2.x and 1.3.0 work showed two things.
First, every read and write already passes through one typed service boundary
(`CoordinationService.invoke`), which is why defects such as the connection
leak, the uncontained transport paths, and the claim-exclusivity gaps were
fixable in one place — and why downstream consumers could be moved off direct
SQLite reads. Second, the audit table records only committed writes: refused
attempts, contention, and failures are invisible, and the ledger cannot record
actors it does not know.

Schema version 1 is "frozen" in the sense that any change to the schema is a
version upgrade (v2), not in the sense that the schema may never change.

## Decision

1. **The service dispatch boundary is the observability boundary.** It emits a
   structured operation log (JSON lines on standard error; opt-in for the CLI,
   on by default for the MCP server) for every invocation, success and
   failure: operation, actor, session, transport, outcome code, duration,
   lock wait, and the audit id range produced. It is observability, not a
   ledger; it may disagree with the database and carries no free text. No
   managed log files are created.
2. **Every mutation returns its receipt.** Audit ids written inside one
   transaction are contiguous; mutating results carry `audit_range`.
3. **The audit ledger is append-only and keeps free text.** Reasons, notes,
   and detail stay human-readable in `audit_log.detail`. Append-only is
   enforced at the schema level in v2, with exactly one constrained, audited
   exception: `audit redact ID`, which replaces `detail` with the redaction
   marker and appends a row recording the redaction. Record *values* belong to
   records, not to the ledger; `detail` carries facts and references (ids,
   enums, old→new status, field names, reasons).
4. **Change records are an audit feature, not a console feature.** Before and
   after values for behavior and security review are a v2 `change_log`
   referenced by audit rows and redactable with the record. Diffs are rendered
   from change records for the operator; agents and consoles consume current
   state, cursors, and inboxes.
5. **Declarative where uniform, hand-written where semantic.** Per-entity
   descriptors define the read surface — filterable columns and operators,
   ordering, `show`, `since` — and the generic predicate builder accepts only
   what a descriptor lists: that whitelist is the capability boundary for the
   layers above. Transitions, claims, leases, revisions, and compare-and-swap
   stay in hand-written entity code. CLI parsers and MCP tools are not
   generated; `tests/unit/test_cli_service_parity.py` polices the seam.
6. **Batch reads, not batch writes.** Multi-id reads are bounded by the
   existing array cap. Transactional batch writes are not planned: no consumer
   needs them, they lengthen write transactions, and they widen one call's
   blast radius under the transport trust model.
7. **Schema v2 is an additive version upgrade**: versioned additive steps, a
   `migrate` command, a verifier that accepts the current and next version
   during the upgrade window, and backup-first guidance. It is safe to plan
   because 1.3.0 moved consumers onto CLI and MCP reads.
8. **Semantic observability is in scope**: causality references on status
   changes (the review, decision, or message that caused a move) and derived
   time-in-state in `summary`; backup and export are attributed and audited.

## Non-Goals

- Tamper evidence against an adversary with file access (see ADR 0001).
- Auditing reads in the database; if ever needed it belongs in the operation
  log.
- Generic delete, raw SQL above the service, unbounded results, caller-
  controlled security gates, or a generated contract.

## Roadmap

- **1.4.0 (schema v1):** operation log; `audit_range`; `<entity> history ID`
  from existing audit rows; `doctor` flags rows whose `updated_at` postdates
  their last audit row; backup/export attribution; causality references and
  time-in-state; per-agent inbox cursor (#19) as a `metadata` row; batch
  reads; list descriptors with `--where`, `--order-by`, `--updated-since`;
  uniform `show`; entity functions take a connection instead of an argparse
  namespace.
- **2.0 (schema v2):** append-only `audit_log` with the single `audit redact`
  exception; `operation_id` and `transport` columns; `change_log` for
  behavior audit; archival with a recorded boundary; `migrate` and the
  dual-version verifier.
- **Deferred until asked:** diffs for consoles, generated CLI/MCP surfaces,
  batch writes.
