"""Logs/Log50.txt / HTMLz/work_stuck.html: a required field that shows up LATE
must be waited out, not treated as the end of the road.

The first attempt at fixing the "saved with a required field blank" bug raised
as soon as fillByTestId() missed the job title field. That detected the problem,
but it aborted handleJob() at its FIRST line -- so company, location, both date
pairs and the description were never filled either, and the person called in to
help found a completely empty form to type out by hand
(HTMLz/work_stuck.html: every field value="").

And the miss itself was usually recoverable. These forms render a moment after
"Add work experience" is clicked, sometimes slower than the 8s fillByTestId
waits (Log50 line 1827 burned 30s of wall time inside a single wait while the
page was mid-save) -- but the capture taken at the point it gave up shows the
job title field present, visible and empty. It had simply arrived late.

So the check moved to just BEFORE Save: fill everything, then look again at the
text fields, re-fill whatever is still empty (by which point a late field is
there), and only stop for a person if a required one still will not take --
without clicking Save, so Indeed is never asked to save an entry it will reject.
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


def job_dict():
    return {"JobTitle": "AI Consultant", "CompanyName": "Acme Corp", "CompanyType": "",
            "areaSpec": "Atlanta, GA", "currentPosition": "No", "From": "October 2017",
            "To": "May 2020", "country": "United States", "Description": ""}


COMMON_FORM = """
  <input data-testid="company-input-autocomplete-input">
  <input data-testid="location-input-autocomplete-input">
  <div role="checkbox" aria-checked="false" data-testid="is-current-toggle"
       aria-label="I currently work here"></div>
  <div role="textbox" aria-label="Description" contenteditable="true"></div>
  <button aria-label="Save this work experience"
          onclick="window.__saveClicked = true;
                   const t = document.querySelector('[data-testid^=job-title]');
                   window.__titleAtSave = t ? t.value : null;
                   document.querySelectorAll('[data-testid^=job-title]')
                           .forEach(e => e.remove());">Save</button>"""

# The Log50 shape: the job title field is not in the DOM when handleJob starts
# and only appears a few seconds in, exactly as the real form does when it is
# still rendering.
LATE_JOB_TITLE_PAGE = f"""
  <div id="late"></div>
  {COMMON_FORM}
  <script>
    setTimeout(() => {{
      const i = document.createElement('input');
      i.setAttribute('data-testid', 'job-title-input-autocomplete-input');
      i.setAttribute('required', '');
      document.getElementById('late').appendChild(i);
    }}, 3000);
  </script>"""

# A job title field that is there but will never accept text -- the case that
# genuinely does need a person.
REFUSING_JOB_TITLE_PAGE = f"""
  <input data-testid="job-title-input-autocomplete-input" required oninput="this.value=''">
  {COMMON_FORM}"""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        located = build_helper(page)

        print("--- a job title field that arrives late is filled, not given up on ---")
        page.set_content(LATE_JOB_TITLE_PAGE)
        # set_content keeps the same window, so these must be cleared per case.
        page.evaluate("() => { window.__saveClicked = false; window.__titleAtSave = null; }")
        raised = None
        try:
            located.handleJob(job_dict())
        except main3.NeedsHumanError as exc:
            raised = str(exc)
        except Exception as exc:                 # noqa: BLE001
            raised = f"other: {exc!r}"
        check("handleJob does not stop for a person over a field that was merely late",
              raised is None, f"raised={raised!r}")
        titleAtSave = page.evaluate("() => window.__titleAtSave")
        check("the late job title was actually filled in by the time Save was clicked",
              titleAtSave == "AI Consultant", f"the field held {titleAtSave!r} at Save")
        check("and Save was clicked, so the entry was actually submitted",
              page.evaluate("() => !!window.__saveClicked"))

        print()
        print("--- a field that truly will not take stops the run BEFORE Save ---")
        located2 = build_helper(page)
        page.set_content(REFUSING_JOB_TITLE_PAGE)
        page.evaluate("() => { window.__saveClicked = false; window.__titleAtSave = null; }")
        page.wait_for_timeout(150)
        raised2 = None
        try:
            located2.handleJob(job_dict())
        except main3.NeedsHumanError as exc:
            raised2 = str(exc)
        except Exception as exc:                 # noqa: BLE001
            raised2 = f"other: {exc!r}"
        check("it raises NeedsHumanError", isinstance(raised2, str)
              and "job title" in raised2, f"raised={raised2!r}")
        check("Save was NEVER clicked, so Indeed was not asked to save a doomed entry",
              not page.evaluate("() => !!window.__saveClicked"),
              "clicking Save on an invalid form is what left it open blocking the next entry")
        check("the message tells the person the rest of the form is already filled",
              isinstance(raised2, str) and "rest of the form is filled" in raised2,
              f"message was {raised2!r}")
        check("and the rest of the form really IS filled, so they type one field",
              page.evaluate("""() => {
                  const c = document.querySelector('[data-testid^=company]');
                  const l = document.querySelector('[data-testid^=location]');
                  return (c && c.value) + '|' + (l && l.value);
              }""") == "Acme Corp|Atlanta, GA",
              "aborting early is what left the person a blank form to retype")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL LATE FIELD REPAIR TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
