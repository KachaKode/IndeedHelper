"""Does smartClick(ctrl=True) actually move the wrapper onto the new tab?

The bot ctrl+clicks a job card to open it in a new tab and then expects every
later lookup to run against that tab. This drives the real PlaywrightWrap over
controlled local pages so the answer does not depend on guessing from logs.

Three shapes are covered, because Indeed uses all of them:
  plain link          - <a href>, ctrl+click opens a background tab
  target=_blank link  - opens a tab with or without the modifier
  JS-intercepted link - a click handler that navigates the CURRENT page and
                        calls preventDefault, so no tab is ever created
"""

from __future__ import annotations

import sys
import tempfile
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


TARGET = "<!doctype html><html><body><h1 id='marker'>TARGET PAGE</h1></body></html>"

PAGES = {
    "plain": "<a id='go' href='target.html'>open job</a>",
    "blank": "<a id='go' href='target.html' target='_blank'>open job</a>",
    "jsnav": ("<a id='go' href='target.html'>open job</a>"
              "<script>document.getElementById('go').addEventListener('click', e => {"
              " e.preventDefault(); window.location = 'target.html'; });</script>"),
}


def run_case(wrap, page, kind, tmp):
    page.goto((tmp / f"{kind}.html").as_uri())
    page.wait_for_timeout(200)
    wrap._page = page
    wrap._context = page.context

    before_pages = len(page.context.pages)
    link = wrap.findAndClick(wrap.WHOLE, wrap.WHOLE, "//a[@id='go']",
                             txtCond="never-matches", timeLimit=2)
    wrap.smartClick(element=link, ctrl=True)
    page.wait_for_timeout(1200)

    after_pages = len(wrap._context.pages)
    landed = ""
    try:
        landed = wrap._page.text_content("#marker") or ""
    except Exception:
        landed = "<no marker>"
    return before_pages, after_pages, landed, wrap._page.url


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "target.html").write_text(TARGET, encoding="utf-8")
    for kind, body in PAGES.items():
        (tmp / f"{kind}.html").write_text(
            f"<!doctype html><html><body><h2>{kind}</h2>{body}</body></html>", encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context()

        wrap = main3.PlaywrightWrap.__new__(main3.PlaywrightWrap)
        main3.PlaywrightWrap.__init__(wrap, "", "", "user-data-dir=")

        for kind in PAGES:
            page = context.new_page()
            before, after, landed, url = run_case(wrap, page, kind, tmp)
            opened_tab = after > before
            on_target = "TARGET" in landed

            print(f"\n--- {kind} ---")
            print(f"    tabs {before} -> {after}   wrapper now on: {url.rsplit('/', 1)[-1]}")
            print(f"    sees marker: {landed!r}")

            if kind in ("plain", "blank"):
                check(f"{kind}: a new tab opened", opened_tab,
                      "ctrl+click did not produce a second tab")
                check(f"{kind}: wrapper followed onto the new tab", on_target,
                      "self._page still points at the old page")
            else:
                # No tab is created here; the wrapper must still end up on the
                # target, via the current page having navigated.
                check(f"{kind}: no phantom tab reported", not opened_tab or on_target)
                check(f"{kind}: wrapper ends up on the target page", on_target,
                      "JS-intercepted click left the wrapper stranded -- this is "
                      "the shape that would look like 'the tab did not switch'")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL TAB SWITCH TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
