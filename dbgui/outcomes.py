"""Reading and writing application_events -- the outcome log.

stats.py only ever reads. This module owns the writes, and the review queue that
sits between automated capture and the log.

Two rules shape the design:

1. NOTHING IS GUESSED INTO THE LOG. An automated capture that cannot be tied to a
   specific application with confidence lands in capture_items for a human to
   resolve, never in application_events. The log is meant to be trustworthy
   enough to compute rates from; a wrong row there is worse than a missing one.

2. REJECTING A CAPTURED EVENT IS REMEMBERED. Deleting an event that came from a
   capture also marks its capture_item 'rejected', because the next sync would
   otherwise re-create the row it just deleted -- the partial unique index only
   stops duplicates while the event still exists.

Follows dbgui/runner.py's precedent of a module owning its own SQL against
db._connect() rather than growing data.py, which is at its size limit.
"""

from __future__ import annotations

import datetime
from typing import Any

from .data import IndeedDB
from .stats import STAGE_LABELS, STAGE_RANK, TIMESTAMP_FORMAT, parse_timestamp

MANUAL_SOURCE = "manual"

# Off-ladder outcomes, which can arrive from any stage.
TERMINAL_LABELS = {
    "rejected": "Rejected",
    "withdrawn": "Withdrawn (by me)",
}

EVENT_TYPES: tuple[str, ...] = tuple(STAGE_RANK) + tuple(TERMINAL_LABELS)

ALL_LABELS: dict[str, str] = {**STAGE_LABELS, **TERMINAL_LABELS}

# What a human may resolve a review item to, in ladder order then terminals.
REVIEW_STATES = ("pending", "matched", "ambiguous", "unmatched", "ignored",
                 "confirmed", "rejected")

# The states that still want a human's attention.
OPEN_REVIEW_STATES = ("pending", "ambiguous", "unmatched")


def event_choices() -> list[dict[str, Any]]:
    """The stages a human can record, for the UI's buttons."""
    ladder = sorted(STAGE_RANK, key=lambda key: STAGE_RANK[key])
    return (
        [{"value": key, "label": STAGE_LABELS[key], "rank": STAGE_RANK[key],
          "terminal": False} for key in ladder]
        + [{"value": key, "label": label, "rank": 0, "terminal": True}
           for key, label in TERMINAL_LABELS.items()]
    )


