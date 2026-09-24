"""A self-resolved pause must not leave the run blocked on the control file.

From Logs/Log44.txt: the new stuck-loop recovery (see
tools/test_stuck_loop_recovery.py) detected the ghost-profile page, beeped,
and then correctly noticed on its own that the page had moved on --
"ATTENTION CLEARED" fired automatically at line 1233. But the run still sat
at "PAUSED, waiting for a command from the Run tab" until a person opened
the browser and (it turned out) effectively pressed Start applying anyway --
11 seconds later, at line 1236.

The cause: dbgui/runner.py's _pump() writes mode="paused" to the control file
the moment "NEEDS ATTENTION" appears, and main3.py's own waitWhilePaused()
blocks on THAT FILE, not just its in-process selfPaused flag. Clearing
selfPaused (main3.py's side of "auto-resume") did nothing, because nothing
ever wrote the file back to "running".

The fix: pauseAndAlert() tags its "ATTENTION CLEARED" line with
"[auto-resume]" exactly when resumeWhenResolved is True (the same condition
that already clears selfPaused), and _pump() reacts to that tag by writing
mode="running" back to the control file -- so the persisted state agrees
with the in-process one, and the run actually continues without a human.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbgui.data import IndeedDB  # noqa: E402
from dbgui.runner import RunnerManager  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


FAKE_MAIN3 = """\
import time, sys
print('[CT]     0.0ms | start_up | ENTER | fake', flush=True)
print('[CT]     1.0ms | start_up | EXIT |  result=ok', flush=True)
print('[CT]     2.0ms | StateMachine | NEEDS ATTENTION | STUCK: stuck cycling on this page -- pausing and alerting', flush=True)
time.sleep(1)
print('[CT]     3.0ms | StateMachine | ATTENTION CLEARED | STUCK: stuck cycling on this page: https://x [auto-resume]', flush=True)
time.sleep(60)
"""

FAKE_MAIN3_MANUAL = """\
import time, sys
print('[CT]     0.0ms | start_up | ENTER | fake', flush=True)
print('[CT]     1.0ms | start_up | EXIT |  result=ok', flush=True)
print('[CT]     2.0ms | StateMachine | NEEDS ATTENTION | BOT CHECK -- pausing and alerting', flush=True)
time.sleep(1)
print('[CT]     3.0ms | StateMachine | ATTENTION CLEARED | BOT CHECK: https://x', flush=True)
time.sleep(60)
"""


def run_fake(root: Path, db: IndeedDB, script: str) -> RunnerManager:
    (root / "main3.py").write_text(script, encoding="utf-8")
    runner = RunnerManager(db, root)
    runner.preflight = lambda ids: []      # bypass checks for this probe
    runner.start([7])
    return runner


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        db_copy = root / "IndHelperDB.db"
        shutil.copy2(ROOT / "IndHelperDB.db", db_copy)
        db = IndeedDB(db_copy, project_root=root)

        print("--- a stuck-page pause that resolves itself ---")
        runner = run_fake(root, db, FAKE_MAIN3)
        time.sleep(0.6)
        check("NEEDS ATTENTION pauses the control file",
              runner.read_control(7)["mode"] == "paused",
              f"mode={runner.read_control(7)['mode']!r}")
        check("the run reports 'attention' while waiting",
              runner.status()[0]["state"] == "attention",
              f"state={runner.status()[0]['state']!r}")

        time.sleep(1.6)
        check("an auto-resumed ATTENTION CLEARED flips the control file back to running",
              runner.read_control(7)["mode"] == "running",
              f"mode={runner.read_control(7)['mode']!r}")
        check("the run reports 'running', not 'paused', after an auto-resume",
              runner.status()[0]["state"] == "running",
              f"state={runner.status()[0]['state']!r}")
        runner.stop(7)

        print()
        print("--- a bot-check pause still waits for a person (no [auto-resume] tag) ---")
        runner2 = run_fake(root, db, FAKE_MAIN3_MANUAL)
        time.sleep(0.6)
        check("NEEDS ATTENTION pauses the control file",
              runner2.read_control(7)["mode"] == "paused")

        time.sleep(1.6)
        check("a plain ATTENTION CLEARED (bot check) leaves the control file paused",
              runner2.read_control(7)["mode"] == "paused",
              f"mode={runner2.read_control(7)['mode']!r}")
        check("the run still reports 'paused', waiting for Start applying",
              runner2.status()[0]["state"] == "paused",
              f"state={runner2.status()[0]['state']!r}")
        runner2.stop(7)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL AUTO-RESUME CONTROL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
