"""The "Review your resume for this application" page (Logs/Log53.txt).

Indeed rebuilt the first resume page of the apply flow. The radio cards are gone;
the one resume is shown as a preview, and editing it means

    "Resume options" (three dots)  ->  a menu appears  ->  "Edit"

(HTMLz/review_resume4.html, HTMLz/review_resume4_menu_open.html). Nothing knew
the page: its title was not in config/ExpectedEnvironments.txt, so the state
machine reported an UNKNOWN PAGE and beeped.

Pinned here: the selectors against the real captures, the config rules for the
page, and the behaviour of startResume() on both the new layout and the old one
(which must keep working). The options button is a TOGGLE, so the cases that
matter are the ones where a second click would undo the first.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

H = main3.IndeedHelper
CAPTURES = ROOT / "HTMLz"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def count(page, xpath: str) -> int:
    return len(page.query_selector_all(f"xpath={xpath}"))


def load(name: str, page) -> bool:
    path = CAPTURES / name
    if not path.exists():
        print(f"       (skipped: {name} is not in HTMLz/)")
        return False
    page.goto(path.as_uri())
    page.wait_for_timeout(300)
    return True


def transitions_for(env_snippet):
    """The config's rules for the page whose pattern contains env_snippet."""
    text = (ROOT / "config" / "StateTransitions.txt").read_text(encoding="utf-8")
    rules, inside, pending = {}, False, []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if "|" in stripped and "--" not in stripped:
            inside = env_snippet in stripped.lower()
            pending = []
            continue
        if not inside:
            continue
        if "--" in stripped:
            state, func, nxt = stripped.split("--")
            for s in pending + [state.strip()]:
                rules[s] = (func.strip("() "), nxt.strip("-> "))
            pending = []
        else:
            pending.append(stripped)
    return rules


# The new page, shaped after the capture. The menu is mounted when the toggle
# opens it and removed when it closes, and the toggle is a plain toggle -- which
# is what makes a second click undo the first. {open_delay} models a menu that is
# slow to appear; {paint_delay} a page whose title is set before its content.
NEW_PAGE = """
  <div id="slot"></div>
  <script>
    window.toggles = 0;
    function paint() {{
      document.getElementById('slot').innerHTML =
        '<h1>Review your resume</h1>'
        + '<div data-testid="resume-selection-resume-preview">'
        + '<button aria-label="Resume options"'
        + ' data-testid="resume-selection-resume-preview-options"'
        + ' aria-expanded="false" onclick="toggle()">...</button>'
        + '<div id="menuSlot"></div></div>'
        + '<button data-testid="continue-button"><span>Continue</span></button>';
      if ({start_open}) setTimeout(openMenu, 0);
    }}
    function openMenu() {{
      document.getElementById('menuSlot').innerHTML =
        '<ul><li><button type="button"'
        + ' data-testid="resume-selection-resume-preview-options-edit"'
        + ' onclick="document.title=\\'edited\\'"><span>Edit</span></button></li></ul>';
    }}
    function toggle() {{
      window.toggles++;
      var slot = document.getElementById('menuSlot');
      if (slot.innerHTML) {{ slot.innerHTML = ''; }}
      else {{ setTimeout(openMenu, {open_delay}); }}
    }}
    setTimeout(paint, {paint_delay});
  </script>"""

# The page this replaced: radio card, then a menu on the card holding
# "Edit resume details". Must keep working.
OLD_PAGE = """
  <label data-testid="resume-selection-structured-resume-radio-card-label">
    Use your Indeed Resume</label>
  <button data-testid="resume-selection-structured-resume-radio-card-resume-options"
          onclick="document.getElementById('m').style.display='block'">...</button>
  <div id="m" style="display:none">
    <button data-testid="resume-selection-structured-resume-radio-card-resume-options-editResumeDetails"
            onclick="document.title='edited-old'">Edit resume details</button>
  </div>"""


def build_helper(page):
    wrap = main3.IndeedHelper.__new__(main3.IndeedHelper)
    main3.PlaywrightWrap.__init__(wrap, "", "", "user-data-dir=")
    wrap._page = page
    wrap._context = page.context
    wrap.outputFile = None
    return wrap


