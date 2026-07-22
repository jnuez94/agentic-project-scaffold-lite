.PHONY: test validate-skill

test:
	sh tests/install.sh

validate-skill:
	python3 scripts/validate-skill.py
