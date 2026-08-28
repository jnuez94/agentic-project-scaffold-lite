# Coordination CLI Contract

Contract version: `1.4.0`.

This document defines the stable public machine interface for the
harness-neutral SQLite coordination CLI. Version 1.4.0 preserves every 1.1.0
through 1.3.0 command and result shape and adds, additively: the `audit_range`
receipt on every mutation's envelope, the opt-in operation log, `<entity>
history`, `doctor` record-consistency findings, attributed `backup` and
`export`, `--because` causality references, `summary` time-in-state, the
per-agent `inbox`, `--where`/`--order-by`/`--updated-since` on every list,
`show` for every entity, and batch read via `id:in`. The 1.3.0 tightenings
(recovery stale floor with `--force`; explicit `--actor` on agent status
changes) stand, and `escalation resolve` audit detail now reads
`previous -> new` like the other status changes.

## Supported Environment

- one local machine
- one SQLite database shared by participating local processes
- Python 3.10 or newer
- no third-party Python runtime dependencies
- a filesystem that supports POSIX advisory locks and atomic same-directory
  replacement
- trusted local operating-system users
- no secrets, credentials, regulated data, or unapproved proprietary data

The CLI does not provide network synchronization, authentication, or
authorization. Network filesystems and independent project clones are not a
supported way to share the database.

## Invocation And Discovery

The installed executable is:

```sh
./.agents/agentic-project-scaffold-lite/bin/coordination
```

Global options must precede the command:

```text
coordination [--db PATH] [--session ID] COMMAND ...
```

- `--db PATH` selects an explicit database. Inside a configured coordination
  project it may name that project's configured main database or an alternate
  database whose complete operational namespace is disjoint. It cannot name
  managed metadata or reinterpret the configured database's main, sidecar,
  journal, or advisory-lock roles.
- Without `--db`, the CLI searches the current directory and then each parent
  for the nearest `.coordination/config.yml`.
- `init` in a current directory that has no configuration may create or
  revalidate the default `.coordination/coordination.sqlite3`; this remains
  retry-safe. Other commands, and incomplete ancestor boundaries, require
  `config.yml`.
- An existing nearest `.coordination` component must be a real directory, and
  an existing `config.yml` at that boundary must be a non-symbolic-link regular
  file. An encountered `.coordination/` directory with no `config.yml`, or any
  other malformed nearer boundary, is rejected rather than skipped in favor of
  a parent project.
- A discovered configuration consists of blank lines, comments, or unique
  `key: value` scalar lines. Leading and trailing line whitespace is ignored.
  It must contain `version: 1`, select `backend: sqlite`, contain exactly one
  nonempty `database` value, and resolve that value to a file below the same
  `.coordination/` directory.
- The configured database value is relative, contains neither `..` nor a
  nested `.coordination` path component, does not traverse symbolic links, and
  cannot begin with the managed root names `config.yml`, `README.md`, or
  `backups`. These component reservations are case-insensitive so the contract
  is consistent across filesystems. Existing intermediate components must be
  directories.
- `--session ID` selects an execution session for mutation attribution.
- `COORDINATION_SESSION` supplies the default session when `--session` is
  absent.
- An explicit option overrides its environment default.
- Long options do not accept unambiguous abbreviations.

`COORDINATION_LOG` selects the operation log: `stderr` writes one JSON record
per invocation to standard error; `off` (the default) writes none. Any other
value is a `configuration_error`. See "Operation Log" below.

`COORDINATION_BUSY_TIMEOUT_MS` controls the wait for SQLite and operational
file locks. It defaults to `5000` and accepts decimal integers from `0` through
`60000`. Invalid environment configuration returns `configuration_error`.

The installed launcher imports only the sibling bundled `lib/coordination`
package. The repository root `coordination/` directory is the sole
implementation copied by the installer. Missing or unimportable installed
runtime modules return JSON `installation_error` on stderr with exit code 5,
without a Python traceback.

## Lexical And Size Limits

Arguments are validated before database mutation.

| Domain | Contract |
| --- | --- |
| Identifier | 1-128 ASCII characters; first character is a letter or digit; remaining characters are letters, digits, `.`, `_`, `:`, `@`, `+`, or `-` |
| Required text | 1-65,536 valid Unicode scalar values after requiring at least one non-whitespace character; content is preserved; NUL is rejected |
| Optional text | 0-65,536 valid Unicode scalar values; content is preserved; NUL is rejected |
| Path | 1-4,096 valid Unicode scalar values with at least one non-whitespace character; NUL is rejected |
| Revision | Integer from 1 through 2,147,483,647 |
| List limit | Integer from 1 through 500; default 100 |
| List offset | Integer from 0 through 2,147,483,647; default 0 |
| Identifier array | At most 500 elements; every element must satisfy the identifier contract |
| Health stale days | Integer from 0 through 3,650; default 7 |
| Health stale-session minutes | Integer from 0 through 5,256,000; default 60 |
| Recovery stale seconds | Integer from 60 through 315,360,000; default 3,600 |
| Priority | Integer from 1 through 5; default 3 |

Identifiers are rejected rather than trimmed or rewritten. Required and
optional text retain leading and trailing whitespace after validation.
Repeated `--assignee`, `--add`, `--remove`, `--task`, and `--reviewer`
values must be unique. Their corresponding identifier arrays are limited to
500 elements before database discovery or mutation.

File input and output paths must not alias the configured database, managed
configuration or README, database journal, WAL or shared-memory sidecar,
advisory lock, or another protected operational path. Restore input and
backup/export output must be regular files when they already exist.
Directories and special files are rejected. Case variants of protected
operational filenames are also
reserved so behavior remains safe on case-insensitive filesystems. An explicit
`--db` may name an absent destination for `init` or `restore`, but an existing
database target must be a non-symbolic-link regular file. Discovered configured
targets enforce the same file-type rule. Live database files with hard-link
aliases are rejected because each database must have one canonical operational
path and lock namespace. WAL, shared-memory, rollback-journal, and advisory-lock
files must likewise be non-symbolic-link regular files with no hard-link
aliases; sidecars for an absent database are rejected as stale.
Restore additionally requires the complete source and target operational path
sets to be disjoint; no database, WAL, shared-memory, journal, or lock name in
one namespace may alias any such name in the other. A backup output is also a
database namespace and must be completely disjoint from its source.

## JSON And Stream Contract

Successful machine-readable commands write exactly one JSON value followed by
a newline to standard output:

```json
{
  "ok": true,
  "data": {}
}
```

A successful mutation's envelope also carries its receipt:

```json
{
  "ok": true,
  "data": {},
  "audit_range": [418, 420]
}
```

`audit_range` is the inclusive `[first, last]` of the `audit_log` ids the
command wrote. A command writes every audit row inside one write transaction,
so the ids are contiguous and the range identifies exactly what the command
recorded; `audit list --since first - 1 --limit last - first + 1` returns
those rows. Reads, `init`, and commands that write no audit row omit the key.
The per-command result shapes documented below describe `data` and are
unchanged.

Expected failures write exactly one JSON value followed by a newline to
standard error and do not write a success value:

```json
{
  "ok": false,
  "error": {
    "code": "stable_snake_case_code",
    "message": "Human-readable explanation",
    "details": {}
  }
}
```

`details` is omitted when no structured detail exists. Consumers must branch on
`error.code`, not `message`. JSON key ordering, indentation, and message text
are not contractual. Field names, JSON value types, nullability, array
contents, and documented ordering are contractual.

The only non-JSON success output is:

- `--help`, which writes human-readable command help
- `export` without `--output`, which writes only a Markdown report

Timestamps are UTC ISO 8601 strings at one-second resolution with a `+00:00`
offset. Integer database keys are JSON numbers. Nullable database values are
JSON `null`.

### Operation Log

With `COORDINATION_LOG=stderr`, every invocation that reaches the service
layer -- success or failure, read or write -- writes one JSON object on one
line to standard error *in addition to* the success or error envelope. The
log is observability, not a ledger: it is the only place refused writes,
conflicts, busy timeouts, durations, and lock waits are visible, because the
audit table records only committed writes. It never carries free text; actors
and objects appear only when they are well-formed identifiers.

```json
{"ts": "2026-08-23T10:11:12+00:00", "transport": "cli", "operation": "task_update",
 "actor": "engineering", "session": "codex-run", "object": "TASK-1",
 "outcome": "error", "code": "stale_task_revision", "exit_code": 4,
 "audit_range": null, "duration_ms": 3, "lock_wait_ms": 0}
