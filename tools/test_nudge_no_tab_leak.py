"""nudgeStuckPage() must never leak a tab.

From Logs/Log45.txt: "why do we have like ten different tabs open". The
stuck-loop recovery added in response to Logs/Log42-44.txt (see
tools/test_stuck_loop_recovery.py) clicks blind at the middle of the
viewport, scrolls to the bottom, and clicks again -- on purpose, since it
does not know what is under the cursor on a page it cannot otherwise
interact with. Real pages have real clickable content wherever that lands
(footer links, ads, job cards), a lot of which opens in a new tab, and
nothing was watching for that -- so a run that needed several rounds of this
recovery quietly accumulated a browser full of stray tabs.

PlaywrightWrap._clickWithoutOpeningTabs is the fix: it snapshots the open
tabs before each click and closes anything new that appears, so a click that
happens to land on a target="_blank" link cannot leave a tab behind, however
many times nudgeStuckPage() runs.
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


# Covers the whole viewport regardless of scroll position, so both the
# pre-scroll and post-scroll click in nudgeStuckPage() land on it -- standing
# in for "whatever happens to be under a blind click", which on a real page
# is sometimes a target="_blank" link.
FULL_PAGE_NEW_TAB_LINK = """
<a id="everywhere" href="about:blank" target="_blank"
   style="position:fixed;top:0;left:0;width:100vw;height:100vh;display:block;">
</a>
<div style="height:3000px;"></div>
"""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content(FULL_PAGE_NEW_TAB_LINK)
        page.wait_for_timeout(100)

        wrap = main3.IndeedHelper.__new__(main3.IndeedHelper)
        main3.PlaywrightWrap.__init__(wrap, "", "", "user-data-dir=")
        wrap._page = page
        wrap._context = page.context
        wrap.outputFile = None

        print("--- a click that lands on a target=\"_blank\" link ---")
        check("only the original tab is open before nudging",
              len(page.context.pages) == 1, f"pages={len(page.context.pages)}")

        wrap.nudgeStuckPage()

        check("no stray tab is left open after clicking, scrolling, and clicking again",
              len(page.context.pages) == 1,
              f"pages={len(page.context.pages)} urls="
              f"{[pg.url for pg in page.context.pages]}")
        check("the wrap is still pointed at the original page",
              wrap._page is page, "nudgeStuckPage() reassigned _page")
        check("the original page is still usable", not page.is_closed(),
              "the original page got closed along with the spawned tab")

        print()
        print("--- repeated nudges (the actual escalation, up to 3 cycles) never accumulate tabs ---")
        for i in range(3):
            wrap.nudgeStuckPage()
        check("three more rounds still leave exactly one tab open",
              len(page.context.pages) == 1, f"pages={len(page.context.pages)}")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL NUDGE TAB-LEAK TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
