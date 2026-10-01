"""A NeedsHumanError raised after the page function navigated must be
reported against the page it is ACTUALLY stuck on, not the page transition()
was called with.

From Logs/Log48.txt / HTMLz/work_history_stuck.html: doWorkExp() adds one job
after another in a single call, each behind its own "Add work experience"
button. The second entry's job title field lost a rendering race, handleJob()
filled the rest of the form anyway and clicked Save, Indeed blocked the save
on the empty required field, and handleJob() correctly raised NeedsHumanError.

But transition() passed the ENVIRONMENT IT STARTED WITH (the resume list page,
before "Add work experience" was ever clicked) into handleStuck(). handleStuck's
auto-resume considers the situation resolved the moment the live page differs
from that baseline -- and by the time the exception reached it, the live page
already WAS different (profile.indeed.com/resume/experience/add), simply
because doWorkExp() had navigated there before the error surfaced. So the
pause declared "ATTENTION CLEARED" about a second after it began, nobody had
looked at anything, and the run went on to retry "Add work experience" against
the same still-broken, still-open form thirty-plus times before finally
giving up for real.

The fix: re-read the environment right before calling handleStuck, so the
"has the page moved on" check is measured against the page the error is
actually sitting on.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402

main3.t.sleep = lambda *_a, **_k: None

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


class FakeControl:
    def mode(self):
        return "running"

    def seq(self):
        return 1

    def pending_command(self):
        return None


class FakeHelper:
    def __init__(self, live_env):
        self.live_env = live_env
        self.actions = []

    def reportAction(self, message, *_args, **_kwargs):
        self.actions.append(message)

    def getCurrentEnv(self, quiet=True):
        return self.live_env


def state_machine_for(helper):
    sm = main3.StateMachine.__new__(main3.StateMachine)
    sm.helper = helper
    sm.control = FakeControl()
    sm.selfPaused = False
    sm.current_state = "finishedEditSummary"
    sm.prev_state = None
    sm.states = ["start"]
    return sm


def main() -> int:
    ENV_PATTERN = ".*"

    # The page transition() was called with -- the resume LIST page, before
    # "Add work experience" navigated anywhere.
    stale_env = ("https://profile.indeed.com/resume?co=US&hl=en_US&continue=https%3A%2F%2Fx"
                 "|Profile - Indeed")
    # Where the run actually is by the time handleJob() raises -- a different
    # page entirely, reached via clicks that happened INSIDE doWorkExp().
    live_env = "https://profile.indeed.com/resume/experience/add|Add work experience"

    helper = FakeHelper(live_env)
    sm = state_machine_for(helper)
    sm.envIsValid = lambda e: ENV_PATTERN
    sm.envNextTrans = lambda e: ENV_PATTERN
    sm._checkForStuckLoop = lambda *_a, **_k: False

    def fake_start_work_exp():
        raise main3.NeedsHumanError(
            "Clicked 'Save this work experience' but the form is still open.")

    helper.startWorkExp = fake_start_work_exp
    sm.transitions = {ENV_PATTERN: {"finishedEditSummary": ("startWorkExp", "finishedEditWorkExp")}}

    captured = {}

    def fake_handle_stuck(reason, environment, message):
        captured["environment"] = environment

    sm.handleStuck = fake_handle_stuck

    sm.transition(stale_env)

    check("handleStuck() was called at all", "environment" in captured)
    check("it is told the page the error is ACTUALLY on, not the page transition() started with",
          captured.get("environment") == live_env,
          f"got {captured.get('environment')!r}, expected the live page {live_env!r} "
          f"-- passing the stale page lets handleStuck's auto-resume see a 'page changed' "
          f"the instant it looks, since the page had already changed before the pause began")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL STALE ENVIRONMENT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