def normalise_timestamp(value: Any) -> str:
    """Accept 'YYYY-MM-DD' or a full timestamp; return the stored format.

    A bare date becomes midday rather than midnight: these are recorded by hand
    after the fact, and midday keeps a same-day outcome from landing *before* the
    application it belongs to and computing a negative time-to-response.
    """
    text = (str(value or "")).strip()
    if not text:
        return datetime.datetime.now().strftime(TIMESTAMP_FORMAT)
    if len(text) == 10:
        try:
            datetime.datetime.strptime(text, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Not a date: {text!r}") from exc
        return f"{text} 12:00:00"
    parsed = parse_timestamp(text)
    if parsed is None:
        raise ValueError(f"Not a timestamp: {text!r}")
    return parsed.strftime(TIMESTAMP_FORMAT)


def _application_owner(conn, application_id: int) -> int | None:
    row = conn.execute(
        "SELECT user_id FROM applications WHERE id = ?", (application_id,)).fetchone()
    return None if row is None else row["user_id"]


def add_manual_event(
    db: IndeedDB,
    application_id: int,
    event_type: str,
    *,
    occurred_at: Any = None,
    note: str = "",
) -> dict[str, Any]:
    """Record one outcome by hand. Raises ValueError on bad input."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown outcome: {event_type!r}")
    when = normalise_timestamp(occurred_at)

    db._ensure_backup()
    with db._connect() as conn:
        owner = _application_owner(conn, application_id)
        if owner is None:
            raise ValueError(f"No application with id {application_id}")

        applied = conn.execute(
            "SELECT DateTime FROM applications WHERE id = ?", (application_id,)
        ).fetchone()["DateTime"]
        applied_at = parse_timestamp(applied)
        if applied_at and parse_timestamp(when) and parse_timestamp(when) < applied_at:
            raise ValueError(
                f"That is before the application was submitted ({applied[:10]}).")

        cursor = conn.execute(
            "INSERT INTO application_events (user_id, application_id, event_type, "
            "occurred_at, source, confidence, external_id, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1.0, NULL, ?, ?)",
            (int(owner), application_id, event_type, when, MANUAL_SOURCE, note or "",
             datetime.datetime.now().strftime(TIMESTAMP_FORMAT)),
        )
        return {"id": int(cursor.lastrowid), "application_id": application_id,
                "event_type": event_type, "occurred_at": when, "source": MANUAL_SOURCE,
                "note": note or ""}


def delete_event(db: IndeedDB, event_id: int) -> bool:
    """Remove one event. Returns False if it was already gone.

    If the event came from a capture, its capture_item is marked 'rejected' so the
    next sync does not simply recreate it -- the unique index only prevents a
    duplicate while the original row still exists.
    """
    db._ensure_backup()
    with db._connect() as conn:
        row = conn.execute(
            "SELECT user_id, external_id, source FROM application_events WHERE id = ?",
            (event_id,)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM application_events WHERE id = ?", (event_id,))
        if row["external_id"]:
            conn.execute(
                "UPDATE capture_items SET match_state = 'rejected' "
                "WHERE user_id = ? AND external_id = ?",
                (row["user_id"], row["external_id"]))
        return True


def list_events_for_application(db: IndeedDB, application_id: int) -> list[dict[str, Any]]:
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT id, event_type, occurred_at, source, confidence, note "
            "FROM application_events WHERE application_id = ? "
            "ORDER BY occurred_at, id", (application_id,)).fetchall()
    return [dict(row) | {"label": ALL_LABELS.get(row["event_type"], row["event_type"])}
            for row in rows]


def recent_events(db: IndeedDB, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """The newest outcomes for one user, with enough application context to read."""
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT application_events.id, application_events.application_id, "
            "application_events.event_type, application_events.occurred_at, "
            "application_events.source, application_events.note, "
            "applications.companyName, applications.jobTitle "
            "FROM application_events "
            "LEFT JOIN applications ON applications.id = application_events.application_id "
            "WHERE application_events.user_id = ? "
            "ORDER BY application_events.occurred_at DESC, application_events.id DESC "
            "LIMIT ?", (user_id, int(limit))).fetchall()
    return [dict(row) | {"label": ALL_LABELS.get(row["event_type"], row["event_type"])}
            for row in rows]


def review_queue(db: IndeedDB, user_id: int, limit: int = 100) -> list[dict[str, Any]]:
    """Captured items that still need a human decision.

    Empty until a capture source is running -- which is the correct empty state,
    not an error.
    """
    placeholders = ",".join("?" for _ in OPEN_REVIEW_STATES)
    with db._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM capture_items WHERE user_id = ? "
            f"AND match_state IN ({placeholders}) "
            "ORDER BY observed_at DESC, id DESC LIMIT ?",
            (user_id, *OPEN_REVIEW_STATES, int(limit))).fetchall()
    return [dict(row) for row in rows]


def review_counts(db: IndeedDB, user_id: int) -> dict[str, int]:
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT match_state, COUNT(*) AS n FROM capture_items "
            "WHERE user_id = ? GROUP BY match_state", (user_id,)).fetchall()
    counts = {row["match_state"]: int(row["n"]) for row in rows}
    counts["open"] = sum(counts.get(state, 0) for state in OPEN_REVIEW_STATES)
    return counts


def resolve_item(
    db: IndeedDB,
    item_id: int,
    *,
    application_id: int | None = None,
    event_type: str | None = None,
    ignore: bool = False,
) -> dict[str, Any]:
    """Settle one review item: either attach it to an application, or ignore it.

    Ignoring is a real answer, not a deferral -- job alerts and newsletters that
    slipped past the classifier belong here, and marking them keeps them from
    coming back on the next sync.
    """
    db._ensure_backup()
    with db._connect() as conn:
        item = conn.execute(
            "SELECT * FROM capture_items WHERE id = ?", (item_id,)).fetchone()
        if item is None:
            raise ValueError(f"No review item with id {item_id}")

        if ignore:
            conn.execute(
                "UPDATE capture_items SET match_state = 'ignored' WHERE id = ?", (item_id,))
            return {"id": item_id, "match_state": "ignored"}

        if application_id is None:
            raise ValueError("Pick an application, or ignore the item.")
        chosen_type = event_type or item["classified_type"]
        if chosen_type not in EVENT_TYPES:
            raise ValueError(f"Unknown outcome: {chosen_type!r}")

        owner = _application_owner(conn, application_id)
        if owner is None:
            raise ValueError(f"No application with id {application_id}")
        if int(owner) != int(item["user_id"]):
            raise ValueError("That application belongs to a different user.")

        # Confirmed by a human, so confidence is 1.0 whatever the classifier said.
        # external_id is carried over so a re-sync recognises this as already handled.
        conn.execute(
            "INSERT OR IGNORE INTO application_events (user_id, application_id, "
            "event_type, occurred_at, source, confidence, external_id, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1.0, ?, ?, ?)",
            (int(item["user_id"]), application_id, chosen_type, item["observed_at"],
             item["source"], item["external_id"], "confirmed in review",
             datetime.datetime.now().strftime(TIMESTAMP_FORMAT)),
        )
        conn.execute(
            "UPDATE capture_items SET match_state = 'confirmed', application_id = ?, "
            "classified_type = ?, classifier = 'manual', confidence = 1.0 WHERE id = ?",
            (application_id, chosen_type, item_id))
        return {"id": item_id, "match_state": "confirmed",
                "application_id": application_id, "event_type": chosen_type}
