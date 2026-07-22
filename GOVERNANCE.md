# Governance

This project is intended to become an open, portable standard for multi-agent project coordination.

## Governance Goals

- Keep the framework harness-agnostic.
- Keep the model simple enough to adopt quickly.
- Keep regulated and sensitive-data projects safe by default.
- Avoid coupling the framework to one vendor, agent runtime, database, or issue tracker.
- Prefer contracts and templates over tool-specific assumptions.

## Maintainer Responsibilities

Maintainers should:

- review proposed changes for portability
- reject tool-specific assumptions unless placed in adapters
- keep core status vocabulary stable
- preserve evidence-based completion rules
- maintain starter templates
- keep examples generic

## Versioning

Use semantic versioning once the project is public:

- major: breaking model changes
- minor: new templates, roles, adapters, or optional records
- patch: clarifications and typo fixes

## Compatibility Rule

The core spec should remain implementable in:

- markdown-only workflows
- SQLite-backed local workflows
- issue tracker workflows
- hybrid human/agent workflows

If a change requires one specific harness, it belongs in an adapter document, not the core spec.
