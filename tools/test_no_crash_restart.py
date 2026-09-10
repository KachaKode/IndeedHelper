"""A missing control must pause the run, not close the browser.

From a real run: the review page no longer had a text node of exactly
"Resume", so hitEditFromReviewPage's `findClosestRelatives(...)[0]` raised
IndexError. Nothing caught it below RunUser, whose handler closes Chrome and
relaunches -- which is what "the browser closed twice" was.

Two separate things are tested here:
  1. hitEditFromReviewPage finds the Edit control across the shapes Indeed
     might render, and raises NeedsHumanError (not IndexError) when it cannot.
  2. StateMachine.transition turns that into a pause, and does the same for a
     state with no configured transition -- which crashed on None.strip().
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


# The shapes the review page's resume section might take. The first is what the
# old code assumed; the rest are what broke it.
SHAPES = {
    "bare text node (what the old code assumed)":
        """<div><h3>Resume</h3><button>Edit</button></div>""",
    "heading padded with whitespace":
        """<div><h3>
             Resume
           </h3><button>Edit</button></div>""",
    "heading reworded":
        """<div><h3>Your resume</h3><button>Edit</button></div>""",
    "icon button identified by aria-label":
        """<div><h3>Resume</h3>
             <button aria-label="Edit resume"></button></div>""",
    "edit button identified by data-testid":
        """<div><span>anything at all</span>
             <button data-testid="ResumeSection-edit-button"></button></div>""",
}

CLICK_PROBE = ("<div id='out'>nothing</div>"
               "<script>addEventListener('click', e => {"
               "  if (e.target.tagName === 'BUTTON')"
               "    document.getElementById('out').textContent = 'edit clicked';"
               "});</script>")


class FakeControl:
    """Stands in for the GUI control file: always running, never changes."""

    def mode(self):
        return "running"

    def seq(self):
        return 1

    def pending_command(self):
        return None


def state_machine_for(helper):
    sm = main3.StateMachine.__new__(main3.StateMachine)
    sm.helper = helper
    sm.control = FakeControl()
    sm.selfPaused = False
    sm.current_state = "hitApply"
    sm.prev_state = None
    sm.states = ["start"]
    return sm


def main() -> int:
    tmp = Path(tempfile.mkdtemp())

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()

        wrap = main3.IndeedHelper.__new__(main3.IndeedHelper)
        main3.PlaywrightWrap.__init__(wrap, "", "", "user-data-dir=")
        wrap._page = page
        wrap._context = page.context
        wrap.outputFile = None
        # The 45s wait for a review page to finish loading is correct on a
        # real page and pure dead time here, where the fixtures never load.
        wrap.PAGE_LOAD_LIMIT = 2

        print("--- the review page's Edit control, in each shape ---")
        for label, markup in SHAPES.items():
            page.set_content(markup + CLICK_PROBE)
            page.wait_for_timeout(100)
            try:
                wrap.hitEditFromReviewPage()
                clicked = page.text_content("#out") == "edit clicked"
                check(f"finds Edit: {label}", clicked, "found nothing to click")
            except main3.NeedsHumanError:
                check(f"finds Edit: {label}", False, "raised NeedsHumanError")
            except IndexError as exc:
                check(f"finds Edit: {label}", False, f"IndexError -- the old crash: {exc}")

        print()
        print("--- when there is genuinely nothing there ---")
        # The prose deliberately contains the word "resume". A looser matcher
        # picks that sentence up, climbs to the nearest Edit -- Contact
        # information's -- and edits the wrong section instead of reporting.
        NOTHING_THERE = ("<div><h3>Contact information</h3><button>Edit</button></div>"
                         "<p>This application has no resume section on the page at all.</p>")
        page.set_content(NOTHING_THERE + CLICK_PROBE)
        page.wait_for_timeout(100)
        raised = None
        try:
            wrap.hitEditFromReviewPage()
        except BaseException as exc:      # noqa: BLE001 -- the type is the point
            raised = exc
        check("a missing resume section raises NeedsHumanError",
              isinstance(raised, main3.NeedsHumanError),
              f"raised {type(raised).__name__ if raised else 'nothing'}")
        check("and NeedsHumanError is not something RunUser restarts on",
              not isinstance(raised, main3.RecoverableBrowserError),
              "it would be treated as a browser fault and close Chrome")
        check("it does not edit the wrong section instead",
              page.text_content("#out") == "nothing",
              "clicked an Edit button belonging to some other section")

        print()
        print("--- the state machine pauses instead of crashing ---")
        page.set_content(NOTHING_THERE + CLICK_PROBE)
        page.wait_for_timeout(100)
        sm = state_machine_for(wrap)
        paused = {}

        def fake_pause(reason, isResolved, message, clearedMessage, **kwargs):
            paused["reason"] = reason
            paused["message"] = message
            return False          # "resumed by hand, still stuck"

        sm.pauseAndAlert = fake_pause
        sm.envIsValid = lambda env: "known"
        sm.envNextTrans = lambda env: "known"
        sm.isInterstitial = lambda env: False
        sm.transitions = {"known": {"hitApply": ("hitEditFromReviewPage", "didContactInfo")}}

        env = ("https://smartapply.indeed.com/beta/indeedapply/form/review-module"
               "|Review the contents of this job application | Indeed")
        try:
            sm.transition(env)
            crashed = None
        except BaseException as exc:      # noqa: BLE001
            crashed = exc
        check("a NeedsHumanError does not escape transition()", crashed is None,
              f"escaped as {type(crashed).__name__ if crashed else ''}: {crashed}")
        check("it pauses and alerts instead", "STUCK" in paused.get("reason", ""),
              f"reason was {paused.get('reason')!r}")
        check("the state did not advance on a failure",
              sm.current_state == "hitApply", f"advanced to {sm.current_state}")

        # A second pass on the same page must stay quiet, not beep again.
        paused.clear()
        sm.transition(env)
        check("a page already waved through does not re-alert", not paused,
              f"alerted again: {paused.get('reason')!r}")

        # ...but the waiver expires, so later jobs on the same URL still alert.
        sm._attentionWaivedFor = (env, 0)      # long ago
        paused.clear()
        sm.transition(env)
        check("the waiver expires so a later job still alerts",
              "STUCK" in paused.get("reason", ""),
              "stayed silent forever after one wave-through")

        print()
        print("--- a pause must not clear itself for a cosmetic URL change ---")
        # Indeed rewrites query strings without navigating: the resume editor
        # drops its `continue=` parameter on its own. A run paused over a work
        # experience that would not delete, then 1.3 seconds later announced
        # "ATTENTION CLEARED" because
        #   /resume?co=US&hl=en_US&continue=...  had become  /resume
        # while the offending entry was still sitting on the page.
        SM = main3.StateMachine
        withParam = ("https://profile.indeed.com/resume?co=US&hl=en_US&continue=https%3A%2F%2Fx"
                     "|Edit your resume")
        without = "https://profile.indeed.com/resume|Edit your resume"
        elsewhere = "https://profile.indeed.com/resume/contact|About you"
        check("a dropped query string is the same page",
              SM.pageIdentity(withParam) == SM.pageIdentity(without),
              "the alarm would clear itself while nothing had changed")
        check("a trailing slash is the same page",
              SM.pageIdentity(without) == SM.pageIdentity(without.replace("/resume|", "/resume/|")))
        check("a genuinely different page still counts as different",
              SM.pageIdentity(withParam) != SM.pageIdentity(elsewhere))

        # And when a pause DOES resolve, the run has to come back on its own.
        sm3 = state_machine_for(wrap)
        sm3.selfPaused = True
        seen = {}

        def resolving_pause(reason, isResolved, message, clearedMessage, **kwargs):
            # Stand in for the real loop's resolved branch.
            seen["reason"] = reason
            sm3.selfPaused = False
            return True

        sm3.pauseAndAlert = resolving_pause
        sm3.handleStuck("something", withParam, "message")
        check("a resolved pause leaves the run running, not paused",
              sm3.selfPaused is False,
              "it announced ATTENTION CLEARED and then sat waiting for a human anyway")

        src = (ROOT / "main3.py").read_text(encoding="utf-8")
        idx = src.find('ct_print("StateMachine", "ATTENTION CLEARED"')
        check("the real resolved branch clears selfPaused",
              "self.selfPaused = False" in src[idx:idx + 700], "it stays paused forever")

        print()
        print("--- a state with no configured transition ---")
        sm2 = state_machine_for(wrap)
        alerted = {}
        sm2.pauseAndAlert = lambda reason, isResolved, message, clearedMessage, **kw: (
            alerted.update(reason=reason) or True)
        sm2.envIsValid = lambda e: "known"
        sm2.envNextTrans = lambda e: "known"
        sm2.isInterstitial = lambda e: False
        sm2.current_state = "somethingUnmapped"
        sm2.transitions = {"known": {"hitApply": ("hitEditFromReviewPage", "didContactInfo")}}
        try:
            sm2.transition(env)
            crashed = None
        except BaseException as exc:      # noqa: BLE001
            crashed = exc
        check("no rule for the current state does not crash on None.strip()",
              crashed is None,
              f"raised {type(crashed).__name__ if crashed else ''}: {crashed}")
        check("it reports the config gap and pauses",
              "no rule" in alerted.get("reason", ""),
              f"reason was {alerted.get('reason')!r}")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL CRASH/RESTART TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