```

`outcome` is `ok` or `error`; `code` and `exit_code` appear only on error.
`audit_range` matches the envelope receipt and is `null` when nothing was
written. `lock_wait_ms` is time spent waiting for operational file locks.
Failures before dispatch (argument parsing, unknown commands) are not logged.
With the log on, standard error is a stream of concatenated JSON values: each
log record is one line, and an error envelope is the usual pretty-printed
object. Consumers that parse standard error as a single JSON value must leave
the log off; with it on, decode values from the stream (for example with a
JSON decoder's `raw_decode` in a loop), not lines. Record key order is not
contractual; the field set is.

## Exit Codes

| Exit | Meaning |
| --- | --- |
| `0` | Success |
| `1` | Unexpected internal failure |
| `2` | Invalid arguments, missing required attribution, or missing destructive confirmation |
| `3` | Requested resource, input, or database not found |
| `4` | State conflict, uniqueness conflict, existing output, or constraint violation |
| `5` | Installation, configuration, schema, integrity, database, interruption, filesystem, restore, or environment failure |
| `6` | SQLite busy timeout or operational advisory-lock timeout |

## Actor And Session Semantics

An actor ID is a durable accountable identity. `actor_type` describes whether
that identity is an `ai`, `human`, or `service`. A session records the harness
and optional model for one execution. Harness or model names are not actor
identity.

Every audited mutation requires an existing active actor. The actor is resolved
as follows:

| Command | Accountable actor |
| --- | --- |
| `agent add` | `--actor`, or new `--id` when omitted |
| `agent update` | `--actor`; required when `--status` changes, otherwise the target agent ID when omitted |
| `session start` | `--agent` |
| `session heartbeat`, `session end` | agent stored on the session |
| `session recover` | required `--actor` |
| `task create`, `task assign`, `task update`, `task status`, `task release` | required `--actor` |
| `task claim` | required `--agent` |
| `evidence add`, `dependency add`, `dependency resolve` | required `--actor` |
| `review add` | required `--reviewer` |
| `decision add` | required `--owner` |
| `message send` | required `--sender` |
| `artifact add` | required `--owner` |
| `artifact status`, `artifact update` | required `--actor` |
| `decision status` | required `--actor` |
| `message redact` | required `--actor` |
| `inbox mark-read` | the inbox owner (`--agent`, or the global session's agent) |
| `escalation add` | required `--raised-by` |
| `escalation resolve` | required `--actor` |
| `restore` | required `--actor`, which must be active in the restore input |

`init`, queries, and diagnostics do not append an actor audit. `export` and
`backup` append one only when `--actor` is supplied (action `export` or
`backup`, object type `database`, object id the database path, detail naming
the output); egress is then in the record. Over MCP the actor is required.

When a global session is present for an audited mutation, it must exist, be
active, belong to the accountable actor, and belong to an active agent.
Successful session-aware mutations update `last_seen_at`. A wrong actor/session
pair is a conflict; an unknown referenced resource is not found. `task claim`
always requires a session. Leaving off a session on other mutations is allowed
and produces a null `audit_log.session_id`.

`session start` is the one lifecycle special case: its start audit is
attributed to the newly inserted session itself. `session heartbeat` and
`session end` use their positional session ID. A global session is not used by
those three commands. `session recover` may use a global operator session, but
that session must differ from the session being recovered.

## Pagination And Ordering

Every command named `list` accepts:

```text
[--limit LIMIT] [--offset OFFSET]
```

The defaults are `--limit 100 --offset 0`; the maximum limit is 500. Filtering
occurs before ordering, then offset and limit are applied. A page past the end
is `data: []`. List results are arrays directly under `data`; there is no
implicit total count.

Ordering is deterministic:

| Command | Order |
| --- | --- |
| `agent list` | `role`, `id` |
| `session list` | `started_at`, `id` |
| `task list` | `priority`, `updated_at`, `id` |
| `evidence list` | `created_at`, `id` |
| `review list` | `created_at`, `id` |
| `decision list` | `created_at`, `id` |
| `message list` | `created_at`, `id` |
| `artifact list` | `updated_at`, `id` |
| `escalation list` | `created_at`, `id` |
| `audit list` | `id` |

Nested task evidence and reviews use `created_at`, `id`; dependencies use
`depends_on_task_id`, `dependency_type`. Identifier arrays use ascending
identifier order.

### Filtering And Ordering

Every command named `list` also accepts:

```text
[--where COLUMN:OP=VALUE]...  [--order-by COLUMN[:asc|desc]]...
```

and, where the table carries `updated_at` (`agent`, `task`, `decision`,
`artifact`, `escalation`):

```text
[--updated-since TIMESTAMP]
```

`--where` is repeatable and every filter must hold (AND), together with the
command's own flags. Each entity lists the columns it may be filtered by and
their kind; the operator set follows the kind: identifier and enum columns
take `eq`, `ne`, `in`; text columns `eq`, `ne`; integer columns `eq`, `ne`,
`ge`, `le`; timestamp columns `ge`, `le`. `in` takes a comma-separated list of
at most 500 values. Values are validated by kind before any query runs --
enum values against the column's choices, identifiers against the identifier
contract, timestamps against the contract's UTC one-second form -- and a
column, operator, or value outside what the entity lists is
`invalid_arguments` with `field: "where"` (and `columns` naming what is
allowed). `--updated-since TIMESTAMP` is `updated_at:ge=TIMESTAMP`.

`--order-by` is repeatable, from the entity's orderable columns, ascending by
default; `id` ascending is always appended as the final tiebreak unless named,
so ordering is deterministic. Without `--order-by` the default orders above
apply. Filtering happens before ordering, then offset and limit.

**Batch read:** `--where id:in=A,B,C` returns those records (absent ids are
simply absent, not errors) in one call and one snapshot, in the list's order.

| Command | Filterable columns (kind) | Orderable |
| --- | --- | --- |
| `agent list` | `id` (identifier), `name`, `role` (text), `actor_type`, `status` (enum), `created_at`, `updated_at` (timestamp) | `id`, `name`, `role`, `actor_type`, `status`, `created_at`, `updated_at` |
| `session list` | `id`, `agent_id` (identifier), `harness`, `model` (text), `status` (enum), `started_at`, `last_seen_at`, `ended_at` (timestamp) | `id`, `agent_id`, `harness`, `status`, `started_at`, `last_seen_at`, `ended_at` |
| `task list` | `id`, `created_by` (identifier), `title` (text), `status` (enum), `priority`, `revision` (integer), `created_at`, `updated_at` (timestamp) | `id`, `title`, `status`, `priority`, `revision`, `created_by`, `created_at`, `updated_at` |
| `evidence list` | `id` (integer), `task_id`, `added_by` (identifier), `evidence_type` (text), `created_at` (timestamp) | `id`, `evidence_type`, `added_by`, `created_at` |
| `review list` | `id`, `task_id`, `reviewer_id` (identifier), `scope` (text), `decision` (enum), `created_at` (timestamp) | `id`, `task_id`, `reviewer_id`, `decision`, `created_at` |
| `decision list` | `id`, `owner_id` (identifier), `title` (text), `status` (enum), `created_at`, `updated_at` (timestamp) | `id`, `title`, `owner_id`, `status`, `created_at`, `updated_at` |
| `message list` | `id`, `sender_id`, `task_id` (identifier), `recipient` (text), `created_at` (timestamp) | `id`, `sender_id`, `recipient`, `task_id`, `created_at` |
| `artifact list` | `id`, `owner_id` (identifier), `uri`, `type` (text), `status` (enum), `created_at`, `updated_at` (timestamp) | `id`, `uri`, `owner_id`, `type`, `status`, `created_at`, `updated_at` |
| `escalation list` | `id`, `raised_by` (identifier), `owner` (text), `status` (enum), `created_at`, `updated_at` (timestamp) | `id`, `raised_by`, `owner`, `status`, `created_at`, `updated_at` |

Free-text content columns (descriptions, bodies, notes, and the like) are
deliberately not filterable: the list is a query surface, not a search.

## Common Row Shapes

Query commands return the stored columns listed here. Extra fields are listed
with the relevant command.

| Row | Fields and JSON types |
| --- | --- |
| Agent | `id`, `name`, `role`, `actor_type`, `status`, `responsibilities`, `goal`, `operating_style`, `decision_authority`, `review_authority`, `escalation_rules`, `unavailable_for`, `created_at`, `updated_at`: strings |
| Session | `id`, `agent_id`, `harness`, `model`, `status`, `started_at`, `last_seen_at`: strings; `ended_at`: string or null |
| Task | `id`, `title`, `description`, `status`, `tags`, `acceptance_criteria`, `next_steps`, `blocked_claims`, `notes`, `created_at`, `updated_at`: strings; `priority`, `revision`: integers; `created_by`: string |
| Evidence | `id`: integer; `task_id`, `uri`, `evidence_type`, `added_by`, `created_at`: strings |
| Dependency | `task_id`, `depends_on_task_id`, `dependency_type`, `status`, `rationale`, `created_at`: strings |
| Review | `id`, `reviewer_id`, `artifact_uri`, `scope`, `decision`, `accepted_items`, `required_changes`, `remaining_risks`, `blocked_claims`, `follow_up_tasks`, `created_at`: strings; `task_id`: string or null |
| Decision | `id`, `title`, `owner_id`, `status`, `context`, `decision`, `options_considered`, `implications`, `evidence`, `blocked_claims`, `review_required`, `created_at`, `updated_at`: strings |
| Message | `id`, `sender_id`, `recipient`, `body`, `tags`, `created_at`: strings; `task_id`: string or null |
| Artifact | `id`, `uri`, `owner_id`, `type`, `status`, `usage_boundaries`, `created_at`, `updated_at`: strings |
| Escalation | `id`, `raised_by`, `owner`, `status`, `related_tasks`, `issue`, `requested_decision`, `resolution`, `follow_up_tasks`, `created_at`, `updated_at`: strings; `needed_by`: string or null |
| Audit | `id`: integer; `actor`, `action`, `object_type`, `object_id`, `detail`, `created_at`: strings; `session_id`: string or null |

Fields created through the stable CLI that name an actor are non-null. Direct
database writes remain unsupported even when a column is nullable for delete
semantics or defensive compatibility.

## Command Reference

Notation: brackets mean optional syntax; `...` after an option means it is
repeatable. Defaults are stated explicitly. Every command also accepts the
global options described above.

Every entity with a public identifier also has `show`:

```text
agent show ID
session show ID
artifact show ID
decision show ID
message show ID
review show ID
escalation show ID
```

`data` is the stored row (the Artifact row plus `related_tasks` and
`reviewers` for artifacts; `task show` is documented with tasks and adds its
detail arrays). An unknown `ID` is `not_found` with `resource` naming the
entity and id.

### Initialization And Diagnostics

```text
init
```

`data`:

```json
{
  "database": "/absolute/path/coordination.sqlite3",
  "schema_version": 2,
  "status": "initialized"
}
```

`status` is `initialized` when an empty database is created and `ready` when an
exact schema version 1 database is verified. `init` never adopts or changes an
unknown nonempty schema.

```text
version
```

This command does not discover or open a database.

```json
{
  "cli_version": "1.4.0",
  "schema_version": 2
}
```

```text
doctor
```

On success, every value has the exact type and successful value shown:

```json
{
  "healthy": true,
  "cli_version": "1.4.0",
  "database": "/absolute/path/coordination.sqlite3",
  "database_writable": true,
  "directory_writable": true,
  "busy_timeout_ms": 5000,
  "foreign_keys": true,
  "integrity_check": "ok",
  "foreign_key_check": "ok",
  "coordination_invariants": "ok",
  "journal_mode": "wal",
  "metadata_schema_version": 1,
  "schema_version": 2,
  "synchronous": "full",
  "record_consistency": "ok",
  "out_of_band_edits": [],
  "out_of_band_edit_count": 0,
  "out_of_band_edits_truncated": false
}
```

`record_consistency` is `ok` or `findings`. Every write through the runtime
audits before it commits, so a row whose `updated_at` postdates its last audit
row -- or that has no audit row at all -- was written around the runtime.
`doctor` lists such rows for the tables that carry `updated_at` (`tasks`,
`agents`, `decisions`, `artifacts`, `escalations`) as
`{"table", "id", "updated_at", "last_audit_at"}` (`last_audit_at` is null when
the row has no audit row), ordered by table then id, at most 100 per table with
`out_of_band_edits_truncated` reporting the cap, and `out_of_band_edit_count`
the number listed. A finding does not fail `doctor` or change `healthy`: the
database is consistent; the record is suspect. A subsequent write through the
runtime re-audits the row and clears it. This is the schema-v1 consistency
check for cooperating parties, not tamper evidence against an adversary.

`busy_timeout_ms` reflects configuration rather than always being 5000.
Unhealthy diagnostics fail instead of returning `healthy: false`.

### Agents

```text
agent add
  --id ID
  --name TEXT
  --role TEXT
  [--actor-type ai|human|service]
  [--responsibilities TEXT]
  [--goal TEXT]
  [--operating-style TEXT]
  [--decision-authority TEXT]
  [--review-authority TEXT]
  [--escalation-rules TEXT]
  [--unavailable-for TEXT]
  [--actor ID]
