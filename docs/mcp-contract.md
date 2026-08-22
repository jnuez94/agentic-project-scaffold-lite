# Coordination MCP Contract

Contract version: `1.2.1`.

The optional MCP adapter is a local `stdio` transport over the canonical
coordination service layer and schema version 1 database. It is not a second
coordination implementation and it does not replace the stable CLI.

## Runtime Boundary

- Transport is MCP over process standard input/output only.
- The server opens no network listener and accepts no host, port, HTTP, SSE, or
  authentication options.
- One server process uses the database selected by its fixed `--db PATH`
  startup option or by normal nearest-project discovery from its working
  directory.
- Tools cannot change the server's configured database, execute raw SQL, or
  perform unrestricted filesystem operations.
- Every file path a tool accepts -- backup output and restore input -- must
  resolve inside the coordination root (the `.coordination` directory that
  holds the configured database). A path outside it, including one that
  escapes through `..`, `~`, or a symbolic link, fails with
  `path_outside_coordination_root` (exit code 2) before any file is opened.
  The CLI is not contained this way; an operator at a shell may back up to or
  restore from any path. The transport is deliberately more restricted than
  the CLI, not equivalent to it, because its caller acts on text it did not
  write.
- Within the root, backup and restore paths pass through the same
  protected-path, namespace, locking, verification, and atomic-publication
  rules as the CLI.
- The optional Python dependency is `mcp>=1.28.1,<2`. The default CLI
  installation has no third-party Python dependency.

An operator must install the optional package extra, run the project installer
with `--with-mcp`, verify the installation, and register the server with the
local client before a shell-less agent can use MCP. MCP is therefore a
pre-provisioned peer transport, not a mechanism for an agent to install its own
dependencies. A CLI-only installation intentionally returns a structured
`installation_error` if its launcher is invoked without the optional SDK.

The installed launcher is:

```text
.agents/agentic-project-scaffold-lite/bin/coordination-mcp [--db PATH]
```

The generic Python console bootstrap named `coordination-mcp` discovers that
project-installed launcher from the current directory or a parent. Neither
launcher changes Codex, Claude, or another client's configuration.

## Result And Error Mapping

Every successfully dispatched tool returns one MCP tool result whose text
content is the formatted JSON form of its `structuredContent`:

```json
{"ok": true, "data": {}}
```

Canonical expected failures are returned as tool errors (`isError: true`):

```json
{
  "ok": false,
  "error": {
    "code": "stable_cli_error_code",
    "message": "Human-readable explanation",
    "details": {},
    "exit_code": 4
  }
}
```

`details` is omitted when absent. `code`, `details`, and `exit_code` are the
same values the CLI contract assigns to the equivalent operation. MCP protocol
or request-schema errors generated before tool dispatch are transport errors
and do not use the canonical envelope.

All identifier, text, path, pagination, threshold, revision, workflow,
transaction, claim, audit, and concurrency rules come from the
[CLI contract](cli-contract.md) and shared service layer.

## Identity And Session Attribution

Actor IDs are durable accountable identities such as `engineering`,
`reviewer`, or `owner`. `actor_type` is `ai`, `human`, or `service`.
`harness` and `model` describe one execution session and never form an actor ID
or actor type.

Mutation tools expose their accountable actor through `actor`, `agent`,
`reviewer`, `owner`, `sender`, or `raised_by`, matching the domain operation.
The optional or required `session` field identifies the execution session used
for audit attribution. Claim and release require it. When supplied, it must be
active and belong to the accountable actor. Session lifecycle tools use the
session ID in their `id` field; recovery may attribute its audit to a distinct
`operator_session`.

Two harnesses may run separate server processes from one project directory.
Both processes discover or explicitly select the same database and retain
their distinct session metadata.

## Tools

Defaults and result data match the corresponding service/CLI operation.
Fields shown in brackets are optional.
Every identifier-array field, including `assignees`, `add`, `remove`, `tasks`,
and `reviewers`, accepts at most 500 elements. Oversized arrays fail before
database discovery or mutation.

