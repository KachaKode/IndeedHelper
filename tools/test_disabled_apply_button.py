"""A disabled Apply button ("Apply with Indeed", greyed out, <button disabled>)
means Indeed itself is saying a job cannot be applied to -- already filled, an
external-site-only posting, etc. Before this, process_job_openings only ever
asked "did the button click?", and a disabled button answers that the same
way a MISSING button does (smartClick's own disabled check returns None
either way) -- so it fell into the captcha-suspicion retry path and burned a
~16s clearCaptcha()/waitOutLoading() cycle chasing a challenge that could
never appear, before landing on the same skip regardless. This pins the
detection and its placement: fast, definitive, and not confused with a
captcha.

The FIRST fix only covered process_job_openings, but that is not the only
place a disabled button gets clicked: startApplication() (state hitApply,
reached by navigating straight to a /viewjob URL rather than through a
search-results card) has its own, independent Apply-button click with no
disabled check at all (Logs/Log33.txt, HTMLz/job_listing_page_disabled.html).
smartClick's own disabled check never caught it there either, for the same
underlying reason: APPLY_BUTTON_XPATH's class-based alternative matches
jobsearch-IndeedApplyButton-contentWrapper, a CHILD <div> of the real
<button disabled> with no disabled attribute of its own -- so smartClick
"clicked" the harmless child div instead, which does nothing, the URL never
changed, and config/StateTransitions.txt's "default -- startApplication() -->
hitApply" rule just called it again, forever (the 15-minute no-progress
watchdog fired 17 times in one run before the log was captured). This file
now also pins startApplication()'s copy of the same fix.
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


# Exactly the markup reported: the disabled attribute lives on the <button>,
# but APPLY_BUTTON_XPATH's own class-based alternative actually matches the
# CHILD contentWrapper <div> -- which has no disabled attribute of its own.
DISABLED_BUTTON_PAGE = """
  <button id="indeedApplyButton" data-testid="indeedApplyButton-test" title=""
          disabled="" aria-label="Apply with Indeed" class="css-1rxpv9j e8ju0x50">
    <div class="jobsearch-IndeedApplyButton-contentWrapper">
      <span class="jobsearch-IndeedApplyButton-newDesign css-1ebo7dz eu4oa1w0">Apply with Indeed</span>
    </div>
  </button>"""

ENABLED_BUTTON_PAGE = """
  <button id="indeedApplyButton" data-testid="indeedApplyButton-test" title=""
          aria-label="Apply with Indeed" class="css-1rxpv9j e8ju0x50">
    <div class="jobsearch-IndeedApplyButton-contentWrapper">
      <span class="jobsearch-IndeedApplyButton-newDesign css-1ebo7dz eu4oa1w0">Apply with Indeed</span>
    </div>
  </button>"""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        located = build_helper(page)

        print("--- APPLY_BUTTON_DISABLED_XPATH on the reported markup ---")
        page.set_content(DISABLED_BUTTON_PAGE)
        page.wait_for_timeout(150)
        disabledMatch = located._visible_only(
            located.driver.find_elements('xpath', located.APPLY_BUTTON_DISABLED_XPATH))
        check("a disabled Apply button is detected",
              bool(disabledMatch), f"got {disabledMatch!r}")

        # Confirms the reasoning in the comment: checking the CHILD wrapper's
        # own disabled attribute (what APPLY_BUTTON_XPATH's first alternative
        # actually resolves to) would have missed this entirely.
        wrapperDiv = page.query_selector(".jobsearch-IndeedApplyButton-contentWrapper")
        check("and the child wrapper div itself has no disabled attribute -- "
              "checking IT would have missed the disabled button completely",
              wrapperDiv is not None and wrapperDiv.get_attribute("disabled") is None)

        print()
        print("--- an ENABLED Apply button is not mistaken for a disabled one ---")
        page.set_content(ENABLED_BUTTON_PAGE)
        page.wait_for_timeout(150)
        enabledMatch = located._visible_only(
            located.driver.find_elements('xpath', located.APPLY_BUTTON_DISABLED_XPATH))
        check("no false positive on a normal, clickable Apply button",
              not enabledMatch, f"got {enabledMatch!r}")
        stillFindable = located._visible_only(
            located.driver.find_elements('xpath', located.APPLY_BUTTON_XPATH))
        check("and APPLY_BUTTON_XPATH itself still finds it, unaffected",
              bool(stillFindable))

        print()
        print("--- startApplication(): the SECOND, independent path to the "
              "same button (Logs/Log33.txt, state hitApply) ---")
        located2 = build_helper(page)
        backCalls = []
        located2.backToStart = lambda: backCalls.append(1) or "stubbed"

        page.set_content(DISABLED_BUTTON_PAGE)
        page.wait_for_timeout(150)
        result = located2.startApplication()
        check("a disabled button makes startApplication back out via "
              "backToStart(), the same as the existing 'Applied' badge case",
              backCalls == [1] and result == "stubbed", f"backCalls={backCalls!r} result={result!r}")

        backCalls.clear()
        page.set_content(ENABLED_BUTTON_PAGE)
        page.wait_for_timeout(150)
        located2.startApplication()
        check("an enabled button does NOT back out -- the click is still attempted",
              backCalls == [], f"backCalls={backCalls!r}")

        browser.close()

    print()
    print("--- process_job_openings: disabled is checked before the captcha "
          "detour, and skips without waiting on one ---")
    src = (ROOT / "main3.py").read_text(encoding="utf-8")
    loop = src[src.index("def process_job_openings("):]
    loop = loop[:loop.index("\n    def ", 1)]
    first_search_at = loop.find("APPLY_BUTTON_XPATH")
    disabled_check_at = loop.find("APPLY_BUTTON_DISABLED_XPATH")
    clear_captcha_at = loop.find("self.clearCaptcha()")
    check("the disabled check exists in process_job_openings", disabled_check_at != -1)
    check("it runs right after the first Apply-button search",
          first_search_at != -1 and disabled_check_at != -1 and first_search_at < disabled_check_at,
          "a button that has not been searched for yet cannot be judged enabled or not")
    check("and before the clearCaptcha detour, so a disabled button never "
          "waits out a captcha that will never appear",
          disabled_check_at != -1 and clear_captcha_at != -1 and disabled_check_at < clear_captcha_at)
    next_if_at = loop.find("if buttonElement is None:", disabled_check_at + 1)
    disabled_block = loop[disabled_check_at:next_if_at if next_if_at != -1 else disabled_check_at + 900]
    check("the disabled branch skips via backToStart()+continue directly",
          "self.backToStart()" in disabled_block and "continue" in disabled_block)
    check("and does not call clearCaptcha on the way",
          "clearCaptcha" not in disabled_block)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL DISABLED APPLY BUTTON TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
