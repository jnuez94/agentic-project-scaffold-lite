# SQLite Adapter

Status: conceptual; not implemented by the version 1.0 installer.

SQLite is a good local-first substrate when a project needs queryability without running infrastructure.

This adapter is intentionally conceptual. Implement the tables in the language or migration system of your choice.

## Core Tables

```sql
agents(id, name, role, goal, active, created_at, updated_at)
tasks(id, title, description, status, priority, created_by, created_at, updated_at)
task_assignees(task_id, agent_id)
task_tags(task_id, tag)
task_dependencies(task_id, depends_on_task_id)
task_evidence(task_id, evidence_uri, evidence_type, created_at)
messages(id, sender_id, task_id, body, created_at)
message_recipients(message_id, recipient)
reviews(id, reviewer_id, artifact_uri, scope, decision, created_at)
review_items(review_id, item_type, body)
decisions(id, title, owner_id, context, decision, created_at)
decision_options(decision_id, option_text, outcome, reason)
artifacts(id, uri, owner_id, type, status, created_at, updated_at)
artifact_tasks(artifact_id, task_id)
```

## Status Constraint

Tasks should only use:

```text
todo
in_progress
review
blocked
done
```

If another system uses different states, map them into this set before agents reason about work.

## Useful Queries

Open work:

```sql
select * from tasks where status in ('todo', 'in_progress', 'review', 'blocked');
```

Tasks completed without evidence:

```sql
select t.*
from tasks t
left join task_evidence e on e.task_id = t.id
where t.status = 'done'
and e.task_id is null;
```

Review queue:

```sql
select *
from tasks
where status = 'review';
```

Blocked tasks:

```sql
select *
from tasks
where status = 'blocked';
```

## Strengths

- queryable
- portable as one file
- fast enough for small and medium projects
- easy to validate status and evidence rules

## Weaknesses

- requires an adapter or CLI
- merge conflicts are harder than markdown
- needs backup discipline

## Minimum Conformance

A SQLite implementation conforms if it enforces:

- stable IDs
- canonical statuses
- task ownership
- evidence for done work
- persistent messages
- persistent reviews
- persistent decisions
- timestamped changes
