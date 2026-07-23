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
4. Describe user impact, validation evidence, and migration requirements.

Maintainers may request changes when a proposal weakens portability, evidence requirements, sensitive-data boundaries, or compatibility with the canonical status model.

Executable coordination code belongs only in the root `coordination/`, `scripts/`, and `sqlite/` paths. Harness-specific skills and adapters may provide guidance, but must not vendor a second implementation.
