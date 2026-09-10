"""A captcha on the final "review and submit" step kept the run stuck even
AFTER the user solved it by hand (Logs/Log32.txt): submitApp() raised
NeedsHumanError purely because a captcha WIDGET was visible, but neither
reCAPTCHA nor Cloudflare Turnstile removes or hides its widget once solved --
HTMLz/review_application_stuck.html still shows the same iframe either way,
just with a checkmark instead of an empty box. So every retry, solved or not,
found the exact same widget, raised the exact same error, and
attentionWaived (main3.py) then muted the re-alert after the first one --
the run just sat there quietly re-failing to submit every 5 seconds forever,
looking identical to a captcha that was never solved at all.

Fixed by checking the provider's own solved signal (the hidden response
field, empty until solved, holding a long token afterward) instead of mere
widget presence, and by adding an immediate, unmissable alert -- this
window raised above every other bot's window, plus a sharp 5-beep burst --
right at the moment a GENUINELY unsolved captcha is found, since several
bots run in parallel and a beep alone does not say which window needs you.
"""

from __future__ import annotations

import sys
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


def build_helper(page):
    located = main3.IndeedHelper.__new__(main3.IndeedHelper)
    main3.PlaywrightWrap.__init__(located, "", "", "user-data-dir=")
    located._page = page
    located._context = page.context
    located.outputFile = None
    return located


SUBMIT_PAGE = """
  <input type="checkbox">
  <button data-testid="submit-application-button"><span>Submit your application</span></button>
  <div id="captcha-wrapper">
    <iframe src="https://www.recaptcha.net/recaptcha/enterprise/anchor?k=fake"></iframe>
    <textarea id="g-recaptcha-response">{token}</textarea>
  </div>"""

TURNSTILE_PAGE = """
  <input type="checkbox">
  <button data-testid="submit-application-button"><span>Submit your application</span></button>
  <div id="cf-turnstile"></div>
  <input type="hidden" name="cf-turnstile-response" value="{token}">"""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()

        print("--- _submitCaptchaSolved reads the provider's own solved signal ---")
        located = build_helper(page)
        page.set_content(SUBMIT_PAGE.format(token=""))
        page.wait_for_timeout(150)
        check("an empty reCAPTCHA response field reads as unsolved",
              not located._submitCaptchaSolved())

        page.set_content(SUBMIT_PAGE.format(token="03AGdBq27fake-solved-token"))
        page.wait_for_timeout(150)
        check("a populated reCAPTCHA response field reads as solved",
              located._submitCaptchaSolved())

        page.set_content(TURNSTILE_PAGE.format(token=""))
        page.wait_for_timeout(150)
        check("an empty Turnstile response field reads as unsolved",
              not located._submitCaptchaSolved())

        page.set_content(TURNSTILE_PAGE.format(token="0.fake-turnstile-token"))
        page.wait_for_timeout(150)
        check("a populated Turnstile response field reads as solved",
              located._submitCaptchaSolved())

        print()
        print("--- the real stuck capture: present AND unsolved, matching Log32 ---")
        page.goto((CAPTURES / "review_application_stuck.html").as_uri())
        page.wait_for_timeout(300)
        captchaPresent = bool(located._visible_only(
            located.driver.find_elements('xpath', located.SUBMIT_CAPTCHA_XPATH)))
        check("SUBMIT_CAPTCHA_XPATH matches the real captcha widget",
              captchaPresent, "if this is False the rest of this test proves nothing")
        check("and _submitCaptchaSolved correctly reads it as NOT solved",
              not located._submitCaptchaSolved(),
              "this is the exact real-world shape of the bug: present, and genuinely unsolved")

        print()
        print("--- submitApp(): an unsolved captcha stops for a person AND alerts once ---")
        page.set_content(SUBMIT_PAGE.format(token=""))
        page.wait_for_timeout(150)
        located2 = build_helper(page)

        alertCalls = []
        located2._bringWindowToFront = lambda: alertCalls.append("front")
        original_beep = main3._beep
        beepCalls = []
        main3._beep = lambda: beepCalls.append(1)
        try:
            raised = None
            try:
                located2.submitApp()
            except main3.NeedsHumanError:
                raised = True
            except Exception:                 # noqa: BLE001
                raised = False
        finally:
            main3._beep = original_beep

        check("an unsolved captcha raises NeedsHumanError instead of looping silently",
              raised is True, f"raised={raised!r}")
        check("the window-to-front alert fires exactly once",
              alertCalls == ["front"], f"got {alertCalls!r}")
        check("and beeps 5 times", len(beepCalls) == 5, f"got {len(beepCalls)} beeps")

        print()
        print("--- submitApp(): a SOLVED captcha does not raise, and does not alert ---")
        page.set_content(SUBMIT_PAGE.format(token="03AGdBq27fake-solved-token"))
        page.wait_for_timeout(150)
        located3 = build_helper(page)
        alertCalls3 = []
        located3._bringWindowToFront = lambda: alertCalls3.append("front")
        original_beep = main3._beep
        beepCalls3 = []
        main3._beep = lambda: beepCalls3.append(1)
        try:
            raised3 = None
            try:
                located3.submitApp()
            except main3.NeedsHumanError:
                raised3 = True
            except Exception:                 # noqa: BLE001
                raised3 = "other"
        finally:
            main3._beep = original_beep

        check("a solved captcha does NOT stop the run",
              raised3 is None, f"raised={raised3!r}")
        check("and does not trigger the manual-captcha alert at all",
              alertCalls3 == [] and beepCalls3 == [],
              f"front={alertCalls3!r} beeps={len(beepCalls3)}")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL SUBMIT CAPTCHA TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
