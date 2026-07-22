# Governance

This project is intended to become an open, portable standard for multi-agent project coordination.

The project currently uses maintainer-led governance. The repository owner is the final decision maker for releases, compatibility, and changes to the core model. Significant changes should begin as a GitHub issue and remain open for public review before implementation.

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

Release candidates and experimental work use semantic prerelease identifiers such as `1.1.0-alpha.1`. Stable releases are tagged from `main`; release notes must identify compatibility changes and migration requirements.

## Compatibility Rule

The core spec should remain implementable in:

- markdown-only workflows
- SQLite-backed local workflows
- issue tracker workflows
- hybrid human/agent workflows

If a change requires one specific harness, it belongs in an adapter document, not the core spec.

## Adapter Policy

Specifications, bundled local adapters, and their validation tools live in this repository while they share the core release cycle. An adapter may move to a separate repository if it requires a service-specific runtime, independent release cadence, or substantially different security boundary.
