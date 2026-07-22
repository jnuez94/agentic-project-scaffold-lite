# Multi-Agent Project Working Model Specification

Version: 1.0

Status: Open-source project seed

Purpose: Define a harness-agnostic operating model for multiple AI or human-assisted agents working on the same project.

## 1. Intent

This specification describes how a small multi-agent team can coordinate product, design, engineering, security, research, QA, documentation, and delivery work on a shared project without depending on a specific agent harness, chat product, IDE, workflow tool, issue tracker, or database.

The model assumes:

- multiple agents may work asynchronously
- agents may have specialized roles
- work may happen in the same repository, document set, issue tracker, or shared workspace
- the team needs durable communication, task state, review evidence, and decision history
- the system should preserve ownership and accountability even when agents are autonomous

## 2. Core Principles

### 2.1 Shared Source Of Coordination Truth

Every project needs a durable coordination layer that records:

- active agents
- roles
- tasks
- messages
- review requests
- decisions
- blockers
- dependencies
- evidence
- status changes

The coordination layer can be a SQLite database, issue tracker, markdown log, message queue, project-management API, GitHub Issues, Linear, Jira, Notion database, or another persistent system.

The tool does not matter. The contract does.

### 2.2 Role Clarity Before Work Starts

Every agent must have a named role, responsibility boundary, goal, operating style, decision authority, and review authority.

Agents may wear multiple functional hats, but those hats must be explicit.

### 2.3 Check Before Acting

Before starting work, each agent checks the coordination layer for:

- new messages
- assigned tasks
- review requests
- blockers
- overlapping work
- dependency changes
- decisions that affect scope

If overlap or conflict is possible, the agent posts intent before acting.

### 2.4 Durable Decisions Over Chat Memory

Important decisions must be recorded in durable project artifacts or coordination records.

Transient chat history is not the source of truth.

### 2.5 Evidence-Based Completion

No task should be marked complete because an agent believes it is done.

Completion requires evidence appropriate to the task type:

- artifact path
- design review
- test output
- implementation commit
- security review
- acceptance note
- demo dry run
- stakeholder approval
- release checklist

### 2.6 Explicit Boundaries

Every task and review should identify what it does not approve.

Examples:

- This does not approve production launch.
- This does not approve customer-data use.
- This does not trigger implementation.
- This is internal review only.

## 3. Required Project Records

### 3.1 Agent Profile

```yaml
agent:
  id: string
  name: string
  role: string
  responsibilities:
    - string
  goal: string
  operating_style:
    - string
  decision_authority:
    - string
  review_authority:
    - string
  escalation_rules:
    - string
```

### 3.2 Task

```yaml
task:
  id: string
  title: string
  description: string
  status: todo | in_progress | review | blocked | done
  assignees:
    - agent_id
  priority: 1-5
  tags:
    - string
  dependencies:
    - task_id
  next_steps:
    - string
  acceptance_criteria:
    - string
  evidence:
    - string
  blocked_claims:
    - string
  notes:
    - string
  created_at: timestamp
  updated_at: timestamp
  created_by: agent_id
```

### 3.3 Message

```yaml
message:
  id: string
  timestamp: timestamp
  sender: agent_id
  recipients:
    - agent_id | team | role
  task_id: string | null
  tags:
    - string
  body: string
```

Messages should be concise but complete enough for another agent to act without rereading a long conversation.

### 3.4 Review Record

```yaml
review:
  id: string
  reviewer: agent_id
  artifact: string
  scope: string
  decision: accepted | conditionally_accepted | changes_requested | rejected
  accepted_items:
    - string
  required_changes:
    - string
  blocked_claims:
    - string
  remaining_risks:
    - string
  follow_up_tasks:
    - task_id
  created_at: timestamp
```

### 3.5 Decision Record

```yaml
decision:
  id: string
  title: string
  owner: agent_id
  date: date
  context: string
  decision: string
  options_considered:
    - option: string
      outcome: selected | rejected | deferred
      reason: string
  implications:
    - string
  blocked_claims:
    - string
  review_required:
    - agent_id | role
```

### 3.6 Artifact Record

```yaml
artifact:
  path_or_uri: string
  owner: agent_id
  type: string
  status: draft | review | accepted | superseded
  related_tasks:
    - task_id
  reviewers:
    - agent_id
  last_updated: timestamp
```

## 4. Status Model

| Status | Meaning |
| --- | --- |
| `todo` | Work is identified but not actively started. |
| `in_progress` | An agent is actively working on it. |
| `review` | Work exists and is waiting for one or more review decisions. |
| `blocked` | Work cannot proceed without a specific dependency, decision, or external event. |
| `done` | Work is complete and supported by evidence. |

Rules:

- Use `done` as the only terminal success state.
- Do not use both `done` and `completed`.
- If imported systems require multiple closed states, map them into one canonical status for coordination.

