"""Gate for the job_searches migration (verification checks 1 and 2).

Runs the migration against a throwaway COPY of the database and grades it:

  check 1  round-trip  - rebuilding the legacy blob from job_searches must not
                         lose information vs users.homePage
  check 2  behaviour   - the profile list the bot would build from job_searches
                         must be identical to tools/profile_baseline.json, which
                         was captured from the current code before any change

The real database is only touched when both pass AND --apply is given.

    python tools/verify_migration.py            # grade against a copy, change nothing
    python tools/verify_migration.py --apply    # grade, then migrate for real if clean
"""

from __future__ import annotations

import json
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
BASELINE_PATH = ROOT / "tools" / "profile_baseline.json"


def load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        raise SystemExit(
            f"No baseline at {BASELINE_PATH}. Run tools/capture_profile_baseline.py "
            "BEFORE migrating -- it must be captured from the pre-migration code."
        )
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def profiles_from_db(db_path: Path) -> dict[str, list]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    out = {}
    for user in conn.execute("SELECT id FROM users ORDER BY id").fetchall():
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT url, job_nums, edu_nums FROM job_searches "
                "WHERE user_id = ? ORDER BY position",
                (user["id"],),
            ).fetchall()
        ]
        out[str(user["id"])] = migrations.profiles_from_searches(rows)
    conn.close()
    return out


def grade(db_path: Path, baseline: dict) -> bool:
    db = IndeedDB(db_path)
    ok = True

    print("--- check 1: round-trip (no information lost) ---")
    result = migrations.verify_round_trip(db)
    print(f"  byte-identical : {result['exact']}")
    print(f"  normalized-only: {result['normalized']}  (differed only by blank/trailing space)")
    if result["mismatch"]:
        ok = False
        print(f"  MISMATCH       : {len(result['mismatch'])} user(s)")
        for item in result["mismatch"]:
            print(f"    user {item['user_id']}")
            print(f"      original: {item['original']!r}")
            print(f"      rebuilt : {item['rebuilt']!r}")
    else:
        print("  no mismatches")

    print("\n--- check 2: bot behaviour unchanged vs baseline ---")
    migrated = profiles_from_db(db_path)
    for user_id, expected_rec in sorted(baseline.items(), key=lambda kv: int(kv[0])):
        expected = expected_rec["profiles"]
        actual = migrated.get(user_id, [])
        if expected == actual:
            print(f"  user {user_id:>3}: OK ({len(actual)} profiles)")
        else:
            ok = False
            print(f"  user {user_id:>3}: DIFFERS")
            print(f"      baseline: {expected}")
            print(f"      migrated: {actual}")
    return ok


def main() -> int:
    apply = "--apply" in sys.argv
    baseline = load_baseline()

    with tempfile.TemporaryDirectory() as tmpdir:
        trial = Path(tmpdir) / "trial.db"
        shutil.copy2(DB_PATH, trial)
        print(f"Grading migration on a throwaway copy: {trial}\n")

        report = migrations.migrate(IndeedDB(trial))
        print(f"migrate(): inserted {report['inserted']} rows, "
              f"skipped {report['skipped']} user(s), "
              f"created schema: {report['created_schema']}\n")

        passed = grade(trial, baseline)

    print("\n" + "=" * 60)
    if not passed:
        print("RESULT: FAILED -- real database NOT touched.")
        return 1

    print("RESULT: PASSED")
    if not apply:
        print("Real database unchanged. Re-run with --apply to migrate for real.")
        return 0

    print("\nApplying to the real database...")
    db = IndeedDB(DB_PATH)
    report = migrations.migrate(db)
    print(f"  inserted {report['inserted']} rows, skipped {report['skipped']} user(s)")

    print("\nRe-grading the real database:")
    if not grade(DB_PATH, baseline):
        print("\nPOST-APPLY GRADING FAILED -- restore from the .backup_ file next to the DB.")
        return 1
    print("\nMigration applied and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
