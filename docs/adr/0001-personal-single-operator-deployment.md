# ADR 0001 — Personal, Single-Operator Deployment Scope

Status: Accepted, 2026-08-23.

## Context

The SQLite backend is a project-local database protected by POSIX advisory
locks and atomic same-directory replacement, installed into one working
directory and driven by the CLI and the optional local stdio MCP transport.
Its participants are a person and the AI harnesses, agents, and services that
person runs on one machine. The trust and threat model follows from that:
actor identity is asserted by the caller and validated for existence and
status, never authenticated; the live database is readable by any local user
account; and the guarantees the runtime makes (exclusive claims, revisions,
audit attribution, contained transport paths) protect cooperating principals
from each other's mistakes and from injected instructions, not from a hostile
co-tenant.

## Decision

Agentic Project Scaffold Lite is for **personal work**: one operator, one
machine, one project directory, any number of harnesses and agents acting as
cooperating principals under that operator. It is **not** designed for shared
hosts — multi-user machines, cloud desktops, shared development servers,
network filesystems, or any deployment where a second human or an untrusted
process can reach the project directory. A shared-host-capable coordination
layer, with authenticated actors, per-user isolation, and adversarial tamper
evidence, is a **separate product offering**, not a configuration of this one.

User-facing documentation states this scope where an adopter decides how to
deploy: the README, `SECURITY.md`, the SQLite adapter guide, and the MCP
contract.

## Consequences

- Actor identity remains a claimed, validated principal; authenticating it is
  out of scope.
- Tamper evidence against an adversary with file access (hash chains, external
  anchors) is a non-goal. Detecting out-of-band edits between cooperating
  parties — a human or agent who bypassed the CLI — remains in scope.
- Database file modes follow the operator's umask; restrictive modes are not
  enforced as a security boundary.
- The MCP transport's policy of being *more* restricted than the CLI
  (contained paths, no `force`, confirmations) stands: it protects the operator
  from an agent acting on text it did not write, which is the threat that
  exists in this scope.
- Requests that presuppose a shared host are redirected to the separate
  offering rather than accommodated here.
