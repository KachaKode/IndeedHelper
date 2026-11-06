"""The review page must not wave through a resume that was never rewritten.

Logs/Log55.txt: the run arrived at the review page from hitApply, searched the
page for the resume's Edit button, found none, logged "has no resume edit step"
and went on to the "ready to review" beep with the PREVIOUS application's
resume. The search never reached the review page's iframe
(<iframe data-testid="application-preview">), which is where its sections are.

Two fixes are pinned here:

  1. hitEditFromReviewPage() also looks inside the page's iframes.
  2. verifyResumeEdited(), a new step on the review page, compares the summary
     the page shows with the summary in the user's last application. Identical
     means the resume was not rewritten for this job, so it clicks Edit.

The summary text below is the one from the report, byte for byte as it was
pasted; HTMLz/review_resume5.html is the real page showing it.
"""

from __future__ import annotations

import html as htmlmod
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402
import resume_repeat  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

# transition() sleeps 1s per call for the real polling loop's benefit.
main3.t.sleep = lambda *_a, **_k: None

failures: list[str] = []

REPORTED_SUMMARY = (
    "I am a Python and TypeScript engineer with hands-on experience in data generation, "
    "labeling, evaluation, and end-to-end ML data platforms. \n"
    "I built an automated, real-time relative-value trading engine in Python that ingests "
    "multi-instrument data, normalizes to a common unit, derives a signal from executable "
    "bid and ask prices, and uses a rolling-window adaptive Bollinger style envelope with "
    "three tiered state machines and unit tests plus a replay capability. \n"
    "I developed an end-to-end mean reversion trading platform with Python, PyTorch, and "
    "AWS SageMaker, building data pipelines, walk-forward validation, and deploying models "
    "as real-time endpoints or batch jobs with CloudWatch monitoring and Model Monitor for "
    "drift; I track Sharpe ratio, win rate, and maximum drawdown and define rubrics for "
    "model selection and signal stability. \n"
    "I designed the Redfish Beach Equipment Rental Platform backend with Node.js and "
    "MongoDB, implemented authentication with Auth.js, and led a data quality initiative "
    "with validation rules and a rubric to ensure data accuracy for downstream model work "
    "and optimization. \n"
    "I share Turing's philosophy of turning complex data problems into repeatable "
    "processes, and I can commit to 40 hours per week with at least a six-hour overlap with "
    "Pacific Time at a rate of $120 per hour, ready to contribute immediately shaping data "
    "generation, labeling, and evaluation pipelines.")

OTHER_SUMMARY = (
    "I design and ship data pipelines and scalable infrastructure that turn messy inputs "
    "into clean, documented processes and data-driven evaluation criteria.")


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def page_summary_html(summary: str) -> str:
    """The summary the way the review page renders it: a <div> per sentence,
    each ending in a non-breaking space."""
    divs = "".join(f"<div>{htmlmod.escape(s.strip())}&nbsp;</div>"
                   for s in summary.split("\n"))
    return f'<div id="res_summary" data-shield-id="res_summary">{divs}</div>'


EDIT_IN_FRAME = ("<button aria-label='Edit resume' "
                 "onclick=\"document.getElementById('marker').textContent='clicked'\">"
                 "Edit</button><div id='marker'>not clicked</div>")


def review_page(inner_html: str) -> str:
    # The real Submit button's test id, so waitForReviewPage() resolves
    # instantly rather than waiting out its 45s on every call.
    return ('<button data-testid="submit-application-button">Submit your application</button>'
            f'<iframe data-testid="application-preview" srcdoc="{htmlmod.escape(inner_html)}">'
            '</iframe>')


def frame_marker(page) -> str:
    frame = next(f for f in page.frames if f != page.main_frame)
    return frame.evaluate("document.getElementById('marker').textContent")


def build_helper(page):
    located = main3.IndeedHelper.__new__(main3.IndeedHelper)
    main3.PlaywrightWrap.__init__(located, "", "", "user-data-dir=")
    located._page = page
    located._context = page.context
    located.outputFile = None
    located.user_id = 9
    located.SUMMARY_READ_LIMIT = 2          # a missing summary should not cost 10s a case
    return located