## 5. Team Operating Loop

Every agent follows this loop:

1. Sync coordination state.
2. Select work based on priority, ownership, blockers, and goal alignment.
3. Announce intent when overlap, scope change, or shared artifact risk exists.
4. Produce artifact, code, review, test result, decision, or evidence.
5. Request review with artifact, evidence, requested decision, and blocked claims.
6. Integrate feedback explicitly.
7. Close only with evidence.

## 6. Role Model

A small team can assign multiple role archetypes to the same agent.

### Product Owner

Owns:

- vision
- scope
- prioritization
- requirements
- market or stakeholder strategy
- acceptance decisions
- workload balance
- final product decision

### Design Owner

Owns:

- user flows
- information architecture
- interaction design
- accessibility expectations
- user-facing language
- usability review
- experience QA

### Engineering Owner

Owns:

- implementation
- architecture execution
- technical design
- tests
- data model
- APIs
- frontend/backend delivery
- technical evidence

### Security/Privacy Owner

Owns:

- security requirements
- privacy boundaries
- data handling rules
- access control review
- incident handling
- infrastructure/security gates
- launch risk signoff

### Infrastructure Owner

Owns:

- deployment
- CI/CD
- environment readiness
- infrastructure-as-code
- observability
- rollback
- runtime runbooks

### QA Owner

Owns:

- test strategy
- regression evidence
- acceptance evidence
- workflow verification
- usability checks
- accessibility checks
- release confidence

## 7. Decision Rights

Every project should define who can approve:

- scope changes
- new tasks
- release readiness
- external use
- production launch
- customer-data use
- security risk acceptance
- architecture changes
- UX acceptance
- task closure

See [decision-rights.md](decision-rights.md).

## 8. Review Protocol

Reviews should be explicit and scoped.

A review should answer:

- What artifact or change was reviewed?
- What was the review lens?
- What is accepted?
- What is conditionally accepted?
- What blocks external use, release, production, or customer exposure?
- What follow-up tasks are required?

Review decisions:

| Decision | Meaning |
| --- | --- |
| `accepted` | Usable for the stated scope. |
| `conditionally_accepted` | Usable internally or for limited scope, but not for broader claims. |
| `changes_requested` | Needs revision before use. |
| `rejected` | Direction is not acceptable. |

## 9. Communication Rules

Use messages for:

- review requests
- decisions
- task handoffs
- blocker notices
- scope changes
- acceptance notes
- status broadcasts

A broadcast should include:

- decision
- artifacts
- affected tasks
- requested reviews
- blocked claims
- next steps

Do not use messages as a dumping ground for raw work, sensitive data, or long unstructured transcripts.

## 10. Dependency Model

```yaml
dependency:
  task_id: string
  depends_on_task_id: string
  dependency_type: blocks | informs | review_required | evidence_required
  status: active | resolved
  rationale: string
```

## 11. Artifact Lifecycle

Recommended lifecycle:

1. `draft`
2. `review`
3. `accepted`
4. `superseded`

Rules:

- Do not delete old artifacts unless there is a privacy/security reason.
- Prefer versioning or dated filenames.
- Every accepted artifact should list owner, status, scope, and review cycles.
- Every artifact that limits scope should state what it does not approve.

## 12. Workload Balance

One agent should own coordination health.

This owner ensures:

- every agent has useful work
- blockers are visible
- overloaded agents get support
- ambiguous work is triaged
- new tasks have owners
- work aligns with the project goal

This is usually the product owner, project lead, or delivery lead.

## 13. Harness-Agnostic Requirements

A compliant harness needs only:

- persistent task records
- persistent message records
- agent identity or role labels
- artifact references
- status updates
- timestamped history
- review records or equivalent messages
- dependency tracking or dependency notes

Optional capabilities:

- SQL database
- issue tracker integration
- Git integration
- notification routing
- UI dashboard
- automation hooks
- file attachment support
- test-result ingestion

## 14. Sensitive Data Rule

For any project with sensitive data, regulated data, customer data, secrets, credentials, or proprietary information:

- define allowed data
- define blocked data
- define storage locations
- define incident handling
- define redaction rules
- define review owners
- define external-use gates

Never let the coordination layer become an accidental sensitive-data store.

## 15. Completion Standard

A task can move to `done` only when:

- acceptance criteria are met
- required reviewers accepted
- evidence is linked
- remaining work is moved into separate tasks
- no blocked claim is implied
- artifact or code state is current

If any of those are missing, use `review`, `todo`, or `blocked`.

## 16. Portable Operating Agreement

Every agent agrees to:

- check coordination state before starting work
- respect role boundaries
- post intent when overlap is likely
- create durable artifacts for durable decisions
- request review before claiming readiness
- state blocked claims explicitly
- keep sensitive data out of coordination records
- close work only with evidence
- create follow-up tasks instead of burying gaps
- keep the project goal above local task optimization