def run_new(page, wrap, **kw):
    """Run startResume() against the new layout; returns (result, secs, toggles)."""
    params = dict(start_open="false", open_delay=0, paint_delay=0)
    params.update(kw)
    page.set_content(NEW_PAGE.format(**params))
    page.wait_for_timeout(100)
    started = time.time()
    result = wrap.startResume()
    return result, time.time() - started, page.evaluate("window.toggles")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        wrap = build_helper(page)

        # --- the selectors, against the real captures -------------------------
        print("--- the real captures ---")
        for name in ("review_resume4.html", "review_resume4_menu_open.html"):
            if not load(name, page):
                continue
            check(f"{name}: the 'Resume options' button is found, once",
                  count(page, H.RESUME_PREVIEW_OPTIONS_XPATH) == 1,
                  f"matched {count(page, H.RESUME_PREVIEW_OPTIONS_XPATH)}")
            check(f"{name}: the menu's Edit is found, once",
                  count(page, H.RESUME_PREVIEW_EDIT_XPATH) == 1,
                  f"matched {count(page, H.RESUME_PREVIEW_EDIT_XPATH)}")
            check(f"{name}: it has no radio card, so it is not mistaken for the old layout",
                  count(page, H.RESUME_CARD_XPATH) == 0)
            # Edit lives in a menu that shares the page with 'Change resume
            # template' and 'Download'; the Edit selector must not pick those up.
            check(f"{name}: addResume() still has exactly one real Continue button",
                  count(page, H.CONTINUE_BUTTON_XPATH) == 1,
                  f"found {count(page, H.CONTINUE_BUTTON_XPATH)}")

        if load("Add_a_resume.html", page):
            check("the OLD capture is not mistaken for the new layout",
                  count(page, H.RESUME_PREVIEW_OPTIONS_XPATH) == 0)

        # --- the config -------------------------------------------------------
        print()
        print("--- the config knows the page ---")
        new_rules = transitions_for("review your resume for this application")
        old_rules = transitions_for("upload or")
        check("the page has rules", bool(new_rules))
        check("arriving from Apply (hitApply) opens the editor",
              new_rules.get("hitApply") == ("startResume", "startedOnResume"),
              f"hitApply -> {new_rules.get('hitApply')}")
        check("and its rules are the old page's, so the rest of the flow is unchanged",
              new_rules == old_rules, f"new {new_rules}\n         old {old_rules}")

        # --- the new layout, end to end ---------------------------------------
        print()
        print("--- startResume() on the new layout ---")
        result, secs, toggles = run_new(page, wrap)
        check("opens the menu and clicks Edit", page.title() == "edited",
              f"title is {page.title()!r}")
        check("returns the Edit button", result is not None)
        check("does not sit out the old radio card's 8s timeout first", secs < 6,
              f"took {secs:.1f}s")
        check("opens the menu exactly once", toggles == 1, f"toggled {toggles}x")

        result, secs, toggles = run_new(page, wrap, open_delay=1200)
        check("a menu that is slow to appear is waited for, not re-toggled",
              page.title() == "edited" and toggles == 1,
              f"title {page.title()!r}, toggled {toggles}x -- a second click would close it")

        result, secs, toggles = run_new(page, wrap, paint_delay=2000)
        check("a page that paints after its title is set is waited for",
              page.title() == "edited", f"title is {page.title()!r}")

        # The menu being open already is what a retry looks like: a first attempt
        # opened it, the Edit click missed, and the state machine came back.
        result, secs, toggles = run_new(page, wrap, start_open="true")
        check("a menu that is already open does not strand the click",
              page.title() == "edited" and result is not None,
              f"title {page.title()!r}, toggled {toggles}x")

        # --- the old layout must keep working ---------------------------------
        print()
        print("--- startResume() on the old layout ---")
        page.set_content(OLD_PAGE)
        page.wait_for_timeout(100)
        started = time.time()
        result = wrap.startResume()
        check("the radio-card layout still opens the editor", page.title() == "edited-old",
              f"title is {page.title()!r}")
        check("and does not wait out the new-layout detection",
              time.time() - started < 12, f"took {time.time() - started:.1f}s")

        if load("Add_a_resume.html", page):
            check("the real old-layout capture is still recognised by its own selectors",
                  count(page, H.RESUME_CARD_XPATH) > 0
                  and count(page, H.RESUME_OPTIONS_XPATH) > 0)

        # --- the failure mode -------------------------------------------------
        print()
        print("--- a menu with no Edit in it ---")
        page.set_content(
            '<button data-testid="resume-selection-resume-preview-options">...</button>')
        page.wait_for_timeout(100)
        raised, result = None, "unset"
        try:
            result = wrap.startResume()
        except BaseException as exc:      # noqa: BLE001
            raised = exc
        check("reports it and returns rather than crashing",
              raised is None and result is None,
              f"raised {raised!r}, returned {result!r}")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL RESUME PREVIEW MENU TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
