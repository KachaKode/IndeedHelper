"""Logs/Log52.txt / HTMLz/work_stuck_again.html: an "Add" click that WORKED was
scored as a failure, and the job it had opened the form for was abandoned.

Three of the user's four jobs were added cleanly. On the fourth, the click on
"Add work experience" landed -- Playwright's own log says so:

    - performing click action
    - click action done
    - waiting for scheduled navigations to finish
    TimeoutError: ElementHandle.click: Timeout 5000ms exceeded

The click is not what timed out. The wait for the navigation the click
scheduled is. But findAndClick returned None either way, do_work_exp read that
as "could not find the 'Add work experience' button" and returned, leaving the
fourth job unwritten and its form sitting open and empty.

From there nothing could recover: the open form hides the entry list, so the
next pass read zero entries (the list is filtered to visible elements), could
not match the section against the jobs, could not delete, and could not reach
"Add work experience" either -- it is behind the form.

Two fixes, verified here:
1. An "Add" click that reports failure is only a failure if the form did NOT
   open. If it is open, the click landed -- fill it in.
2. The entry form pages offer no Close/Back/Cancel at all -- the old
   FORM_DISMISS_XPATH matched one hidden element and nothing else, so
   _leaveEntryForm could never dismiss one. Their real, visible way out is the
   modal back button, the same control do_skills already backs out with, and
   it is present on every capture of this going wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

main3.t.sleep = lambda *_a, **_k: None

CAPTURES = ROOT / "HTMLz"
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def build_helper(page, jobs):
    wrap = main3.IndeedHelper.__new__(main3.IndeedHelper)
    main3.PlaywrightWrap.__init__(wrap, "", "", "user-data-dir=")
    wrap._page = page
    wrap._context = page.context
    wrap.outputFile = None
    wrap.jobs = jobs
    wrap.sectionAlreadyCorrect = lambda *a, **k: False
    wrap.deleteExistingEntries = lambda *a, **k: 0
    return wrap


def job_dict(title):
    return {"JobTitle": title, "CompanyName": "Acme Corp", "CompanyType": "",
            "areaSpec": "Atlanta, GA", "currentPosition": "No", "From": "December 2015",
            "To": "August 2019", "country": "United States", "Description": ""}


# The Add button is present but its click never resolves the way findAndClick
# wants (the handler opens the form, then the page keeps a navigation pending),
# which is the shape Log52 line 772 recorded.
ADD_CLICK_TIMES_OUT_PAGE = """
  <div id="list">
    <button aria-label="Add work experience" onclick="openForm()">Add work experience</button>
  </div>
  <div id="form" style="display:none">
    <input data-testid="job-title-input-autocomplete-input" required>
    <input data-testid="company-input-autocomplete-input">
    <input data-testid="location-input-autocomplete-input">
    <div role="checkbox" aria-checked="false" data-testid="is-current-toggle"
         aria-label="I currently work here"></div>
    <div role="textbox" aria-label="Description" contenteditable="true"></div>
    <button aria-label="Save this work experience"
            onclick="window.__saved = (window.__saved || 0) + 1;
                     window.__savedTitle =
                       document.querySelector('[data-testid^=job-title]').value;
                     closeForm();">Save</button>
  </div>
  <script>
    function openForm() {
      document.getElementById('list').style.display = 'none';
      document.getElementById('form').style.display = 'block';
    }
    function closeForm() {
      document.getElementById('form').style.display = 'none';
      document.getElementById('list').style.display = 'block';
    }
  </script>"""


def main() -> int:
    H = main3.IndeedHelper
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()

        print("--- the real stuck page has nothing the old dismiss selector could click ---")
        capture = CAPTURES / "work_stuck_again.html"
        if capture.exists():
            page.goto(capture.as_uri())
            page.wait_for_timeout(300)
            wrap = build_helper(page, [])
            oldSelector = ("//*[@aria-label='Close'] | //*[@aria-label='Back']"
                           " | //button[normalize-space(.)='Cancel']")
            oldMatches = wrap._visible_only(wrap.driver.find_elements('xpath', oldSelector))
            newMatches = wrap._visible_only(
                wrap.driver.find_elements('xpath', H.FORM_DISMISS_XPATH))
            check("the old dismiss selector finds nothing CLICKABLE on this page",
                  len(oldMatches) == 0,
                  f"{len(oldMatches)} matched -- the form would have been dismissable")
            check("the new one finds the form's modal back button, and it is visible",
                  len(newMatches) == 1, f"{len(newMatches)} visible matches")
            check("and the form really is open on this capture",
                  wrap._formStillOpen(H.WORK_TITLE_TESTID))
            check("while the entry list behind it is hidden, which is why nothing could "
                  "read the section",
                  len(wrap._liveEntries(H.WORK_ENTRY_XPATH)) == 0,
                  "the list should be invisible behind the open form")
        else:
            check("capture present", False, f"{capture} missing")

        print()
        print("--- an Add click that lands but reports a timeout still fills the job ---")
        page.set_content(ADD_CLICK_TIMES_OUT_PAGE)
        page.evaluate("() => { window.__saved = 0; window.__savedTitle = null; }")
        page.wait_for_timeout(150)
        wrap2 = build_helper(page, [job_dict("Fourth Job")])
        # Force the exact failure: the click happens, then findAndClick reports None.
        realFindAndClick = wrap2.findAndClick

        def flakyAdd(*args, **kwargs):
            # The real click happens and the form opens; only the report of it
            # is lost, which is exactly what a navigation-wait timeout does.
            result = realFindAndClick(*args, **kwargs)
            if args and args[2] == H.ADD_WORK_XPATH:
                return None
            return result

        wrap2.findAndClick = flakyAdd
        raised = None
        try:
            wrap2.do_work_exp()
        except BaseException as exc:            # noqa: BLE001
            raised = exc
        check("do_work_exp does not bail out when the form is open",
              raised is None, f"raised {raised!r}")
        check("the job was actually filled in and saved",
              page.evaluate("() => window.__savedTitle") == "Fourth Job",
              f"saved title was {page.evaluate('() => window.__savedTitle')!r}")

        print()
        print("--- a genuinely missing Add button is still reported as missing ---")
        page.set_content("<div>nothing here</div>")
        page.wait_for_timeout(100)
        wrap3 = build_helper(page, [job_dict("Nope")])
        result = wrap3.do_work_exp()
        check("it returns None rather than pretending a form is open",
              result is None)

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL ADD-CLICK FALSE NEGATIVE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
