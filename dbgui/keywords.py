"""Keyword based information: the GUI's reading and writing of keyword_info.

Each row is one piece of information the applicant wants the generators to
know about, plus the keywords that trigger it. When any of an entry's keywords
appears in a listing's job description, the bot adds the information to what it
tells the model while writing the cover letter, work history, summary, headline,
skills, and screener answers. The matching and the prompt side live in the
top-level keyword_info.py, which reads the same table with raw sqlite3 the way
the other bot-side loaders do.

Follows dbgui/outcomes.py's precedent of a module owning its own SQL against
db._connect() rather than growing data.py, which is over its size limit.
"""

from __future__ import annotations

import datetime
import json
from contextlib import contextmanager
from typing import Any, Iterator

from .data import IndeedDB
from .migrations import ensure_keyword_info_schema, keyword_info_schema_exists


def _now() -> str:
    return datetime.datetime.now().isoformat(" ", "seconds")


@contextmanager
def _open(db: IndeedDB) -> Iterator[Any]:
    """Commit on success and always close.

    `with sqlite3.connect(...)` commits but does not close, and on Windows the
    unclosed handle keeps the file locked.

    Also creates the table if it is missing, so the tab works however the
    server was started (db_admin.py already does this on startup).
    """
    conn = db._connect()
    try:
        with conn:
            if not keyword_info_schema_exists(conn):
                db._ensure_backup()
                ensure_keyword_info_schema(conn)
            yield conn
    finally:
        conn.close()


def normalize_keywords(raw: Any) -> list[str]:
    """A clean, de-duplicated keyword list from a list or a comma-separated string.

    Whitespace inside a keyword is collapsed, empties are dropped, and
    duplicates are removed case-insensitively keeping the first spelling.
    Items of a list are kept whole (a deliberate list element is one keyword,
    even if it contains a comma); only a plain string is split on commas.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        parts = []
        for item in raw:
            if not isinstance(item, str):
                raise ValueError(f"Keywords must be text, not {type(item).__name__}.")
            parts.append(item)
    else:
        raise ValueError("Keywords must be a list or a comma separated string.")

    seen: set[str] = set()
    keywords: list[str] = []
    for part in parts:
        word = " ".join(part.split())
        if not word or word.lower() in seen:
            continue
        seen.add(word.lower())
        keywords.append(word)
    return keywords


def _decode(row: Any) -> dict[str, Any]:
    try:
        keywords = json.loads(row["keywords"] or "[]")
    except (TypeError, ValueError):
        keywords = []
    if not isinstance(keywords, list):
        keywords = []
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "keywords": [str(word) for word in keywords],
        "info": row["info"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_entries(db: IndeedDB, user_id: int) -> list[dict[str, Any]]:
    with _open(db) as conn:
        rows = conn.execute(
            "SELECT * FROM keyword_info WHERE user_id = ? ORDER BY id", (user_id,)
        ).fetchall()
    return [_decode(row) for row in rows]


def get_entry(db: IndeedDB, entry_id: int) -> dict[str, Any] | None:
    with _open(db) as conn:
        row = conn.execute(
            "SELECT * FROM keyword_info WHERE id = ?", (entry_id,)
        ).fetchone()
    return _decode(row) if row else None


def create_entry(db: IndeedDB, user_id: int, keywords: Any = None, info: str = "") -> int:
    """Insert one entry and return its id. A blank entry is valid: with no
    keywords it can never match, so the tab's Add button can create one and let
    the user fill it in."""
    cleaned = normalize_keywords(keywords)
    db._ensure_backup()
    stamp = _now()
    with _open(db) as conn:
        cursor = conn.execute(
            "INSERT INTO keyword_info (user_id, keywords, info, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, json.dumps(cleaned), str(info or ""), stamp, stamp),
        )
        return int(cursor.lastrowid)


def save_entry(db: IndeedDB, entry_id: int, values: dict[str, Any]) -> bool:
    """Update the whitelisted fields present in `values`.

    Returns False when the entry does not exist. Raises ValueError on a bad
    keywords payload.
    """
    payload: dict[str, Any] = {}
    if "keywords" in values:
        payload["keywords"] = json.dumps(normalize_keywords(values["keywords"]))
    if "info" in values:
        payload["info"] = str(values["info"] or "")
    if not payload:
        return get_entry(db, entry_id) is not None

    db._ensure_backup()
    payload["updated_at"] = _now()
    assignments = ", ".join(f"{column} = ?" for column in payload)
    with _open(db) as conn:
        cursor = conn.execute(
            f"UPDATE keyword_info SET {assignments} WHERE id = ?",
            (*payload.values(), entry_id),
        )
        return cursor.rowcount > 0


def delete_entry(db: IndeedDB, entry_id: int) -> bool:
    db._ensure_backup()
    with _open(db) as conn:
        cursor = conn.execute("DELETE FROM keyword_info WHERE id = ?", (entry_id,))
        return cursor.rowcount > 0
