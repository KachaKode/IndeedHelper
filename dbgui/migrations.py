"""Schema migration: users.homePage blob -> job_searches table.

The legacy format packs every job search for a user into one column: lines
separated by CRLF, each line "<url> <jobNums> <eduNums>" split on single spaces.
Line order is behavioural -- IndeedHelper.getProfileGen() cycles the parsed list
and startup takes profiles[0] -- so `position` preserves it exactly.

users.homePage is NOT dropped. It stays as the audit trail and rollback path;
the migration is idempotent and simply skips users that already have rows.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path
from typing import Any

from .data import IndeedDB, parse_home_page, format_home_page, SearchRow, normalize_question_text


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


def add_max_applications_per_search(db: IndeedDB) -> dict[str, Any]:
    """Add job_searches.max_applications -- caps how many applications the bot
    submits from one search in a single session before rotating to the next
    job search, even when this search still has result pages left.

    0 (the default) means no cap: the bot only leaves a search when it runs
    out of pages, exactly like before this column existed.

    Idempotent -- does nothing if the column already exists.
    """
    report = {"added": False}
    with db._connect() as conn:
        if not schema_exists(conn):
            raise RuntimeError("job_searches does not exist; run migrate() first.")
        if "max_applications" in _column_names(conn, "job_searches"):
            return report

        db._ensure_backup()
        conn.execute(
            "ALTER TABLE job_searches ADD COLUMN max_applications INTEGER NOT NULL DEFAULT 0"
        )
        report["added"] = True
    return report


def add_search_id_to_applications(db: IndeedDB) -> dict[str, Any]:
    """Add applications.search_id -- which job_searches row produced this
    application, so a per-search "applications this session" count can be
    computed straight from the applications table (same principle as
    RunnerManager._applications_since) instead of parsed out of the bot's log.

    NULL on every historical row: the applications table never recorded this
    before, so there is nothing to backfill from. Only rows saved by a bot new
    enough to set it (main3.py saveAppInDB) get it filled in.

    Idempotent -- does nothing if the column already exists.
    """
    report = {"added": False}
    with db._connect() as conn:
        if "search_id" in _column_names(conn, "applications"):
            return report
        db._ensure_backup()
        conn.execute("ALTER TABLE applications ADD COLUMN search_id INTEGER")
        report["added"] = True
    return report


def add_writing_sample(db: IndeedDB) -> dict[str, Any]:
    """Add users.WritingSample -- a passage the applicant actually wrote.

    Everything the bot generates (cover letter, resume summary, work
    descriptions, free-text screener answers) went out in the model's default
    register, which reads as machine-written. A real sample of the applicant's
    own prose gives the prompts something concrete to imitate: sentence length,
    vocabulary, how formal they are, what they never say.

    Idempotent -- does nothing if the column already exists.
    """
    report = {"added": False}
    with db._connect() as conn:
        if "WritingSample" in _column_names(conn, "users"):
            return report
        db._ensure_backup()
        conn.execute('ALTER TABLE users ADD COLUMN WritingSample TEXT DEFAULT \'\'')
        report["added"] = True
    return report


def add_avoid_employers(db: IndeedDB) -> dict[str, Any]:
    """Add users.avoidEmployers -- a newline-separated list of employer names
    the bot should skip on sight.

    Unlike users.avoid (job characteristics, which need an AI call per line to
    evaluate against the job description), an employer name is compared
    directly against self.companyName once it is scraped, so a match skips
    the job before any AI call is made for it.

    Idempotent -- does nothing if the column already exists.
    """
    report = {"added": False}
    with db._connect() as conn:
        if "avoidEmployers" in _column_names(conn, "users"):
            return report
        db._ensure_backup()
        conn.execute('ALTER TABLE users ADD COLUMN avoidEmployers TEXT DEFAULT \'\'')
        report["added"] = True
    return report


def add_linkedin_profile(db: IndeedDB) -> dict[str, Any]:
    """Add users.LinkedInProfile -- the applicant's LinkedIn profile URL.

    Used directly when a screener question asks for it (main3.py:
    setDetails() adds it to self.details, the same canned-fact lookup
    phone/email/zip already use), rather than leaving the model to guess or
    fabricate one.

    Idempotent -- does nothing if the column already exists.
    """
    report = {"added": False}
    with db._connect() as conn:
        if "LinkedInProfile" in _column_names(conn, "users"):
            return report
        db._ensure_backup()
        conn.execute('ALTER TABLE users ADD COLUMN LinkedInProfile TEXT DEFAULT \'\'')
        report["added"] = True
    return report


CREATE_VETTED_QUESTIONS = """
CREATE TABLE IF NOT EXISTS vetted_questions (
    id                     INTEGER PRIMARY KEY,
    user_id                INTEGER NOT NULL,
    question_type          TEXT NOT NULL,
    question_text          TEXT NOT NULL,
    normalized_question    TEXT NOT NULL,
    answer                 TEXT NOT NULL,
    answer_bank            TEXT,
    status                 TEXT NOT NULL DEFAULT 'unvetted',
    source_application_id  INTEGER,
    last_answered_at       TEXT NOT NULL,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
)
"""

CREATE_VETTED_QUESTIONS_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_vetted_questions_user_norm
    ON vetted_questions (user_id, normalized_question)
"""