def raised_by(fn):
    try:
        return fn(), None
    except BaseException as exc:      # noqa: BLE001 -- the type is the point
        return None, exc


def transitions_for(env_snippet):
    """The config's rules for the page whose pattern contains env_snippet."""
    text = (ROOT / "config" / "StateTransitions.txt").read_text(encoding="utf-8")
    rules, inside, pending = {}, False, []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if "|" in stripped and "--" not in stripped:
            inside = env_snippet in stripped.lower()
            pending = []
            continue
        if not inside:
            continue
        if "--" in stripped:
            state, func, nxt = stripped.split("--")
            for s in pending + [state.strip()]:
                rules[s] = (func.strip("() "), nxt.strip("-> "))
            pending = []
        else:
            pending.append(stripped)
    return rules


def main() -> int:
    # --- comparing two summaries --------------------------------------------
    print("--- the same summary in the two shapes it arrives in ---")
    page_text = "\n".join(s.strip() + " " for s in REPORTED_SUMMARY.split("\n"))
    check("the stored form and the page's form of one summary match",
          resume_repeat.same_summary(page_text, REPORTED_SUMMARY))
    check("HTML entities do not make it a different summary",
          resume_repeat.same_summary("Turing&#39;s &amp; co", "Turing's & co"))
    check("a different summary does not match",
          not resume_repeat.same_summary(OTHER_SUMMARY, REPORTED_SUMMARY))
    check("a summary that only gained a sentence does not match",
          not resume_repeat.same_summary(REPORTED_SUMMARY + " Extra sentence.", REPORTED_SUMMARY))
    check("an empty summary never matches, not even another empty one",
          not resume_repeat.same_summary("", "") and not resume_repeat.same_summary(None, "x"))

    # --- finding the last application ---------------------------------------
    print()
    print("--- the user's last application ---")
    tmp = Path(tempfile.mkdtemp())
    dbfile = tmp / "t.db"
    conn = sqlite3.connect(dbfile)
    conn.execute("CREATE TABLE applications (id INTEGER PRIMARY KEY, user_id INTEGER, "
                 "resumeSummary TEXT)")
    conn.executemany("INSERT INTO applications (id, user_id, resumeSummary) VALUES (?,?,?)", [
        (1, 9, "first"), (2, 9, OTHER_SUMMARY), (3, 4, "someone else, newer"),
        (4, 9, REPORTED_SUMMARY), (5, 9, "   "), (6, 9, None)])
    conn.commit()
    conn.close()
    found = resume_repeat.last_application_summary(9, str(dbfile))
    check("it is the user's highest-numbered application that has a summary",
          found == (4, REPORTED_SUMMARY), f"got {found!r}")
    check("another user's applications are never used",
          resume_repeat.last_application_summary(4, str(dbfile)) == (3, "someone else, newer"))
    check("a user with no applications gets None",
          resume_repeat.last_application_summary(77, str(dbfile)) is None)
    missing = tmp / "missing.db"
    check("an unreadable database gets None",
          resume_repeat.last_application_summary(9, str(missing)) is None)
    check("and looking does not create an empty database file there",
          not missing.exists(), "a wrong working directory would leave stray empty databases")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        located = build_helper(page)

        # --- reading the page -----------------------------------------------
        print()
        print("--- reading the summary off the review page ---")
        page.set_content(review_page(page_summary_html(REPORTED_SUMMARY)))
        page.wait_for_timeout(200)
        shown = located.reviewPageSummary()
        check("the summary is read out of the preview iframe",
              shown is not None and resume_repeat.same_summary(shown, REPORTED_SUMMARY),
              f"got {shown!r}")

        page.set_content(review_page("<p>no summary in this preview</p>"))
        page.wait_for_timeout(200)
        check("a page with no summary reads as None, not an error",
              located.reviewPageSummary() is None)

        capture = ROOT / "HTMLz" / "review_resume5.html"
        if capture.exists():
            page.goto(capture.as_uri())
            page.wait_for_timeout(500)
            shown = located.reviewPageSummary()
            check("HTMLz/review_resume5.html (the reported page) gives the reported summary",
                  shown is not None and resume_repeat.same_summary(shown, REPORTED_SUMMARY),
                  f"got {shown!r}")
        else:
            print("       (skipped: HTMLz/review_resume5.html is not there)")

        # --- the first visit: Edit lives in the iframe ----------------------
        print()
        print("--- hitEditFromReviewPage() finds Edit inside the iframe ---")
        page.set_content(review_page(EDIT_IN_FRAME))
        page.wait_for_timeout(200)
        clicked, err = raised_by(located.hitEditFromReviewPage)
        check("it did not decide the page has no resume edit step",
              err is None and clicked is not None, f"returned {clicked!r}, raised {err!r}")
        check("and the iframe's Edit button is the thing that got clicked",
              frame_marker(page) == "clicked", f"marker says {frame_marker(page)!r}")

        # --- the check itself -----------------------------------------------
        print()
        print("--- verifyResumeEdited() ---")
        shipped = main3.last_application_summary

        def last_is(summary, app_id=5238):
            main3.last_application_summary = lambda user_id: (app_id, summary)

        try:
            # identical to the last application: Edit is clicked
            located._resumeReeditAttempts = 0
            located._resumeRepeatEscalated = False
            last_is(REPORTED_SUMMARY)
            page.set_content(review_page(page_summary_html(REPORTED_SUMMARY) + EDIT_IN_FRAME))
            page.wait_for_timeout(200)
            result, err = raised_by(located.verifyResumeEdited)
            check("a summary identical to the last application's sends the bot to Edit",
                  isinstance(result, main3.GoToState) and result.state == "didContactInfo",
                  f"returned {result!r}, raised {err!r}")
            check("and Edit really was clicked", frame_marker(page) == "clicked")
            check("and the attempt is counted", located._resumeReeditAttempts == 1)

            # rewritten for this job: left alone
            located._resumeReeditAttempts = 0
            last_is(OTHER_SUMMARY)
            page.set_content(review_page(page_summary_html(REPORTED_SUMMARY) + EDIT_IN_FRAME))
            page.wait_for_timeout(200)
            result, err = raised_by(located.verifyResumeEdited)
            check("a summary that differs from the last application's passes straight through",
                  result is None and err is None, f"returned {result!r}, raised {err!r}")
            check("and nothing is clicked", frame_marker(page) == "not clicked")

            # identical, but this application offers no resume Edit at all
            last_is(REPORTED_SUMMARY)
            page.set_content(review_page(page_summary_html(REPORTED_SUMMARY)))
            page.wait_for_timeout(200)
            result, err = raised_by(located.verifyResumeEdited)
            check("with no Edit control to click it carries on rather than stopping the run",
                  result is None and err is None, f"returned {result!r}, raised {err!r}")

            # the reported page itself: identical summary, and the capture has no Edit
            if capture.exists():
                page.goto(capture.as_uri())
                page.wait_for_timeout(500)
                result, err = raised_by(located.verifyResumeEdited)
                check("the reported page, as captured, is handled without a crash",
                      err is None, f"raised {err!r}")

            # no summary on the page: cannot compare, so does not guess
            page.set_content(review_page("<p>nothing</p>" + EDIT_IN_FRAME))
            page.wait_for_timeout(200)
            result, err = raised_by(located.verifyResumeEdited)
            check("a page that shows no summary is not treated as a repeat",
                  result is None and err is None and frame_marker(page) == "not clicked",
                  f"returned {result!r}, raised {err!r}")

            # no known user: nothing to compare against
            located.user_id = -1
            page.set_content(review_page(page_summary_html(REPORTED_SUMMARY) + EDIT_IN_FRAME))
            page.wait_for_timeout(200)
            result, err = raised_by(located.verifyResumeEdited)
            check("with no user id it does nothing",
                  result is None and err is None and frame_marker(page) == "not clicked")
            located.user_id = 9

            # an Edit that never changes the summary must not loop forever
            print()
            print("--- an edit that never takes ---")
            located._resumeReeditAttempts = 0
            located._resumeRepeatEscalated = False
            last_is(REPORTED_SUMMARY)
            outcomes = []
            for _ in range(located.RESUME_REEDIT_LIMIT + 3):
                page.set_content(review_page(page_summary_html(REPORTED_SUMMARY) + EDIT_IN_FRAME))
                page.wait_for_timeout(150)
                result, err = raised_by(located.verifyResumeEdited)
                if isinstance(result, main3.GoToState):
                    outcomes.append("edit")
                elif isinstance(err, main3.NeedsHumanError):
                    outcomes.append("person")
                else:
                    outcomes.append("carry on")
            expected = (["edit"] * located.RESUME_REEDIT_LIMIT) + ["person", "carry on", "carry on"]
            check("it tries to edit a bounded number of times, calls a person once, "
                  "then carries on", outcomes == expected, f"got {outcomes}")
        finally:
            main3.last_application_summary = shipped

        browser.close()

    # --- the config ----------------------------------------------------------
    print()
    print("--- the review page's rules ---")
    rules = transitions_for("review the contents of this job application")
    check("resume done -> verified before supporting documents",
          rules.get("finishedResume") == ("verifyResumeEdited", "verifiedResume"),
          f"finishedResume -> {rules.get('finishedResume')}")
    check("verified -> the supporting documents step, as before",
          rules.get("verifiedResume") == ("clickAddDocs", "clickedAddDocs"),
          f"verifiedResume -> {rules.get('verifiedResume')}")
    check("the first visit still edits unconditionally",
          rules.get("hitApply") == ("hitEditFromReviewPage", "didContactInfo"),
          f"hitApply -> {rules.get('hitApply')}")
    check("the rest of the chain is untouched",
          rules.get("clickedAddDocs") == ("addDocs", "finishedAddingDocs")
          and rules.get("finishedAddingDocs") == ("submitApp", "submittedApplication"))
    check("every state that used to go straight to clickAddDocs goes through the check",
          all(rules.get(s, ("",))[0] == "verifyResumeEdited" for s in (
              "passedQualCheck", "passedQualReview", "passedWorkHighlight", "passedQuestions",
              "addedResume", "finishedResume", "didContactInfo", "finishedEditSkills")),
          f"{ {s: rules.get(s) for s in sorted(rules)} }")

    # --- the state machine honours GoToState ---------------------------------
    print()
    print("--- a function that picks its own next state ---")

    class FakeControl:
        def mode(self): return "running"
        def seq(self): return 1
        def pending_command(self): return None

    class FakeHelper:
        def __init__(self):
            self.actions = []
            self.env = "https://x.example/review|Review"

        def reportAction(self, message, *_a, **_k): self.actions.append(message)
        def getCurrentEnv(self, quiet=True): return self.env
        def verifyResumeEdited(self): return main3.GoToState("didContactInfo")

    pattern = "https://x.example/review|Review"
    helper = FakeHelper()
    sm = main3.StateMachine.__new__(main3.StateMachine)
    sm.helper = helper
    sm.control = FakeControl()
    sm.selfPaused = False
    sm.states = ["start"]
    sm.current_state = "finishedResume"
    sm.prev_state = None
    sm.envIsValid = lambda e: pattern
    sm.envNextTrans = lambda e: pattern
    sm.isInterstitial = lambda e: False
    sm.transitions = {pattern: {"finishedResume": ("verifyResumeEdited", "verifiedResume")}}
    sm.transition(helper.env)
    check("the state is the one the function chose, not the config's",
          sm.current_state == "didContactInfo", f"state is {sm.current_state!r}")
    check("and the state it left is remembered", sm.prev_state == "finishedResume")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL RESUME REPEAT GUARD TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
