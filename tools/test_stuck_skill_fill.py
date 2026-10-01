"""HTMLz/skill_stuck.html / Logs/Log49.txt: the same failure as
HTMLz/work_history_stuck.html, on the skills form instead of work experience.

do_skills() already had a guard: if fillByTestId() for the skill name field
returns None, back out via the modal's "back" button instead of saving a
blank skill. But fillByTestId() only ever returned None when the field could
not be FOUND -- when it was found but silently refused the typed text (the
read-back check already existed, but only logged a warning and returned the
element anyway), the guard never fired. do_skills() clicked Save with an
empty required Skill name field, Indeed blocked it, and the still-open,
still-empty "Add skill" form sat there hiding every later skill's own "Add
skill" button, exactly like the work-experience incident this guard was
supposed to prevent (Logs/Log49.txt line 8258 on: 30+ retries against a
button that could never appear because this same form was still open).

Two fixes, verified here:
1. fillByTestId() now returns None on a read-back mismatch too, so the
   existing "back out and skip this one skill" recovery actually fires for
   this failure mode instead of only the not-found one.
2. do_skills() now also checks _formStillOpen() after clicking Save, the
   same belt-and-suspenders check handleJob()/handleEdu() already had, in
   case Save is ever blocked for some other reason (e.g. a duplicate skill)
   even when the name field DID take correctly.
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


def build_helper(page, skills):
    located = main3.IndeedHelper.__new__(main3.IndeedHelper)
    main3.PlaywrightWrap.__init__(located, "", "", "user-data-dir=")
    located._page = page
    located._context = page.context
    located.outputFile = None
    located.skills = skills
    located.sectionAlreadyCorrect = lambda *a, **k: False
    located.clearSkills = lambda: None
    located._reopenSkillsPanel = lambda: False
    return located


# The exact bug: the field is found every time (never logged as missing),
# but an input handler wipes it back to empty right after -- the same shape
# as an Indeed autocomplete that resets on blur when nothing was picked from
# its listbox.
SELF_CLEARING_SKILL_PAGE = """
  <button aria-label="Add skill">Add skill</button>
  <input data-testid="skill-name-input-autocomplete-input"
         oninput="this.value=''">
  <button aria-label="Save this skill">Save</button>"""

# A skill name that takes normally, but Save is blocked for some unrelated
# reason (e.g. Indeed rejecting a duplicate) -- the form simply never closes.
SAVE_BLOCKED_SKILL_PAGE = """
  <button aria-label="Add skill">Add skill</button>
  <input data-testid="skill-name-input-autocomplete-input">
  <button aria-label="Save this skill">Save</button>"""

# A Save that genuinely works and removes the form.
SAVE_WORKS_SKILL_PAGE = """
  <button aria-label="Add skill">Add skill</button>
  <input data-testid="skill-name-input-autocomplete-input">
  <button aria-label="Save this skill"
          onclick="document.querySelector('[data-testid^=skill-name]').remove()">
    Save
  </button>"""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()

        print("--- a skill-name field that silently refuses the value is caught before Save ---")
        located = build_helper(page, ["Python"])
        clicked_modal_back = {"count": 0}
        page.set_content(SELF_CLEARING_SKILL_PAGE)
        page.wait_for_timeout(150)
        page.expose_function = None  # not used; placeholder to keep lints quiet

        # Wrap the real modal-back click target so we can tell whether the
        # graceful back-out path actually ran.
        page.evaluate("""() => {
            const btn = document.createElement('button');
            btn.setAttribute('data-testid', 'modal-back-button');
            btn.addEventListener('click', () => { window.__modalBackClicked = true; });
            document.body.appendChild(btn);
        }""")

        raised = None
        try:
            located.do_skills()
        except main3.NeedsHumanError:
            raised = True
        except Exception:                 # noqa: BLE001
            raised = "other"
        modal_back_clicked = page.evaluate("() => !!window.__modalBackClicked")
        check("do_skills() does not raise -- the pre-Save guard skips this skill instead",
              raised is None, f"raised={raised!r}")
        check("...and it actually took the graceful back-out path (clicked modal-back)",
              modal_back_clicked, "the field-not-accepted case never triggered the same "
              "recovery the not-found case gets")

        print()
        print("--- Save blocked for an unrelated reason is still caught (belt and suspenders) ---")
        located2 = build_helper(page, ["Python"])
        page.set_content(SAVE_BLOCKED_SKILL_PAGE)
        page.wait_for_timeout(150)
        raised2 = None
        try:
            located2.do_skills()
        except main3.NeedsHumanError:
            raised2 = True
        except Exception:                 # noqa: BLE001
            raised2 = "other"
        check("a Save click that does not remove the form raises NeedsHumanError",
              raised2 is True, f"raised={raised2!r}")

        print()
        print("--- a Save that genuinely works is not treated as stuck ---")
        located3 = build_helper(page, ["Python"])
        page.set_content(SAVE_WORKS_SKILL_PAGE)
        page.wait_for_timeout(150)
        raised3 = None
        try:
            located3.do_skills()
        except main3.NeedsHumanError:
            raised3 = True
        except Exception:                 # noqa: BLE001
            raised3 = "other"
        check("a Save that actually closes the form is NOT treated as stuck",
              raised3 is None, f"raised={raised3!r}")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL STUCK SKILL FILL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
