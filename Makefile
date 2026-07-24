.PHONY: test validate-skill check-links syntax artifact-check check release-check

test:
	sh tests/install.sh
	sh tests/sqlite.sh
	sh tests/cli-contract.sh
	sh tests/sqlite-concurrency.sh
	sh tests/sqlite-operations.sh
	sh tests/sqlite-stability.sh
	sh tests/sqlite-restore-qualification.sh

validate-skill:
	python3 scripts/validate-skill.py

check-links:
	python3 scripts/check-markdown-links.py

syntax:
	for script in $$(find scripts tests -type f -name '*.sh' -print); do \
		sh -n "$$script"; \
	done
	python3 -m compileall -q coordination
	python3 -m py_compile scripts/*.py tests/*.py

artifact-check:
	sh tests/release-artifact.sh

check: test validate-skill check-links syntax

release-check: check artifact-check
