# Changelog

## [Unreleased]

No changes yet.

## [1.2.0] - 2026-07-24

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

## [1.1.0] - 2026-07-23

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
