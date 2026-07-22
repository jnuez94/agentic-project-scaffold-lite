# Project Bootstrap

Use this when starting a new project with the Multi-Agent Working Model.

This prompt is optional. It is written so it can be adapted for Codex, another agent harness, or a human project lead.

## Bootstrap Prompt

```text
We are adopting the Multi-Agent Working Model for this project.

Read the local `agentic-project-scaffold-lite` guidance directory first:

- README.md
- SPEC.md
- QUICKSTART.md
- GOVERNANCE.md
- docs/decision-rights.md
- docs/health-metrics.md
- checklists/startup_checklist.md
- templates/

Then create the initial coordination records for this project:

1. Project goal and near-term deliverable
2. Hard boundaries and non-goals
3. Coordination substrate choice
4. Agent profiles
5. Decision-rights matrix
6. Sensitive-data rules
7. Initial task backlog
8. Review flow
9. Release readiness checklist

Keep the system harness-agnostic. Do not assume a specific tool unless the project has selected one.

Every active agent must check the coordination records before starting work, announce intent when overlap is possible, create tasks for self or others when needed, request role-appropriate review, and close work only with evidence.
```

## First Customizations

Replace the placeholders with project-specific answers:

- project name
- project goal
- near-term milestone
- agent names or role labels
- coordination substrate
- data policy
- release or demo boundary
- external sharing policy

## Keep These Invariant

- one canonical status vocabulary
- evidence-based completion
- durable decision records
- explicit review scope
- blocked claims on approvals
- sensitive-data hygiene
- role-based decision authority