def vetted_questions_schema_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vetted_questions'"
    ).fetchone()
    return row is not None


def ensure_vetted_questions_schema(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_VETTED_QUESTIONS)
    conn.execute(CREATE_VETTED_QUESTIONS_INDEX)


def _infer_seed_question_type(answer: Any) -> str:
    """Best-effort type guess for a historical applications.QsAndAs answer,
    which never recorded which question type produced it.

    Only one shape is unambiguous: SelectApplicable's legacy format is
    literally str(list_of_labels), e.g. "['Python', 'SQL']", so anything that
    round-trips through ast.literal_eval into a list is confidently that type.
    Every other historical answer (which could originally have been
    mult_choice, drop_down, search_select, or select_applicable_combobox) is
    indistinguishable from plain text by format alone -- bucketing those as
    free_response (rather than skipping them) was an explicit, deliberate
    choice: it still gives Level 2's context-aware reasoning something to
    draw on, at the cost of showing up as a plain-text row (no answer bank)
    in the GUI until an admin re-vets it, or the bot naturally re-records it
    with a real bank the next time it's asked live.
    """
    if isinstance(answer, str):
        try:
            parsed = ast.literal_eval(answer)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            parsed = None
        if isinstance(parsed, list):
            return "select_applicable"
    return "free_response"


def _is_datefill_or_blank(answer: Any) -> bool:
    """DateFill's answer is never actually recorded today (main3.py never sets
    final_answer for that type), so every historical DateFill entry is None
    or the string "None" -- skip these defensively, per DateFill being
    entirely out of scope for the vetted-questions system."""
    if answer is None:
        return True
    text = str(answer).strip()
    return text == "" or text == "None"


def seed_vetted_questions(db: IndeedDB, *, dry_run: bool = True) -> dict[str, Any]:
    """Populate vetted_questions from every historical applications.QsAndAs.

    Every seeded row starts 'unvetted' with answer_bank=None (historical data
    never recorded the offered choices, only the one chosen) and the type
    inferred per _infer_seed_question_type. When the same question appears
    across many past applications, only the most-recently-answered one
    survives: rows are processed oldest-first and each (user_id, normalized
    question) key is simply overwritten on every later occurrence, so the
    last write is naturally the most recent.

    Uses upsert_unvetted_question for the actual write, so re-running this
    script is safe: a row a human has since vetted is never touched, and an
    existing unvetted row is refreshed in place rather than duplicated.
    """
    report: dict[str, Any] = {
        "created_schema": False, "applications_scanned": 0, "parsed": 0,
        "unparseable": 0, "skipped_datefill_or_blank": 0, "skipped_missing_user": 0,
        "unique_questions": 0, "per_user": {},
    }

    if not dry_run:
        db._ensure_backup()

    # Read pass only -- this connection is closed before any write happens
    # below, so it never overlaps with upsert_unvetted_question's own
    # connection (each write method here manages its own short-lived one).
    with db._connect() as conn:
        had_schema = vetted_questions_schema_exists(conn)
        if not dry_run:
            ensure_vetted_questions_schema(conn)
        report["created_schema"] = not had_schema

        valid_user_ids = {row[0] for row in conn.execute("SELECT id FROM users")}

        rows = conn.execute(
            "SELECT id, user_id, DateTime, QsAndAs FROM applications ORDER BY id ASC"
        ).fetchall()
        report["applications_scanned"] = len(rows)

        best: dict[tuple[int, str], dict[str, Any]] = {}
        for row in rows:
            parsed = IndeedDB.parse_stored_literal(row["QsAndAs"])
            if not isinstance(parsed, list):
                report["unparseable"] += 1
                continue
            report["parsed"] += 1

            user_id = row["user_id"]
            if user_id not in valid_user_ids:
                report["skipped_missing_user"] += 1
                continue

            for entry in parsed:
                if not isinstance(entry, dict):
                    continue
                question = (entry.get("Question") or "").strip()
                answer = entry.get("Answer")
                if not question:
                    continue
                if _is_datefill_or_blank(answer):
                    report["skipped_datefill_or_blank"] += 1
                    continue

                question_type = _infer_seed_question_type(answer)
                normalized_answer = ast.literal_eval(answer) if question_type == "select_applicable" else answer
                normalized = normalize_question_text(question)
                best[(user_id, normalized)] = {
                    "question_text": question,
                    "answer": normalized_answer,
                    "question_type": question_type,
                    "application_id": row["id"],
                }

    report["unique_questions"] = len(best)
    for (user_id, _normalized), entry in best.items():
        report["per_user"][user_id] = report["per_user"].get(user_id, 0) + 1
        if not dry_run:
            db.upsert_unvetted_question(
                user_id,
                question_type=entry["question_type"],
                question_text=entry["question_text"],
                answer=entry["answer"],
                answer_bank=None,
                source_application_id=entry["application_id"],
            )

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
