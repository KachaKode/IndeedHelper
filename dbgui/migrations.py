"""Schema migration: users.homePage blob -> job_searches table.

The legacy format packs every job search for a user into one column: lines
separated by CRLF, each line "<url> <jobNums> <eduNums>" split on single spaces.
Line order is behavioural -- IndeedHelper.getProfileGen() cycles the parsed list
and startup takes profiles[0] -- so `position` preserves it exactly.

users.homePage is NOT dropped. It stays as the audit trail and rollback path;
the migration is idempotent and simply skips users that already have rows.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .data import IndeedDB, parse_home_page, format_home_page, SearchRow


CREATE_JOB_SEARCHES = """
CREATE TABLE IF NOT EXISTS job_searches (
    id       INTEGER PRIMARY KEY,
    user_id  INTEGER NOT NULL,
    position INTEGER NOT NULL,
    url      TEXT NOT NULL,
    job_nums TEXT DEFAULT '',
    edu_nums TEXT DEFAULT ''
)
"""

CREATE_JOB_SEARCHES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_job_searches_user
    ON job_searches (user_id, position)
"""


def schema_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='job_searches'"
    ).fetchone()
    return row is not None


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_JOB_SEARCHES)
    conn.execute(CREATE_JOB_SEARCHES_INDEX)


def rows_to_search_objects(rows: list[dict[str, Any]]) -> list[SearchRow]:
    return [
        SearchRow(url=r["url"], job_nums=r["job_nums"] or "", edu_nums=r["edu_nums"] or "")
        for r in rows
    ]


def migrate(db: IndeedDB, *, dry_run: bool = False) -> dict[str, Any]:
    """Populate job_searches from users.homePage.

    Idempotent: a user that already has job_searches rows is left alone.
    Returns a report describing what happened per user.
    """
    report: dict[str, Any] = {"created_schema": False, "users": {}, "inserted": 0, "skipped": 0}

    if not dry_run:
        db._ensure_backup()

    with db._connect() as conn:
        had_schema = schema_exists(conn)
        if not dry_run:
            ensure_schema(conn)
            report["created_schema"] = not had_schema

        users = conn.execute("SELECT id, homePage FROM users ORDER BY id").fetchall()

        for user in users:
            user_id = user["id"]
            parsed = parse_home_page(user["homePage"])

            existing = 0
            if had_schema or not dry_run:
                existing = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM job_searches WHERE user_id = ?", (user_id,)
                    ).fetchone()[0]
                )

            if existing:
                report["users"][user_id] = {"action": "skipped-existing", "rows": existing}
                report["skipped"] += 1
                continue

            if not dry_run:
                for position, row in enumerate(parsed):
                    conn.execute(
                        "INSERT INTO job_searches (user_id, position, url, job_nums, edu_nums) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (user_id, position, row.url, row.job_nums, row.edu_nums),
                    )
            report["users"][user_id] = {"action": "migrated", "rows": len(parsed)}
            report["inserted"] += len(parsed)

    return report


def verify_round_trip(db: IndeedDB) -> dict[str, Any]:
    """Rebuild the legacy blob from job_searches and compare against the original.

    Reports three outcomes per user:
      exact      - rebuilt bytes identical to users.homePage
      normalized - differs only by blank lines / trailing whitespace the parser
                   already discarded, so no information was lost
      MISMATCH   - real divergence; the migration must not be trusted
    """
    results: dict[str, Any] = {"exact": [], "normalized": [], "mismatch": []}

    with db._connect() as conn:
        if not schema_exists(conn):
            raise RuntimeError("job_searches table does not exist; run migrate() first.")

        users = conn.execute("SELECT id, homePage FROM users ORDER BY id").fetchall()
        for user in users:
            user_id = user["id"]
            original = user["homePage"] or ""

            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT url, job_nums, edu_nums FROM job_searches "
                    "WHERE user_id = ? ORDER BY position",
                    (user_id,),
                ).fetchall()
            ]
            rebuilt = format_home_page(rows_to_search_objects(rows))

            if rebuilt == original:
                results["exact"].append(user_id)
            elif rebuilt == format_home_page(parse_home_page(original)):
                results["normalized"].append(user_id)
            else:
                results["mismatch"].append(
                    {"user_id": user_id, "original": original, "rebuilt": rebuilt}
                )

    return results


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def add_target_position(db: IndeedDB) -> dict[str, Any]:
    """Add job_searches.target_position -- a human-facing label for what a search
    is going after.

    Purely descriptive: nothing in main3.py reads it. Existing rows are seeded
    from the search URL's own `q=` term so the column is useful immediately
    rather than 41 blank cells; the label is editable afterwards.

    Idempotent -- does nothing if the column already exists.
    """
    report = {"added": False, "backfilled": 0}
    with db._connect() as conn:
        if not schema_exists(conn):
            raise RuntimeError("job_searches does not exist; run migrate() first.")
        if "target_position" in _column_names(conn, "job_searches"):
            return report

        db._ensure_backup()
        conn.execute("ALTER TABLE job_searches ADD COLUMN target_position TEXT DEFAULT ''")
        report["added"] = True

        for row in conn.execute("SELECT id, url FROM job_searches").fetchall():
            label = position_from_url(row["url"])
            if label:
                conn.execute("UPDATE job_searches SET target_position = ? WHERE id = ?",
                             (label, row["id"]))
                report["backfilled"] += 1
    return report


def position_from_url(url: str) -> str:
    """Best-effort label from an Indeed search URL's `q` term."""
    from urllib.parse import parse_qs, urlparse
    try:
        term = parse_qs(urlparse(url or "").query).get("q", [""])[0].strip()
    except ValueError:
        return ""
    return term.title() if term else ""


def profiles_from_searches(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the profile dicts IndeedHelper expects, from job_searches rows.

    Must match the legacy shape exactly: {"home", "eduN", "jobN"} where a
    missing number list is None ("use every record"), not an empty list.
    """
    profiles = []
    for row in rows:
        job_nums = (row["job_nums"] or "").strip()
        edu_nums = (row["edu_nums"] or "").strip()
        profiles.append(
            {
                "home": row["url"],
                "eduN": [int(n) for n in edu_nums.split(",")] if edu_nums else None,
                "jobN": [int(n) for n in job_nums.split(",")] if job_nums else None,
            }
        )
    return profiles