```

`--actor-type` defaults to `ai`; every optional text field defaults to `""`.
When `--actor` is omitted, the newly created ID is the actor, allowing the
first actor to bootstrap itself. A supplied `--actor` may equal the new ID;
any other supplied actor must already exist and be active.

```json
{"id": "actor-id", "actor_type": "ai", "status": "created"}
```

```text
agent list
  [--all]
  [--actor-type ai|human|service]
  [--limit LIMIT]
  [--offset OFFSET]
```

Without `--all`, only active agents are returned. `data` is an array of Agent
rows.

```text
agent update ID
  [--name TEXT]
  [--role TEXT]
  [--actor-type ai|human|service]
  [--status active|inactive]
  [--actor ID]
```

At least one changed field is required. An agent with an active session cannot
be made inactive. Changing `--status` requires an explicit `--actor`; a status
change is the consequential edit, and the record must name who made it rather
than attribute it to the target. Profile edits keep the target agent as the
default accountable actor. `data` is the complete updated Agent row.

### Sessions

```text
session start
  --id ID
  --agent ID
  --harness TEXT
  [--model TEXT]
```

`--model` defaults to `""`.

```json
{
  "id": "session-id",
  "agent_id": "actor-id",
  "harness": "harness-name",
  "model": "",
  "status": "active"
}
```

```text
session list
  [--agent ID]
  [--status active|ended]
  [--harness TEXT]
  [--limit LIMIT]
  [--offset OFFSET]
```

`data` is an array of Session rows.

```text
session heartbeat ID
```

```json
{"id": "session-id", "status": "active"}
```

```text
session end ID
```

The session must be active and have no active task claims.

```json
{"id": "session-id", "status": "ended"}
```

```text
session recover ID
  --actor ID
  --reason TEXT
  [--stale-after-seconds SECONDS]
  [--force]
```

The stale threshold defaults to 3600 seconds and cannot be set below 60: the
threshold is the one gate separating a dead session from a live one, and a
caller may not zero it. The reason must contain non-whitespace text. The
session must be active and, without `--force`, have `last_seen_at` at or before
the calculated cutoff; otherwise `session_not_stale` is returned. `--force`
recovers a session that has not reached the threshold. It is the explicit
operator override, and the session's `recover` audit detail is prefixed
`forced; ` so a forced intervention is never mistaken for a stale one.

```json
{
  "id": "session-id",
  "previous_status": "active",
  "status": "ended",
  "recovered_tasks": [
    {"id": "TASK-1", "status": "blocked", "revision": 3}
  ],
  "forced": false
}
```

`recovered_tasks` is ordered by task ID. Recovery atomically blocks every task
claimed by that session, increments each revision, appends the reason to notes,
removes claims, ends the session, and audits the intervention. Recovery never
transfers a claim; the tasks are claimed fresh from `blocked`.

```text
session sweep
  --actor ID
  --reason TEXT
  [--stale-after-seconds SECONDS]
  [--limit LIMIT]
```

Sweep recovers every active session whose `last_seen_at` is at or before the
cutoff, oldest first, in one transaction, using the same recovery as
`session recover`. The threshold has the same default and floor. The
accountable actor's own global session is never swept. At most `--limit`
sessions (default 100, maximum 500) are recovered per call; `truncated` is true
when more stale sessions remain, and a further call continues from the oldest.

```json
{
  "stale_after_seconds": 3600,
  "recovered_sessions": [
    {
      "id": "session-id",
      "recovered_tasks": [{"id": "TASK-1", "status": "blocked", "revision": 3}]
    }
  ],
  "truncated": false
}
```

### Tasks

```text
task create
  --id ID
  --title TEXT
  --actor ID
  [--description TEXT]
  [--priority 1|2|3|4|5]
  [--tags TEXT]
  [--acceptance TEXT]
  [--next-steps TEXT]
  [--blocked-claims TEXT]
  [--assignee ID]...
