"""do_cover_letter()'s own Continue-button check raises NeedsHumanError when
the page will not let the application proceed (main3.py: "its Continue
button is still disabled, which means the page wants something it has not
been given"). On a review page that was never actually going to offer a
working "add a cover letter" step in the first place, that button can never
enable -- and since attentionWaived mutes the alert after the very first
pause, every later retry raised the same error quietly, forever, once every
~5 seconds, and the application never reached submitApp() at all.

Fixed with a small shared attempt counter (_addDocsAttemptsExhausted),
checked at the top of both clickAddDocs() and do_cover_letter(): after
ADD_DOCS_ATTEMPT_LIMIT (5) combined attempts, both give up and return None
instead of trying again, letting the state machine's "advance unless
intercepted" rule carry the run on to submitApp() -- the application still
gets submitted, just without a cover letter, exactly as asked ("if we can't
find it then we can't find it... just submit the application and move on").
generateCL() resets the counter, so a fresh application always gets its own
full budget regardless of what a previous job used up.
"""

from __future__ import annotations

import sys
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


def build_helper(page):
    located = main3.IndeedHelper.__new__(main3.IndeedHelper)
    main3.PlaywrightWrap.__init__(located, "", "", "user-data-dir=")
    located._page = page
    located._context = page.context
    located.outputFile = None
    return located


# A cover-letter step that can never actually complete: the radio and text
# box work fine, but Continue stays disabled forever -- wrapped in a
# disabled <fieldset> rather than carrying the attribute itself, so
# smartClick's own naive target.get_attribute("disabled") pre-check (which
# only looks at the element itself) still finds and returns it, and it is
# Playwright's real is_enabled() -- which DOES account for a disabled
# fieldset ancestor -- that correctly keeps seeing it as not usable. This is
# the same "Continue starts disabled until a choice is made" shape the real
# do_cover_letter() comment describes.
NEVER_ENABLES_PAGE = """
  <input type="radio" data-testid="cover-letter-radio-card-input" name="cover-letter">
  <textarea data-testid="cover-letter-radio-card-text-area"></textarea>
  <fieldset disabled><button data-testid="continue-button">Continue</button></fieldset>"""


def main() -> int:
    print("--- _addDocsAttemptsExhausted: pure counting logic ---")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        located = build_helper(page)

        results = [located._addDocsAttemptsExhausted("test") for _ in range(8)]
        check("the first 5 attempts are NOT exhausted",
              results[:5] == [False] * 5, f"got {results[:5]!r}")
        check("the 6th and later attempts ARE exhausted",
              results[5:] == [True, True, True], f"got {results[5:]!r}")
        check("the counter actually reached the configured limit",
              located._addDocsAttempts == 8
              and main3.IndeedHelper.ADD_DOCS_ATTEMPT_LIMIT == 5)

        print()
        print("--- clickAddDocs() short-circuits once exhausted, without searching ---")
        located2 = build_helper(page)
        located2._addDocsAttempts = main3.IndeedHelper.ADD_DOCS_ATTEMPT_LIMIT
        page.set_content("<button aria-label='Add supporting documents'>Add</button>")
        page.wait_for_timeout(150)
        result = located2.clickAddDocs()
        check("returns None instead of searching for the button",
              result is None, f"got {result!r}")

        print()
        print("--- do_cover_letter() short-circuits once exhausted, without trying ---")
        located3 = build_helper(page)
        located3._addDocsAttempts = main3.IndeedHelper.ADD_DOCS_ATTEMPT_LIMIT
        located3.coverLetter = "A test cover letter."
        page.set_content(NEVER_ENABLES_PAGE)
        page.wait_for_timeout(150)
        raised = None
        try:
            result3 = located3.do_cover_letter()
        except main3.NeedsHumanError:
            raised = True
        check("returns None instead of raising NeedsHumanError yet again",
              raised is None and result3 is None,
              f"raised={raised!r} result={result3!r}")

        print()
        print("--- end to end: a Continue button that never enables eventually "
              "stops raising and lets the run move on ---")
        located4 = build_helper(page)
        located4.coverLetter = "A test cover letter."
        outcomes = []
        for attempt in range(1, 8):
            page.set_content(NEVER_ENABLES_PAGE)
            page.wait_for_timeout(100)
            try:
                outcomes.append(("raised", located4.do_cover_letter()))
            except main3.NeedsHumanError:
                outcomes.append(("raised_error", None))
        raised_count = sum(1 for kind, _ in outcomes if kind == "raised_error")
        gave_up_count = sum(1 for kind, val in outcomes if kind == "raised" and val is None)
        check("it raised NeedsHumanError (a real, alertable stuck state) on the "
              "first several attempts, not silently from the start",
              raised_count >= 1, f"outcomes={outcomes!r}")
        check("but it gave up (returned None) rather than raising forever",
              gave_up_count >= 1, f"outcomes={outcomes!r}")
        check("and the LAST attempt in this run of 7 gave up rather than raised, "
              "proving the loop actually terminates",
              outcomes[-1] == ("raised", None), f"last outcome={outcomes[-1]!r}")

        print()
        print("--- generateCL() resets the budget for a fresh application ---")

        class FixedCLReply:
            def __init__(self, *_args, **_kwargs):
                pass

            def sendAll(self):
                return "A generated cover letter."
            need_redo = False

        located5 = build_helper(page)
        located5._addDocsAttempts = main3.IndeedHelper.ADD_DOCS_ATTEMPT_LIMIT + 3
        located5.jobTitle = "Engineer"
        located5.companyName = "Acme"
        located5.JobDescriptionText = "Do engineering things."
        located5.firstName = "Test"
        located5.lastName = "User"
        located5.lifeSummary = "A summary."
        located5.phone_num = "555-555-5555"
        located5.email = "test@example.com"
        located5.areaSpec = "Remote"
        located5.writingSample = ""

        original_myGPT2 = main3.myGPT2
        main3.myGPT2 = FixedCLReply
        try:
            located5.generateCL()
        finally:
            main3.myGPT2 = original_myGPT2
        check("a fresh application resets the attempt count back to 0",
              located5._addDocsAttempts == 0, f"got {located5._addDocsAttempts!r}")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL COVER LETTER ATTEMPT LIMIT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
