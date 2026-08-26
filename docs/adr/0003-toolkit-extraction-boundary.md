# ADR 0003 — Toolkit Extraction Boundary

Status: Accepted, 2026-08-24.

## Context

The 250-line file budget refactor decomposed the runtime into facades over
small part modules and made an internal layering visible: a tier of generic
infrastructure with no coordination-domain knowledge — advisory file locking
and connection scopes, path identity and containment, durable atomic file
publication, JSON envelopes and the operation-log sink, argument validation,
and the descriptor filter/ordering engine — each depending only on the error
surface in `errors.py` and the constants in `_primitives.py`.

Extracting that tier into a standalone package is attractive in principle but
carries real costs here. The runtime is vendored into each project by the
installer and verified against complete canonical sources, so a pip-resolved
dependency would add exactly the mutable, unverified surface the trust model
excludes. And a package with a single consumer removes no duplication while
adding a second release pipeline, a version compatibility matrix, and API
stability commitments on modules that are currently private and free to
change.

## Decision

The reusable tier is **recorded, not extracted**. Extraction waits for the
first concrete second consumer — most plausibly the shared-host-capable
variant that ADR 0001 anticipates as a separate product offering.

Until then the boundary is maintained as a dependency rule. The portable
kernel is `errors.py`, `_primitives.py`, `_validators.py`, `_locking.py`,
`_paths.py`, `_output.py`, and `entities/_descriptor_engine.py`. Kernel
modules may import only from each other; domain modules may depend on the
kernel; the kernel must never import configuration, discovery, schema,
entity, service, or transport modules — nor the `core` facade, whose import
would pull the whole runtime behind it.

When extraction happens, the kernel moves as one unit with `errors.py` as its
root, and distribution stays vendored: the toolkit is copied into a
consumer's tree by its installer, never pip-installed at runtime, so
installation verification keeps comparing complete canonical sources.

## Consequences

- Reuse today is copy-out — deliberate, and cheap because the seams already
  exist.
- The dependency rule is checkable by inspecting the import block of each
  kernel module; a violation is a regression even though no automated gate
  enforces it yet.
- No second release pipeline or stability commitment is taken on for modules
  that remain private and free to change.
- ADR 0001's product split stays clean: a shared-host offering would consume
  the kernel without inheriting the single-operator runtime.
