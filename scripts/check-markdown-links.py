#!/usr/bin/env python3
"""Check repository-local Markdown links without external dependencies."""

from pathlib import Path
import re
import sys


repository = Path(__file__).resolve().parent.parent
pattern = re.compile(r"\]\(([^)]+)\)")
# Only repository-owned Markdown is part of the contract. Virtual environments,
# build output, and vendored dependencies carry unrelated documents whose links
# must not decide whether this repository passes.
excluded_directories = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".release-dist",
        ".ruff_cache",
        ".tox",
        ".venv",
        "build",
        "dist",
        "htmlcov",
        "node_modules",
        "site-packages",
        "venv",
    }
)
missing: list[str] = []

for document in repository.rglob("*.md"):
    parts = set(document.relative_to(repository).parts)
    if parts & excluded_directories or any(
        part.endswith(".egg-info") for part in parts
    ):
        continue
    for link in pattern.findall(document.read_text(encoding="utf-8")):
        if link.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path_text = link.split("#", 1)[0].strip("<>")
        if path_text and not (document.parent / path_text).resolve().exists():
            missing.append(f"{document.relative_to(repository)}: {link}")

if missing:
    print("Missing local Markdown links:", file=sys.stderr)
    print("\n".join(missing), file=sys.stderr)
    raise SystemExit(1)

print("Local Markdown links validated")
