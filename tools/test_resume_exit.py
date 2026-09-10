"""Getting OUT of the resume editor, and not rebuilding it five times over.

A run spent its whole life on https://profile.indeed.com/resume, redoing the
entire resume again and again:

    finishedEditSkills -- finishResume()            --> finishedResume
    finishedResume     -- startAtTopOfReviewPage()  --> startedOnResume   <-- loop
    startedOnResume    -- startContactInfo()        --> ...whole resume again

It left twenty "X removed" banners behind, four passes of deleting and
re-adding the same four jobs.

The cause is visible in the two captures, which are otherwise identical -- same
jobs, same skills, same empty summary:

    Edit_Resume_Stuck.html    footer = "Delete resume",     no Continue applying
    Edit_resume_unstuck.html  footer = "Continue applying", no Delete resume

"Continue applying" exists only while the editor holds the application it came
from, as /resume?...&continue=<application url>. Saving a work experience
navigates inside the editor and Indeed drops that query string; from then on
the page is the standalone profile editor and there is no way onward.
"""

from __future__ import annotations

import sys
import tempfile
import urllib.parse
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


def load(page, name: str) -> bool:
    path = CAPTURES / name
    if not path.exists():
        print(f"       (skipped: HTMLz/{name} is missing)")
        return False
    page.goto(path.as_uri())
    page.wait_for_timeout(300)
    return True


