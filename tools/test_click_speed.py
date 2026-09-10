"""Clicking must not waste time on hidden duplicates.

A profile of a real run showed 1052 of its 1344 seconds -- 78% -- spent inside
ElementHandle.click waiting for elements that were never going to become
visible. Indeed's pages carry hidden copies of the things the bot clicks (six
"Continue" buttons where only one works, decoy nav buttons), and picking
matches[0] blindly landed on them.

This builds a page with that exact shape and measures the difference.
"""

from __future__ import annotations

import sys
import tempfile
import time
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


# Five hidden decoys before the real button -- the shape of the resume
# selection page, where hp-continue-button-0..4 precede continue-button.
PAGE = """<!doctype html><html><body>
<div id="out">nothing</div>
""" + "".join(
    f'<button class="decoy" style="display:none">Continue</button>' for _ in range(5)
) + """
<button id="real" onclick="document.getElementById('out').textContent='clicked'">Continue</button>
</body></html>"""


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "page.html").write_text(PAGE, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.goto((tmp / "page.html").as_uri())
        page.wait_for_timeout(200)

        wrap = main3.IndeedHelper.__new__(main3.IndeedHelper)
        main3.PlaywrightWrap.__init__(wrap, "", "", "user-data-dir=")
        wrap.outputFile = None
        wrap._page = page
        wrap._context = page.context

        matches = wrap._resolve_matches("//button[normalize-space(.)='Continue']", None)
        check("the page really has hidden duplicates", len(matches) == 6,
              f"expected 6 buttons, got {len(matches)}")

        visible = wrap._visible_only(matches)
        check("only one of them is visible", len(visible) == 1,
              f"{len(visible)} reported visible")
        check("the visible one is the real button",
              visible and visible[0]._handle.get_attribute("id") == "real",
              "picked the wrong element")

        # The click path should now land on the real button, quickly.
        started = time.time()
        wrap.smartClick("//button[normalize-space(.)='Continue']", timeLimit=20)
        elapsed = time.time() - started

        landed = page.text_content("#out")
        check("the click reached the working button", landed == "clicked",
              f"#out says {landed!r}")
        check("and did not burn a click timeout getting there", elapsed < 5,
              f"took {elapsed:.1f}s -- a hidden element was probably clicked first")
        print(f"         click took {elapsed:.2f}s "
              f"(before the fix each hidden miss cost ~5.6s)")

        # fillMoveOn should set a long value in one shot, not 20 chars at a time.
        page.set_content("<input id='t' style='width:400px'>")
        field = wrap._resolve_matches("//input[@id='t']", None)[0]
        long_text = "word " * 400          # 2000 characters
        started = time.time()
        wrap.fillMoveOn(field, long_text)
        elapsed = time.time() - started
        value = page.input_value("#t")
        check("long text is filled correctly", value.strip() == long_text.strip(),
              f"got {len(value)} chars, expected {len(long_text)}")
        check("filling 2000 chars is fast", elapsed < 5,
              f"took {elapsed:.1f}s -- still chunking?")
        print(f"         filled {len(long_text)} chars in {elapsed:.2f}s")

        # --- a form that renders a moment after the button is clicked --------
        # This is the real shape of "Add work experience": the fields do not
        # exist at the instant the button is clicked. Looking for them without
        # waiting left job title, company and location silently empty, and the
        # form was then saved half-filled.
        page.set_content("""
          <button id="open">Add work experience</button>
          <div id="slot"></div>
          <script>
            document.getElementById('open').addEventListener('click', function () {
              setTimeout(function () {
                var input = document.createElement('input');
                input.setAttribute('data-testid', 'job-title-input-autocomplete-input');
                document.getElementById('slot').appendChild(input);
              }, 900);
            });
          </script>""")
        page.wait_for_timeout(150)
        wrap.smartClick("//button[@id='open']")
        filled = wrap.fillByTestId("job-title-input-autocomplete-input",
                                   "Technical Project Manager", "job title")
        check("a field that renders late is still filled", filled is not None,
              "gave up before the form had rendered")
        if filled:
            value = page.input_value('[data-testid="job-title-input-autocomplete-input"]')
            check("and holds the right value", value == "Technical Project Manager",
                  f"holds {value!r}")

        # --- every match hidden: poll, do not click one ----------------------
        # After saving a work experience the "Add" button exists but is still
        # covered by the form. Clicking it burned the full timeout each pass and
        # the run looped. It should wait for it to become visible instead.
        page.set_content("""
          <div id="out">nothing</div>
          <button id="late" aria-label="Add work experience" style="display:none"
                  onclick="document.getElementById('out').textContent='clicked'">Add</button>
          <script>setTimeout(() => {
              document.getElementById('late').style.display = '';
            }, 1500);</script>""")
        page.wait_for_timeout(100)
        started = time.time()
        wrap.smartClick("//*[@aria-label='Add work experience']", timeLimit=12)
        elapsed = time.time() - started
        check("a hidden-then-shown button is waited for, not clicked blind",
              page.text_content("#out") == "clicked",
              "never reached the button once it appeared")
        check("and it does not burn a click timeout doing so", elapsed < 8,
              f"took {elapsed:.1f}s")
        print(f"         waited {elapsed:.1f}s for a button shown after 1.5s")

        # --- a form that saves WITHOUT changing the URL -----------------------
        # checkNewPage waited only for a new URL. The resume forms save in
        # place, so every save burned the full ten-second window:
        #   Save this work experience ... 10038ms, 10074ms, 10044ms, 10164ms
        # for one application's four jobs. The form closing is the real signal.
        page.set_content("""
          <div id="form">
            <button id="save" aria-label="Save this work experience">Save</button>
          </div>
          <div id="out">open</div>
          <script>
            document.getElementById('save').addEventListener('click', function () {
              setTimeout(function () {
                document.getElementById('form').style.display = 'none';
                document.getElementById('out').textContent = 'saved';
              }, 400);
            });
          </script>""")
        page.wait_for_timeout(100)
        started = time.time()
        wrap.smartClick("//*[@aria-label='Save this work experience']",
                        checkNewPage=True, timeLimit=10)
        elapsed = time.time() - started
        check("an in-place save is detected by the form closing",
              page.text_content("#out") == "saved", "the save never happened")
        check("and does not wait out the whole window for a URL that never changes",
              elapsed < 4, f"took {elapsed:.1f}s -- still waiting only on the URL")
        print(f"         in-place save took {elapsed:.2f}s (was a flat ~10s)")

        # A click that genuinely navigates must still be waited for.
        page.set_content("""
          <button id="go">Go</button>
          <script>
            document.getElementById('go').addEventListener('click', function () {
              setTimeout(function () { location.hash = 'next'; }, 600);
            });
          </script>""")
        page.wait_for_timeout(100)
        wrap.smartClick("//button[@id='go']", checkNewPage=True, timeLimit=10)
        check("a click that really navigates is still waited for",
              page.url.endswith("#next"), f"url is {page.url[-30:]!r}")

        # If nothing ever becomes visible it must give up, not hang.
        page.set_content("""<button aria-label="Add work experience"
                                    style="display:none">Add</button>""")
        page.wait_for_timeout(100)
        started = time.time()
        result = wrap.smartClick("//*[@aria-label='Add work experience']", timeLimit=3)
        elapsed = time.time() - started
        check("a permanently hidden match gives up at the time limit",
              result is None and elapsed < 8, f"result={result!r} after {elapsed:.1f}s")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL CLICK SPEED TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
