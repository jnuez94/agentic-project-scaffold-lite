#!/usr/bin/env python3
"""Validate the bundled skill without third-party dependencies."""

from pathlib import Path
import re
import sys


skill_path = Path(__file__).resolve().parent.parent / "skills" / "agentic-project-scaffold-lite" / "SKILL.md"
text = skill_path.read_text(encoding="utf-8")
match = re.match(r"\A---\n(?P<header>.*?)\n---\n", text, flags=re.DOTALL)
if not match:
    sys.exit("SKILL.md is missing YAML frontmatter")

fields = {}
for line in match.group("header").splitlines():
    if ":" not in line:
        sys.exit(f"Invalid frontmatter line: {line}")
    key, value = line.split(":", 1)
    fields[key.strip()] = value.strip()

if set(fields) != {"name", "description"}:
    sys.exit("Skill frontmatter must contain only name and description")
if fields["name"] != "agentic-project-scaffold-lite":
    sys.exit("Skill name does not match its directory")
if not re.fullmatch(r"[a-z0-9-]{1,63}", fields["name"]):
    sys.exit("Skill name is invalid")
if not fields["description"]:
    sys.exit("Skill description is empty")

required = [
    skill_path.parent / "agents" / "openai.yaml",
    skill_path.parent / "references" / "spec.md",
    skill_path.parent / "references" / "decision-rights.md",
    skill_path.parent / "references" / "health-metrics.md",
    skill_path.parent / "assets" / "templates" / "task.md",
]
missing = [str(path.relative_to(skill_path.parent)) for path in required if not path.is_file()]
if missing:
    sys.exit("Missing skill resources: " + ", ".join(missing))

print(f"Skill validated: {skill_path.parent}")
