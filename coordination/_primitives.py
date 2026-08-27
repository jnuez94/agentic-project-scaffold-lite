"""Shared constants, the identifier pattern, `Params`, and the clock."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import re


SCHEMA_VERSION = 2

DEFAULT_BUSY_TIMEOUT_MS = 5000

MAX_BUSY_TIMEOUT_MS = 60000

MAX_IDENTIFIER_LENGTH = 128

MAX_TEXT_LENGTH = 65536

MAX_PATH_LENGTH = 4096

DEFAULT_LIST_LIMIT = 100

MAX_LIST_LIMIT = 500

MAX_IDENTIFIER_ARRAY_ITEMS = 500

MAX_STALE_DAYS = 3650

MAX_STALE_SESSION_MINUTES = 5_256_000

MAX_STALE_SECONDS = 315_360_000

MIN_STALE_SECONDS = 60

SESSION_LEASE_SECONDS = 3600

MAX_DIAGNOSTIC_FINDINGS = 100

MAX_AUDIT_CURSOR = 9_223_372_036_854_775_807

IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+-]*\Z")


class Params(argparse.Namespace):
    """Parameter bag the service hands to entity operations.

    Built by the service after validation; no parser is involved. It subclasses
    `argparse.Namespace` only for its typed dynamic attribute access, so entity
    functions depend on a neutral bag of validated values rather than on the
    CLI's parsing artifact (#25).
    """


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
