"""The path from "Apply with Indeed" through the review page and back.

The flow, as observed on a real application:

    Apply with Indeed
      -> review page, which arrives as a SPINNER and nothing else
         (HTMLz/review_loading.html)
      -> click Edit            <button aria-label="Edit resume">Edit</button>
      -> resume selection      (HTMLz/Add_a_resume.html)
      -> Resume options -> Edit resume details
      -> resume editor         (HTMLz/Edit_Resume_HTML.html)
      -> Continue applying
      -> spinner again         (HTMLz/before_review_resume.html)
      -> review page -- and THIS time submit rather than edit

Two things make it easy to get wrong, and both are pinned here: the review page
looks empty while it loads, and the very same page needs opposite actions on the
two visits.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

H = main3.IndeedHelper
CAPTURES = ROOT / "HTMLz"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def count(page, xpath: str) -> int:
    return len(page.query_selector_all(f"xpath={xpath}"))


def load(name: str, page) -> bool:
    path = CAPTURES / name
    if not path.exists():
        print(f"       (skipped: {name} is not in HTMLz/)")
        return False
    page.goto(path.as_uri())
    page.wait_for_timeout(300)
    return True


# The review page once it has finished loading: the Edit control the user
# pointed at, verbatim.
REVIEW_LOADED = """
  <h3>Resume</h3>
  <button type="button" aria-label="Edit resume">Edit</button>
  <button><span>Submit your application</span></button>
"""

# It starts as this and becomes the above.
REVIEW_SPINNER = """
  <div data-testid="loading-indicator"><span>Loading</span></div>
  <div id="slot"></div>
  <script>
    setTimeout(function () {
      document.querySelector('[data-testid="loading-indicator"]').remove();
      document.getElementById('slot').innerHTML =
        '<h3>Resume</h3>'
        + '<button type="button" aria-label="Edit resume"'
        + ' onclick="document.title=\\'edited\\'">Edit</button>';
    }, 1500);
  </script>