```

Priority defaults to 3; optional text defaults to `""`. Assignees default to an
empty array and must be unique active or inactive existing actors.

```json
{
  "id": "TASK-1",
  "status": "todo",
  "revision": 1,
  "assignees": ["actor-a", "actor-b"]
}
```

`assignees` is sorted by actor ID.

```text
task list
  [--status todo|in_progress|review|blocked|done]...
  [--assignee ID]
  [--tag TOKEN]
  [--limit LIMIT]
  [--offset OFFSET]
```

`--status` is repeatable: tasks in any of the given statuses match, so
"everything not done" is `--status todo --status in_progress --status review
--status blocked`. A single `--status` behaves exactly as before. `--tag`
matches one token of the task's comma-separated `tags` text with surrounding
whitespace ignored; `frontend` matches `frontend, urgent` and `frontend` but
not `frontend-2`, and the token itself may not contain commas or whitespace.
Filters combine with AND.

Each element contains the Task row plus:

```json
{
  "claimed_by": null,
  "claim_session_id": null,
  "claimed_at": null,
  "assignees": [],
  "evidence_count": 0
}
```

The claim fields are strings when a claim exists. `assignees` is a sorted array
of actor IDs, never a comma-delimited string.

```text
task show ID
```

`data` contains the same Task and aggregate fields as `task list`, plus:

```json
{
  "evidence": [],
  "dependencies": [],
  "reviews": [],
  "truncated_sections": []
}
```

The arrays contain Evidence, Dependency, and Review rows with the deterministic
ordering defined above. Each array is bounded by the list limit maximum (500
rows). When a task has more attached rows than that, the array holds the first
500 in the deterministic order and the array's name appears in
`truncated_sections`; `evidence_count` remains the complete count, and
`evidence list`, `review list`, and the dependency rows on the task remain the
complete, pageable views. Truncation is reported, never silent.

```text
task assign ID
  --actor ID
  --if-revision REVISION
  [--add ID]...
  [--remove ID]...
```

At least one add or remove is required, the two sets cannot overlap, and a
current claim owner cannot be removed. While a task is claimed, only the actor
and session holding that claim may change its assignees; others are rejected
with `task_claim_owner_mismatch` or `task_claim_session_mismatch`. An unclaimed
task may be assigned by any active actor. A successful change increments the
revision and returns the sorted complete assignee array:

```json
{
  "id": "TASK-1",
  "revision": 2,
  "assignees": ["actor-a", "actor-b"]
}
```

```text
task update ID
  --actor ID
  --if-revision REVISION
  [--title TEXT]
  [--description TEXT]
  [--priority 1|2|3|4|5]
  [--tags TEXT]
  [--acceptance TEXT]
  [--next-steps TEXT]
  [--blocked-claims TEXT]
```

At least one content field is required. Workflow status and claim ownership
cannot be changed by this command. While a task is claimed, only the actor and
session holding that claim may update it; others are rejected with
`task_claim_owner_mismatch` or `task_claim_session_mismatch`. An unclaimed task
may be updated by any active actor. A successful update increments the
revision:

```json
{
  "id": "TASK-1",
  "revision": 3,
  "updated_fields": ["description", "title"]
}
```

```text
task claim ID
  --agent ID
  --if-revision REVISION
```

A global active session is required. The task must be `todo`, `review`, or
`blocked`, or `in_progress` under an expired claim lease (below). A successful
new claim returns:

```json
{
  "id": "TASK-1",
  "status": "in_progress",
  "revision": 2,
  "agent": "actor-id",
  "session_id": "session-id",
  "claimed": true,
  "idempotent_replay": false,
  "reaped_session": null
}
```

Retrying the same agent/session claim with the original revision after its
commit returns the same shape with `claimed: false`,
`idempotent_replay: true`, and the committed revision. It does not mutate state
again.

A claim is a lease held by the claiming session. When a task is `in_progress`
and its holding session has `last_seen_at` more than 3600 seconds in the past,
another actor's claim reaps that session inside the same transaction -- the
same recovery `session recover` performs, attributed to the claimant -- and
then takes the task. `--if-revision` is checked against the revision the
caller observed; the reap increments it once and the claim once more, so the
result reports `revision` two higher and `reaped_session` names the ended
session. The claimed task's notes carry the lease-expiry reason. A holder whose
session has been seen within the lease is never displaced:
`task_already_claimed` is returned as before. Heartbeat during long silent work
to keep a lease.

```text
task status ID STATUS
  --actor ID
  --if-revision REVISION
  [--note TEXT]
  [--because TYPE:ID]
```

`--because TYPE:ID` records the cause of a status change: `TYPE` is `review`,
`decision`, `message`, `task`, `escalation`, or `artifact`, and `ID` must name
an existing record of that type, checked at write time (`not_found`
otherwise; a malformed reference is `invalid_arguments`). The reference is
appended to the audit detail as `because=TYPE:ID` after the other facts. It
is a fact the ledger carries, never free text. The same option, with the same
rules, is accepted by `task release`, `decision status`, `artifact status`,
and `escalation resolve`.

`STATUS` is one of `todo`, `in_progress`, `review`, `blocked`, or `done`.
`--note` defaults to `""`. Entering `in_progress` is rejected; use
`task claim`. When leaving `in_progress`, the actor and global session must own
the claim; omitting that global session returns `session_required`.

```json
{
  "id": "TASK-1",
  "previous_status": "in_progress",
  "status": "review",
  "revision": 3
}
```

```text
task release ID
  --to todo|review|blocked
  --actor ID
  --if-revision REVISION
  [--note TEXT]
  [--because TYPE:ID]
```

This is an explicit spelling of an owned transition out of `in_progress`.
The accountable actor and global session must own the claim. A task that is
not `in_progress` is rejected with `task_not_claimed`; an actor or session
that does not hold the claim is rejected with `task_claim_owner_mismatch` or
`task_claim_session_mismatch`. Apart from that precondition, its result and
revision behavior are identical to the equivalent `task status` transition.

Use `task status` for an unowned transition. `task release` never performs
one.

Allowed status transitions are:

| From | To |
| --- | --- |
| `todo` | `in_progress`, `blocked` |
| `in_progress` | `todo`, `review`, `blocked` |
| `review` | `in_progress`, `blocked`, `done` |
| `blocked` | `todo`, `in_progress` |
| `done` | none |

Transitioning to the current status is a conflict. Transitioning to `done`
requires at least one evidence row. Every task starts at revision 1; successful
claim and status operations increment it. A stale revision fails before any
partial mutation.

### Evidence And Dependencies

```text
evidence add
  --task ID
  --uri TEXT
  --actor ID
  [--type TEXT]
```

`--type` defaults to `artifact`.

```json
{"id": 1, "task_id": "TASK-1", "status": "created"}
```

```text
evidence list
  --task ID
  [--limit LIMIT]
  [--offset OFFSET]
```

`data` is an array of Evidence rows. The referenced task must exist even when
it has no evidence.

```text
dependency add
  --task ID
  --depends-on ID
  --actor ID
  [--type blocks|informs|review_required|evidence_required]
  [--rationale TEXT]
```

`--type` defaults to `blocks`; `--rationale` defaults to `""`. Both tasks must
exist and differ.

```json
{
  "task_id": "TASK-1",
  "depends_on": "TASK-0",
  "type": "blocks",
  "status": "active"
}
```

```text
dependency resolve
  --task ID
  --depends-on ID
  --actor ID
  [--type blocks|informs|review_required|evidence_required]
```

`--type` defaults to `blocks`. The success shape matches `dependency add` with
`status: "resolved"`.

### Reviews And Decisions

```text
review add
  --id ID
  [--task ID]
  --reviewer ID
  --artifact TEXT
  --scope TEXT
  --decision accepted|conditionally_accepted|changes_requested|rejected
  [--accepted-items TEXT]
  [--required-changes TEXT]
  [--risks TEXT]
  [--blocked-claims TEXT]
  [--follow-up-tasks TEXT]
```

Optional text defaults to `""`; omitted `--task` is stored as null.

```json
{"id": "REV-1", "decision": "accepted", "status": "created"}
```

```text
review list
  [--task ID]
  [--limit LIMIT]
  [--offset OFFSET]
```

`data` is an array of Review rows.

```text
decision add
  --id ID
  --title TEXT
  --owner ID
  [--status proposed|accepted|superseded|rejected]
  --context TEXT
  --decision TEXT
  [--options TEXT]
  [--implications TEXT]
  [--evidence TEXT]
  [--blocked-claims TEXT]
  [--review-required TEXT]
```

Status defaults to `proposed`; optional text defaults to `""`.

```json
{"id": "DEC-1", "status": "proposed"}
```

```text
decision list
  [--limit LIMIT]
  [--offset OFFSET]
