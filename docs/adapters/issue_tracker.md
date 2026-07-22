# Issue Tracker Adapter

GitHub Issues, Linear, Jira, or similar systems can serve as the coordination substrate.

The tracker does not need to match this spec perfectly. It needs a reliable mapping.

## Object Mapping

| Working Model Object | Issue Tracker Equivalent |
| --- | --- |
| Agent profile | Team member profile, project document, or pinned issue |
| Task | Issue or ticket |
| Message | Comment |
| Review | Comment with structured review format |
| Decision | Decision issue, project document, or labeled ticket |
| Artifact | Linked file, pull request, design, document, build, or URL |
| Dependency | Blocking issue link or explicit dependency field |

## Label Mapping

Recommended labels:

```text
status:todo
status:in-progress
status:review
status:blocked
status:done
role:product
role:design
role:engineering
role:security
role:qa
type:task
type:review
type:decision
type:artifact
priority:1
priority:2
priority:3
priority:4
priority:5
```

If the tracker has native statuses, prefer those and reserve labels for role, type, priority, and risk.

## Required Fields

Every task issue should include:

- owner or assignee
- status
- priority
- scope
- acceptance criteria
- evidence
- blocked claims
- dependencies
- review request, when applicable

## Review Comments

Use the review template for comments that approve or request changes. A casual comment should not be treated as a formal review unless it includes:

- scope
- decision
- required changes
- risks
- blocked claims

## Strengths

- familiar to developers
- notification support
- assignment and status workflows
- links to pull requests and commits
- good audit trail

## Weaknesses

- may overfit to engineering work
- product/design/security records can become buried
- status vocabulary may differ across tools
- automation can obscure human-readable intent

## Minimum Conformance

An issue tracker implementation conforms if agents can reliably find:

- their assigned tasks
- unassigned high-priority work
- review requests
- blockers
- recent decisions
- evidence for closed work
- external or production approval boundaries
