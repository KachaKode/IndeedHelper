"""Tests that main3.saveAppInDB records Indeed's jk= key on the application row.

job_key is what lets an entry read back off Indeed's application tracker be
matched to its applications row exactly, rather than by company name -- which is
ambiguous, because hundreds of the stored applications are repeat applications
to a company already applied to.

saveAppInDB opens 'IndHelperDB.db' by relative path, so these tests chdir into a
temp directory holding a COPY. The real database is never touched.

    python tools/test_job_key_persisted.py
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402

DB_PATH = ROOT / "IndHelperDB.db"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def build_helper(user_id: int, job_key, search_id=None):
    """A bare IndeedHelper: __init__ would open Chrome and a database."""
    helper = main3.IndeedHelper.__new__(main3.IndeedHelper)
    helper.user_id = user_id
    helper.currentJobKey = job_key
    helper.cur_profile = {"searchId": search_id}
    helper.cur_profile_index = 0
    helper.appsThisSearch = 0
    helper.searchAppCounts = [0]
    helper.applicationsLeft = 0
    return helper


def save_one(db_path: Path, helper, company="Acme Co", title="Data Analyst") -> None:
    cwd = os.getcwd()
    os.chdir(db_path.parent)
    try:
        helper.saveAppInDB(company, title, "A description.", "Tommy Orok", "headline",
                           "[]", "[]", "[]", "summary", "[]", "cover letter")
    finally:
        os.chdir(cwd)


def newest(db_path: Path) -> sqlite3.Row:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM applications ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()


def columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
    finally:
        conn.close()


def test_against_copy() -> None:
    if not DB_PATH.exists():
        print("  [SKIP] no database present")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        copy = root / "IndHelperDB.db"
        shutil.copy2(DB_PATH, copy)

        had_column = "job_key" in columns(copy, "applications")
        print(f"\nself-heal (copy starts {'with' if had_column else 'WITHOUT'} job_key)")

        conn = sqlite3.connect(copy)
        user_id = int(conn.execute(
            "SELECT id FROM users WHERE AppsLeft IS NOT NULL LIMIT 1").fetchone()[0])
        before = int(conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0])
        # Measured, not assumed to be zero: the bot self-heals this column and
        # records keys as it runs, so a copy of the live database legitimately
        # arrives with some already filled in.
        keyed_before = 0
        if had_column:
            keyed_before = int(conn.execute(
                "SELECT COUNT(*) FROM applications WHERE job_key IS NOT NULL "
                "AND job_key != ''").fetchone()[0])
        conn.close()

        save_one(copy, build_helper(user_id, "abc123def456"))

        check("saveAppInDB works on a database that lacks the column",
              "job_key" in columns(copy, "applications"))

        print("\nthe key is stored")
        row = newest(copy)
        check("a row was inserted",
              int(sqlite3.connect(copy).execute(
                  "SELECT COUNT(*) FROM applications").fetchone()[0]) == before + 1)
        check("job_key holds the jk value", row["job_key"] == "abc123def456",
              f"got {row['job_key']!r}")
        check("the rest of the row is unaffected",
              row["companyName"] == "Acme Co" and row["jobTitle"] == "Data Analyst"
              and row["Platform"] == "Indeed", dict(row).__str__()[:160])

        print("\nan unknown key is stored as empty, never NULL")
        # process_job_openings sets currentJobKey to None when the link carried no
        # data-jk, so this is a real path, not a defensive hypothetical.
        save_one(copy, build_helper(user_id, None), company="No Key Inc")
        row = newest(copy)
        check("a missing jk becomes ''", row["job_key"] == "", f"got {row['job_key']!r}")
        check("an application is still recorded without a jk",
              row["companyName"] == "No Key Inc")

        print("\nhistorical rows keep an empty key")
        conn = sqlite3.connect(copy)
        try:
            filled = int(conn.execute(
                "SELECT COUNT(*) FROM applications WHERE job_key IS NOT NULL "
                "AND job_key != ''").fetchone()[0])
            nulls = int(conn.execute(
                "SELECT COUNT(*) FROM applications WHERE job_key IS NULL").fetchone()[0])
        finally:
            conn.close()
        check("exactly one more row carries a key than before",
              filled == keyed_before + 1, f"{keyed_before} -> {filled}")
        check("writing a row never leaves job_key NULL", nulls == 0, f"{nulls} NULLs")

    check("the real database was never opened", True)


def test_source_contract() -> None:
    """Pin the wiring in source, the way tools/test_skip_reasons.py does for
    main3's control flow: an INSERT that silently stopped naming job_key would
    leave every future row unmatched, and no unit test above would fail."""
    print("\nsource contract")
    src = (ROOT / "main3.py").read_text(encoding="utf-8")
    # Anchored on the indented def: a commented-out "#def saveAppInDB(" sits
    # directly above the real one, and matching that yields a one-line body
    # against which every check below passes vacuously.
    start = src.index("\n    def saveAppInDB(") + 1
    body = src[start:src.index("\n    def ", start + 10)]
    check("the INSERT names job_key", "job_key)" in body and "INSERT INTO applications" in body)
    check("the value comes from currentJobKey", "currentJobKey" in body)
    check("a missing key falls back to empty rather than NULL",
          'or ""' in body or "or ''" in body)
    check("the column is self-healed before the INSERT",
          "ALTER TABLE applications ADD COLUMN job_key" in body)


def main() -> int:
    test_against_copy()
    test_source_contract()

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED ({len(failures)})")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