```

`data` is an array of Decision rows.

```text
decision status ID STATUS
  --actor ID
  [--if-status proposed|accepted|superseded|rejected]
  [--note TEXT]
  [--because TYPE:ID]
```

Records a ruling on a decision after it was recorded: `STATUS` is `proposed`,
`accepted`, `superseded`, or `rejected`. The change writes `updated_at` and an
audit row whose detail is `previous -> new`, followed by `; NOTE` when a note
is given; decisions carry no notes column, so the note lives in the audit
trail. `--if-status` is compare-and-swap on the status the caller saw: when the
current status differs, nothing changes and `status_mismatch` is returned.

```json
{"id": "DEC-1", "previous_status": "proposed", "status": "accepted"}
```

### Messages, Artifacts, And Escalations

```text
message send
  --id ID
  --sender ID
  --recipient TEXT
  [--task ID]
  --body TEXT
  [--tags TEXT]
```

`--tags` defaults to `""`; omitted `--task` is stored as null.

```json
{"id": "MSG-1", "status": "sent"}
```

```text
message list
  [--recipient TEXT]
  [--task ID]
  [--limit LIMIT]
  [--offset OFFSET]
```

Without a recipient, all messages are returned. With a recipient, results
include messages addressed to that recipient or to the literal recipient
`team`. `--task` restricts results to messages whose `task_id` is that task;
the two filters combine with AND. `data` is an array of Message rows.

```text
message redact ID
  --actor ID
  --reason TEXT
```

Removes a message's content while keeping the fact that it was sent: the body
is replaced by the literal `[redacted]`; the row, sender, recipient, task,
tags, and timestamps are unchanged; and the redaction is audited with the
reason as its detail. This is the supported remediation when content that
should never have been stored -- a pasted token, a customer name -- reaches a
message. Any active actor may redact. Redacting a message that is already
redacted returns `already_redacted`.

```json
{"id": "MSG-1", "status": "redacted"}
```

```text
artifact add
  --id ID
  --uri TEXT
  --owner ID
  --type TEXT
  [--status draft|review|accepted|superseded]
  [--usage-boundaries TEXT]
  [--task ID]...
  [--reviewer ID]...
```

Status defaults to `draft`; usage boundaries default to `""`. Task and reviewer
values must be unique.

```json
{"id": "ART-1", "status": "draft"}
```

```text
artifact list
  [--status draft|review|accepted|superseded]
  [--limit LIMIT]
  [--offset OFFSET]
```

Each element contains the Artifact row plus:

```json
{"related_tasks": ["TASK-1"], "reviewers": ["reviewer-id"]}
```

Both fields are sorted JSON arrays, never comma-delimited strings.

```text
artifact status ID STATUS
  --actor ID
  [--if-status draft|review|accepted|superseded]
  [--because TYPE:ID]
```

`STATUS` is `draft`, `review`, `accepted`, or `superseded`. The audit detail is
`previous -> new`. `--if-status` is compare-and-swap on the status the caller
saw: when the current status differs, nothing changes and `status_mismatch` is
returned with `expected_status` and `actual_status`.

```json
{"id": "ART-1", "status": "accepted"}
```

```text
artifact update ID
  --actor ID
  [--uri TEXT]
  [--type TEXT]
  [--usage-boundaries TEXT]
  [--if-status draft|review|accepted|superseded]
```

At least one changed field is required. URIs are paths and paths move; this
corrects a record in place instead of adding a superseding duplicate. Status,
owner, related tasks, and reviewers are not changed by this command. The
change writes `updated_at` and an audit row naming the changed fields. `data`
is the complete updated Artifact row.

```text
escalation add
  --id ID
  --raised-by ID
  --owner TEXT
  [--related-tasks TEXT]
  [--needed-by TEXT]
  --issue TEXT
  --requested-decision TEXT
```

Related tasks default to `""`; needed-by defaults to null.

```json
{"id": "ESC-1", "status": "open"}
```

```text
escalation list
  [--status open|in_review|resolved|closed_no_action]
  [--limit LIMIT]
  [--offset OFFSET]
```

`data` is an array of Escalation rows.

```text
escalation resolve ID
  --resolution TEXT
  --actor ID
  [--status resolved|closed_no_action]
  [--follow-up-tasks TEXT]
  [--if-status open|in_review|resolved|closed_no_action]
  [--because TYPE:ID]
```

Status defaults to `resolved`; follow-up tasks default to `""`. `--if-status`
is compare-and-swap on the status the caller saw; a mismatch changes nothing
and returns `status_mismatch`.

```json
{"id": "ESC-1", "status": "resolved"}
```

### Inbox

```text
inbox list
  [--agent ID]
  [--limit LIMIT]
  [--offset OFFSET]
```

```text
inbox mark-read
  --cursor CURSOR
  [--agent ID]
```

An agent's inbox is the messages addressed to it or to the literal recipient
`team` whose `send` audit id is greater than the agent's **cursor** -- a
self-asserted read position the agent keeps about itself, the same species as
`agent_sessions.last_seen_at`. It asserts nothing about delivery or receipt and
nothing about anyone else. `--agent` names the owner; when omitted, the owner
is the agent of the global `--session`, and with neither the command is
`invalid_arguments`.

`agent add` initialises the cursor at the audit head -- the new agent's own
creation -- so a newly registered agent inherits an empty inbox rather than the
project's history. `inbox list` never moves the cursor: a query that consumed
its own results could not be run twice. `inbox mark-read --cursor CURSOR` sets
it explicitly, forward only: a cursor below the current one is
`cursor_not_monotonic` (exit 4), one beyond the audit head is
`invalid_arguments`, and the same cursor again is a no-op. The change is
audited as action `mark_read` on the agent, by the agent.

```json
{
  "agent": "reviewer",
  "cursor": 418,
  "head": 425,
  "messages": [{"id": "MSG-1", "...": "Message row fields", "audit_id": 421}]
}
```

`messages` are Message rows plus `audit_id` (the `send` audit id), ordered by
`audit_id`, bounded like every list. `mark-read` returns
`{"agent", "previous_cursor", "cursor", "head"}`.

Cursors are stored in the schema-v1 `metadata` table as one row,
`inbox_cursors`, a JSON object keyed by agent id; the schema is unchanged. An
agent registered before this command existed has no cursor and reads as 0, so
its first `inbox list` returns every message ever addressed to it or to
`team`; `inbox mark-read --cursor HEAD` (the `head` from `inbox list`) catches
it up.

### Audit

```text
audit list
  [--actor ID]
  [--session-id ID]
  [--object-type TEXT]
  [--object-id TEXT]
  [--action TEXT]
  [--since CURSOR]
  [--limit LIMIT]
  [--offset OFFSET]
```

`data` is an array of Audit rows ordered by `id`. Each filter is an exact
match and the filters combine with AND. `--session-id` filters by the session
a row was attributed to; it is distinct from the global `--session` option,
which `audit list` never uses. `--since CURSOR` returns rows whose `id` is
greater than the cursor (0, the default, means from the beginning), which is
the change-detection primitive: `audit_log.id` is a monotonic integer that
increments on every recorded mutation, so a client polls with the highest `id`
it has seen and receives only what is new, or nothing. `summary` reports the
current head as `audit_cursor`. The audit log is read-only through every
interface.

```text
task history ID      [--since CURSOR] [--limit LIMIT] [--offset OFFSET]
agent history ID
session history ID
artifact history ID
decision history ID
message history ID
review history ID
escalation history ID
```

One record's timeline: the Audit rows whose `object_type` is the entity and
`object_id` is `ID`, ordered by `id`, after `--since` (default 0), bounded
like every list. An unknown `ID` is an empty array, not an error. This is the
same data as `audit list --object-type TYPE --object-id ID`, spelled from the
record's side.

#### `audit changes`

`audit changes` reads the `change_log`: field-level before/after rows written
in the same transaction as their audit row. It exists for security and
behavior audit; console reports never render diffs. Filters: `--id AUDIT_ID`
(rows of one audit event), `--object-type TYPE --object-id ID` (one record's
field history), and `--since CURSOR` (rows with change id greater than the
cursor), with `--limit` and `--offset` as elsewhere. Rows carry `id`,
`audit_id`, `object_type`, `object_id`, `field`, `old_value`, `new_value`,
and `created_at`, ordered by `id`.

Change rows are recorded for field-bearing mutations of entity records --
task update, status, and assign; agent update; artifact update and status;
decision status; escalation resolve -- and only for fields whose value
actually changed. Creates record nothing: current state plus the recorded
updates reconstructs any earlier state. Revision bookkeeping is not a field,
session lifecycle and claims are audited without field rows, and
`message redact` deliberately writes no change rows, because recording the
previous body would preserve exactly the content redaction removes.

#### `audit redact`

`audit redact --id AUDIT_ID --actor ACTOR --reason TEXT` is the ledger's only
admitted mutation. It appends a redaction event (`action` `redact`,
`object_type` `audit`), then rewrites the target row's `detail` and every one
of its change rows' values to `[redacted:<redaction-audit-id>]` in the same
transaction, so the removal itself is permanently attributable. The schema's
triggers refuse any other rewrite. A redaction event's own reason can itself
be redacted the same way; redacting an already-redacted row is
`already_redacted`. `doctor` reports `audit_redaction_dangling_count` --
sentinels whose named redaction event does not exist -- and
`change_log_orphan_count`, folding both into `record_consistency`.

### Health And Summary

```text
health
  [--stale-days DAYS]
  [--stale-session-minutes MINUTES]
  [--limit LIMIT]
  [--section NAME]...
