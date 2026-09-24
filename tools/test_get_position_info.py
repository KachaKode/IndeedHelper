"""getPositionInfo() crashed with AttributeError: 'NoneType' object has no
attribute 'text' the moment the APPLY_BUTTON_XPATH anchor-variant fix let the
bot reach jobs it had previously been silently skipping.

That fix (see APPLY_BUTTON_XPATH's fifth alternative) let the bot get PAST
the Apply-button check on a newer viewjob template, but getPositionInfo()
right after it still only knew the OLD template's three selectors:
inlineHeader-companyName, h1.jobsearch-JobInfoHeader-title, and
id="jobDescriptionText" -- none of which exist on the new template
(HTMLz/retirement_plan_implementation_Consultant.html). Every job on that
template crashed RunUser, which restarted the whole browser with growing
backoff (15s, 30s, 45s...) and landed on the exact same job -- and the exact
same crash -- every single time, forever.

This pins getPositionInfo() working end to end against BOTH templates, so a
future selector change to one cannot silently break the other the same way.
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


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()

        print("--- old template: HTMLz/OpeningHTML.html ---")
        old_html = ROOT / "HTMLz" / "OpeningHTML.html"
        if old_html.exists():
            located = build_helper(page)
            page.goto(old_html.as_uri())
            page.wait_for_timeout(300)
            try:
                located.getPositionInfo()
                check("getPositionInfo() runs without crashing on the old template", True)
                check("companyName was extracted", bool((located.companyName or "").strip()),
                      f"got {located.companyName!r}")
                check("jobTitle was extracted", bool((located.jobTitle or "").strip()),
                      f"got {located.jobTitle!r}")
                check("JobDescriptionText was extracted",
                      bool((located.JobDescriptionText or "").strip()),
                      f"got {len(located.JobDescriptionText or '')} chars")
            except AttributeError as exc:
                check("getPositionInfo() runs without crashing on the old template",
                      False, f"{type(exc).__name__}: {exc}")
        else:
            print("[SKIP] HTMLz/OpeningHTML.html not found")

        print()
        print("--- new template: HTMLz/retirement_plan_implementation_Consultant.html ---")
        new_html = ROOT / "HTMLz" / "retirement_plan_implementation_Consultant.html"
        located2 = build_helper(page)
        page.goto(new_html.as_uri())
        page.wait_for_timeout(300)
        try:
            located2.getPositionInfo()
            check("getPositionInfo() runs without crashing on the new template", True)
        except AttributeError as exc:
            check("getPositionInfo() runs without crashing on the new template",
                  False, f"{type(exc).__name__}: {exc}")
            located2.companyName = located2.jobTitle = located2.JobDescriptionText = None

        check("companyName is the real employer, not something else",
              located2.companyName == "Leading Retirement Solutions",
              f"got {located2.companyName!r}")
        check("jobTitle is the real title",
              located2.jobTitle == "Retirement Plan Implementation Consultant",
              f"got {located2.jobTitle!r}")
        check("JobDescriptionText holds the actual posting body",
              bool(located2.JobDescriptionText) and "Leading Retirement Solutions" in located2.JobDescriptionText
              and "Essential Job Duties" in located2.JobDescriptionText,
              f"got {len(located2.JobDescriptionText or '')} chars")
        check("the Apply-button anchor's own text was not mistaken for the company name",
              located2.companyName != "Apply now")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL GET POSITION INFO TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
