.PHONY: test validate-skill check-links

test:
	sh tests/install.sh
	sh tests/sqlite.sh
	sh tests/cli-contract.sh
	sh tests/sqlite-concurrency.sh
	sh tests/sqlite-operations.sh

validate-skill:
	python3 scripts/validate-skill.py

check-links:
	python3 scripts/check-markdown-links.py
