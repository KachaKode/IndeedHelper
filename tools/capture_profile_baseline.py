"""Capture what the CURRENT code produces for self.profiles, per user.

This is the reference the job_searches migration is graded against: after the
migration and the main3.py rewrite, every user's profile list must come out
byte-identical to what this script recorded. Run it BEFORE migrating.

It deliberately calls the real IndeedHelper.load_startup_info rather than
re-implementing the parse, so the baseline captures actual behaviour -- quirks
(including the bare `except: return`) and all. __init__ is bypassed via
__new__ so that importing this does not launch Chrome.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402


BASELINE_PATH = ROOT / "tools" / "profile_baseline.json"


def capture_for_user(user_row: sqlite3.Row) -> dict:
    """Run the real load_startup_info against one users row."""
    helper = main3.IndeedHelper.__new__(main3.IndeedHelper)
    # Minimum attribute surface load_startup_info touches before it can run.
    helper.profiles = []
    helper.chrome_profile = "user-data-dir="
    helper.home_url = ""

    helper.load_startup_info(user_row)

    return {
        "profiles": getattr(helper, "profiles", []),
        "cur_profile": getattr(helper, "cur_profile", None),
        "home_url": getattr(helper, "home_url", None),
        "home_url_pattern": getattr(helper, "home_url_pattern", None),
        "my_path": getattr(helper, "MY_PATH", None),
    }


def main() -> int:
    conn = sqlite3.connect(ROOT / "IndHelperDB.db")
    conn.row_factory = sqlite3.Row
    users = conn.execute("SELECT * FROM users ORDER BY id").fetchall()

    baseline = {}
    for row in users:
        captured = capture_for_user(row)
        baseline[str(row["id"])] = captured
        profiles = captured["profiles"]
        raw_lines = [ln for ln in (row["homePage"] or "").split("\n") if ln.strip()]
        flag = "" if len(profiles) == len(raw_lines) else \
            f"  <-- MISMATCH: {len(raw_lines)} raw lines but {len(profiles)} profiles"
        print(f"user {row['id']:>3} ({row['FirstName']} {row['LastName']}): "
              f"{len(profiles)} profiles{flag}")

    BASELINE_PATH.parent.mkdir(exist_ok=True)
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print(f"\nWrote baseline -> {BASELINE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