def resume_page_rules():
    """The configured transitions for the main resume page."""
    text = (ROOT / "config" / "StateTransitions.txt").read_text(encoding="utf-8")
    rules, inside, pending = {}, False, []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        if "|" in s and "--" not in s:
            inside = "resume((([/?].*)?))" in s
            pending = []
            continue
        if not inside:
            continue
        if "--" in s:
            state, func, nxt = s.split("--")
            for st in pending + [state.strip()]:
                rules[st] = (func.strip("() "), nxt.strip("-> "))
            pending = []
        else:
            pending.append(s)
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

        print("--- the two captures differ in exactly one button ---")
        if load(page, "Edit_Resume_Stuck.html"):
            check("stuck page has no 'Continue applying'",
                  count(page, H.FINISH_RESUME_XPATH) == 0)
            check("stuck page offers 'Delete resume' instead",
                  count(page, H.DELETE_RESUME_XPATH) == 1,
                  "so it is not the application's editor at all")
            check("stuck page still has a back arrow",
                  count(page, H.RESUME_GO_BACK_XPATH) == 1,
                  "there would be no way out of it")
            check("the summary is empty, with no Edit button",
                  count(page, H.SUMMARY_EDIT_XPATH) == 0)
            check("but the empty-state button IS there",
                  count(page, H.SUMMARY_EMPTY_STATE_XPATH) == 1,
                  "this is the only way into a blank summary")

        if load(page, "Edit_resume_unstuck.html"):
            check("unstuck page has 'Continue applying'",
                  count(page, H.FINISH_RESUME_XPATH) == 1)
            check("unstuck page has no 'Delete resume'",
                  count(page, H.DELETE_RESUME_XPATH) == 0)
            check("its summary is ALSO empty",
                  count(page, H.SUMMARY_EMPTY_STATE_XPATH) == 1,
                  "if it were filled, the missing summary would explain the stuck page")

        print()
        print("--- the way back is taken from the editor's own URL ---")
        # /resume?...&continue=<application url>. Indeed drops that query string
        # the moment anything inside the editor navigates, so it has to be
        # captured while it is still there.
        wrap.applicationReturnUrl = ""
        app_url = ("https://smartapply.indeed.com/beta/indeedapply/form"
                   "?from=profile-resume-edit")
        page.goto("data:text/html,<title>Edit your resume</title>")
        page.wait_for_timeout(100)
        # Drive it through a real URL carrying the parameter.
        tmp = Path(tempfile.mkdtemp())
        (tmp / "resume.html").write_text(
            "<title>Edit your resume</title><p>editor</p>", encoding="utf-8")
        page.goto((tmp / "resume.html").as_uri() + "?co=US&hl=en_US&continue="
                  + urllib.parse.quote(app_url, safe=""))
        page.wait_for_timeout(150)
        wrap.rememberApplicationUrl()
        check("the application address is decoded out of the URL",
              wrap.applicationReturnUrl == app_url,
              f"got {wrap.applicationReturnUrl!r}")

        # Once the parameter is gone, what was captured must survive.
        page.goto((tmp / "resume.html").as_uri())
        page.wait_for_timeout(120)
        wrap.rememberApplicationUrl()
        check("and it survives the parameter being dropped",
              wrap.applicationReturnUrl == app_url,
              f"got {wrap.applicationReturnUrl!r}")

        print()
        print("--- the profile page is recognised as outside the application ---")
        if load(page, "profile_resume_indeed.html"):
            check("the capture has no 'Continue applying'",
                  count(page, H.FINISH_RESUME_XPATH) == 0)
            check("and no resume section controls",
                  count(page, H.SKILL_ENTRY_XPATH) == 0
                  and count(page, "//*[@aria-label='Add work experience']") == 0,
                  "it is not the resume editor at all")

        print()
        print("--- finishResume prefers the remembered address over Go back ---")
        landed = tmp / "application.html"
        landed.write_text("<title>the application</title><p>back in the flow</p>",
                          encoding="utf-8")
        wrap.applicationReturnUrl = landed.as_uri()
        page.set_content("""
          <title>Edit your resume</title>
          <button aria-label="Go back" onclick="document.title='WRONG - used Go back'">back</button>
          <button data-testid="delete-resume-button">Delete resume</button>""")
        page.wait_for_timeout(120)
        wrap.finishResume()
        page.wait_for_timeout(200)
        check("it navigates straight to the application",
              "application.html" in page.url,
              f"ended on {page.url[-60:]!r} -- Go back leads to the profile page")

        wrap.applicationReturnUrl = ""

        print()
        print("--- finishResume falls back to Go back ---")
        page.set_content("""
          <button aria-label="Go back"
                  onclick="document.title='went back'; location.hash='selection';">‹</button>
          <button data-testid="delete-resume-button">Delete resume</button>""")
        page.wait_for_timeout(100)
        raised, result = None, None
        try:
            result = wrap.finishResume()
        except BaseException as exc:      # noqa: BLE001
            raised = exc
        check("no Continue applying: it goes back instead of giving up",
              page.title() == "went back",
              f"raised={raised!r}; the run would redo the whole resume")
        check("and it does not raise when the way out worked", raised is None, f"{raised}")

        # When Continue applying IS there, that is what gets clicked.
        page.set_content("""
          <button aria-label="Go back" onclick="document.title='WRONG - went back'">‹</button>
          <button data-testid="indeed-resume-detail-continue-to-application"
                  onclick="document.title='continued'">Continue applying</button>""")
        page.wait_for_timeout(100)
        wrap.finishResume()
        check("Continue applying is preferred when present",
              page.title() == "continued", f"title is {page.title()!r}")

        # Neither works: stop and ask for a person, do not spin.
        page.set_content("<p>a resume editor with no way out</p>")
        page.wait_for_timeout(100)
        raised = None
        try:
            wrap.finishResume()
        except BaseException as exc:      # noqa: BLE001
            raised = exc
        check("no way out at all: it stops and asks for a person",
              isinstance(raised, main3.NeedsHumanError),
              f"raised {type(raised).__name__ if raised else 'nothing'}")

        print()
        print("--- the config cannot restart the resume ---")
        rules = resume_page_rules()
        check("the resume page has a rule for finishedResume", "finishedResume" in rules,
              f"states: {sorted(rules)}")
        check("and it retries the exit rather than starting over",
              rules.get("finishedResume", ("", ""))[0] == "finishResume",
              f"finishedResume -> {rules.get('finishedResume')} -- this is the loop")
        check("the default still exists for genuinely unknown states",
              "default" in rules)

        print()
        print("--- a section that is already correct is left alone ---")
        page.set_content("""
          <button aria-label="Edit AI Consultant work experience">
            AI Consultant Kacha Inc · Atlanta, GA August 2023 to Present
            Advised clients on technical solutions.
          </button>
          <button aria-label="Edit Software Developer work experience">
            Software Developer 21st Century Realty · Austell, GA October 2017 to May 2020
            Led and managed complex projects.
          </button>""")
        page.wait_for_timeout(150)

        # Values in the positional order handleJob unpacks them.
        def job(title, comp, city, frm, to, desc, current="No"):
            return {"JobTitle": title, "CompanyName": comp, "CompanyType": "",
                    "areaSpec": city, "currentPosition": current, "From": frm,
                    "To": to, "country": "United States", "Description": desc}

        same = [
            job("AI Consultant", "Kacha Inc", "Atlanta, GA", "August 2023", "",
                "- Advised clients on technical solutions.", current="Yes"),
            job("Software Developer", "21st Century Realty", "Austell, GA",
                "October 2017", "May 2020", "- Led and managed complex projects."),
        ]
        check("an identical section is recognised",
              wrap.sectionAlreadyCorrect(H.WORK_ENTRY_XPATH,
                                         [H._jobSignature(j) for j in same],
                                         "work experience"),
              "it would delete and retype entries that are already right")

        # A tailored description differs per posting; that must still rewrite.
        retailored = [
            job("AI Consultant", "Kacha Inc", "Atlanta, GA", "August 2023", "",
                "- Something written specifically for this posting.", current="Yes"),
            job("Software Developer", "21st Century Realty", "Austell, GA",
                "October 2017", "May 2020", "- Led and managed complex projects."),
        ]
        check("a differently worded description is NOT treated as correct",
              not wrap.sectionAlreadyCorrect(H.WORK_ENTRY_XPATH,
                                             [H._jobSignature(j) for j in retailored],
                                             "work experience"),
              "the resume would keep the previous posting's wording")

        check("a different number of entries is not treated as correct",
              not wrap.sectionAlreadyCorrect(H.WORK_ENTRY_XPATH,
                                             [H._jobSignature(same[0])],
                                             "work experience"))
        check("an empty wish list never counts as correct",
              not wrap.sectionAlreadyCorrect(H.WORK_ENTRY_XPATH, [], "work experience"))

        print()
        print("--- a handle that goes stale under a re-render ---")
        # The real crash: after the third deletion the section re-rendered, the
        # next handle was taken from the outgoing tree, and generate_full_xpath
        # walked up a DETACHED subtree until it ran out of ancestors:
        #     parent_xpath = self.generate_full_xpath(
        #         element.find_elements('xpath', "./..")[0])
        #     IndexError: list index out of range
        # That escaped to RunUser, which closes Chrome and restarts the run.
        page.set_content("<div id='host'><button id='doomed'>click me</button></div>")
        page.wait_for_timeout(100)
        doomed = wrap._resolve_matches("//button[@id='doomed']", None)[0]
        check("the element starts out attached", wrap._isAttached(doomed))

        # Detach it exactly the way a React re-render would.
        page.evaluate("() => document.getElementById('host').replaceChildren()")
        page.wait_for_timeout(100)
        check("and is seen as detached once it is replaced", not wrap._isAttached(doomed))

        raised = None
        try:
            wrap.generate_full_xpath(doomed)
        except BaseException as exc:      # noqa: BLE001 -- the type is the point
            raised = exc
        check("building an xpath for it raises StaleElementError, not IndexError",
              isinstance(raised, main3.StaleElementError),
              f"raised {type(raised).__name__ if raised else 'nothing'}: {raised}")
        check("and it is NOT an IndexError that would restart the browser",
              not isinstance(raised, IndexError), f"{raised!r}")

        clicked = None
        try:
            clicked = wrap.smartClick(element=doomed)
        except BaseException as exc:      # noqa: BLE001
            raised = exc
            clicked = "raised"
        check("clicking a stale element reports and returns None instead of crashing",
              clicked is None, f"got {clicked!r}")

        # A live element still resolves normally.
        page.set_content("<div><span></span><button id='real'>ok</button></div>")
        page.wait_for_timeout(100)
        real = wrap._resolve_matches("//button[@id='real']", None)[0]
        path = wrap.generate_full_xpath(real)
        check("a live element still gets a full xpath", path.startswith("/html"), f"{path!r}")
        check("and that xpath actually finds it again",
              len(page.query_selector_all(f"xpath={path}")) == 1, f"{path!r}")

        print()
        print("--- the questions page ---")
        if load(page, "questions.html"):
            check("its Continue button has a hashed test id, so the preferred one misses",
                  count(page, H.CONTINUE_BUTTON_XPATH) == 0,
                  "then this test is not proving anything")
            check("but the text fallback finds it",
                  count(page, "//*[text()='Continue']") == 1)

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL RESUME EXIT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
