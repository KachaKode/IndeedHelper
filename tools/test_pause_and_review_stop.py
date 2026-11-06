"""Two run-control fixes:

1. Pausing used to only be checked BETWEEN whole page functions. A screener
   questions page answers every question on it inside one
   analyzeAndAnsQuestions() call, with no check of its own, so pressing Pause
   mid-page kept right on answering (and clicking Continue) until every
   question on that page was done.

2. submitApp() stops deliberately every time, right before the irreversible
   Submit click, so a person can look the review page over first
   (Logs/Log54.txt: "STUCK: submitApp() could not continue"). The generic
   handleStuck() clears an alert the moment the page differs from the one it
   stopped on -- which fits a selector that was temporarily missing, but not
   this stop: looking the application over often means clicking back to the
   screener questions to check an answer, and that page change is not a
   submission. Treating it as one both silenced the alert and flipped the run
   back to "running" right as the questions page's own default rule matched,
   re-answering questions and clicking Continue on an application that was
   already sitting at review.
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
    def __init__(self, mode="running"):
        self._mode = mode

    def mode(self):
        return self._mode

    def set_mode(self, mode):
        self._mode = mode

    def seq(self):
        return 1

    def pending_command(self):
        return None


def make_helper():
    """A real IndeedHelper, built the way tools/test_review_flow.py does --
    skip IndeedHelper.__init__ (database setup) and run only the parent's,
    which is cheap and just sets the WHOLE/CLASS/CONTAINS/etc. constants."""
    wrap = main3.IndeedHelper.__new__(main3.IndeedHelper)
    main3.PlaywrightWrap.__init__(wrap, "", "", "user-data-dir=")
    wrap.actions = []
    wrap.reportAction = lambda message, *_a, **_k: wrap.actions.append(message)
    return wrap


# ======================================================================
# 1. Pausing mid-page stops analyzeAndAnsQuestions() between questions.
# ======================================================================

def test_pause_stops_between_questions() -> None:
    print("--- pausing mid-page stops the screener questions loop ---")
    wrap = make_helper()
    wrap.control = FakeControl("running")

    questions = ["Q1", "Q2", "Q3"]
    processed: list[str] = []
    keep_going_calls = []

    def fake_find_and_click(*args, **kwargs):
        xpath = args[2] if len(args) > 2 else kwargs.get("elementXpath")
        if xpath == "Questions-item":
            return list(questions)
        return None  # the blind "Continue" probe click

    def fake_process_question(questn):
        processed.append(questn)
        if questn == "Q1":
            # Simulate the Run tab's Pause button being pressed while Q2 and
            # Q3 are still sitting on the page, unanswered.
            wrap.control.set_mode("paused")
        return None

    wrap.findAndClick = fake_find_and_click
    wrap._questionKey = lambda q: q
    wrap.checkIfMoreQuestionsAppeared = lambda _args: None
    wrap.MML = []
    wrap.process_question = fake_process_question
    wrap.keepGoing = lambda: keep_going_calls.append(True)
    wrap.driver = type("D", (), {"current_url": "https://example.test/questions"})()

    result = wrap.analyzeAndAnsQuestions()

    check("only the question in progress when Pause was pressed got answered",
          processed == ["Q1"], f"processed {processed}")
    check("Continue was never clicked -- the page was not advanced while paused",
          keep_going_calls == [], f"keepGoing() called {len(keep_going_calls)} time(s)")
    check("the function returns without raising", result is None)


def test_pause_requested_before_any_question_is_touched() -> None:
    print()
    print("--- already paused before the questions page is even read ---")
    wrap = make_helper()
    wrap.control = FakeControl("paused")

    find_and_click_calls = []
    wrap.findAndClick = lambda *a, **k: find_and_click_calls.append((a, k))

    result = wrap.analyzeAndAnsQuestions()

    check("nothing on the page was even looked at",
          find_and_click_calls == [], f"findAndClick called: {find_and_click_calls}")
    check("the function returns without raising", result is None)


def test_pause_requested_is_safe_without_a_control() -> None:
    print()
    print("--- helpers built without a StateMachine (other tests) still work ---")
    wrap = make_helper()
    # No wrap.control at all -- e.g. tools/test_review_flow.py's IndeedHelper,
    # which never goes through StateMachine.__init__.
    check("no control object means 'keep going', not a crash",
          wrap._pauseRequested() is False)


# ======================================================================
# 2. The review-ready stop only clears on an actual submission.
# ======================================================================

QUESTIONS_ENV = ("https://smartapply.indeed.com/beta/indeedapply/form/review-module"
                 "|Answer screener questions from the employer")
SUBMITTED_ENV = "https://smartapply.indeed.com/beta/indeedapply/postresumeapply|Your application has been submitted"
DASHBOARD_ENV = "https://u.indeed.com/o/dashboard?workflowExecutionId=abc123|Indeed"


def test_is_submitted_confirmation() -> None:
    print()
    print("--- isSubmittedConfirmation only matches the two real confirmations ---")
    sm = main3.StateMachine.__new__(main3.StateMachine)

    check("the screener-questions page (going back to check an answer) is NOT a submission",
          sm.isSubmittedConfirmation(QUESTIONS_ENV) is False)
    check("the 'application submitted' title is",
          sm.isSubmittedConfirmation(SUBMITTED_ENV) is True)
    check("the u.indeed.com dashboard redirect is too",
          sm.isSubmittedConfirmation(DASHBOARD_ENV) is True)


def test_transition_routes_submitapp_failure_to_review_stop() -> None:
    print()
    print("--- submitApp() failing calls handleReviewStop, not the generic handleStuck ---")

    class FakeHelper:
        def __init__(self, env):
            self.env = env
            self.actions = []

        def reportAction(self, message, *_a, **_k):
            self.actions.append(message)

        def getCurrentEnv(self, quiet=True):
            return self.env

    helper = FakeHelper(QUESTIONS_ENV)
    sm = main3.StateMachine.__new__(main3.StateMachine)
    sm.helper = helper
    sm.control = FakeControl("running")
    sm.selfPaused = False
    sm.current_state = "finishedAddingDocs"
    sm.prev_state = None
    sm.states = ["start"]

    ENV_PATTERN = ".*"
    sm.envIsValid = lambda e: ENV_PATTERN
    sm.envNextTrans = lambda e: ENV_PATTERN
    sm._checkForStuckLoop = lambda *_a, **_k: False
    sm.transitions = {ENV_PATTERN: {"finishedAddingDocs": ("submitApp", "submittedApplication")}}

    def fake_submit_app():
        raise main3.NeedsHumanError("TEMPORARY STOP before submitting")

    helper.submitApp = fake_submit_app

    review_stop_calls = []
    stuck_calls = []
    sm.handleReviewStop = lambda environment, message: review_stop_calls.append((environment, message))
    sm.handleStuck = lambda *a, **k: stuck_calls.append((a, k))

    sm.transition(QUESTIONS_ENV)

    check("handleReviewStop was called", len(review_stop_calls) == 1,
          f"calls: {review_stop_calls}")
    check("the generic handleStuck was NOT called -- it would auto-clear on any page change",
          stuck_calls == [], f"calls: {stuck_calls}")
    check("state did not silently advance to submittedApplication",
          sm.current_state == "finishedAddingDocs", f"current_state={sm.current_state!r}")


def test_review_stop_ignores_going_back_to_questions() -> None:
    print()
    print("--- going back to the questions page does not clear the review-stop alert ---")

    class FakeHelper:
        def __init__(self, envs):
            self._envs = list(envs)
            self.actions = []

        def reportAction(self, message, *_a, **_k):
            self.actions.append(message)

        def getCurrentEnv(self, quiet=True):
            # Each poll inside pauseAndAlert's loop advances one step: first
            # the person clicks back to the questions page to check an
            # answer, then they submit for real.
            if len(self._envs) > 1:
                return self._envs.pop(0)
            return self._envs[0]

    helper = FakeHelper([QUESTIONS_ENV, QUESTIONS_ENV, SUBMITTED_ENV])
    sm = main3.StateMachine.__new__(main3.StateMachine)
    sm.helper = helper
    sm.control = FakeControl("paused")
    sm.selfPaused = False
    sm.beep = lambda: None  # don't actually make noise during tests

    sm.handleReviewStop(QUESTIONS_ENV, "TEMPORARY STOP before submitting")

    check("clearing only happened once the submitted page was actually seen",
          any("submitted" in a.lower() for a in helper.actions),
          f"reported actions: {helper.actions}")
    check("the run is no longer self-paused once the submission is seen",
          sm.selfPaused is False)


def main() -> int:
    test_pause_stops_between_questions()
    test_pause_requested_before_any_question_is_touched()
    test_pause_requested_is_safe_without_a_control()
    test_is_submitted_confirmation()
    test_transition_routes_submitapp_failure_to_review_stop()
    test_review_stop_ignores_going_back_to_questions()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL PAUSE / REVIEW-STOP TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
