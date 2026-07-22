# Decision Rights

Decision rights prevent a multi-agent project from drifting into unclear authority, accidental launches, or endless consensus loops.

Use this file to define who can approve what. A person, agent, role, or committee can hold a decision right. If one agent holds multiple roles, list each role explicitly.

## Decision Matrix

| Decision Area | Decision Owner | Required Reviewers | Evidence Required | Notes |
| --- | --- | --- | --- | --- |
| Project vision |  |  |  |  |
| Scope priority |  |  |  |  |
| Task creation |  |  |  |  |
| Task closure |  |  |  |  |
| Design acceptance |  |  |  |  |
| Architecture acceptance |  |  |  |  |
| Security/privacy acceptance |  |  |  |  |
| External stakeholder sharing |  |  |  |  |
| Sensitive-data access |  |  |  |  |
| Production release |  |  |  |  |
| Incident response |  |  |  |  |

## Recommended Default

For a small team, start with this pattern:

| Decision Area | Recommended Owner |
| --- | --- |
| Vision, scope, acceptance, external messaging | Product Owner |
| User experience and usability acceptance | Design Owner |
| Architecture, implementation feasibility, technical delivery | Engineering Owner |
| Security, privacy, sensitive data, production risk | Security/Privacy Owner |
| Release readiness | Product Owner with Engineering and Security approval |

## Decision Rules

- A decision owner may approve within their domain.
- A reviewer may block approval only within their review authority.
- Cross-domain decisions must identify all required approvers.
- A decision that changes scope must create or update tasks.
- A decision that changes a previous decision must reference the older decision record.
- A decision that affects users, customers, production, security, privacy, compliance, or external messaging must be recorded durably.

## Escalation Rules

Escalate when:

- two agents claim ownership of the same decision
- reviewers disagree on whether evidence is sufficient
- a task is blocked for more than the project-defined stale threshold
- a proposed change expands scope, risk, timeline, or external commitments
- sensitive data, regulated data, or customer data may be involved

## Blocked Claims

Every approval should state what it does not approve.

Examples:

- This approves internal prototype use only.
- This does not approve production launch.
- This does not approve use of customer data.
- This does not approve external claims about compliance.
- This does not approve implementation until security review is complete.
