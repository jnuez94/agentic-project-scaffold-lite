# Release Readiness Checklist

Use this checklist for version 1.1.0 and later releases. Record a command,
test name, log, or reviewed file beside every checked item. Do not infer
qualification from a single aggregate test result.

## Release Identity

- [ ] `VERSION` contains exactly the intended stable semantic version.
- [ ] `CHANGELOG.md` has a dated entry for that version.
- [ ] `coordination version` reports the same CLI version and supported schema.
- [ ] Release notes contain no stale maturity or unsupported-capability
      language.
- [ ] Python 3.10 or newer is documented and tested as the minimum runtime.

## Public CLI Contract

- [ ] Every command, option, positional argument, choice, default, and
      repeatable option matches `docs/cli-contract.md`.
- [ ] Every success result matches the documented JSON field names, types,
      nullability, array ordering, and row ordering.
- [ ] Every expected failure uses the documented error code, exit code, stream,
      and details shape.
- [ ] Identifiers reject values outside the 128-character ASCII token grammar.
- [ ] Required text rejects empty and whitespace-only values.
- [ ] Text rejects NUL and values longer than 65,536 characters.
- [ ] Paths reject empty, whitespace-only, NUL, and values longer than 4,096
      characters.
- [ ] List commands enforce `--limit` default 100, maximum 500, and `--offset`
      default 0.
- [ ] Health enforces its bounded thresholds and reports every capped section
      in `truncated_sections`.
- [ ] Task assignees and artifact task/reviewer aggregates are JSON arrays for
      zero, one, and multiple related rows.
- [ ] Every mutation has an active accountable actor, with documented
      derivation where no `--actor` flag exists.
- [ ] A supplied global session is active and belongs to the mutation actor.

## Canonical Runtime And Installation

- [ ] Repository root `coordination/` is the sole executable implementation.
- [ ] The installed launcher loads only the sibling bundled
      `lib/coordination` package.
- [ ] No harness-specific executable copy exists.
- [ ] Codex, Claude, human, and service invocations use the same installed CLI
      and configured database in qualification fixtures.
- [ ] Installer rejects a missing target, non-directory target, unsafe source
      overlap, incompatible backend, invalid configuration, escaping database
      path, and invalid existing destination types.
- [ ] Installer and verifier resolve the same configured database path.
- [ ] Clean installation succeeds with and without a managed root agent file.
- [ ] Installation into a pre-existing project preserves user content.
- [ ] Nested project discovery selects the nearest valid configuration.
- [ ] Reinstall repairs incomplete managed blocks and installed runtime files.
- [ ] Reinstall preserves live SQLite state and is idempotent.
- [ ] Backend switching is rejected without explicit migration support.

## Schema And Database Semantics

- [ ] `sqlite/schema.sql` is schema version 1 and both schema-version sources
      agree.
- [ ] All documented tables, columns, types, nullability, defaults, checks,
      primary keys, foreign keys, indexes, and triggers match exactly.
- [ ] `init` creates only an empty schema or verifies an exact supported schema.
- [ ] Missing required objects and same-name/wrong-definition required objects
      are rejected.
- [ ] Older, newer, mismatched, and incomplete schemas are rejected without
      mutation.
- [ ] Foreign keys, WAL journal mode, and `FULL` synchronous durability are
      enabled for initialized operation.
- [ ] Textual primary keys and required identifiers reject null and blank
      values at the schema boundary.
- [ ] Evidence-gated completion, claim/session consistency, and revision
      triggers reject invalid direct writes.
- [ ] Schema version 1 is documented as the first supported schema; no
      pre-release migration is advertised.

## Concurrency And Publication

- [ ] Simultaneous claims produce exactly one winner and one documented
      conflict.
- [ ] An interrupted response can retry the winning claim idempotently.
- [ ] Competing revisions cannot silently overwrite committed state.
- [ ] Concurrent entity writes preserve all committed rows and audits.
- [ ] Lock timeout returns `database_busy` with exit code 6 and no partial
      mutation.
- [ ] Advisory locks serialize database maintenance against ordinary
      processes.
- [ ] Concurrent export or backup publication to one new path has exactly one
      winner without `--force`.
- [ ] Output publication does not overwrite a path created after the
      precondition check.
- [ ] Temporary files and locks do not leave a partially published artifact
      after an injected interruption.

## Backup, Restore, And Recovery

- [ ] Backup uses the online backup operation and validates schema, integrity,
      foreign keys, and coordination invariants before publication.
- [ ] Backup output is mode `0600`, atomic, verified, and no-clobber by default.
- [ ] Backup rejects paths that alias the live database, configuration, sidecar,
      lock, or another protected operational path.
- [ ] Restore requires `--force` and a non-empty active actor.
- [ ] Restore rejects missing, corrupt, incompatible, aliased, or invalid input
      before changing the target.
- [ ] Restore rejects every active target session and reports the sorted IDs.
- [ ] A healthy target receives a verified pre-restore safety backup.
- [ ] An unreadable target receives an atomic byte-preservation copy and
      reports `safety_backup_verified: false`.
- [ ] Restore audit is inserted and verified in staged state before
      publication.
- [ ] Successful restore atomically publishes verified staged state and reports
      `publication: "atomic_replace"`, `audit_recorded: true`,
      `rollback_performed: false`, and `verified: true`.
- [ ] Injected prepublication and publication failures leave the original
      target unchanged.
- [ ] Injected postpublication verification failure restores safety state and
      reports `restore_verification_failed` plus the rollback outcome.
- [ ] Recovery rejects a fresh or ended session and an empty explanation.
- [ ] Stale-session recovery blocks claimed tasks, increments revisions,
      appends the reason, removes claims, ends the session, and audits the
      intervention atomically.

## Output Integrity And Scale

- [ ] Markdown export escapes stored headings, list markers, code delimiters,
      links, and line breaks so records cannot alter report structure.
- [ ] Export without `--output` is Markdown only; file export returns JSON.
- [ ] Export and backup refuse an existing output unless `--force` is supplied.
- [ ] Task and artifact aggregates use independent queries and do not multiply
      associations or counts.
- [ ] Deterministic tie-breakers cover every list and nested result.
- [ ] Empty, one-row, page-boundary, maximum-page, offset-past-end, and
      over-limit cases are tested.
- [ ] Health returns bounded results with accurate truncation metadata at
      operational scale.

## Qualification Evidence

- [ ] `make test`
- [ ] `make validate-skill`
- [ ] `python3 scripts/check-markdown-links.py`
- [ ] Contract tests cover every command's success shape and stable expected
      failure.
- [ ] Installer tests cover clean, existing, nested, repaired, and repeated
      installations.
- [ ] Concurrency tests use multiple operating-system processes.
- [ ] Failure-injection tests cover interrupted export, backup, restore,
      publication, verification, and rollback.
- [ ] A fresh temporary SQLite installation passes `version`, `doctor`,
      lifecycle, backup, restore, recovery, reinstall, and verifier checks.
- [ ] The final worktree diff contains only intended release changes.
- [ ] Exactly one pull-request commit exists; every update used
      `git commit --amend`.
- [ ] No remote state was changed during qualification without explicit
      approval.

## Release Decision

- [ ] Open blockers are resolved or explicitly accepted by the release owner.
- [ ] Required product, engineering, documentation, and QA acceptance is
      recorded.
- [ ] User-facing limitations and sensitive-data boundaries are current.
- [ ] The release owner reviewed concrete evidence for every 1.1.0 requirement.
- [ ] The release owner recorded the final go/no-go decision.