```

Defaults are 7 days, 60 minutes, 100 rows per section, and every section.
Each section is queried independently at one coherent database snapshot and
capped at the limit. Sections are of two kinds. **Anomalies** describe decay:
`unowned_tasks`, `stale_tasks`, `stale_sessions`,
`unclaimed_in_progress_tasks`, `invalid_active_claims`, `active_blockers`,
`done_without_evidence`, `open_escalations`. **Informational** sections
describe normal workflow worth surfacing: `tasks_awaiting_review` (tasks in
`review`, ordered by priority, `updated_at`, `id`).

```json
{
  "healthy": false,
  "unowned_tasks": [],
  "stale_tasks": [],
  "stale_sessions": [],
  "unclaimed_in_progress_tasks": [],
  "invalid_active_claims": [],
  "active_blockers": [],
  "done_without_evidence": [],
  "open_escalations": [],
  "tasks_awaiting_review": [],
  "anomalies": {"unowned_tasks": [], "...": []},
  "informational": {"tasks_awaiting_review": []},
  "truncated_sections": ["stale_tasks"]
}
```

Every computed section appears both as a top-level key, for existing clients,
and under `anomalies` or `informational`. `healthy` is true only when every
computed anomaly section has zero findings; informational sections never make
a project unhealthy. Because every nonempty section returns at least its first
row, truncation cannot hide an unhealthy result. `truncated_sections` is a
deterministic array in the section order shown and names each section for
which additional rows exist. It is always present, including as `[]`.

`--section` is repeatable and restricts the report to the named sections; a
section that is not computed is absent from the top level and from its group,
and `healthy` reflects only the computed anomalies. A client that wants one
check pays for one query.

Section element shapes are exact:

- `unowned_tasks`, `stale_tasks`, `unclaimed_in_progress_tasks`,
  `active_blockers`, `done_without_evidence`, and `tasks_awaiting_review`
  contain stored Task rows without task-list aggregate fields.
- `stale_sessions` contains Session rows.
- `invalid_active_claims` contains string fields `task_id`, `agent_id`,
  `session_id`, `claimed_at`, `task_status`, `session_status`,
  `session_agent_id`, and `agent_status`.
- `open_escalations` contains Escalation rows.

```text
summary
  [--section totals|task_status|task_priority|workload|time_in_state]...
```

Aggregate counts computed inside one read transaction, so every number agrees
with every other: the task histogram cannot disagree with the task total
because another agent committed between two reads. `--section` is repeatable
and defaults to every section.

```json
{
  "audit_cursor": 418,
  "totals": {
    "agents": 3, "sessions": 2, "tasks": 42, "evidence": 10,
    "dependencies": 4, "reviews": 6, "decisions": 5, "messages": 12,
    "artifacts": 7, "escalations": 1, "audit": 418
  },
  "task_status": {"todo": 10, "in_progress": 3, "review": 2, "blocked": 1, "done": 26},
  "task_priority": {"1": 2, "2": 5, "3": 30, "4": 3, "5": 2},
  "workload": [
    {
      "agent_id": "engineering",
      "agent_status": "active",
      "assigned_open_tasks": 4,
      "claimed_tasks": 1,
      "active_sessions": 1
    }
  ],
  "workload_truncated": false,
  "time_in_state": {
    "todo": {"count": 10, "oldest_seconds": 432000, "average_seconds": 90000},
    "in_progress": {"count": 3, "oldest_seconds": 7200, "average_seconds": 3000},
    "review": {"count": 2, "oldest_seconds": 86400, "average_seconds": 50000},
    "blocked": {"count": 1, "oldest_seconds": 172800, "average_seconds": 172800}
  },
  "sections": ["totals", "task_status", "task_priority", "workload", "time_in_state"]
}
```

`audit_cursor` is always present: the highest `audit_log.id` at the snapshot,
or 0. `task_status` carries every status and `task_priority` every priority
from 1 through 5, with zero counts. `workload` is one row per agent ordered by
`agent_id`, counting assigned tasks not yet `done`, active claims, and active
sessions; it is capped at 500 rows with `workload_truncated` reporting the cap.
`time_in_state` covers every status except `done` with zero counts: how long
open work has sat in its current status, measured in whole seconds from each
task's last status-changing audit row (`create`, `status`, `claim`,
`recover_claim`) to the snapshot -- derived from the ledger, no new state.
`sections` lists the computed sections in canonical order.

```text
export
  [--output PATH]
  [--force]
  [--actor ID]
```

Without `--output`, success writes the Markdown report rather than JSON. With
`--output`, success atomically publishes the report and returns:

```json
{"output": "/absolute/path/report.md", "tasks": 42}
```

Stored text is rendered as Markdown text, not report syntax. Headings, list
markers, code delimiters, links, HTML, and embedded newlines cannot inject
additional report structure.

An existing destination is rejected unless `--force` is supplied. Without
`--force`, publication is atomic no-clobber even if another process creates the
destination concurrently.

Backup and file-export outputs, including their derived publication-lock
paths, cannot alias the selected source database's operational namespace.
When an output is inside a `.coordination/` tree with a valid `config.yml`, it
also cannot alias that project's configured main database, WAL, shared-memory,
journal, or advisory-lock path—even when a different database was selected
with `--db`. Direct replacement of configured state is a restore-only
operation. The names `config.yml` and `README.md` are reserved as metadata only
inside `.coordination/` trees; ordinary sibling files with those names remain
valid for standalone explicit databases.

### Backup And Restore

```text
backup
  --output PATH
  [--force]
  [--actor ID]
```

With `--actor`, a successful backup is audited in the *source* database after
the copy is published (so the copy itself does not contain that row), and the
result's `audit_recorded` is true; without it, `audit_recorded` is false and
no row is written.

Backup uses SQLite's online backup operation, validates exact schema identity,
integrity, foreign keys, and coordination invariants, and publishes a mode
`0600` file atomically. An existing destination is rejected unless `--force`
is supplied. Publication holds both an output lock and the destination
database's exclusive operational lock. Existing destination WAL,
shared-memory, or journal sidecars are rejected rather than discarded.

```json
{
  "backup": "/absolute/path/backup.sqlite3",
  "bytes": 131072,
  "schema_version": 2,
  "source": "/absolute/path/coordination.sqlite3",
  "verified": true
}
```

```text
restore
  --input PATH
  --actor ID
  --force
