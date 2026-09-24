"""The run loop must never let an error close the browser.

Logs/Log46.txt: a job title carrying U+202F (narrow no-break space) raised
UnicodeEncodeError from inside print() on a cp1252 console. That reached
RunUser, which closed Chrome and relaunched it -- losing a logged-in browser
over a log line. Logs/Log41.txt was the same shape: an unreadable company name
restarted the browser 9 times in a row.

Two guarantees are pinned here:
  1. Printing anything, in any encoding, cannot raise.
  2. An exception from transition() is recovered in place -- the run keeps
     going, the state resets, the failed job is remembered, and nothing the
     StateMachine does closes the browser.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


# The exact title from Log46, narrow no-break space and all.
NASTY = "Forward Deployed Solution Engineer | Remote — €90k – café"


class FakeHelper:
    """Stands in for IndeedHelper: records what the run loop did to it."""

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.envs_read = 0
        self.backToStartCalls = 0
        self.goHomeCalls = 0
        self.closed = False
        self.currentJobKey = "jk_that_failed"
        self.crashedJobKeys = set()
        self.jobOpeningGenerator = iter(())
        self.generatorRebuilds = 0

    def getCurrentEnv(self, quiet=False):
        self.envs_read += 1
        # Stop the loop once the scripted failures are done.
        if self.envs_read > self.fail_times:
            return "exit"
        return f"https://www.indeed.com/viewjob?jk=abc|{NASTY}"

    def process_job_openings(self):
        self.generatorRebuilds += 1
        return iter(())

    def backToStart(self):
        self.backToStartCalls += 1

    def goHome(self):
        self.goHomeCalls += 1

    def close(self):
        self.closed = True

    def reportAction(self, *a, **k):
        pass


class FakeControl:
    def pending_command(self):
        return None


def build_machine(helper):
    sm = main3.StateMachine.__new__(main3.StateMachine)
    sm.helper = helper
    sm.control = FakeControl()
    sm.states = ["start", "initNewApp"]
    sm.current_state = "initNewApp"
    sm.prev_state = "start"
    sm.lastEnvironment = ""
    sm.selfPaused = False
    sm.stuckCalls = []
    sm.waitWhilePaused = lambda: None
    sm.isInterstitial = lambda env: False
    sm.handleStuck = lambda *a: sm.stuckCalls.append(a)
    return sm


def test_printing_never_raises():
    """A cp1252 stream must not be able to kill the run (Log46)."""
    original = sys.stdout
    # Exactly what Python hands you on a Windows console: no reconfigure, no
    # replacement characters, raises on anything outside cp1252.
    sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    try:
        main3.ct_print("reportAction", f"Calling function: newApp() in environment: {NASTY}")
        main3.ct_section("PAGE", NASTY, NASTY)
        main3.ct_error("somewhere", ValueError(NASTY))
        raised = None
    except Exception as exc:  # noqa: BLE001 - the point of the test
        raised = exc
    finally:
        sys.stdout = original
    check("printing a cp1252-hostile title does not raise", raised is None,
          f"raised {type(raised).__name__}: {raised}" if raised else "")


def test_run_recovers_without_closing():
    helper = FakeHelper(fail_times=3)
    sm = build_machine(helper)

    def boom(env):
        raise UnicodeEncodeError("charmap", NASTY, 0, 1, "character maps to <undefined>")

    sm.transition = boom
    sm.recoverInPlace = main3.StateMachine.recoverInPlace.__get__(sm)
    main3.StateMachine.run(sm)

    check("the run survived every error instead of propagating", True)
    check("the browser was never closed", not helper.closed)
    check("each failure was recovered in place", helper.backToStartCalls == 3,
          f"backToStart called {helper.backToStartCalls} times, expected 3")
    check("the failed job is remembered so it is not retried",
          helper.crashedJobKeys == {"jk_that_failed"}, f"got {helper.crashedJobKeys}")
    check("the dead job generator was rebuilt", helper.generatorRebuilds == 3,
          f"rebuilt {helper.generatorRebuilds} times, expected 3")
    check("the state machine was reset to the first state",
          sm.current_state == "start" and sm.prev_state is None,
          f"state={sm.current_state} prev={sm.prev_state}")
    check("a person was not bothered for a handful of errors", sm.stuckCalls == [],
          f"handleStuck called {len(sm.stuckCalls)} times")


def test_persistent_failure_asks_for_help():
    helper = FakeHelper(fail_times=main3.StateMachine.RECOVER_IN_PLACE_LIMIT)
    sm = build_machine(helper)
    sm.transition = lambda env: (_ for _ in ()).throw(RuntimeError("same wall every time"))
    sm.recoverInPlace = main3.StateMachine.recoverInPlace.__get__(sm)
    main3.StateMachine.run(sm)

    check("after repeated failures a person is alerted", len(sm.stuckCalls) == 1,
          f"handleStuck called {len(sm.stuckCalls)} times")
    check("the browser is still open when help is asked for", not helper.closed)


def main() -> int:
    test_printing_never_raises()
    print()
    test_run_recovers_without_closing()
    print()
    test_persistent_failure_asks_for_help()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): " + "; ".join(failures))
        return 1
    print("ALL RUN-LOOP RESILIENCE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
