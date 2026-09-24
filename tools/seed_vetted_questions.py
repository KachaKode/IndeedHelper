"""Seeds vetted_questions from every historical applications.QsAndAs record.

Every seeded row starts 'unvetted', so this just gives the Vetted Questions
GUI tab a running start instead of an empty table -- nothing seeded here
changes bot behaviour until a human promotes a row to 'vetted' (or edits its
answer, which promotes it automatically).

Runs against a throwaway COPY of the database first and prints what it found;
the real database is only touched with --apply.

    python tools/seed_vetted_questions.py            # dry run, changes nothing
    python tools/seed_vetted_questions.py --apply    # seed the real database

Safe to re-run: seeding uses the same update-in-place upsert the bot's own
runtime hook uses, so a row a human has since vetted is never touched, and an
existing unvetted row is refreshed rather than duplicated.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbgui.data import IndeedDB  # noqa: E402
from dbgui.migrations import seed_vetted_questions  # noqa: E402


DB_PATH = ROOT / "IndHelperDB.db"


def print_report(report: dict, *, applied: bool) -> None:
    verb = "Seeded" if applied else "Would seed"
    print(f"  applications scanned      : {report['applications_scanned']}")
    print(f"  QsAndAs parsed            : {report['parsed']}")
    print(f"  QsAndAs unparseable       : {report['unparseable']}")
    print(f"  skipped (DateFill/blank)  : {report['skipped_datefill_or_blank']}")
    print(f"  skipped (deleted user)    : {report['skipped_missing_user']}")
    print(f"  {verb.lower()} rows{'':<14}: {report['unique_questions']} "
          f"across {len(report['per_user'])} user(s)")
    for user_id in sorted(report["per_user"]):
        print(f"    user {user_id:>3}: {report['per_user'][user_id]} question(s)")


def main() -> int:
    apply = "--apply" in sys.argv

    with tempfile.TemporaryDirectory() as tmpdir:
        trial = Path(tmpdir) / "trial.db"
        shutil.copy2(DB_PATH, trial)
        print(f"Dry run against a throwaway copy: {trial}\n")

        report = seed_vetted_questions(IndeedDB(trial), dry_run=True)
        print_report(report, applied=False)

    print()
    if not apply:
        print("Real database unchanged. Re-run with --apply to seed for real.")
        return 0

    print("Applying to the real database...")
    db = IndeedDB(DB_PATH)
    real_report = seed_vetted_questions(db, dry_run=False)
    print()
    print_report(real_report, applied=True)
    print("\nSeed complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