"""


def transitions_for(env_snippet):
    """The config's rules for the page whose pattern contains env_snippet."""
    text = (ROOT / "config" / "StateTransitions.txt").read_text(encoding="utf-8")
    rules, inside = {}, False
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
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()

        wrap = main3.IndeedHelper.__new__(main3.IndeedHelper)
        main3.PlaywrightWrap.__init__(wrap, "", "", "user-data-dir=")
        wrap._page = page
        wrap._context = page.context
        wrap.outputFile = None

        # --- the spinner ------------------------------------------------------
        print("--- the review page arrives as a spinner ---")
        if load("review_loading.html", page):
            check("the capture really is just a loading indicator",
                  count(page, H.LOADING_INDICATOR_XPATH) > 0,
                  "no loading-indicator in it, so this test proves nothing")
            check("and carries no Edit control yet",
                  count(page, H.REVIEW_RESUME_EDIT_XPATH) == 0,
                  "the Edit button IS there, so waiting would be unnecessary")
            check("the bot can tell the page is still loading", wrap._loadingShowing())

        if load("before_review_resume.html", page):
            check("the post-resume page is a spinner too",
                  count(page, H.LOADING_INDICATOR_XPATH) > 0)

        # --- waiting it out ---------------------------------------------------
        print()
        print("--- waiting for the spinner to become the real page ---")
        page.set_content(REVIEW_SPINNER)
        page.wait_for_timeout(100)
        started = time.time()
        clicked = wrap.hitEditFromReviewPage()
        elapsed = time.time() - started
        check("Edit is clicked once the page finishes loading",
              page.title() == "edited", "never reached the Edit button")
        check("and it waited rather than giving up on the spinner",
              clicked is not None and elapsed < 12, f"took {elapsed:.1f}s")
        print(f"         waited {elapsed:.1f}s for a page that loaded after 1.5s")

        # A page that never loads must not hang forever.
        page.set_content('<div data-testid="loading-indicator">Loading</div>')
        page.wait_for_timeout(100)
        started = time.time()
        stuck = wrap.waitOutLoading(limit=3)
        check("a page that never loads gives up at the limit",
              stuck is False and time.time() - started < 8,
              f"returned {stuck} after {time.time() - started:.1f}s")

        # And a page that is not loading costs nothing.
        page.set_content("<p>already loaded</p>")
        started = time.time()
        wrap.waitOutLoading()
        check("a loaded page is not waited on at all", time.time() - started < 1,
              f"cost {time.time() - started:.1f}s for nothing")

        # --- the page that arrives AFTER the spinner --------------------------
        # review_loading.html is only the spinner; review_application.html is
        # what it becomes. That page has no Edit control at all -- its only
        # controls are "Preview what the employer sees" and "Submit your
        # application" -- so treating a missing Edit as a fault stopped the run
        # on a perfectly healthy page.
        print()
        print("--- the loaded review page (review_application.html) ---")
        if load("review_application.html", page):
            check("it is not a spinner", count(page, H.LOADING_INDICATOR_XPATH) == 0)
            check("it has no resume Edit control",
                  count(page, H.REVIEW_RESUME_EDIT_XPATH) == 0,
                  "it does have one, so this case does not exist")
            check("it does have a Submit button",
                  count(page, H.SUBMIT_BUTTON_XPATH) > 0)
            check("the bot counts it as a loaded review page", wrap._reviewPageReady())

            raised, result = None, None
            try:
                result = wrap.hitEditFromReviewPage()
            except BaseException as exc:      # noqa: BLE001
                raised = exc
            check("a review page with nothing to edit does NOT stop the run",
                  raised is None,
                  f"raised {type(raised).__name__ if raised else ''}: {raised}")
            check("and it reports that rather than pretending it clicked something",
                  result is None, f"returned {result!r}")

            # The captcha guard must not fire on the reCAPTCHA legal notice this
            # page carries in its footer text.
            check("the reCAPTCHA legal notice is not mistaken for a captcha",
                  count(page, H.SUBMIT_CAPTCHA_XPATH) == 0,
                  "every submit would pause and beep for a captcha that is not there")

        # --- acting before the page has navigated -----------------------------
        # What actually happened: the flow sat on .../applybyapplyablejobid with
        # the review page's TITLE already set, so the state machine dispatched,
        # and the real page arrived 1.3s later.
        print()
        print("--- the page that is still on its way ---")
        page.set_content("""
          <div id="slot"><p>nothing here yet</p></div>
          <script>
            setTimeout(function () {
              document.getElementById('slot').innerHTML =
                '<button aria-label="Edit resume"'
                + ' onclick="document.title=\\'edited\\'">Edit</button>'
                + '<button data-testid="submit-application-button">'
                + 'Submit your application</button>';
            }, 2000);
          </script>""")
        page.wait_for_timeout(100)
        check("the controls are genuinely absent at first", not wrap._reviewPageReady())
        started = time.time()
        wrap.hitEditFromReviewPage()
        elapsed = time.time() - started
        check("it waits for a page that has not navigated yet, instead of giving up",
              page.title() == "edited",
              "gave up before the review page arrived -- the log's exact failure")
        print(f"         waited {elapsed:.1f}s for controls that appeared after 2.0s")

        # --- the user's Edit button, verbatim ---------------------------------
        print()
        print("--- the controls named in the flow ---")
        page.set_content(REVIEW_LOADED)
        page.wait_for_timeout(100)
        check("the review page's Edit control is found",
              count(page, H.REVIEW_RESUME_EDIT_XPATH) == 1,
              f"matched {count(page, H.REVIEW_RESUME_EDIT_XPATH)}")

        if load("Add_a_resume.html", page):
            check("resume selection: the card is found",
                  count(page, H.RESUME_CARD_XPATH) > 0)
            check("resume selection: 'Resume options' is found",
                  count(page, H.RESUME_OPTIONS_XPATH) > 0)
            check("resume selection: 'Edit resume details' is found",
                  count(page, H.RESUME_EDIT_XPATH) > 0)
            # The page ships six Continue buttons; only one works.
            check("resume selection: exactly one real Continue button",
                  count(page, H.CONTINUE_BUTTON_XPATH) == 1,
                  f"found {count(page, H.CONTINUE_BUTTON_XPATH)}")

        if load("Edit_Resume_HTML.html", page):
            check("resume editor: 'Continue applying' is found",
                  count(page, H.FINISH_RESUME_XPATH) > 0)
            check("resume editor: the summary Edit button is found",
                  count(page, H.SUMMARY_EDIT_XPATH) > 0)

        # An already-open summary editor has no Edit button at all -- only
        # Save/Cancel/Clear. Waiting 8s for one that cannot be there and then
        # giving up is how a run left the summary unwritten.
        if load("Summary_Section.html", page):
            check("an open summary editor has no Edit button",
                  count(page, H.SUMMARY_EDIT_XPATH) == 0,
                  "it does have one, so the already-open case does not arise")
            check("but its Save button is there, which is how that state is spotted",
                  count(page, H.SUMMARY_SAVE_XPATH) > 0)
            check("and its text box is found",
                  count(page, H.SUMMARY_TEXT_XPATH) > 0)
            check("resume editor: the review page's Edit control is NOT here",
                  count(page, H.REVIEW_RESUME_EDIT_XPATH) == 0,
                  "it would be clicked instead of Continue applying")

        # --- the same page, two different actions -----------------------------
        print()
        print("--- edit on the first visit, submit on the second ---")
        rules = transitions_for("review the contents of this job application")
        check("the config has rules for the review page", bool(rules))
        check("arriving from Apply (hitApply) edits the resume",
              rules.get("hitApply", ("", ""))[0] == "hitEditFromReviewPage",
              f"hitApply -> {rules.get('hitApply')}")
        check("and lands in a state the resume-selection page handles",
              rules.get("hitApply", ("", ""))[1] == "didContactInfo",
              f"hitApply -> {rules.get('hitApply')}")

        selection = transitions_for("upload or")
        check("the resume-selection page picks that state up",
              selection.get("didContactInfo", ("", ""))[0] == "startResume",
              f"didContactInfo -> {selection.get('didContactInfo')}")

        check("coming back after the resume does NOT edit again",
              rules.get("finishedResume", ("", ""))[0] != "hitEditFromReviewPage",
              f"finishedResume -> {rules.get('finishedResume')} -- it would loop")
        # When the review page has no Edit control, hitEditFromReviewPage still
        # leaves us in didContactInfo -- but on THIS page, not the resume
        # selection page. Without a rule for it the run stalls on a page that is
        # merely offering nothing to edit.
        check("a review page with no edit step carries on rather than stalling",
              "didContactInfo" in rules,
              "no rule for didContactInfo on the review page")
        check("and the flow reaches submitApp",
              any(func == "submitApp" for func, _ in rules.values()),
              f"no state on the review page submits: {sorted(rules)}")

        # --- the supporting documents / cover letter step ---------------------
        print()
        print("--- 'Add supporting documents' on the review page ---")
        # The review page has footer links. The old code looked for the nearest
        # <a> to the words "Supporting documents"; there is no anchor in that
        # section, so it climbed until it found one -- the footer's Privacy
        # Policy -- and navigated out of the application.
        page.set_content(
            '<h3>Supporting documents</h3>'
            '<button type="button" aria-label="Add supporting documents"'
            ' onclick="document.title=\'add clicked\'">Add</button>'
            '<footer><a href="#privacy" onclick="document.title=\'LEFT THE APPLICATION\'">'
            'Privacy Policy</a></footer>')
        page.wait_for_timeout(100)
        check("the Add button is found by its label",
              count(page, H.ADD_DOCS_XPATH) == 1, f"matched {count(page, H.ADD_DOCS_XPATH)}")
        wrap.clickAddDocs()
        check("and it is the Add button that gets clicked, not a footer link",
              page.title() == "add clicked", f"page title is {page.title()!r}")

        # No documents section at all: skip quietly, do not wander off.
        page.set_content('<p>this application takes no documents</p>'
                         '<footer><a href="#terms" onclick="document.title=\'WANDERED OFF\'">'
                         'Terms of Service</a></footer>')
        page.wait_for_timeout(100)
        page.evaluate("document.title = 'still here'")
        skipped = wrap.clickAddDocs()
        check("a page with no documents section is skipped",
              skipped is None, "it clicked something")
        check("and nothing else was clicked in the process",
              page.title() == "still here", f"page title is {page.title()!r}")

        print()
        print("--- the cover letter page ---")
        if load("Add_Documents.html", page):
            check("the OLD selector is dead",
                  count(page, "//div[@data-testid='CoverLetterRadioCard']") == 0,
                  "it still matches, so it did not need replacing")
            check("the cover letter radio is found",
                  count(page, H.COVER_LETTER_INPUT_XPATH) > 0)
            check("the cover letter box is found",
                  count(page, H.COVER_LETTER_TEXT_XPATH) > 0)
            check("the Continue button is found",
                  count(page, H.DOCS_CONTINUE_XPATH) > 0)

            # The trap: "No cover letter" is what the page comes preselected on.
            no_cl = page.query_selector('[data-testid="no-cover-letter-radio-card-input"]')
            check("'No cover letter' really is preselected",
                  no_cl is not None and no_cl.is_checked(),
                  "if it were not, choosing explicitly would be unnecessary")
            check("Continue starts out disabled",
                  not page.query_selector(f"xpath={H.DOCS_CONTINUE_XPATH}").is_enabled(),
                  "clicking it immediately would work, so waiting is unnecessary")

            wrap.coverLetter = "Dear hiring manager, I would like to apply."
            wrap.do_cover_letter()

            check("the cover letter option ends up selected",
                  page.query_selector(f"xpath={H.COVER_LETTER_INPUT_XPATH}").is_checked(),
                  "the letter would be typed but never attached")
            check("and the letter is in the box",
                  page.input_value('[data-testid="cover-letter-radio-card-text-area"]')
                  == wrap.coverLetter,
                  "the box did not take the text")

        # --- the AI-tailored resume review ------------------------------------
        # A new step in the flow. Its controls use data-tn-element rather than
        # data-testid, so every existing Continue selector walks straight past
        # them and the run stopped on an unrecognised page.
        print()
        print("--- the tailored resume review ---")
        if load("review_taylorded_resume.html", page):
            check("the ordinary Continue selector does not see it",
                  count(page, H.CONTINUE_BUTTON_XPATH) == 0,
                  "then it would not have needed its own handling")
            check("its Continue button is found by data-tn-element",
                  count(page, H.TAILORED_CONTINUE_XPATH) == 1)
            check("the confirmation dialog is not open yet",
                  count(page, H.TAILORED_DIALOG_XPATH) == 0)

        # Clicking Continue raises a dialog whose OWN Continue starts disabled
        # until the review checkbox is ticked. Both buttons carry the same
        # data-tn-element, so the second click has to be scoped to the dialog.
        page.set_content("""
          <button data-tn-element="continue-btn" onclick="openDialog()">
            <span>Continue</span></button>
          <div id="slot"></div>
          <script>
            window.confirmed = false;
            function openDialog() {
              document.getElementById('slot').innerHTML =
                '<div data-tn-component="tailored-resume-ai-confirmation-dialog">'
              + '<label><input type="checkbox" data-tn-element="confirm-changes"'
              + ' onchange="document.getElementById(\\'go\\').disabled = !this.checked">'
              + 'I have reviewed all changes</label>'
              + '<button id="go" data-tn-element="continue-btn" disabled'
              + ' onclick="window.confirmed = true">Continue</button></div>';
            }
          </script>""")
        page.wait_for_timeout(150)
        raised = None
        try:
            wrap.confirmTailoredResume()
        except BaseException as exc:      # noqa: BLE001
            raised = exc
        check("it gets through the dialog without stopping", raised is None,
              f"raised {type(raised).__name__ if raised else ''}: {raised}")
        check("the review checkbox ends up ticked",
              page.is_checked('[data-tn-element="confirm-changes"]'),
              "the dialog's Continue stays disabled without it")
        check("and the DIALOG's Continue is what gets clicked",
              page.evaluate("() => window.confirmed") is True,
              "it pressed the page's button again instead")

        # Logs/Log25.txt: confirmTailoredResume was called correctly (routing
        # was fine) but looped for many minutes -- every single call gave up
        # with "no confirmation dialog, carrying on" even though the dialog
        # demonstrably opened each time, because it was on-screen just not
        # detected. The real DOM nests the tn-component wrapper inside a
        # separate role="dialog" element (seen in an earlier capture,
        # question_unanswered1.html) that was never accounted for, and
        # whatever made the WRAPPER register as not-visible did not
        # necessarily apply to elements inside it. Reproduced here literally:
        # the wrapper is visibility:hidden, its content overrides back to
        # visible, exactly the shape that made the old wrapper-visibility
        # check useless while the checkbox itself was genuinely on screen.
        page.set_content("""
          <button data-tn-element="continue-btn" onclick="openDialog()">
            <span>Continue</span></button>
          <div id="slot"></div>
          <script>
            window.confirmed2 = false;
            function openDialog() {
              document.getElementById('slot').innerHTML =
                '<div data-tn-component="tailored-resume-ai-confirmation-dialog" style="visibility:hidden">'
              + '<div style="visibility:visible">'
              + '<label><input type="checkbox" data-tn-element="confirm-changes"'
              + ' onchange="document.getElementById(\\'go2\\').disabled = !this.checked">'
              + 'I have reviewed all changes</label>'
              + '<button id="go2" data-tn-element="continue-btn" disabled'
              + ' onclick="window.confirmed2 = true">Continue</button>'
              + '</div></div>';
            }
          </script>""")
        page.wait_for_timeout(150)
        raised = None
        try:
            wrap.confirmTailoredResume()
        except BaseException as exc:      # noqa: BLE001
            raised = exc
        check("it still gets through when the wrapper itself is not detected as visible",
              raised is None, f"raised {type(raised).__name__ if raised else ''}: {raised}")
        check("the checkbox is what actually gets checked for, not the wrapper",
              page.evaluate("() => window.confirmed2") is True,
              "gave up thinking there was no dialog, exactly like the log")

        # No dialog at all is normal: Indeed only asks when AI changed something.
        page.set_content("""
          <div id="out">not clicked</div>
          <button data-tn-element="continue-btn"
                  onclick="document.getElementById('out').textContent='clicked'">
            <span>Continue</span></button>""")
        page.wait_for_timeout(120)
        wrap.confirmTailoredResume()
        check("with no dialog it just continues",
              page.text_content("#out") == "clicked")

        # A checkbox that will not tick must stop rather than press a disabled
        # button forever.
        page.set_content("""
          <button data-tn-element="continue-btn" onclick="openDialog()">Continue</button>
          <div id="slot"></div>
          <script>
            function openDialog() {
              document.getElementById('slot').innerHTML =
                '<div data-tn-component="tailored-resume-ai-confirmation-dialog">'
              + '<input type="checkbox" data-tn-element="confirm-changes">'
              + '<button data-tn-element="continue-btn" disabled>Continue</button></div>';
              document.querySelector('[data-tn-element="confirm-changes"]')
                .addEventListener('click', function (e) { e.preventDefault(); });
            }
          </script>""")
        page.wait_for_timeout(150)
        raised = None
        try:
            wrap.confirmTailoredResume()
        except BaseException as exc:      # noqa: BLE001
            raised = exc
        check("a box that will not tick calls for a person",
              isinstance(raised, main3.NeedsHumanError),
              f"raised {type(raised).__name__ if raised else 'nothing'}")

        # --- a captcha on submit ----------------------------------------------
        print()
        print("--- a captcha on the submit step ---")
        page.set_content('<div id="captcha-wrapper">prove you are human</div>'
                         '<button><span>Submit your application</span></button>')
        page.wait_for_timeout(100)
        raised = None
        try:
            wrap.submitApp()
        except BaseException as exc:      # noqa: BLE001 -- the type is the point
            raised = exc
        check("a captcha stops the submit and calls for a person",
              isinstance(raised, main3.NeedsHumanError),
              f"raised {type(raised).__name__ if raised else 'nothing'} -- it submitted anyway")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL REVIEW FLOW TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
