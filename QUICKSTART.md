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

The installer uses Markdown by default:

```sh
./scripts/install.sh --target /path/to/project --adapter markdown
```

For participants that all share one local project directory, the supported
SQLite backend provides validated, atomic coordination and requires Python 3.10
or newer:

```sh
./scripts/install.sh --target /path/to/project --adapter sqlite
```

The working model can also be adapted to:

- markdown files
- SQLite database
- GitHub Issues
- Linear
- Jira
- Notion database
- another persistent system

Select exactly one source of coordination truth. Do not use Markdown and
SQLite as independent coordination stores for the same project.

After a SQLite installation, verify it and run the installed CLI from the
project root:

```sh
./scripts/verify-install.sh /path/to/project
cd /path/to/project
./.agents/agentic-project-scaffold-lite/bin/coordination version
./.agents/agentic-project-scaffold-lite/bin/coordination doctor
```

The installed launcher always imports the bundled copy of the repository's
canonical `coordination/` runtime. Every local harness, person, and service
must use this executable and the database named by `.coordination/config.yml`
instead of importing or copying the implementation.

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

With SQLite, register the durable actor independently from its execution
environment, then start a unique session for each run:

```sh
tool=./.agents/agentic-project-scaffold-lite/bin/coordination

"$tool" agent add \
  --id engineering-1 \
  --name "Engineering 1" \
  --role engineering \
  --actor-type ai

"$tool" session start \
  --id engineering-1-run-001 \
  --agent engineering-1 \
  --harness local-agent \
  --model model-name

export COORDINATION_SESSION=engineering-1-run-001
```

Keep `engineering-1` stable if the harness or model changes. End the session
when the run finishes:

```sh
"$tool" session end engineering-1-run-001
```

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

For SQLite:

```sh
"$tool" doctor
"$tool" health --stale-days 7 --stale-session-minutes 60
```

Use `doctor` for installation, schema, integrity, and operational diagnostics.
Use `health` for bounded coordination findings; inspect
`data.truncated_sections` before treating an empty tail as complete.

Look for:

- stale tasks
- blocked tasks with no unblocker
- review tasks with no reviewer
- done tasks with no evidence
- decisions with no owner
- duplicate work
- sensitive data in coordination records