| Tool | Request fields |
| --- | --- |
| `coordination_project_status` | none |
| `coordination_health` | `[stale_days]`, `[stale_session_minutes]`, `[limit]`, `[sections]` |
| `coordination_summary` | `[sections]` |
| `coordination_audit_list` | `[actor]`, `[session_id]`, `[object_type]`, `[object_id]`, `[action]`, `[since]`, `[limit]`, `[offset]` |
| `coordination_agent_register` | `id`, `name`, `role`, `[actor_type]`, profile text fields, `[actor]`, `[session]` |
| `coordination_agent_list` | `[include_inactive]`, `[actor_type]`, `[limit]`, `[offset]` |
| `coordination_agent_update` | `id`, changed profile fields, `[actor]`, `[session]` |
| `coordination_session_start` | `id`, `agent`, `harness`, `[model]` |
| `coordination_session_list` | `[agent]`, `[status]`, `[harness]`, `[limit]`, `[offset]` |
| `coordination_session_heartbeat` | `id` |
| `coordination_session_end` | `id` |
| `coordination_session_recover` | `id`, `actor`, `reason`, `[stale_after_seconds]`, `[force]`, `[operator_session]` |
| `coordination_session_sweep` | `actor`, `reason`, `[stale_after_seconds]`, `[limit]`, `[operator_session]` |
| `coordination_task_create` | `id`, `title`, `actor`, task fields, `[assignees]`, `[session]` |
| `coordination_task_list` | `[status]` (one or an array), `[assignee]`, `[tag]`, `[limit]`, `[offset]` |
| `coordination_task_inspect` | `id` |
| `coordination_task_assign` | `id`, `actor`, `if_revision`, `[add]`, `[remove]`, `[session]` |
| `coordination_task_claim` | `id`, `agent`, `if_revision`, `session` |
| `coordination_task_update` | `id`, `actor`, `if_revision`, changed task fields, `[session]` |
| `coordination_task_transition` | `id`, `status`, `actor`, `if_revision`, `[note]`, `[session]` |
| `coordination_task_release` | `id`, `status`, `actor`, `if_revision`, `session`, `[note]` |
| `coordination_evidence_add` | `task`, `uri`, `actor`, `[type]`, `[session]` |
| `coordination_evidence_list` | `task`, `[limit]`, `[offset]` |
| `coordination_review_add` | `id`, `reviewer`, `artifact`, `scope`, `decision`, review fields, `[session]` |
| `coordination_review_list` | `[task]`, `[limit]`, `[offset]` |
| `coordination_message_send` | `id`, `sender`, `recipient`, `body`, `[task]`, `[tags]`, `[session]` |
| `coordination_message_list` | `[recipient]`, `[task]`, `[limit]`, `[offset]` |
| `coordination_decision_add` | `id`, `title`, `owner`, `context`, `decision`, decision fields, `[session]` |
| `coordination_decision_list` | `[limit]`, `[offset]` |
| `coordination_dependency_add` | `task`, `depends_on`, `actor`, `[type]`, `[rationale]`, `[session]` |
| `coordination_dependency_resolve` | `task`, `depends_on`, `actor`, `[type]`, `[session]` |
| `coordination_artifact_add` | `id`, `uri`, `owner`, `type`, artifact fields, `[tasks]`, `[reviewers]`, `[session]` |
| `coordination_artifact_list` | `[status]`, `[limit]`, `[offset]` |
| `coordination_artifact_status` | `id`, `status`, `actor`, `[session]` |
| `coordination_escalation_add` | `id`, `raised_by`, `owner`, `issue`, `requested_decision`, escalation fields, `[session]` |
| `coordination_escalation_list` | `[status]`, `[limit]`, `[offset]` |
| `coordination_escalation_resolve` | `id`, `resolution`, `actor`, `[status]`, `[follow_up_tasks]`, `[session]` |
| `coordination_backup` | `output`, `confirmation` |
| `coordination_restore` | `input`, `actor`, `confirmation`, `[session]` |

`coordination_task_assign` requires at least one changed assignee and rejects
overlap between `add` and `remove`. `coordination_task_update` requires at least
one changed content field. Both increment the optimistic task revision.
`coordination_task_release` moves an owned `in_progress` claim to `todo`,
`review`, or `blocked`.

Backup dispatch requires the exact string `confirmation: "BACKUP"`. The
transport's backup has no `force`: it never replaces an existing file, because
its caller acts on text it did not write. Choose a new name, or use the CLI.
Restore is separate and requires `confirmation: "RESTORE"`; a confirmed restore
uses the canonical forced-restore path because the explicit confirmation
replaces the CLI's `--force` acknowledgement. Missing or incorrect confirmation
fails before any filesystem or database mutation.

A task claim is a lease. `coordination_task_claim` against a task whose
holding session has been silent for longer than the claim lease (3600 seconds)
reaps that session exactly as recovery does, attributed to the claimant, and
takes the task in the same transaction; the result names the `reaped_session`.
A live holder is never displaced. Agents doing long silent work should call
`coordination_session_heartbeat`.

## Unsupported Surfaces

The MCP adapter does not expose initialization, version metadata, Markdown
export, arbitrary SQL (over the audit table or any other), schema changes,
configuration mutation, network transport, or client-configuration editing.
The audit log is readable through the bounded, filtered
`coordination_audit_list`, whose `since` cursor is the change-detection
primitive for an agent polling for a peer's work; it is never writable. Use the
CLI for initialization, version checks, export, and operational release
procedures.
