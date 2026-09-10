"""Tests for GUI -> bot run control (pause / start applying / go home).

Three layers:
  1. main3.RunControl        - the bot's reader: defaults, one-shot commands
  2. RunnerManager.write_control / API - the GUI's writer
  3. StateMachine gating     - that the real loop actually blocks while paused
                               and runs commands without resuming

Layer 3 drives the real StateMachine methods against a stub helper, so no
browser is launched and no database is touched.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402
from dbgui.data import IndeedDB, user_folder_name  # noqa: E402
from dbgui.runner import RunnerManager  # noqa: E402
from dbgui.server import create_app  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


class StubHelper:
    """Stands in for IndeedHelper: records what the state machine asks of it."""

    def __init__(self):
        self.user_id = 999
        self.home_visits = 0
        self.envs = []

    def goHome(self):
        self.home_visits += 1

    def reportAction(self, *a, **k):
        pass


def make_state_machine(control):
    sm = main3.StateMachine.__new__(main3.StateMachine)
    sm.helper = StubHelper()
    sm.control = control
    sm.states = ["Init", "Applying"]
    sm.current_state = "Applying"
    sm.prev_state = "Init"
    sm.selfPaused = False      # set by __init__ in real use; __new__ skips it
    return sm


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    try:
        # ---------------------------------------------- 1. bot-side reader --
        control = main3.RunControl(1, root=tmp)
        check("missing control file reads as paused", control.mode() == "paused",
              f"got {control.mode()!r}")
        check("missing control file has no pending command",
              control.pending_command() is None)

        db_copy = tmp / "IndHelperDB.db"
        shutil.copy2(ROOT / "IndHelperDB.db", db_copy)
        (tmp / "Users").mkdir(exist_ok=True)
        db = IndeedDB(db_copy, project_root=tmp)
        for u in db.list_users():
            (tmp / "Users" / user_folder_name(u)).mkdir(exist_ok=True)
        runner = RunnerManager(db, tmp)

        # ---------------------------------------------- 2. GUI-side writer --
        runner.write_control(1, mode="running")
        check("GUI can switch the bot to running", control.mode() == "running")
        runner.write_control(1, mode="paused")
        check("GUI can pause the bot", control.mode() == "paused")

        runner.write_control(1, mode="paused", command="home")
        check("one-shot command is delivered", control.pending_command() == "home")
        check("one-shot command fires only once", control.pending_command() is None,
              "a repeated poll re-delivered the same command")

        runner.write_control(1, mode="paused", command="home")
        check("a NEW command with a higher seq is delivered again",
              control.pending_command() == "home")

        bad = tmp / "runtime" / "control_1.json"
        bad.write_text("{ not json", encoding="utf-8")
        check("corrupt control file falls back to paused", control.mode() == "paused")

        # ------------------------------------------- 3. state machine gating --
        runner.write_control(2, mode="paused")
        c2 = main3.RunControl(2, root=tmp)
        sm = make_state_machine(c2)

        released = threading.Event()

        def waiter():
            sm.waitWhilePaused()
            released.set()

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        time.sleep(1.2)
        check("waitWhilePaused blocks while paused", not released.is_set())

        # A command must run while still paused -- "Go to home" should not
        # require starting to apply first.
        runner.write_control(2, mode="paused", command="home")
        time.sleep(1.6)
        check("home command runs while paused", sm.helper.home_visits == 1,
              f"home_visits={sm.helper.home_visits}")
        check("still paused after running the command", not released.is_set())
        check("going home resets the state machine", sm.current_state == "Init",
              f"current_state={sm.current_state!r}")

        runner.write_control(2, mode="running")
        released.wait(timeout=4)
        check("switching to running releases the wait", released.is_set())

        # ------------------------------------------------------- 4. the API --
        client = create_app(db, runner).test_client()
        client.post("/api/run/command", json={"userId": 3, "action": "resume"})
        check("API resume sets running", runner.read_control(3)["mode"] == "running")
        client.post("/api/run/command", json={"userId": 3, "action": "pause"})
        check("API pause sets paused", runner.read_control(3)["mode"] == "paused")

        client.post("/api/run/command", json={"userId": 3, "action": "home"})
        after = runner.read_control(3)
        check("API home queues the command", after["command"] == "home")
        check("API home also pauses", after["mode"] == "paused",
              "going home while applying would immediately carry on")

        r = client.post("/api/run/command", json={"userId": 3, "action": "explode"})
        check("unknown action is rejected", r.status_code == 400, f"got {r.status_code}")
        r = client.post("/api/run/command", json={"action": "pause"})
        check("missing userId is rejected", r.status_code == 400, f"got {r.status_code}")

        # ------------------------------- 5. a launched run starts paused --
        runner.write_control(7, mode="running")          # stale state from before
        fake = tmp / "main3.py"
        fake.write_text("import time\nprint('fake', flush=True)\ntime.sleep(30)\n", encoding="utf-8")
        spawn = RunnerManager(db, tmp)
        spawn.preflight = lambda ids: []
        spawn.start([7])
        time.sleep(1.0)
        check("starting a run forces paused, ignoring stale state",
              spawn.read_control(7)["mode"] == "paused",
              f"got {spawn.read_control(7)['mode']!r}")
        check("status reports the mode", spawn.status()[0]["mode"] == "paused")
        spawn.stop(7)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL RUN CONTROL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
