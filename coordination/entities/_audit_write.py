"""Audited redaction of ledger rows.

Redaction is the ledger's only admitted mutation: it appends a redaction
event, then rewrites the target's free text to the sentinel naming that
event, so the removal itself is permanently attributable.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from coordination.core import Params, audit, require_row, transaction
from coordination.errors import EXIT_CONFLICT, fail


REDACTION_SENTINEL = "[redacted:{}]"


def redact(connection: sqlite3.Connection, params: Params) -> dict[str, Any]:
    """Redact one audit row's detail and its change rows, leaving a tombstone."""
    with transaction(connection):
        target = require_row(
            connection,
            "SELECT id, detail FROM audit_log WHERE id = ?",
            (params.audit_id,),
            f"audit row {params.audit_id}",
        )
        if str(target["detail"]).startswith("[redacted:"):
            fail(
                "already_redacted",
                f"Audit row {params.audit_id} is already redacted",
                EXIT_CONFLICT,
                {"audit_id": params.audit_id},
            )
        redaction_id = audit(
            connection,
            params.actor,
            "redact",
            "audit",
            str(params.audit_id),
            params.reason,
            session_id=params.session,
        )
        sentinel = REDACTION_SENTINEL.format(redaction_id)
        connection.execute(
            "UPDATE audit_log SET detail = ? WHERE id = ?",
            (sentinel, params.audit_id),
        )
        cursor = connection.execute(
            "UPDATE change_log SET old_value = ?, new_value = ? WHERE audit_id = ?",
            (sentinel, sentinel, params.audit_id),
        )
    return {
        "id": params.audit_id,
        "redaction_id": redaction_id,
        "change_rows_redacted": cursor.rowcount,
    }
