"""A newer /viewjob template renders the Apply button as an <a role="link">
instead of a <button> (HTMLz/retirement_plan_implementation_Consultant.html,
Logs/Log36.txt). None of APPLY_BUTTON_XPATH's four alternatives matched it:
its class list is just hashed react-native-web utility classes
(css-g5y9jx r-1loqt21 r-1otgn73), not 'jobsearch-IndeedApplyButton', and it is
an <a>, not a <button>, so the text-matching alternatives never applied
either. The only reliable identifier is data-testid="viewjob-indeed-apply".

Without a match, process_job_openings searched for 8s, ran the
clearCaptcha()/waitOutLoading() detour meant for a real challenge, searched
another 8s, and gave up -- silently treating a perfectly applicable job as
"not a job you can apply to from Indeed" (main3.py:2466-2469). Six of seven
opened jobs in Log36.txt were lost to exactly this, on a run where the button
was visibly present in every one of their capture pages.
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


# Exactly the markup from HTMLz/retirement_plan_implementation_Consultant.html:
# an <a>, not a <button>, with hashed utility classes and no
# 'jobsearch-IndeedApplyButton' anywhere -- only data-testid identifies it.
ANCHOR_APPLY_PAGE = """
  <div data-testid="primary-apply-action">
    <a href="https://smartapply.indeed.com/beta/indeedapply/applybyapplyablejobid?indeedApplyableJobId=6f476aaa-1ab1-404e-ac74-457df8755f3a-Y21o"
       rel="nofollow" role="link" tabindex="0"
       class="css-g5y9jx r-1loqt21 r-1otgn73" data-testid="viewjob-indeed-apply">
      <div class="css-g5y9jx"><div class="css-g5y9jx">
        <div dir="auto" class="css-146c3p1 r-1xnzce8">Apply now</div>
      </div></div>
    </a>
  </div>"""

# The OLDER template this codebase was originally built against, still in use
# on some listings -- must keep matching after the fix, unchanged.
BUTTON_APPLY_PAGE = """
  <button id="indeedApplyButton" class="jobsearch-IndeedApplyButton-newDesign">
    <div class="jobsearch-IndeedApplyButton-contentWrapper">Apply with Indeed</div>
  </button>"""

# Pre-fix selector, reconstructed here so the test can show it genuinely
# fails on the anchor markup -- not just that the new alternative exists.
_OLD_APPLY_BUTTON_XPATH = (
    "//*[contains(@class, 'jobsearch-IndeedApplyButton')]"
    " | //button[normalize-space(.)='Apply with Indeed']"
    " | //button[normalize-space(.)='Apply now']"
    " | //button[normalize-space(.)='Apply on Indeed']"
)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        located = build_helper(page)

        print("--- the anchor-based Apply button (the reported markup) ---")
        page.set_content(ANCHOR_APPLY_PAGE)
        page.wait_for_timeout(150)

        oldMiss = located._visible_only(
            located.driver.find_elements('xpath', _OLD_APPLY_BUTTON_XPATH))
        check("the PRE-FIX selector genuinely does not see it -- confirms "
              "this is a real gap, not a test artifact",
              not oldMiss, f"got {oldMiss!r}")

        newMatch = located._visible_only(
            located.driver.find_elements('xpath', located.APPLY_BUTTON_XPATH))
        check("the fixed APPLY_BUTTON_XPATH finds it",
              bool(newMatch), f"got {newMatch!r}")
        check("it resolves to the actual <a>, not some other element",
              bool(newMatch) and newMatch[0].get_attribute("data-testid") == "viewjob-indeed-apply")

        print()
        print("--- the older <button>-based template still matches, unchanged ---")
        page.set_content(BUTTON_APPLY_PAGE)
        page.wait_for_timeout(150)
        buttonMatch = located._visible_only(
            located.driver.find_elements('xpath', located.APPLY_BUTTON_XPATH))
        check("the original button markup is still found",
              bool(buttonMatch), f"got {buttonMatch!r}")

        print()
        print("--- an unrelated link is not mistaken for the Apply button ---")
        page.set_content('<a role="link" data-testid="some-other-link">Apply now</a>')
        page.wait_for_timeout(150)
        noMatch = located._visible_only(
            located.driver.find_elements('xpath', located.APPLY_BUTTON_XPATH))
        check("no false positive on a link that merely says the same words",
              not noMatch, f"got {noMatch!r}")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL APPLY BUTTON ANCHOR VARIANT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
