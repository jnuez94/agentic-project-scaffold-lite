# Health Metrics

Health metrics tell the team whether the working model is keeping coordination clean or quietly decaying.

Run these checks at the start of a project, before major reviews, and before release.

## Coordination Health

| Metric | Warning Sign | Suggested Action |
| --- | --- | --- |
| Stale tasks | No update after the agreed stale threshold | Ask owner for status or reassign |
| Unowned tasks | Task has no assignee | Assign or close as invalid |
| In-progress overload | One agent has too many active tasks | Rebalance or split work |
| Duplicate work | Multiple tasks appear to cover the same outcome | Merge or clarify boundaries |
| Hidden dependencies | Task mentions waiting but has no dependency | Add explicit dependency |
| Review aging | Review task has no reviewer or no response | Assign reviewer and deadline |
| Done without evidence | Closed task has no artifact, test, review, or decision | Reopen or attach evidence |

## Decision Health

| Metric | Warning Sign | Suggested Action |
| --- | --- | --- |
| Ownerless decision | Decision record has no owner | Assign decision owner |
| Missing alternatives | Major decision lists no options considered | Add rationale |
| Reversed decision without reference | New direction conflicts with old record | Link and supersede old record |
| Approval mismatch | Decision was approved by someone without authority | Route to correct owner |

## Review Health

| Metric | Warning Sign | Suggested Action |
| --- | --- | --- |
| Review lacks scope | Reviewer did not say what they reviewed | Request scoped review |
| Acceptance lacks blocked claims | Approval could be read too broadly | Add blocked claims |
| Feedback has no follow-up task | Required change is buried in comments | Create task |
| Conflicting reviews | Reviewers disagree with no decision owner named | Escalate |

## Security And Privacy Health

| Metric | Warning Sign | Suggested Action |
| --- | --- | --- |
| Sensitive data in coordination records | Messages include real secrets, personal data, customer data, or regulated data | Remove if policy allows and file incident note |
| Undefined data policy | Project has no allowed/blocked data rules | Define before work continues |
| External sharing ambiguity | Artifact is shared externally without approval trail | Record approval and boundaries |
| Production implication | Demo or prototype language implies live readiness | Add blocked claims |

## Suggested Cadence

- Daily or per-session: stale tasks, overlap, blockers, review requests.
- Weekly: decision health, workload balance, duplicated work.
- Before external review: artifact evidence, blocked claims, sensitive-data check.
- Before release: full conformance and release readiness checklists.