```

`--force` is mandatory destructive confirmation. Restore validates the input
and actor before staging. It obtains an exclusive operational lock and rejects
active sessions in the current target. A healthy existing target receives a
verified pre-restore safety backup under the discovered project's root
`.coordination/backups/`. For an explicit `--db` outside any
`.coordination/` directory, the safety directory is `backups/` beside that
database; an explicit target cannot itself alias that fallback directory.
An explicit restore target inside a `.coordination/` tree cannot name its
managed `config.yml` or `README.md`, or a sidecar, journal, or advisory lock of
the database selected by that root's configuration. Rejection details identify
the target and protected path, and publication has not begun.

A restore input inside a configured coordination project may be that
project's configured main database, in which case its actual advisory lock is
used, or a fully disjoint database. It cannot reinterpret managed metadata or
a configured sidecar, journal, or lock as an independent input database.

Restore builds a staged database through SQLite's online backup operation,
inserts the restore audit into staged state, verifies that audit and all
database checks, then atomically replaces the target. Success returns:

```json
{
  "database": "/absolute/path/coordination.sqlite3",
  "restored_from": "/absolute/path/backup.sqlite3",
  "safety_backup": "/absolute/path/backups/pre-restore-TIMESTAMP.sqlite3",
  "safety_backup_verified": true,
  "schema_version": 2,
  "verified": true,
  "publication": "atomic_replace",
  "audit_recorded": true,
  "rollback_performed": false
}
```

`safety_backup` and `safety_backup_verified` are null only when no target
existed. A healthy target always produces a verified safety backup. If an
unreadable target can only be preserved byte-for-byte, the safety path is
reported with `safety_backup_verified: false` rather than being described as a
verified database.

The restore actor, and the global session when supplied, are resolved against
the restore input because that is the state being published and audited.

Expected validation, staging, and publication failures leave the target
unchanged. A postpublication verification failure restores the safety state
and returns `restore_verification_failed` with this details contract:

```json
{
  "database": "/absolute/path/coordination.sqlite3",
  "safety_backup": "/absolute/path/backups/pre-restore-TIMESTAMP.sqlite3",
  "rollback_performed": true,
  "rollback_succeeded": true,
  "rollback_verified": true
}
```

`safety_backup` is string or null. `rollback_verified` is true for a previously
healthy or previously absent target. It may be false when rollback can prove
only byte preservation of a previously unreadable target.
`rollback_succeeded` states whether the rollback operation itself completed;
when it is false, `rollback_verified` is also false and the target requires
operator inspection.

If the staged restore audit cannot be read back before publication,
`restore_audit_failed` reports `database`, `restored_from`,
`target_unchanged: true`, and `reason`. If the atomic replacement itself
fails, `restore_publication_failed` reports `database`, `safety_backup`,
`target_unchanged: true`, and `reason`.

All other coordination processes must remain stopped until restore completes.
Callers must run `doctor` after restore and retain the safety backup until the
restored state is accepted.

## Schema Version 1

Schema version 1 is the first supported SQLite schema. Both
`PRAGMA user_version` and `metadata.schema_version` equal `1`. Version 1.4.0
does not migrate databases created by builds before the stable 1.1.0 contract.

The exact SQL definitions and non-internal object set in `sqlite/schema.sql`
are normative. Runtime schema validation compares every table, explicit index,
and trigger definition with that installed canonical schema; matching names
with different definitions, additional tables, indexes, triggers, or views,
and missing objects are rejected. `init` creates schema version 1 only in a
database with user version zero and no non-internal schema objects; otherwise
the database must already be an exact supported schema.

### Migrate

`migrate --actor ACTOR` upgrades a schema-1 database to the current schema.
It is explicit and operator-initiated: the installer never migrates, and every
other operation refuses a schema-1 database with a `run 'coordination
migrate'` hint. Under the exclusive database lock it verifies the version-1
source (integrity, invariants, no active sessions), publishes a verified
version-1 backup under the safety-backup directory, stages a copy carrying
the canonical version-2 objects, verifies the staged database (schema
identity, integrity, invariants, and record preservation), writes the
`migrate` audit row, publishes atomically, and re-verifies. Failure before
publication leaves the database untouched (`migration_publication_failed`
carries `target_unchanged`); failure after publication rolls back to the
backup and reports `rollback_performed`, `rollback_succeeded`, and
`rollback_verified` under `migration_verification_failed`. There is no
downgrade: rollback is restoring the pre-migration backup. `change_log`
starts at migration; earlier history remains audit-rows-only.

### Tables

`!` means `NOT NULL`, `?` means nullable, and quoted values are defaults.

| Table | Columns |
| --- | --- |
| `metadata` | `key TEXT! PRIMARY KEY`, `value TEXT!` |
| `agents` | `id TEXT! PRIMARY KEY`, `name TEXT!`, `role TEXT!`, `actor_type TEXT! "ai"`, `status TEXT! "active"`, `responsibilities TEXT! ""`, `goal TEXT! ""`, `operating_style TEXT! ""`, `decision_authority TEXT! ""`, `review_authority TEXT! ""`, `escalation_rules TEXT! ""`, `unavailable_for TEXT! ""`, `created_at TEXT!`, `updated_at TEXT!` |
| `agent_sessions` | `id TEXT! PRIMARY KEY`, `agent_id TEXT!`, `harness TEXT!`, `model TEXT! ""`, `status TEXT! "active"`, `started_at TEXT!`, `last_seen_at TEXT!`, `ended_at TEXT?` |
| `tasks` | `id TEXT! PRIMARY KEY`, `title TEXT!`, `description TEXT! ""`, `status TEXT! "todo"`, `priority INTEGER! 3`, `tags TEXT! ""`, `acceptance_criteria TEXT! ""`, `next_steps TEXT! ""`, `blocked_claims TEXT! ""`, `notes TEXT! ""`, `revision INTEGER! 1`, `created_by TEXT!`, `created_at TEXT!`, `updated_at TEXT!` |
| `task_assignees` | `task_id TEXT!`, `agent_id TEXT!`, `assigned_at TEXT!`; composite primary key `(task_id, agent_id)` |
| `task_claims` | `task_id TEXT! PRIMARY KEY`, `agent_id TEXT!`, `session_id TEXT!`, `claimed_at TEXT!` |
| `task_dependencies` | `task_id TEXT!`, `depends_on_task_id TEXT!`, `dependency_type TEXT!`, `status TEXT! "active"`, `rationale TEXT! ""`, `created_at TEXT!`; composite primary key `(task_id, depends_on_task_id, dependency_type)` |
| `task_evidence` | `id INTEGER PRIMARY KEY AUTOINCREMENT`, `task_id TEXT!`, `uri TEXT!`, `evidence_type TEXT! "artifact"`, `added_by TEXT!`, `created_at TEXT!` |
| `messages` | `id TEXT! PRIMARY KEY`, `sender_id TEXT!`, `recipient TEXT!`, `task_id TEXT?`, `body TEXT!`, `tags TEXT! ""`, `created_at TEXT!` |
| `reviews` | `id TEXT! PRIMARY KEY`, `task_id TEXT?`, `reviewer_id TEXT!`, `artifact_uri TEXT!`, `scope TEXT!`, `decision TEXT!`, `accepted_items TEXT! ""`, `required_changes TEXT! ""`, `remaining_risks TEXT! ""`, `blocked_claims TEXT! ""`, `follow_up_tasks TEXT! ""`, `created_at TEXT!` |
| `decisions` | `id TEXT! PRIMARY KEY`, `title TEXT!`, `owner_id TEXT!`, `status TEXT! "proposed"`, `context TEXT!`, `decision TEXT!`, `options_considered TEXT! ""`, `implications TEXT! ""`, `evidence TEXT! ""`, `blocked_claims TEXT! ""`, `review_required TEXT! ""`, `created_at TEXT!`, `updated_at TEXT!` |
| `artifacts` | `id TEXT! PRIMARY KEY`, `uri TEXT! UNIQUE`, `owner_id TEXT!`, `type TEXT!`, `status TEXT! "draft"`, `usage_boundaries TEXT! ""`, `created_at TEXT!`, `updated_at TEXT!` |
| `artifact_tasks` | `artifact_id TEXT!`, `task_id TEXT!`; composite primary key `(artifact_id, task_id)` |
| `artifact_reviewers` | `artifact_id TEXT!`, `reviewer_id TEXT!`; composite primary key `(artifact_id, reviewer_id)` |
| `escalations` | `id TEXT! PRIMARY KEY`, `raised_by TEXT!`, `owner TEXT!`, `status TEXT! "open"`, `related_tasks TEXT! ""`, `needed_by TEXT?`, `issue TEXT!`, `requested_decision TEXT!`, `resolution TEXT! ""`, `follow_up_tasks TEXT! ""`, `created_at TEXT!`, `updated_at TEXT!` |
| `audit_log` | `id INTEGER PRIMARY KEY AUTOINCREMENT`, `actor TEXT!`, `session_id TEXT?`, `action TEXT!`, `object_type TEXT!`, `object_id TEXT!`, `detail TEXT! ""`, `created_at TEXT!` |

The schema directly enforces identifier grammar on durable entity IDs and
directly bounds the required text columns shown with `CHECK` clauses in
`sqlite/schema.sql`. The CLI additionally applies the public size,
Unicode-scalar, and NUL rules to every text argument before persistence;
direct database writes are unsupported. Status and type checks are:

- actor type: `ai`, `human`, `service`
- agent status: `active`, `inactive`
- session status: `active`, `ended`
- task status: `todo`, `in_progress`, `review`, `blocked`, `done`
- priority: 1 through 5
- dependency type: `blocks`, `informs`, `review_required`,
  `evidence_required`
- dependency status: `active`, `resolved`
- review decision: `accepted`, `conditionally_accepted`,
  `changes_requested`, `rejected`
