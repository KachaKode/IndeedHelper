"""Tests for the run-control layer, against a COPY of the database.

Covers the parts that must be right before any real browser is launched:
  - preflight blocks shared Chrome profiles (users 5 and 9 both use Profile 12)
  - preflight blocks missing folders / no searches / no applications left
  - ticking users writes the Active column so main3.py standalone agrees
  - a subprocess is really spawned, its output captured, and stop() kills it

The "spawn" test substitutes a trivial script for main3.py so no Chrome opens.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbgui.data import IndeedDB, user_folder_name  # noqa: E402
from dbgui.runner import PreflightError, RunnerManager  # noqa: E402
from dbgui.server import create_app  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        db_copy = root / "IndHelperDB.db"
        shutil.copy2(ROOT / "IndHelperDB.db", db_copy)

        db = IndeedDB(db_copy, project_root=root)
        # Give every user the folder the bot expects, so folder-missing does not
        # mask the specific things each test is checking.
        for user in db.list_users():
            (root / "Users" / user_folder_name(user)).mkdir(parents=True, exist_ok=True)

        runner = RunnerManager(db, root)

        # -------------------------------------------- shared-profile blocking --
        problems = runner.preflight([5, 9])   # both point at "Profile 12"
        shared = [p for p in problems if "same Chrome profile" in p["message"]]
        check("preflight blocks users sharing a Chrome profile", len(shared) == 1,
              f"problems={[p['message'][:60] for p in problems]}")
        check("shared-profile problem is blocking", bool(shared) and shared[0]["blocking"])

        problems67 = runner.preflight([6, 7])  # both point at "Profile 9"
        check("preflight blocks the other shared pair (6+7)",
              any("same Chrome profile" in p["message"] for p in problems67))

        # A single user from that pair is fine on its own.
        solo = runner.preflight([5])
        check("running one of the pair alone is allowed",
              not any("same Chrome profile" in p["message"] for p in solo),
              f"got {[p['message'][:60] for p in solo]}")

        # ------------------------------------------------- other blocked cases --
        check("user with no Chrome profile path is blocked",
              any("no Chrome profile path" in p["message"] for p in runner.preflight([10])))
        check("user with no job searches is blocked",
              any("no job searches" in p["message"] for p in runner.preflight([10])))

        db.save_user(1, {"AppsLeft": 0})
        check("user with 0 applications left is blocked",
              any("no applications left" in p["message"] for p in runner.preflight([1])))

        missing = db.list_users()[0]
        shutil.rmtree(root / "Users" / user_folder_name(missing))
        check("user with a missing Users/ folder is blocked",
              any("missing its folder" in p["message"] for p in runner.preflight([missing["id"]])))

        # ------------------------------------------------ start() refuses these --
        raised = False
        try:
            runner.start([5, 9])
        except PreflightError:
            raised = True
        check("start() raises rather than launching a blocked combination", raised)
        check("nothing was spawned by the blocked start", len(runner.runs) == 0,
              f"runs={list(runner.runs)}")

        # ------------------------------------- selection writes Active column --
        client = create_app(db, runner).test_client()
        client.post("/api/run/selection", json={"userIds": [7, 8]})
        conn = sqlite3.connect(db_copy)
        active = {r[0]: r[1] for r in conn.execute("SELECT id, Active FROM users").fetchall()}
        conn.close()
        check("ticked users become Active='T'", active[7] == "T" and active[8] == "T",
              f"7={active[7]!r} 8={active[8]!r}")
        check("unticked users become Active='F'",
              all(active[i] == "F" for i in active if i not in (7, 8)),
              f"got {active}")

        # main3.py standalone must now agree with what the GUI selected.
        conn = sqlite3.connect(db_copy)
        standalone = [r[0] for r in conn.execute(
            "SELECT id FROM users WHERE AppsLeft > 0 AND Active = 'T'").fetchall()]
        conn.close()
        check("standalone main3.py would run exactly the ticked users",
              sorted(standalone) == [7, 8], f"got {standalone}")

        # --------------------------------- real subprocess spawn / capture / stop --
        # Stand in for main3.py so this test never opens a browser.
        fake = root / "main3.py"
        fake.write_text(
            "import time, sys\n"
            "print('[CT]     0.0ms | start_up | ENTER | fake', flush=True)\n"
            "print('[CT]     1.0ms | start_up | EXIT |  result=ok', flush=True)\n"
            "print('[CT]     2.0ms | reportAction | pretending to work', flush=True)\n"
            "print('[CT]     3.0ms | StateMachine | PAUSED | waiting', flush=True)\n"
            "time.sleep(60)\n",
            encoding="utf-8",
        )
        spawn_runner = RunnerManager(db, root)
        spawn_runner.preflight = lambda ids: []          # bypass checks for this probe
        spawn_runner.start([7])
        time.sleep(2.5)

        status = spawn_runner.status()
        check("a run appears in status", len(status) == 1, f"got {len(status)}")
        run = status[0]
        check("child process is alive", run["alive"])
        check("stdout is captured", len(run["lines"]) >= 3, f"lines={run['lines']}")
        # A launched run is expected to end up PAUSED on the home page rather
        # than applying, so the PAUSED trace is what the state should reflect.
        check("state reflects the PAUSED trace, not 'running'",
              run["state"] == "paused", f"state={run['state']}")
        check("last activity parsed from reportAction",
              (run["lastActivity"] or "").startswith("pretending"), f"got {run['lastActivity']!r}")
        check("log buffer is bounded", run["lines"].__len__() <= 200)

        stopped = spawn_runner.stop(7)
        time.sleep(1.2)
        check("stop() reports success", stopped)
        check("child process is gone", not spawn_runner.status()[0]["alive"])
        check("any_running() is false after stop", not spawn_runner.any_running())

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL RUNNER TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
