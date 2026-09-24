"""A page that revisits the same state forever must recover, not loop silently.

From Logs/Log42.txt and Logs/Log43.txt (HTMLz/ghost_profile.html): Indeed's
resume page sometimes renders with its controls simply inert -- present or
not, nothing about the DOM says so, every click just times out. Nothing in
transition() ever raised on this, so the state machine ping-ponged between
startedOnResume and startedEditContactInfo for the rest of the run. It only
moved again once a person clicked the middle of the page and waited.

StateMachine._checkForStuckLoop is the fix: once the same state recurs on the
same page STUCK_STATE_REVISIT_LIMIT times, it clicks the page, scrolls to the
bottom, and clicks again -- repeated up to STUCK_RECOVERY_CYCLE_LIMIT times --
then falls back to the normal pause-and-beep if the page is still stuck after
that. No refresh fallback: tried by hand on this exact page and confirmed not
to help.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402

# transition() sleeps 1s per call for the real polling loop's benefit; this
# test drives dozens of calls back to back and does not need the delay.
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
    """Stands in for PlaywrightWrap: records calls instead of touching a page."""

    def __init__(self):
        self.nudges = 0
        self.actions = []

    def reportAction(self, message, *_args, **_kwargs):
        self.actions.append(message)

    def nudgeStuckPage(self):
        self.nudges += 1

    def getCurrentEnv(self, quiet=True):
        return self.env


def state_machine_for(helper):
    sm = main3.StateMachine.__new__(main3.StateMachine)
    sm.helper = helper
    sm.control = FakeControl()
    sm.selfPaused = False
    sm.current_state = "startedOnResume"
    sm.prev_state = None
    sm.states = ["start"]
    return sm


def main() -> int:
    RESUME_ENV_PATTERN = (
        "https://(((m5\\.apply|profile|smartapply)))\\.(((ca\\.)?))indeed\\.com/"
        "(((beta/indeedapply/form/)?))(((apply-)?))resume(([/?].*)?)|((.*))"
    )
    env = ("https://profile.indeed.com/resume?co=US&hl=en_US&continue=https%3A%2F%2Fx"
           "|Profile - Indeed")

    print("--- ping-ponging between two states on the same page ---")
    helper = FakeHelper()
    helper.env = env
    sm = state_machine_for(helper)
    sm.envIsValid = lambda e: RESUME_ENV_PATTERN
    sm.envNextTrans = lambda e: RESUME_ENV_PATTERN
    sm.isInterstitial = lambda e: False
    calls = []

    def fake_start_contact_info():
        calls.append("startContactInfo")
        return None  # the click never finds the button -- the ghost-page symptom

    def fake_start_at_top():
        calls.append("startAtTopOfReviewPage")
        return None

    # executeFunc() resolves page functions on self.helper, not on the state
    # machine itself.
    helper.startContactInfo = fake_start_contact_info
    helper.startAtTopOfReviewPage = fake_start_at_top
    sm.transitions = {
        RESUME_ENV_PATTERN: {
            "startedOnResume": ("startContactInfo", "startedEditContactInfo"),
            "default": ("startAtTopOfReviewPage", "startedOnResume"),
        }
    }

    paused = {}

    def fake_handle_stuck(reason, environment, message):
        paused["reason"] = reason

    sm.handleStuck = fake_handle_stuck

    # Each pair of transition() calls is one full lap: startedOnResume ->
    # startedEditContactInfo -> (falls through to default) -> startedOnResume.
    for _ in range(60):
        if paused:
            break
        sm.transition(env)

    check("it stops calling the real page functions once it recognises the loop",
          len(calls) < 60, f"kept calling the page functions {len(calls)} times")
    check("it clicks/scrolls/clicks the page before giving up", helper.nudges >= 1,
          "never tried nudgeStuckPage()")
    check("it retries the click/scroll/click cycle the configured number of times",
          helper.nudges == main3.StateMachine.STUCK_RECOVERY_CYCLE_LIMIT,
          f"nudged {helper.nudges}x, expected exactly "
          f"{main3.StateMachine.STUCK_RECOVERY_CYCLE_LIMIT}")
    check("it eventually pauses and alerts a person", "reason" in paused,
          "never reached handleStuck -- would loop forever")
    check("the pause reason names the loop", "stuck" in paused.get("reason", "").lower(),
          f"reason was {paused.get('reason')!r}")

    print()
    print("--- a normal multi-step flow on the same page is not mistaken for a loop ---")
    helper2 = FakeHelper()
    helper2.env = env
    sm2 = state_machine_for(helper2)
    sm2.envIsValid = lambda e: RESUME_ENV_PATTERN
    sm2.envNextTrans = lambda e: RESUME_ENV_PATTERN
    sm2.isInterstitial = lambda e: False

    # Each state here is visited exactly once, same as a resume edit that is
    # actually progressing through its sections.
    chain = ["startedOnResume", "startedEditContactInfo", "finishedEditContactInfo",
             "finishedEditSummary", "finishedEditWorkExp", "finishedEditEdu",
             "finishedEditSkills"]
    transitions = {}
    for i in range(len(chain) - 1):
        funcName = f"step{i}"
        setattr(helper2, funcName, lambda: "ok")
        transitions[chain[i]] = (funcName, chain[i + 1])
    sm2.transitions = {RESUME_ENV_PATTERN: transitions}
    sm2.handleStuck = lambda *a, **k: paused.update(unexpected=True)

    for _ in range(len(chain) - 1):
        sm2.transition(env)

    check("a real, progressing multi-step flow never triggers recovery",
          helper2.nudges == 0, f"nudged {helper2.nudges}x on a healthy flow")
    check("...and never pauses either", "unexpected" not in paused,
          "a healthy multi-step flow was mistaken for a stuck loop")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL STUCK LOOP RECOVERY TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
