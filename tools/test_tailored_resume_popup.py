"""The tailored-resume confirmation popup was closing itself the instant it
opened (Logs/Log28.txt): confirmTailoredResume() clicked the page's Continue
button, waited 8s for the confirmation checkbox, never found it, and looped
back to the same state -- forever, once every ~9 seconds.

The real mechanism (HTMLz/post_continue_pop_up2.html): the dialog Indeed
opens carries role="dialog" aria-modal="true" and a
<button aria-label="Close dialog" ...> inside it. smartClick() runs
closeDialogBox() after EVERY successful click unless the caller passes
expectingPopUp=True -- and closeDialogBox() dismisses any visible dialog
with a "close"-labeled button, no questions asked. Neither the click that
opens the dialog (main3.py's TAILORED_CONTINUE_XPATH click) nor the click
that ticks its checkbox passed expectingPopUp=True, so each one closed the
very dialog it had just acted inside of, immediately, before
confirmTailoredResume() ever got to look for the checkbox.
"""

from __future__ import annotations

import contextlib
import io
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


# Shaped after the real capture: a page-level Continue button that reveals a
# role="dialog" aria-modal="true" containing its OWN continue-btn (same
# data-tn-element as the page's, which is why confirmTailoredResume scopes
# the second click inside TAILORED_DIALOG_XPATH) plus a close button whose
# aria-label contains "close" -- exactly what closeDialogBox() looks for.
PAGE = """
  <button data-tn-element="continue-btn" onclick="openDialog()">Continue</button>
  <div id="dialog" role="dialog" aria-modal="true" style="display:none"
       data-tn-component="tailored-resume-ai-confirmation-dialog">
    <button aria-label="Close dialog" onclick="document.getElementById('dialog').remove()">X</button>
    <input type="checkbox" data-tn-element="confirm-changes">
    <button data-tn-element="continue-btn" onclick="document.getElementById('dialog').remove()">
      Continue
    </button>
  </div>
  <script>
    function openDialog() {
      document.getElementById('dialog').style.display = 'block';
    }
  </script>"""


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

        print("--- closeDialogBox() really does close a just-opened dialog ---")
        # Isolates the mechanism itself, independent of confirmTailoredResume:
        # a plain smartClick with expectingPopUp left at its default (False)
        # must not survive next to a freshly opened dialog with a close button.
        located = build_helper(page)
        page.set_content(PAGE)
        page.wait_for_timeout(150)
        located.smartClick(elementXpath="//*[@data-tn-element='continue-btn']", timeLimit=3)
        check("the dialog closed itself right after the click that opened it "
              "-- this is the bug, reproduced at the smartClick level",
              page.query_selector("#dialog") is None,
              "if this is None, closeDialogBox() ran and removed it")

        print()
        print("--- expectingPopUp=True keeps a dialog the click just opened alive ---")
        located2 = build_helper(page)
        page.set_content(PAGE)
        page.wait_for_timeout(150)
        located2.smartClick(elementXpath="//*[@data-tn-element='continue-btn']",
                            timeLimit=3, expectingPopUp=True)
        check("the dialog is still there", page.query_selector("#dialog") is not None)
        check("and still visible", page.is_visible("#dialog"))

        print()
        print("--- confirmTailoredResume() end to end: ticks the box and continues, "
              "does not loop back claiming there was no dialog ---")
        located3 = build_helper(page)
        page.set_content(PAGE)
        page.wait_for_timeout(150)

        # Both the buggy and the fixed path end with the dialog gone from the
        # DOM and a non-None return -- the buggy path removes it via the
        # CLOSE button and bails out with "no confirmation dialog", the fixed
        # path removes it via the dialog's OWN Continue after ticking the
        # box. Only the actual trace tells them apart, so it is captured and
        # checked rather than trusting the return value or DOM state alone
        # (a prior version of this test trusted exactly those and could not
        # tell the two apart -- it "passed" against the unfixed code too).
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = located3.confirmTailoredResume()
        trace = buf.getvalue()
        sys.stdout.write(trace)

        check("it did not give up claiming there was no confirmation dialog",
              "no confirmation dialog" not in trace,
              "this is printed only on the bail-out path -- the dialog was gone "
              "again before the checkbox could be found, same as Log28")
        check("the dialog's own scoped Continue was reached and clicked",
              f"clicked {located3.TAILORED_DIALOG_XPATH}//*[@data-tn-element='continue-btn'] "
              "successfully" in trace,
              "this line only appears on the successful path, after the box is ticked")
        check("and the return value reflects that click, not just the opening one",
              result is not None)

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL TAILORED RESUME POPUP TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
