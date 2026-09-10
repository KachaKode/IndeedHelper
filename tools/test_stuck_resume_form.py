"""The bot got permanently stuck on "Add work experience" (Logs/Log30.txt,
HTMLz/add_education_stuck.html -- despite its name, that capture is a WORK
EXPERIENCE form: Company/Job title/Location/"I currently work here"/"Save
this work experience"). The chain:

1. handleJob() clicked the "I currently work here" toggle, but the click was
   intercepted (ElementClickInterceptedException) and gave up. setToggle()
   never looked at smartClick's return value, so it reported success anyway.
2. handleJob() then called setDateRange(..., isCurrent=current) using the
   ORIGINAL requested value, not what actually landed on the page. Believing
   the job was current, it skipped the "To" date entirely.
3. Indeed's form still had the toggle OFF, so it still required a "To" date,
   and silently refused to save without one -- but the Save click's
   checkNewPage wait, if it timed out, was never actually checked either;
   findAndClick returned the clicked element regardless.
4. do_work_exp()'s loop only checks handleJob()'s return for
   ElementClickInterceptedException, so it moved on to the NEXT job and
   tried to click "Add work experience" again -- hidden behind the still-open,
   unsaved form from step 3, forever. Every later call to doWorkExp() hit the
   exact same wall, immediately, invisibly.

Fixed by making setToggle() return the toggle's ACTUAL resulting state (used
for setDateRange's isCurrent instead of the request), and by having
handleJob()/handleEdu() verify the form actually closed after Save, raising
NeedsHumanError instead of silently accepting a click that did not work.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

CAPTURES = ROOT / "HTMLz"

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


# A toggle covered by a full-page overlay: clicking it always intercepts,
# the same obstacle Playwright reported in Logs/Log30.txt.
INTERCEPTED_TOGGLE_PAGE = """
  <div role="checkbox" aria-checked="false" data-testid="is-current-toggle"
       aria-label="I currently work here"
       onclick="this.setAttribute('aria-checked','true')">toggle</div>
  <div style="position:fixed; inset:0; z-index:999;"></div>"""

WORKING_TOGGLE_PAGE = """
  <div role="checkbox" aria-checked="false" data-testid="is-current-toggle"
       aria-label="I currently work here"
       onclick="this.setAttribute('aria-checked','true')">toggle</div>"""


def job_dict(current):
    return {"JobTitle": "Widget Engineer", "CompanyName": "Acme Corp", "CompanyType": "",
            "areaSpec": "Atlanta, GA", "currentPosition": current, "From": "August 2023",
            "To": "May 2025", "country": "United States", "Description": ""}


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        located = build_helper(page)

        print("--- setToggle reports what actually happened, not what was asked for ---")
        page.set_content(INTERCEPTED_TOGGLE_PAGE)
        page.wait_for_timeout(150)
        result = located.setToggle('//*[@data-testid="is-current-toggle"]',
                                   True, "I currently work here")
        check("an intercepted click is reported as NOT on, even though 'on' was requested",
              result is False, f"got {result!r}")
        check("and the page itself genuinely was not changed",
              page.get_attribute('[data-testid="is-current-toggle"]', "aria-checked") == "false")

        page.set_content(WORKING_TOGGLE_PAGE)
        page.wait_for_timeout(150)
        result2 = located.setToggle('//*[@data-testid="is-current-toggle"]',
                                    True, "I currently work here")
        check("a click that genuinely lands is reported as True",
              result2 is True, f"got {result2!r}")

        print()
        print("--- the real stuck capture is recognised as still open ---")
        page.goto((CAPTURES / "add_education_stuck.html").as_uri())
        page.wait_for_timeout(300)
        check("_formStillOpen sees the work-experience form that never actually saved",
              located._formStillOpen(located.WORK_TITLE_TESTID),
              "this exact capture is the stuck state from Logs/Log30.txt")
        check("and its toggle really is off, matching an intercepted click "
              "rather than a job that was genuinely marked current",
              page.get_attribute('[data-testid="is-current-toggle"]', "aria-checked") == "false")

        print()
        print("--- handleJob: Save that does not close the form stops for a person ---")
        page.set_content("""
          <input data-testid="job-title-input-autocomplete-input">
          <input data-testid="company-input-autocomplete-input">
          <input data-testid="location-input-autocomplete-input">
          <div role="checkbox" aria-checked="false" data-testid="is-current-toggle"
               aria-label="I currently work here"></div>
          <div role="textbox" aria-label="Description" contenteditable="true"></div>
          <button aria-label="Save this work experience">Save</button>""")
        page.wait_for_timeout(150)
        raised = None
        try:
            located.handleJob(job_dict("No"))
        except main3.NeedsHumanError:
            raised = True
        except Exception:                 # noqa: BLE001
            raised = False
        check("a Save click that does not remove the form raises NeedsHumanError "
              "instead of silently moving on to the next job",
              raised is True, f"raised={raised!r}")

        print()
        print("--- handleJob: a Save that genuinely works does not raise ---")
        page.set_content("""
          <input data-testid="job-title-input-autocomplete-input">
          <input data-testid="company-input-autocomplete-input">
          <input data-testid="location-input-autocomplete-input">
          <div role="checkbox" aria-checked="false" data-testid="is-current-toggle"
               aria-label="I currently work here"></div>
          <div role="textbox" aria-label="Description" contenteditable="true"></div>
          <button aria-label="Save this work experience"
                  onclick="document.querySelector('[data-testid^=job-title]').remove()">
            Save
          </button>""")
        page.wait_for_timeout(150)
        raised2 = None
        try:
            located.handleJob(job_dict("No"))
        except main3.NeedsHumanError as exc:
            raised2 = True
            detail = str(exc)
        except Exception:                 # noqa: BLE001
            raised2 = "other"
        check("a Save that actually closes the form is NOT treated as stuck",
              raised2 is None, f"raised={raised2!r}")

        print()
        print("--- handleEdu gets the same protection ---")
        page.set_content("""
          <input data-testid="level-of-education-input-autocomplete-input">
          <input data-testid="field-of-study-input-autocomplete-input">
          <input data-testid="school-input-autocomplete-input">
          <input data-testid="education-location-input-autocomplete-input">
          <div role="checkbox" aria-checked="false" data-testid="is-current-toggle"
               aria-label="currently enrolled"></div>
          <button aria-label="Save this education">Save</button>""")
        page.wait_for_timeout(150)
        edu = {"eduLvl": "Bachelor's", "fieldOS": "CS", "schoolName": "Some University",
               "areaSpec": "Atlanta, GA", "currentPosition": "No", "From": "August 2019",
               "To": "May 2023", "country": "United States"}
        raisedEdu = None
        try:
            located.handleEdu(edu)
        except main3.NeedsHumanError:
            raisedEdu = True
        except Exception:                 # noqa: BLE001
            raisedEdu = False
        check("handleEdu also stops for a person when the education form does not close",
              raisedEdu is True, f"raised={raisedEdu!r}")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL STUCK RESUME FORM TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
