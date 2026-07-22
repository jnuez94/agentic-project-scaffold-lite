# Quickstart

Use this guide to start a new project with the Multi-Agent Working Model in about 30 minutes.

## Step 1: Define The Project Goal

Create a short project goal:

```text
The project exists to...
```

Add:

- current priority
- near-term deliverable
- hard boundaries
- what must not be implied

## Step 2: Choose A Coordination Substrate

Pick one:

- markdown files
- SQLite database
- GitHub Issues
- Linear
- Jira
- Notion database
- another persistent system

Minimum requirements:

- tasks
- messages
- statuses
- owners
- artifact references
- timestamped history

## Step 3: Create Agent Profiles

Start with these roles:

- Product Owner
- Design Owner
- Engineering Owner
- Security/Privacy Owner

One person or agent may own multiple roles.

Use [templates/agent_profile.md](templates/agent_profile.md).

## Step 4: Define Decision Rights

Fill out:

[docs/decision-rights.md](docs/decision-rights.md)

At minimum, decide who can approve:

- scope
- external use
- production launch
- sensitive-data access
- security risk
- UX acceptance
- task closure

## Step 5: Create Initial Tasks

Create 5-10 starter tasks:

- project baseline
- product requirements
- design direction
- architecture direction
- security/privacy baseline
- first release plan
- demo or validation plan
- test/QA strategy

Use [templates/task.md](templates/task.md).

## Step 6: Define Sensitive-Data Rules

Even if the project seems harmless, define:

- allowed data
- blocked data
- where records live
- what cannot be stored in coordination messages
- incident response owner

## Step 7: Start The Agent Loop

Each agent does:

1. Sync latest tasks and messages.
2. Pick work by priority and ownership.
3. Announce intent if overlap is possible.
4. Produce artifact or evidence.
5. Request review.
6. Integrate feedback.
7. Close only with evidence.

## Step 8: Run A Health Check

Use:

[docs/health-metrics.md](docs/health-metrics.md)

Look for:

- stale tasks
- blocked tasks with no unblocker
- review tasks with no reviewer
- done tasks with no evidence
- decisions with no owner
- duplicate work
- sensitive data in coordination records