- decision status: `proposed`, `accepted`, `superseded`, `rejected`
- artifact status: `draft`, `review`, `accepted`, `superseded`
- escalation status: `open`, `in_review`, `resolved`, `closed_no_action`
- task revision: at least 1
- a task cannot depend on itself

### Foreign Keys And Delete Actions

- session agent, task creator/assignees/claims, evidence actor, message sender,
  reviewer, decision owner, artifact owner/reviewers, escalation raiser, and
  audit actor reference `agents.id`
- claim session and audit session reference `agent_sessions.id`
- task-owned assignees, claims, dependencies, evidence, and artifact-task links
  cascade when the task is deleted
- message and review task references become null when the task is deleted
- dependency target tasks use restrictive deletion
- artifact task/reviewer links cascade when the artifact is deleted

All CLI connections enable foreign-key enforcement.

### Required Indexes

- `idx_tasks_status_priority(status, priority, updated_at)`
- `idx_agent_sessions_agent_status(agent_id, status, last_seen_at)`
- `idx_task_assignees_agent(agent_id, task_id)`
- `idx_task_claims_agent(agent_id, claimed_at)`
- `idx_evidence_task(task_id)`
- `idx_reviews_task(task_id, created_at)`
- `idx_messages_recipient(recipient, created_at)`
- `idx_escalations_status(status, created_at)`
- `idx_audit_session(session_id, created_at)`

### Required Triggers

- `task_insert_done_requires_evidence`: tasks cannot be created as done
- `task_claim_requires_active_session`: a claim requires the same active actor
  and session
- `task_claim_requires_claimable_state`: a claim requires `todo`, `review`, or
  `blocked`
- `task_enter_in_progress_requires_claim`: only a claim can enter
  `in_progress`
- `task_status_requires_next_revision`: a status change increments revision by
  exactly one
- `task_update_done_requires_evidence`: entering `done` requires evidence

`doctor`, backup, and restore also reject unclaimed in-progress tasks, invalid
active claims, done tasks without evidence, and internally inconsistent session
rows. Invariant error details retain at most 100 rows per section and include
`truncated_sections` naming any section with additional findings. Integrity and
foreign-key errors retain at most 10 detail rows while reporting truncation;
foreign-key errors also report the complete violation count.

## Concurrency, Durability, And Retry

Initialized connections use foreign keys, WAL journal mode, `FULL` synchronous
durability, the configured busy timeout, and a shared operational file lock.
Mutations use short `BEGIN IMMEDIATE` transactions. Multi-statement reports use
one read snapshot. Restore takes the exclusive operational lock.

Export, backup, and restore stage files in the destination directory, flush
file content, publish atomically, and flush the parent directory. Without
`--force`, export and backup use an atomic create-if-absent publication step;
a racing process cannot cause an overwrite.

Retry rules:

- queries, `version`, `doctor`, and `session heartbeat` are safe to retry
- `init` is safe to retry against an empty or exact supported database
- `task claim` is safe to retry only with the same actor, session, and original
  revision
- a consumed `task status` revision fails and does not apply twice
- export and backup can be retried to a new path; an already published path
  returns `output_exists`
- restore is destructive and is not an idempotent mutation
- callers must inspect current state after an interrupted mutation before
  retrying any other write

Signals handled before publication produce `operation_interrupted`;
transaction and staging cleanup leave no partial mutation. If restore is
interrupted after atomic replacement may have occurred, it performs rollback
and returns `restore_verification_failed` so the rollback outcome is explicit.

## Stable Error Registry

The following codes preserve the 1.1.0 registry and remain part of the 1.4.0
contract. Command-specific details listed above supplement this registry.

| Error code | Exit | Meaning / stable details |
| --- | ---: | --- |
| `internal_error` | 1 | Unexpected implementation failure; details contain `error_type` |
| `invalid_arguments` | 2 | Syntax, domain, bound, duplicate repeated value, path, or required-text failure |
| `invalid_actor` | 2 | An accountable actor was omitted |
| `session_required` | 2 | `task claim`, or a transition leaving `in_progress`, did not receive the required global session |
| `task_claim_required` | 2 | `task status` attempted to enter `in_progress` |
| `confirmation_required` | 2 | Restore omitted `--force` |
| `database_not_found` | 3 | Database or restore input is absent |
| `not_found` | 3 | Entity or referenced resource is absent; details contain `resource` or the dependency key |
| `constraint_violation` | 4 | Duplicate ID, unique URI, or remaining schema constraint conflict; details contain `database_error` |
| `output_exists` | 4 | Destination exists and `--force` is absent; details contain `output` |
| `inactive_actor` | 4 | Mutation actor exists but is inactive; details contain `actor` |
| `inactive_session` | 4 | Session exists but is ended |
| `session_actor_mismatch` | 4 | Global session belongs to another actor |
| `agent_has_active_sessions` | 4 | Agent deactivation is blocked; details contain sorted `sessions` |
| `session_has_active_claims` | 4 | Normal session end is blocked; details contain sorted `tasks` |
| `session_not_stale` | 4 | Recovery threshold has not elapsed; details contain `session_id`, `last_seen_at`, `stale_cutoff` |
| `status_mismatch` | 4 | `--if-status` compare-and-swap failed; details contain the entity ID, `expected_status`, `actual_status` |
| `already_redacted` | 4 | The message body is already the redaction marker |
| `cursor_not_monotonic` | 4 | `inbox mark-read` would move a cursor backwards; details contain `agent`, `cursor`, `requested` |
| `task_already_claimed` | 4 | Another active claim exists; details identify task, agent, and session |
| `invalid_task_state` | 4 | Task is already in the requested state or cannot be claimed from its state |
| `invalid_task_transition` | 4 | Status edge is not allowed; details contain `task`, `from`, `to`, sorted `allowed` |
| `stale_task_revision` | 4 | Optimistic revision mismatch; details contain `task`, `expected_revision`, `actual_revision` |
| `task_claim_owner_mismatch` | 4 | Actor does not own the claim; details contain `task`, `claimed_by`, `actor` |
| `task_claim_session_mismatch` | 4 | Global session does not own the claim; details contain `task`, `claim_session_id`, `session_id` |
| `task_not_claimed` | 4 | `task release` requires an owned `in_progress` task; details contain `task`, `status` |
| `restore_active_sessions` | 4 | Restore target has active sessions; details contain sorted `sessions` |
| `configuration_error` | 5 | Discovery, configuration, or busy-timeout environment is invalid |
| `installation_error` | 5 | Installed runtime, schema, or version metadata is missing or invalid |
| `unsupported_schema` | 5 | `PRAGMA user_version` is unsupported; details contain database and supported versions |
| `incomplete_schema` | 5 | Required objects are absent; details name missing tables, columns, indexes, or triggers |
| `schema_mismatch` | 5 | Metadata and pragma schema versions disagree |
| `schema_definition_mismatch` | 5 | Required object definition differs; details list object type and name |
| `database_configuration_error` | 5 | WAL or `FULL` durability could not be established, or the database, sidecar, journal, or advisory-lock path has an unsafe type, stale state, symbolic link, or hard-link alias; details contain `database` and include `operational_path` when one auxiliary path caused the failure |
| `database_not_writable` | 5 | Database or parent directory is not writable; details contain both booleans |
| `database_corrupt` | 5 | SQLite integrity check failed; details contain at most 10 check rows, `result_count`, and `truncated` |
| `foreign_key_violation` | 5 | Foreign-key check failed; details contain `violation_count`, at most 10 `violations`, and `truncated` |
| `coordination_invariant_violation` | 5 | Claim, task, evidence, or session invariant failed; details contain at most 100 rows per section and `truncated_sections` |
| `database_error` | 5 | SQLite operational failure other than lock/busy |
| `environment_error` | 5 | Filesystem, SQLite, or operating-system failure not otherwise classified |
| `operation_interrupted` | 5 | Handled termination, hangup, or keyboard interruption; signal is included when available |
| `restore_audit_failed` | 5 | Staged restore audit could not be verified; details contain `database`, `restored_from`, `target_unchanged: true`, and `reason` |
| `restore_publication_failed` | 5 | Atomic replacement failed; details contain `database`, `safety_backup`, `target_unchanged: true`, and `reason` |
| `restore_verification_failed` | 5 | Postpublication verification failed; details contain `database` (string), `safety_backup` (string or null), `rollback_performed: true`, `rollback_succeeded` (boolean), `rollback_verified` (boolean), and `reason` |
| `database_busy` | 6 | SQLite or advisory lock wait expired; advisory-lock details contain `lock` and `timeout_ms` |

No expected input, state, schema, installation, filesystem, or database failure
uses `internal_error`.
