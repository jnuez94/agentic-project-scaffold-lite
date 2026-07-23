#!/usr/bin/env python3
"""Executable entry point for the entity-oriented coordination package."""

from pathlib import Path
import sys


here = Path(__file__).resolve().parent
for candidate in (here.parent, here.parent / "lib", here / "lib"):
    if (candidate / "coordination").is_dir():
        sys.path.insert(0, str(candidate))
        break
else:
    raise SystemExit("The coordination implementation package is not installed")

from coordination.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
