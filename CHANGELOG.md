# Changelog

## [Unreleased]

No changes yet.

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
