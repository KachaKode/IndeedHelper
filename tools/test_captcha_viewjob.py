"""A Cloudflare challenge on a job page must not cost us the application.

A /viewjob URL sometimes answers with Cloudflare's managed challenge instead of
the job (HTMLz/captcha_view_job.html). That page carries no Apply button, and
process_job_openings read exactly one thing from that:

    buttonElement = self.findAndClick(... APPLY_BUTTON_XPATH ...)
    if buttonElement is None:
        # means this is not a job that you can apply from Indeed site
        self.backToStart()
        continue

-- so every challenged job was quietly skipped as "cannot apply from Indeed",
and the run moved on. Nothing in the log said a captcha had been seen at all.

The challenge cannot be clicked away through the DOM: the Turnstile iframe sits
inside a CLOSED shadow root, which no selector run against the page can pierce.
page.frames is the browser's own frame tree rather than the DOM, so the checkbox
IS reachable there -- but a managed challenge is designed to clear itself once
Cloudflare's background checks pass, and waiting is what actually works. These
tests pin both the detection and the waiting.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

CAPTURES = ROOT / "HTMLz"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


CLEARING_PAGE = """
  <div id="cf-chl-widget-abc">challenge</div>
  <input type="hidden" name="cf-turnstile-response">
  <script>
    setTimeout(function () {
      document.getElementById('cf-chl-widget-abc').remove();
      document.querySelector('[name="cf-turnstile-response"]').remove();
    }, 2500);
  </script>"""

# The real page hides the Turnstile iframe inside a CLOSED shadow root.
# Reproduced here so the frame-tree route is tested against the same obstacle:
# a selector cannot see this iframe, but page.frames can.
CLOSED_SHADOW_PAGE = """
  <div id="host"></div>
  <script>
    var root = document.getElementById('host').attachShadow({mode: 'closed'});
    var f = document.createElement('iframe');
    f.src = 'data:text/html,<label><input type="checkbox" aria-label="Verify you are human">v</label>';
    root.appendChild(f);
  </script>"""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()

        wrap = main3.IndeedHelper.__new__(main3.IndeedHelper)
        main3.PlaywrightWrap.__init__(wrap, "", "", "user-data-dir=")
        wrap._page = page
        wrap._context = page.context
        wrap.outputFile = None

        print("--- the real capture is recognised as a challenge ---")
        path = CAPTURES / "captcha_view_job.html"
        page.goto(path.as_uri())
        page.wait_for_timeout(400)
        check("the challenge page is detected", wrap._captchaShowing(),
              "this is exactly the page that was being skipped as unapplyable")
        check("and it genuinely has no Apply button to find",
              len(page.query_selector_all(
                  "xpath=" + main3.IndeedHelper.APPLY_BUTTON_XPATH)) == 0,
              "then the skip would not have been triggered by this page")

        print()
        print("--- an ordinary page is NOT mistaken for one ---")
        # False positives here are expensive: every job would sit for minutes
        # waiting out a challenge that was never there.
        for name in ("review_application.html", "questions2.html", "Add_Documents.html"):
            other = CAPTURES / name
            if not other.exists():
                continue
            page.goto(other.as_uri())
            page.wait_for_timeout(250)
            check(f"{name} is not treated as a challenge", not wrap._captchaShowing())

        page.set_content("<h1>Software Engineer</h1><button>Apply now</button>")
        page.wait_for_timeout(150)
        check("a plain job page is not treated as a challenge", not wrap._captchaShowing())

        print()
        print("--- clearCaptcha costs nothing when there is no challenge ---")
        started = time.time()
        result = wrap.clearCaptcha(limit=30)
        check("it returns True immediately", result is True)
        check("and does not wait around", time.time() - started < 3,
              f"took {time.time() - started:.1f}s on a page with no challenge")

        print()
        print("--- it waits the challenge out instead of giving up ---")
        page.set_content(CLEARING_PAGE)
        page.wait_for_timeout(150)
        check("the challenge is up to begin with", wrap._captchaShowing())
        started = time.time()
        cleared = wrap.clearCaptcha(limit=30)
        elapsed = time.time() - started
        check("it waits for the challenge to clear and reports success", cleared is True,
              f"returned {cleared!r} after {elapsed:.1f}s")
        check("and it actually waited rather than returning early", elapsed >= 2,
              f"returned after only {elapsed:.1f}s")
        check("the page is no longer showing a challenge", not wrap._captchaShowing())

        print()
        print("--- a challenge that never clears gives up, bounded ---")
        page.set_content('<div id="cf-chl-widget-stuck">challenge that never goes</div>')
        page.wait_for_timeout(150)
        started = time.time()
        cleared = wrap.clearCaptcha(limit=5)
        elapsed = time.time() - started
        check("it gives up rather than hanging forever", cleared is False,
              f"returned {cleared!r}")
        check("and respects the limit it was given", elapsed < 25,
              f"took {elapsed:.1f}s against a 5s limit")

        print()
        print("--- the checkbox is reached through the frame tree, not the DOM ---")
        page.set_content(CLOSED_SHADOW_PAGE)
        page.wait_for_timeout(700)
        check("a DOM selector cannot see the iframe at all",
              page.query_selector("iframe") is None,
              "then the closed shadow root is not reproduced and this proves nothing")
        check("but the browser's frame tree can", len(page.frames) > 1,
              f"{len(page.frames)} frame(s)")

        clicked = False
        for frame in page.frames:
            box = frame.query_selector("input[type=checkbox]")
            if box is not None:
                box.click(timeout=3000)
                clicked = True
        check("and the checkbox inside it can be ticked that way", clicked,
              "the frame-tree route is what _tickTurnstileBox relies on")
        check("_tickTurnstileBox walks page.frames rather than using a selector",
              "self._page.frames" in (ROOT / "main3.py").read_text(encoding="utf-8"),
              "frame_locator resolves through the DOM and would be blocked")

        print()
        print("--- the job loop checks for a challenge only after Apply fails once ---")
        # A one-shot check run the instant a fresh tab opens is USELESS: the tab
        # is still navigating and shows neither the real page nor a challenge
        # yet, so it always reads "no captcha" and the job gets skipped anyway
        # (Logs/log26.txt: three real challenges missed in a row this way,
        # before a fourth happened to be caught). clearCaptcha has to run AFTER
        # the first Apply-button search has already spent its 5 seconds --
        # by then the page, real or challenged, has had time to settle -- and
        # a second Apply-button search has to follow it, or a challenge that
        # DID clear still gets treated as unapplyable.
        loop_src = (ROOT / "main3.py").read_text(encoding="utf-8")
        loop = loop_src[loop_src.index("def process_job_openings"):]
        first_apply_at = loop.find("APPLY_BUTTON_XPATH")
        # Searched from first_apply_at, not from the top of the function: a
        # separate, earlier clearCaptcha()/waitOutLoading() pair now runs
        # before this, giving a still-rendering results PAGE (after a "Next
        # Page" click) a chance to settle before its job-card count is
        # trusted -- an unrelated fix for an unrelated symptom (Logs/Log38.txt),
        # not the retry this section is pinning.
        clear_at = loop.find("self.clearCaptcha()", first_apply_at) if first_apply_at != -1 else -1
        second_apply_at = loop.find("APPLY_BUTTON_XPATH", clear_at + 1) if clear_at != -1 else -1
        check("clearCaptcha runs inside process_job_openings", clear_at != -1)
        check("the FIRST Apply-button search happens before any captcha check",
              first_apply_at != -1 and clear_at != -1 and first_apply_at < clear_at,
              "checking before the tab has had a chance to render finds nothing, every time")
        check("and the Apply-button search runs AGAIN after clearCaptcha, "
              "so a challenge that cleared is not still treated as unapplyable",
              second_apply_at != -1,
              "otherwise clearing the challenge was pointless -- buttonElement stays None")

        print()
        print("--- a merely-slow real page gets a fair chance too, not just a captcha ---")
        # Logs/Log31.txt: "Execution context was destroyed, most likely because
        # of a navigation" during the Apply-button search, 40+ times in one run
        # -- a real page still mid client-side-navigation right after the
        # ctrl+click tab open, nothing Cloudflare-shaped about it at all.
        # clearCaptcha() returns instantly when _captchaShowing() is false, so
        # that case got ZERO extra time before the second search, on top of
        # each search only getting 5s to begin with -- an unapplyable verdict
        # after ~10s total even though the user could see the Apply button
        # sitting right there once the page actually finished loading.
        wait_loading_at = loop.find("self.waitOutLoading()", clear_at) if clear_at != -1 else -1
        check("waitOutLoading() runs between clearCaptcha and the retry",
              clear_at != -1 and wait_loading_at != -1 and clear_at < wait_loading_at < second_apply_at,
              "a real loading page needs its own dedicated wait, not just whatever "
              "clearCaptcha happened to leave behind")
        first_search_call = loop[first_apply_at - 50:first_apply_at + 120]
        check("the first Apply-button search gives the page more than the old 5s",
              "timeLimit=8" in first_search_call,
              f"still using the old budget: {first_search_call!r}")
        second_search_call = loop[second_apply_at - 50:second_apply_at + 120]
        check("so does the retry after clearCaptcha/waitOutLoading",
              "timeLimit=8" in second_search_call,
              f"still using the old budget: {second_search_call!r}")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL CAPTCHA VIEWJOB TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
