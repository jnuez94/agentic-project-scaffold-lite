# Contributing

Contributions should make the working model clearer, more portable, or easier to adopt.

## Good Contributions

- clearer templates
- better quickstart steps
- additional adapter docs
- health metric improvements
- decision-rights refinements
- examples for different team sizes
- sensitive-data guardrail improvements

## Avoid

- coupling the core model to one agent platform
- adding many statuses
- making `done` ambiguous
- storing sensitive data in examples
- turning adapter-specific details into core requirements

## Contribution Checklist

Before submitting a change:

- The change is harness-agnostic or isolated to an adapter.
- The status model remains simple.
- The change preserves evidence-based completion.
- Examples are generic.
- Sensitive-data rules remain strict.
- New templates are easy to copy into a new project.

## Submission Process

1. Open an issue for substantial or compatibility-affecting changes.
2. Create a focused branch and pull request.
3. Run `make test` and `make validate-skill`.
4. Run `python3 scripts/check-markdown-links.py`.
5. Describe user impact, validation evidence, and migration requirements.

Maintainers may request changes when a proposal weakens portability, evidence requirements, sensitive-data boundaries, or compatibility with the canonical status model.

Executable coordination code belongs only in the root `coordination/`,
`scripts/`, and `sqlite/` paths. Harness-specific skills and adapters may
provide guidance, but must not vendor a second implementation. The installed
launcher must import only its sibling bundled runtime.

## SQLite Compatibility

The SQLite CLI is a stable public interface in version 1.1.0. Changes to any of
the following are compatibility-affecting and must update
`docs/cli-contract.md`, tests, changelog, adapter guidance, and release
qualification evidence together:

- commands, arguments, choices, or defaults
- JSON field names, types, nullability, arrays, ordering, or pagination
- error codes, exit codes, or error details
- actor and session attribution semantics
- status transitions, revisions, claims, or evidence requirements
- database tables, columns, constraints, indexes, triggers, or schema identity
- backup, restore, recovery, locking, or publication behavior

Python 3.10 is the minimum supported runtime. List inputs and outputs must stay
bounded. File-producing commands must preserve atomic no-clobber behavior when
`--force` is absent. Every SQLite change should include clean-install,
reinstall, multi-process, failure-path, and operational-diagnostic coverage in
proportion to its risk.

Schema version 1 is the first supported SQLite schema. Do not infer a migration
path from pre-release databases.
