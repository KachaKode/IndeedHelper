""""Add supporting documents" sometimes renders inside
<iframe data-testid="application-preview" srcdoc="..."> -- the review page's
own read-only application preview -- instead of on the page itself
(Logs/Log34.txt, HTMLz/review_application_stuck2.html: the user could SEE
the button, but clickAddDocs() kept reporting "no Add supporting documents
control" and got stuck on it forever).

Playwright's page-level DOM queries never reach into an iframe's own
document, srcdoc or not, same origin or not -- an iframe is always a
separate frame context. clickAddDocs()'s search only ever looked at the top-
level page, the same gap _tickTurnstileBox() already had to work around for
the Cloudflare checkbox. Fixed the same way: fall back to searching every
iframe on the page (via page.frames, not the DOM) when the ordinary search
comes up empty.

This does not change anything after the click -- the same
smartClick(element=addButton, checkNewPage=True) runs either way, since an
application that offers this control directly on the page (confirmed to
happen too, per the user) must keep working exactly as before.
"""

from __future__ import annotations

import html as htmlmod
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


def iframe_page(inner_html: str) -> str:
    # A real button matching SUBMIT_BUTTON_XPATH, so waitForReviewPage()'s
    # own readiness check (which -- like the button search this test is
    # actually about -- only looks at the top-level DOM) resolves instantly
    # instead of waiting out its full 45s timeout on every call.
    return (f'<button data-testid="submit-application-button">Submit your application</button>'
            f'<iframe id="preview" srcdoc="{htmlmod.escape(inner_html)}"></iframe>')


ADD_BUTTON_HTML = (
    "<button aria-label='Add supporting documents' "
    "onclick=\"document.getElementById('marker').textContent='clicked'\">Add</button>"
    "<div id='marker'>not clicked</div>"
)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        located = build_helper(page)

        print("--- the ordinary top-level search cannot see into the iframe at all ---")
        page.set_content(iframe_page(ADD_BUTTON_HTML))
        page.wait_for_timeout(200)
        topLevel = located._visible_only(
            located.driver.find_elements('xpath', located.ADD_DOCS_XPATH))
        check("confirms the real gap: the button is genuinely invisible to a "
              "plain top-level query, same as the real bug",
              not topLevel, f"got {topLevel!r}")

        print()
        print("--- _findInFrames reaches inside the iframe and finds it ---")
        inFrame = located._visible_only(located._findInFrames(located.ADD_DOCS_XPATH))
        check("found via the frame tree instead of the DOM",
              len(inFrame) == 1, f"got {inFrame!r}")

        print()
        print("--- clickAddDocs() end to end: finds and clicks it inside the iframe ---")
        located2 = build_helper(page)
        page.set_content(iframe_page(ADD_BUTTON_HTML))
        page.wait_for_timeout(200)
        result = located2.clickAddDocs()
        check("clickAddDocs() does not give up and report 'no control found'",
              result is not None, f"got {result!r}")

        frame = next((f for f in page.frames if f != page.main_frame), None)
        marker = frame.query_selector("#marker").inner_text() if frame else None
        check("and the click actually landed inside the iframe's own document",
              marker == "clicked", f"got marker={marker!r}")

        print()
        print("--- unaffected: a button directly on the page is still found there first ---")
        located3 = build_helper(page)
        page.set_content(
            "<button aria-label='Add supporting documents' "
            "onclick=\"document.getElementById('m2').textContent='clicked'\">Add</button>"
            "<div id='m2'>not clicked</div>")
        page.wait_for_timeout(200)
        result3 = located3.clickAddDocs()
        check("still finds and clicks a button that is directly on the page",
              result3 is not None, f"got {result3!r}")
        check("without needing the iframe fallback at all",
              page.inner_text("#m2") == "clicked")

        print()
        print("--- unaffected: no control anywhere still skips gracefully ---")
        located4 = build_helper(page)
        page.set_content('<button data-testid="submit-application-button">'
                         'Submit your application</button>')
        page.wait_for_timeout(200)
        result4 = located4.clickAddDocs()
        check("returns None rather than raising or hanging",
              result4 is None, f"got {result4!r}")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL ADD DOCS IFRAME TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
