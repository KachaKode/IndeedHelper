"""Gate for the outcome-tracking migration.

Runs the migration against a throwaway COPY of the database and grades it:

  check 1  additive     - applications keeps every column and every row it had,
                          and gains exactly job_key
  check 2  shape        - application_events and capture_items exist with the
                          expected columns and indexes
  check 3  idempotent   - running the whole migration a second time reports no
                          work done and changes nothing
  check 4  re-sync safe - the partial unique index actually rejects a duplicate
                          (external_id, event_type), which is what makes a
                          repeated capture sync safe to run, while leaving
                          manual events (external_id NULL) unconstrained

The real database is only touched when all pass AND --apply is given.

    python tools/verify_stats_migration.py            # grade against a copy, change nothing
    python tools/verify_stats_migration.py --apply    # grade, then migrate for real if clean
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbgui.data import IndeedDB  # noqa: E402
from dbgui import migrations  # noqa: E402

DB_PATH = ROOT / "IndHelperDB.db"

EXPECTED_EVENT_COLS = {
    "id", "user_id", "application_id", "event_type", "occurred_at",
    "source", "confidence", "external_id", "note", "created_at",
}
EXPECTED_CAPTURE_COLS = {
    "id", "user_id", "source", "external_id", "observed_at", "company", "title",
    "job_key", "sender", "subject", "body_excerpt", "classified_type", "classifier",
    "confidence", "match_state", "application_id", "created_at",
}

INSERT_EVENT = (
    "INSERT INTO application_events (user_id, application_id, event_type, occurred_at, "
    "source, confidence, external_id, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def index_names(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}


def snapshot(path: Path) -> tuple[set[str], int]:
    conn = sqlite3.connect(path)
    try:
        return columns(conn, "applications"), int(
            conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0])
    finally:
        conn.close()


def grade(path: Path, before_cols: set[str], before_rows: int) -> bool:
    db = IndeedDB(path, project_root=path.parent)

    print("\ncheck 1  additive")
    conn = sqlite3.connect(path)
    after_cols = columns(conn, "applications")
    after_rows = int(conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0])
    check("every pre-existing applications column survives",
          before_cols <= after_cols, f"lost {before_cols - after_cols}")
    check("applications has job_key", "job_key" in after_cols)
    # The column may already be there: main3.saveAppInDB self-heals it, so a bot
    # run beats this script to it. Either the migration added it or the bot did,
    # but nothing ELSE may appear.
    gained = after_cols - before_cols
    check("the migration added job_key and nothing else",
          gained in ({"job_key"}, set()),
          f"gained {gained}")
    print(f"     (job_key was {'added by this migration' if gained else 'already present'})")
    check("no application rows were added or lost",
          after_rows == before_rows, f"{before_rows} -> {after_rows}")
    # The real invariant is that the column is never NULL -- the DEFAULT '' plus
    # saveAppInDB's `or ""` guarantee it, and the matcher treats '' as "unknown".
    # Checking for "empty everywhere" instead would fail the moment the bot
    # legitimately records its first key.
    check("job_key is never NULL",
          int(conn.execute(
              "SELECT COUNT(*) FROM applications WHERE job_key IS NULL").fetchone()[0]) == 0)
    filled = int(conn.execute(
        "SELECT COUNT(*) FROM applications WHERE job_key IS NOT NULL AND job_key != ''"
    ).fetchone()[0])
    print(f"     ({filled} of {after_rows} rows carry a job key)")

    print("\ncheck 2  shape")
    check("application_events exists", migrations.application_events_schema_exists(conn))
    check("capture_items exists", migrations.capture_items_schema_exists(conn))
    check("application_events has the expected columns",
          columns(conn, "application_events") == EXPECTED_EVENT_COLS,
          f"got {sorted(columns(conn, 'application_events'))}")
    check("capture_items has the expected columns",
          columns(conn, "capture_items") == EXPECTED_CAPTURE_COLS,
          f"got {sorted(columns(conn, 'capture_items'))}")
    idx = index_names(conn)
    for name in ("idx_app_events_app", "idx_app_events_user", "idx_app_events_ext",
                 "idx_capture_user_ext", "idx_capture_state", "idx_applications_user_dt"):
        check(f"index {name} exists", name in idx)
    conn.close()

    print("\ncheck 3  idempotent")
    again_key = migrations.add_job_key_to_applications(db)
    again_out = migrations.add_outcome_tracking(db)
    check("re-running add_job_key_to_applications is a no-op",
          again_key["added"] is False, str(again_key))
    check("re-running add_outcome_tracking is a no-op",
          not any(again_out.values()), str(again_out))
    cols2, rows2 = snapshot(path)
    check("a second run changes no columns or rows",
          cols2 == after_cols and rows2 == after_rows)

    print("\ncheck 4  re-sync safe")
    conn = sqlite3.connect(path)
    try:
        captured = (9, None, "viewed", "2026-09-01 10:00:00", "indeed", 1.0, "ext-abc", "", "now")
        conn.execute(INSERT_EVENT, captured)
        duplicated = False
        try:
            conn.execute(INSERT_EVENT, captured)
            duplicated = True
        except sqlite3.IntegrityError:
            pass
        check("a duplicate (external_id, event_type) is rejected", not duplicated)

        # A manual event carries external_id NULL and must stay unconstrained:
        # a human may legitimately record the same stage twice.
        manual = (9, None, "screened", "2026-09-02 10:00:00", "manual", 1.0, None, "", "now")
        allowed = True
        try:
            conn.execute(INSERT_EVENT, manual)
            conn.execute(INSERT_EVENT, manual)
        except sqlite3.IntegrityError as exc:
            allowed = False
            check("two manual events with external_id NULL are both allowed", False, str(exc))
        if allowed:
            check("two manual events with external_id NULL are both allowed", True)
    finally:
        conn.rollback()
        conn.close()

    return not failures


def main() -> int:
    apply = "--apply" in sys.argv
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}", file=sys.stderr)
        return 1

    before_cols, before_rows = snapshot(DB_PATH)
    print(f"applications before: {before_rows} rows, {len(before_cols)} columns")

    with tempfile.TemporaryDirectory() as tmpdir:
        copy = Path(tmpdir) / "IndHelperDB.db"
        shutil.copy2(DB_PATH, copy)
        print(f"\nGrading against a copy at {copy}")
        db = IndeedDB(copy, project_root=Path(tmpdir))
        migrations.add_job_key_to_applications(db)
        migrations.add_outcome_tracking(db)
        passed = grade(copy, before_cols, before_rows)

    print("\n" + "=" * 60)
    if not passed:
        print("RESULT: FAILED -- real database NOT touched.")
        for name in failures:
            print(f"  - {name}")
        return 1

    print("RESULT: PASSED")
    if not apply:
        print("Real database unchanged. Re-run with --apply to migrate for real.")
        return 0

    print("\nApplying to the real database...")
    db = IndeedDB(DB_PATH, project_root=ROOT)
    key_report = migrations.add_job_key_to_applications(db)
    out_report = migrations.add_outcome_tracking(db)
    print(f"  job_key added: {key_report['added']}")
    print(f"  outcome tables: {out_report}")

    print("\nRe-grading the real database:")
    failures.clear()
    # Re-snapshot: the bot may have inserted an application while this script
    # ran, and comparing against the opening count would fail on its own success.
    before_cols, before_rows = snapshot(DB_PATH)
    if not grade(DB_PATH, before_cols, before_rows):
        print("\nPOST-APPLY GRADING FAILED -- restore from the .backup_ file next to the DB.")
        return 1
    print("\nMigration applied and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
