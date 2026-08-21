"""Persistent update and archive state for structured thread exports."""

from __future__ import annotations

from typing import Any


ARCHIVE_AFTER_NOT_FOUND = 2


def normalize_update_state(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    state = source.get("state")
    if state not in {"active", "check_failed", "archived"}:
        state = "active"
    count = source.get("consecutive_not_found", 0)
    if not isinstance(count, int) or count < 0:
        count = 0
    return {
        "state": state,
        "last_checked_at": source.get("last_checked_at"),
        "last_success_at": source.get("last_success_at"),
        "last_error": source.get("last_error"),
        "consecutive_not_found": count,
        "archived_at": source.get("archived_at"),
        "archive_reason": source.get("archive_reason"),
    }


def mark_update_success(previous: object, checked_at: str) -> dict[str, Any]:
    state = normalize_update_state(previous)
    state.update(
        {
            "state": "active",
            "last_checked_at": checked_at,
            "last_success_at": checked_at,
            "last_error": None,
            "consecutive_not_found": 0,
            "archived_at": None,
            "archive_reason": None,
        }
    )
    return state


def mark_update_failure(
    previous: object,
    *,
    checked_at: str,
    message: str,
    confirmed_not_found: bool,
) -> dict[str, Any]:
    state = normalize_update_state(previous)
    if state["state"] == "archived":
        state["last_checked_at"] = checked_at
        state["last_error"] = message
        return state

    count = (
        state["consecutive_not_found"] + 1 if confirmed_not_found else 0
    )
    archived = count >= ARCHIVE_AFTER_NOT_FOUND
    state.update(
        {
            "state": "archived" if archived else "check_failed",
            "last_checked_at": checked_at,
            "last_error": message,
            "consecutive_not_found": count,
            "archived_at": checked_at if archived else None,
            "archive_reason": (
                "current_and_legacy_not_found" if archived else None
            ),
        }
    )
    return state
