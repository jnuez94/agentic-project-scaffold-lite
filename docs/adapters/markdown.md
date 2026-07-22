# Markdown Adapter

Markdown is the simplest coordination substrate. It works well when the team wants portability, version control, and low setup cost.

## Recommended Structure

```text
.coordination/
  agents/
  tasks/
  messages/
  reviews/
  decisions/
  artifacts/
  indexes/
```

Each record is a markdown file using the templates in `templates/`.

## Naming Conventions

Use stable, sortable names:

```text
tasks/TASK-0001-short-title.md
messages/MSG-20260722-001-topic.md
reviews/REV-20260722-001-artifact.md
decisions/DEC-20260722-001-title.md
artifacts/ART-20260722-001-name.md
```

## Required Indexes

Maintain lightweight indexes:

- `indexes/open_tasks.md`
- `indexes/review_queue.md`
- `indexes/blocked_tasks.md`
- `indexes/decision_log.md`
- `indexes/artifact_register.md`

Indexes can be hand-maintained at first. If the project grows, replace them with generated reports.

## Strengths

- easy to copy into any repository
- human readable
- works without services or credentials
- versioned through Git
- good for open-source projects

## Weaknesses

- no built-in locking
- easy to forget indexes
- hard to query at scale
- concurrent edits can conflict

## Minimum Conformance

A markdown implementation conforms to the working model if it has:

- durable task records
- durable message or comment records
- named agents or roles
- one canonical status model
- evidence on completed tasks
- decision records for important choices
- review records with scope, decision, risks, and blocked claims
