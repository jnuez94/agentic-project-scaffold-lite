# Changelog

## [Unreleased]

Internal. No CLI contract, MCP contract, schema, or behavior change:

- entity row operations now receive an open connection and a validated
  `Params` bag from the service, which owns database discovery and connection
  for them; the CLI's `argparse.Namespace` no longer reaches business logic
  (#25). Validation still runs before database discovery, and the
  file/system operations (backup, restore, export, diagnostics) keep their
  bespoke path handling deliberately
- `transaction` and `read_transaction` are reentrancy-safe: inside an open
  transaction they yield without beginning or committing
- added `tests/unit/test_entity_injection.py`, which exercises entity logic
  against an in-memory connection with no subprocess or filesystem

## [1.4.0] - 2026-08-23

Observability core (ADR 0002, #23). Schema version 1 is unchanged:

- every successful mutation's envelope -- CLI and MCP -- carries
  `audit_range`, the inclusive `[first, last]` of the audit ids it wrote;
  a command writes every audit row inside one transaction, so the range is
  contiguous and identifies exactly what was recorded. Reads omit it; `data`
  shapes are unchanged
- added the operation log: `COORDINATION_LOG=stderr` writes one JSON record
  per invocation that reaches the service layer, success and failure, with
  transport, operation, actor, session, object, outcome, error code and exit
  code, duration, lock wait, and the audit receipt -- never free text. The
  MCP server logs by default (`COORDINATION_LOG=off` disables). It is
  observability, not a ledger: the only place refused writes, conflicts, and
  busy timeouts are visible, since the audit table records committed writes
  only
- the service boundary now measures advisory-lock wait per operation
- added `tests/observability.py`, which pins the receipt, its contiguity over
  a multi-row intervention, the log's field set and free-text exclusion, the
  refused-write record, the broken-sink guarantee, and measured lock wait
- `doctor` reports `record_consistency` and `out_of_band_edits`: rows in the
  tables that carry `updated_at` whose `updated_at` postdates their last
  audit row, or that have no audit row at all -- rows written around the
  runtime. A finding does not fail `doctor`; a write through the runtime
  clears it. Consistency for cooperating parties, not tamper evidence
- `backup` and `export` take `--actor` and, when given, audit the egress in
  the source database (`audit_recorded` in the result); the MCP
  `coordination_backup` tool requires `actor`
- added `<entity> history ID [--since CURSOR]` for task, agent, session,
  artifact, decision, message, review, and escalation -- one record's audit
  timeline, oldest first -- and the MCP `coordination_history` tool
- added `tests/record_integrity.py`, which pins the out-of-band finding and
  its clearing, backup/export attribution and the audit row it writes, and
  history ordering, cursor, and paging
- `--because TYPE:ID` on `task status`, `task release`, `decision status`,
  `artifact status`, and `escalation resolve` records the review, decision,
  message, task, escalation, or artifact that caused the change; the
  reference is checked to exist at write time and appended to the audit
  detail as `because=TYPE:ID` -- causality as a fact the ledger carries, not
  free text. MCP tools take `because`
- `summary` gains `time_in_state`: per open status, how long work has sat in
  its current status, measured from each task's last status-changing audit
  row -- derived from the ledger, no new state
- added `tests/causality.py`, which pins reference validation, the audit
  detail on every supported command, and time-in-state from aged audit rows
- added the per-agent inbox (#19): `agent add` starts a new agent's read
  position at the audit head, `inbox list [--agent ID]` returns messages to
  the agent or `team` sent after its cursor (owner derived from the global
  `--session` when omitted), and `inbox mark-read --cursor CURSOR` advances
  the cursor explicitly and only forward, audited as the agent. Cursors live
  in one schema-v1 `metadata` row; an agent registered earlier reads as 0 and
  catches up with one `mark-read`. MCP `coordination_inbox_list` and
  `coordination_inbox_mark_read`; the installed `AGENTS.md` loop names it
- added `tests/inbox.py`, which pins the empty start, direct/team/other
  scoping, paging, forward-only marking and its audit row, session-derived
  ownership, the pre-1.4.0 agent, and a 128-character agent id
- a uniform read surface: every `list` accepts repeatable
  `--where COLUMN:OP=VALUE` and `--order-by COLUMN[:asc|desc]`, and
  `--updated-since` where the table carries `updated_at`. Per-entity
  descriptors name the filterable columns and their kinds; operators follow
  the kind; values are validated before any query; a column, operator, or
  value outside the descriptor is `invalid_arguments`. The descriptor is the
  capability boundary for the layers above the service (ADR 0002 §5).
  `--where id:in=A,B,C` is the batch read. MCP list tools take `filters`,
  `order_by`, and `updated_since` with the same rules
- `show ID` for agent, session, artifact, decision, message, review, and
  escalation; MCP `coordination_show`
- added `tests/query_surface.py` and `tests/unit/test_descriptors.py`, which
  pin the grammar, every kind's validation, ordering determinism, batch read,
  each list's filters, and every `show`

Documentation. No runtime, contract, or schema change:

- stated the deployment scope: personal work on one operator's machine with
  cooperating harnesses and agents; not shared hosts, cloud desktops, or
  network filesystems, for which a shared-host-capable coordination layer is a
  separate product offering (README, `SECURITY.md`, SQLite adapter guide, MCP
  contract)
- added architecture decision records under `docs/adr/`: ADR 0001 records the
  deployment scope and its consequences for the trust model; ADR 0002 records
  the audit-first service boundary, the ledger rules (append-only, free text
  kept, one audited redaction exception), the read-surface descriptor
  boundary, batch reads without batch writes, schema v2 as an additive
  version upgrade, and the 1.4.0 / 2.0 observability roadmap

## [1.3.0] - 2026-08-22

Trust model. A claim is a lease, recovery has a floor, and the transport is
more restricted than the CLI by design:

- `session recover` can no longer be aimed at a live session: the stale
  threshold has a floor of 60 seconds, and `--force` is the explicit,
  separately audited override (`forced; ` prefixes the recovery audit detail;
  the result carries `forced`). Recovery by another actor is the only reaper
  for a dead agent's claims, since `session end` refuses while claims exist and
  nothing expires a session on its own -- so it stays cross-actor; only the
  gate changed. Any actor could previously end any other actor's live session
  and take its claims in two calls by passing `stale_after_seconds=0`
- added `session sweep`, which recovers every active session silent past the
  threshold, oldest first, bounded, in one transaction; `health` reports stale
  sessions and `sweep` acts on them
- `task claim` now reaps an expired claim lease itself: when the holding
  session has been silent past 3600 seconds, the claimant recovers it through
  the same path `session recover` uses, attributed to the claimant, and takes
  the task in the same transaction from the revision it observed. The result
  names the `reaped_session`; a live holder is never displaced. Claims no
  longer fail forever against a holder that will never release
- `agent update --status` requires an explicit `--actor`. Omitting it
  attributed the change to the target, so the audit log recorded that an actor
  deactivated itself whenever an operator forgot the flag; profile edits keep
  the documented default
- removed `force` from the MCP `coordination_backup` tool. The transport never
  replaces an existing file; it was the remaining half of the arbitrary-write
  primitive that path containment closed in 1.2.1
- the MCP server maps SIGTERM and SIGHUP to a clean interrupt, so an in-flight
  backup unwinds and removes its staging file instead of orphaning it
- added `tests/trust_model.py`, which pins the floor, the forced audit, sweep
  ordering and bounds, lease expiry and its boundary, the displaced holder's
  fence, and status-change attribution

Operator and console read path. Every item below was requested because the
only alternative was a second read path over the SQLite file, which the
project's own guidance forbids:

- `task list --status` is repeatable and means any-of, so "everything not
  done" is one call whose filter the server applied; a single value behaves
  as before (#9, #14, #18)
- `task list --tag TOKEN` matches one comma-separated token of `tags` with
  surrounding whitespace ignored (#9)
- `message list --task ID` returns one task's correspondence (#9)
- `audit list` reads the audit log with exact-match filters on actor, session,
  object type, object id, and action, ordered by `id`, bounded, and
  `--since CURSOR` returns only rows after a cursor. The audit trail is the
  accountability record the tool exists to keep and was reachable only by
  opening the database file (#10, #15)
- `summary` returns totals per entity, task status and priority histograms,
  and per-agent workload computed inside one read transaction, plus
  `audit_cursor`, the current audit head; `--section` selects sections (#11,
  #15)
- `health` now groups sections into `anomalies`, which alone decide
  `healthy`, and `informational`, beginning with `tasks_awaiting_review`, so a
  board with work in review is not permanently unhealthy; every existing
  top-level key is preserved, and `--section` computes only the named
  sections (#16)
- the MCP transport exposes the same: `coordination_task_list` accepts a
  status array and `tag`, `coordination_message_list` accepts `task`, and
  `coordination_audit_list`, `coordination_summary`, and `sections` on
  `coordination_health` are new. The contract's "raw audit queries" exclusion
  meant arbitrary SQL; a bounded, filtered list is not that, and an agent
  polling for a peer's work is the natural user of the cursor
- added `tests/console_features.py`, which pins each filter, the cursor, the
  snapshot, and the health split through the service and the CLI

Operator and console write path:

- `artifact update` corrects `uri`, `type`, or `usage_boundaries` in place,
  with an audit row naming the changed fields; URIs are paths and paths move
  (#18)
- `decision status` records a ruling on a decision after it was proposed --
  `superseded` was reachable only at creation, the one moment it can never be
  true -- writing `updated_at` and an audit detail of `previous -> new`, with
  an optional note in the audit trail (#12, #18)
- `message redact` replaces a message body with `[redacted]` while keeping
  the row, sender, recipient, task, tags, timestamps, and recording the
  redaction; it is the supported remediation for content that should never
  have been stored, and `SECURITY.md` now points to it (#17)
- `--if-status` compare-and-swap on `artifact status`, `artifact update`,
  `decision status`, and `escalation resolve`: the change applies only if the
  status is still what the caller saw, otherwise `status_mismatch`. This is
  optimistic concurrency for the mutable entities that carry no revision,
  without a schema change (#13)
- the MCP transport exposes the same: `coordination_artifact_update`,
  `coordination_decision_status`, `coordination_message_redact`, and
  `if_status` on `coordination_artifact_status` and
  `coordination_escalation_resolve`
- added `tests/write_features.py`, which pins each operation, the
  compare-and-swap refusal, the audit rows, and that redacted content leaves
  the database file

## [1.2.1] - 2026-08-22

Fixed defects present in both 1.1.0 and 1.2.0. No CLI contract, MCP contract,
or schema change:

- released every database connection and advisory lock at the end of each
  service operation. Entity functions open connections and never close them,
  which a one-shot CLI process hides. A long-lived caller accumulated shared
  locks on the database lock file until `restore` could no longer take its
  exclusive lock, which made the `coordination_restore` MCP tool unusable
  after any prior call and made a live process block CLI restore for every
  other process. Connection release is per thread, so a transport serving
  calls on a thread pool is covered
- removed an unreachable empty result from `doctor`, whose guard duplicates
  the condition `connect` already rejects with `database_not_found`
- bounded the evidence, dependency, and review arrays in `task show` (and the
  `coordination_task_inspect` MCP tool over it) at the list limit maximum of
  500 rows, reporting any truncation in a new `truncated_sections` array.
  They were the one unbounded read in the contract: the response grew
  linearly with attached rows and, at a few thousand reviews near the text
  cap, reached hundreds of megabytes built in memory for one message.
  `evidence_count` and the per-entity list commands remain the complete view
- added `tests/task_inspect_bounds.py`, which pins the bound and the
  truncation report
- corrected the 1.1.0 and 1.2.0 changelog release dates, which both preceded
  their tags
- added `tests/connection_lifecycle.py`, which fails if repeated calls leak
  lock descriptors, if a failed operation leaks, if `restore` stops working
  after prior calls through either the service methods or `invoke`, or if a
  live process blocks CLI restore

Fixed defects specific to the 1.2.0 surface. These tighten behavior on
commands introduced in 1.2.0, so they are corrections rather than breaking
changes to a shipped guarantee:

- `task release` now enforces the ownership its contract already documented.
  It performed an unowned status transition on a task nobody had claimed,
  which made it `task status` with fewer options and a misleading name. A task
  that is not `in_progress` is now rejected with the new `task_not_claimed`
  code; use `task status` for an unowned transition
- `task update` and `task assign` now reject writes to a claimed task from any
  actor or session other than the claim holder, matching what `task status`
  already enforced. Because every write bumps the revision, an uninvolved
  actor could previously keep a claimed task's revision moving and stall the
  owner's own release. Unclaimed tasks remain open to any active actor
- documented that `export` is the one operation in the transport-neutral layer
  that writes to standard output, and added a guard that fails if any MCP tool
  is ever wired to it, which would corrupt the stdio JSON-RPC stream
- `coordination-mcp` argument errors now emit the same JSON envelope as every
  other failure path instead of argparse prose
- the built-artifact suite no longer leaves the wheel installed in the
  developer's environment, and its missing-artifact message no longer
  hardcodes a version
- added `tests/claim_ownership.py`, which fails against the shipped 1.2.0
  behavior and pins both the restriction and its boundaries
- contained every file path the MCP transport accepts to the coordination
  root. `coordination_backup` wrote a verified database copy to any path the
  caller named and, with `force`, replaced whatever was there -- a destructive
  arbitrary file write reachable by prompt injection, which the MCP contract's
  "no unrestricted filesystem operations" rule already forbade. Backup output
  and restore input now fail with `path_outside_coordination_root` before any
  file is opened. The CLI is unchanged; only a service constructed with the
  transport policy is contained
- extended `tests/mcp-integration.py` with a contained backup, an escaping
  backup that must be refused, and a confirmed restore completing in a server
  that has already served many calls -- the happy path the 1.2.0 suite never
  exercised

Repository tooling and hygiene. No runtime behavior, CLI contract, MCP
contract, or schema change:

- added `ruff` lint and format enforcement, `mypy --strict` type checking, and
  a `pytest` unit layer under `tests/unit/`, all configured in `pyproject.toml`
- added a `dev` package extra and `make lint`, `format`, `typecheck`, `unit`,
  and `coverage` targets, and folded lint, typecheck, and unit into `make check`
- added line and branch coverage measurement that reaches the CLI and MCP
  subprocesses the qualification suites launch
- resolved every lint and strict-typing finding in the runtime, launchers, and
  test harnesses, keeping deliberate suppressions documented inline
- reported a missing audit row ID as an internal error instead of coercing None
- added `.venv`, build output, and tooling caches to `.gitignore`, which
  Python 3.10 does not self-ignore
- restricted the Markdown link check to repository-owned documents
- corrected the README layout listing and documented the annotated release-tag
  requirement

## [1.2.0] - 2026-07-26

Optional local MCP transport:

- added a typed transport-neutral service layer used by both the stable CLI
  and the optional MCP adapter without changing schema version 1
- added a thin harness-neutral MCP server over local stdio only, with no raw
  SQL, network listener, or client-specific implementation
- preserved durable actor identity while recording harness, model, and
  execution attribution in sessions and audit records
- added focused project, agent, session, task, evidence, review, message,
  decision, dependency, artifact, escalation, backup, and restore tools
- made backup and restore separate explicitly confirmed tools with the same
  protected paths, verification, publication, and recovery behavior as the CLI
- added an optional `mcp>=1.28.1,<2` package extra and generic
  `coordination-mcp` entry point while keeping the default CLI dependency-free
- added additive task assignment, content update, and explicit release CLI
  operations under optimistic revision control
- added service/CLI parity, independent-client concurrency, process-restart,
  malformed/stale request, installer, and built-artifact qualification
- made MCP verification fail closed on noncanonical installed launchers and
  enforce the same `mcp>=1.28.1,<2` SDK range as installation
- documented backup, same-backend upgrade, MCP enablement, state verification,
  environment selection, and rollback for existing installations
- documented CLI/MCP peer architecture and generic Codex and Claude usage over
  the same project database
- reject symbolic-link and hard-link aliases across generic and installed MCP
  launcher paths before executing or importing project-local Python code
- cap all transport-neutral identifier arrays at 500 elements and make
  duplicate detection linear while preserving deterministic errors

## [1.1.0] - 2026-07-24

Stable SQLite coordination release:

- added `--adapter sqlite` installation for projects whose participants share
  one local working directory
- established `coordination/` as the sole harness-neutral runtime used by the
  installed CLI, agents, people, and services
- added a strict Python 3.10+ launcher and deterministic JSON success and error
  envelopes
- separated durable actor identity and type from harness, model, and execution
  session attribution
- defined the first supported SQLite schema directly as schema version 1, with
  complete object validation and no migration path from pre-release builds
- added schema constraints, evidence-gated completion, exclusive session-bound
  claims, optimistic task revisions, and append-only audit history
- added bounded identifiers, text, paths, result pagination, stale thresholds,
  and explicit actor/session validation
- made aggregate response fields proper JSON arrays and replaced multiplicative
  report joins with independent aggregation
- added WAL concurrency handling, configurable busy timeouts, advisory
  operational locks, and atomic no-clobber publication
- added verified backups, prepublication restore auditing, verified safety
  backups, atomic restore publication, and explicit rollback outcomes
- escaped stored text in Markdown exports and added bounded health diagnostics
  with truncation reporting
- hardened clean installation, nested discovery, existing-project
  installation, managed-block and README repair, import-failure diagnostics,
  reinstall verification, and backend configuration consistency
- reserved configured database operational namespaces across explicit init,
  backup, export, and restore paths so alternate state cannot overwrite live
  project state
- added contract, installer, concurrency, failure-injection, backup, restore,
  recovery, scale, and clean-install release qualification
- published the exact CLI contract, SQLite operations runbook, release
  procedure, and 1.1.0 qualification checklist

## [1.0.0] - 2026-07-22

Stable Markdown release:

- declared Markdown as the supported version 1.0 coordination backend
- added an explicit backend configuration and installer option
- aligned specification fields with the bundled record templates
- added dependency records and stable-version metadata
- added GitHub Actions validation, issue templates, and a pull request template
- completed public governance, security reporting, contribution, and release policies

## [0.1.0-alpha.1] - 2026-07-22

Added:

- idempotent project installer and installation verifier
- root-agent instruction scaffold and durable coordination directory layout
- installable Codex skill package
- MIT License and final GitHub repository metadata

## 0.1.0-seed

Initial open-source project seed.

Included:

- harness-agnostic working model specification
- quickstart
- project bootstrap prompt
- governance guidance
- contribution guidance
- security policy seed
- code of conduct seed
- decision-rights guidance
- health metrics
- markdown, SQLite, and issue-tracker adapter guidance
- reusable record templates
- startup, conformance, and release-readiness checklists
- four-agent team example
