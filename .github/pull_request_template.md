## Summary


## Motivation


## Validation

- [ ] `make test`
- [ ] `make validate-skill`
- [ ] `python3 scripts/check-markdown-links.py`
- [ ] Documentation and examples remain free of sensitive data
- [ ] Clean installation and reinstall were verified when installation changed
- [ ] Multi-process and failure-path tests cover concurrency or maintenance changes

## Compatibility

- [ ] The core remains harness-agnostic, or tool-specific behavior is isolated to an adapter
- [ ] Breaking changes and migration requirements are identified
- [ ] The canonical runtime remains only under `coordination/`, `scripts/`, and `sqlite/`
- [ ] CLI syntax, JSON shapes, errors, exit codes, pagination, and actor/session semantics remain documented and tested
- [ ] Schema object definitions and backup/restore behavior remain documented and tested

## Release Evidence

- [ ] Version and changelog metadata are current when release-facing
- [ ] Release-readiness requirements map to concrete tests or reviewed files
- [ ] Remote state changes are explicitly requested and recorded
