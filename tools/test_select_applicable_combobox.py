"""A newer "select all that apply" question renders as a dropdown: a
role="combobox" trigger inside a <fieldset>/<legend> (the same wrapper shape
a plain radio/checkbox group uses), opening a role="dialog" popup of
role="menuitemcheckbox" <li>s -- ARIA custom controls, not real <input>
elements (HTMLz/questions_stuck.html).

determine_question_type() saw the <fieldset>, assumed that meant a plain
radio/checkbox group, and went looking for AN <input> inside the question to
tell which. The only <input> in this widget is the popup's own search-filter
box, which carries no type="..." attribute at all -- so
inputEle.get_attribute("type") came back None, and

    {"radio": self.MultChoice, "checkbox": self.SelectApplicable}[typeOfInput]

raised KeyError: None (Logs/Log35.txt) before this question's actual shape
was ever considered, once per rescan, every rescan, forever.

Fixed by checking for a role="combobox" inside the fieldset BEFORE assuming
radio/checkbox, giving this shape its own type (SelectApplicableCombobox)
and its own answering path (answerSelectApplicableCombobox), which reuses
the exact same model call and retry convention as the plain-checkbox
version of this question -- only how a chosen answer gets ticked differs,
since these items have no <input> to read is_selected() from at all.
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
    # The question-type constants live on IndeedHelper.__init__, which a
    # __new__'d stub never runs. Same values as the real object.
    located.Bad, located.FreeResponse, located.MultChoice = -1, 0, 1
    located.DropDown, located.FreeResponseLong = 2, 3
    located.SelectApplicable, located.DateFill = 4, 5
    located.SearchSelect = 6
    located.SelectApplicableCombobox = 7
    return located


# A live, wired-up reproduction of the real widget's shape: fieldset/legend,
# role="combobox" trigger, role="dialog" popup holding a search-filter
# <input> with NO type attribute (the actual cause of the KeyError) plus
# several role="menuitemcheckbox" options that toggle aria-checked on click.
COMBOBOX_PAGE = """
  <div class="ia-Questions-item">
    <fieldset>
      <legend>Which of the following have you used? <span aria-hidden="true">*</span></legend>
      <div role="combobox" id="trigger" aria-expanded="false"
           onclick="document.getElementById('popup').style.display='block'">
        <span>Select an option</span>
      </div>
      <div id="popup" role="dialog" style="display:none">
        <input placeholder="Search to select an option">
        <ul role="menu">
          <li role="menuitemcheckbox" aria-checked="false" onclick="toggle(this)"><span>PostgreSQL</span></li>
          <li role="menuitemcheckbox" aria-checked="false" onclick="toggle(this)"><span>MySQL</span></li>
          <li role="menuitemcheckbox" aria-checked="false" onclick="toggle(this)"><span>MongoDB</span></li>
        </ul>
      </div>
    </fieldset>
  </div>
  <script>
    function toggle(li) {
      li.setAttribute('aria-checked', li.getAttribute('aria-checked') === 'true' ? 'false' : 'true');
    }
  </script>"""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        located = build_helper(page)

        print("--- the real stuck capture is recognised, not a KeyError ---")
        page.goto((CAPTURES / "questions_stuck.html").as_uri())
        page.wait_for_timeout(300)
        questions = located._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)
        target = next((q for q in questions
                       if "select all that apply" in q.text.lower()), None)
        check("the real 'select all that apply' dropdown question is present in this capture",
              target is not None, "cannot test against it if it is not there")
        if target is not None:
            raised = None
            detected = None
            try:
                detected = located.determine_question_type(target)
            except Exception as exc:                 # noqa: BLE001
                raised = exc
            check("determine_question_type does not raise KeyError anymore",
                  raised is None, f"raised {raised!r}")
            check("and correctly identifies it as the new combobox type",
                  detected == located.SelectApplicableCombobox, f"got {detected!r}")

            _, extracted, _errorTxt, extractedType = located.extractQuestionInfo(target)
            check("extractQuestionInfo does not crash either",
                  extractedType == located.SelectApplicableCombobox, f"got {extractedType!r}")
            check("and reads the real options (PostgreSQL among them)",
                  "PostgreSQL" in (extracted.get("options") or {}),
                  f"options={list((extracted or {}).get('options', {}))!r}")

        print()
        print("--- a plain radio group is still detected correctly (unaffected) ---")
        page.set_content("""
          <div class="ia-Questions-item">
            <fieldset>
              <legend>Are you authorized to work in the US?</legend>
              <label><input type="radio" name="g" value="yes">Yes</label>
              <label><input type="radio" name="g" value="no">No</label>
            </fieldset>
          </div>""")
        page.wait_for_timeout(150)
        radioQuestn = located._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        check("a plain radio group is still MultChoice, not the new type",
              located.determine_question_type(radioQuestn) == located.MultChoice)

        print()
        print("--- a plain checkbox group is still detected correctly (unaffected) ---")
        page.set_content("""
          <div class="ia-Questions-item">
            <fieldset>
              <legend>Which shifts can you work?</legend>
              <label><input type="checkbox" value="am">Morning</label>
              <label><input type="checkbox" value="pm">Evening</label>
            </fieldset>
          </div>""")
        page.wait_for_timeout(150)
        checkboxQuestn = located._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        check("a plain checkbox group is still SelectApplicable, not the new type",
              located.determine_question_type(checkboxQuestn) == located.SelectApplicable)

        print()
        print("--- end to end: answerSelectApplicableCombobox actually ticks the "
              "model's chosen options ---")

        class PicksTwoOfThree:
            def __init__(self, *_args, **_kwargs):
                pass

            def sendAll(self):
                return "PostgreSQL\nMongoDB"

        located2 = build_helper(page)
        page.set_content(COMBOBOX_PAGE)
        page.wait_for_timeout(150)
        located2.details = {}
        located2.prev_questions = []
        located2.JobDescriptionText = ""
        questn2 = located2._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]

        original_myGPT2 = main3.myGPT2
        main3.myGPT2 = PicksTwoOfThree
        try:
            raised2 = None
            try:
                located2.process_question(questn2)
            except Exception as exc:                 # noqa: BLE001
                raised2 = exc
        finally:
            main3.myGPT2 = original_myGPT2

        check("process_question does not raise for this widget end to end",
              raised2 is None, f"raised {raised2!r}")

        def checked_state(label):
            return page.eval_on_selector(
                f"xpath=//li[.//span[text()='{label}']]", "el => el.getAttribute('aria-checked')")

        check("the model's first pick (PostgreSQL) got ticked",
              checked_state("PostgreSQL") == "true")
        check("the model's second pick (MongoDB) got ticked",
              checked_state("MongoDB") == "true")
        check("the option the model did NOT pick (MySQL) was left alone",
              checked_state("MySQL") == "false")

        print()
        print("--- required and no options at all stops for a person ---")
        located3 = build_helper(page)
        page.set_content("""
          <div class="ia-Questions-item">
            <fieldset>
              <legend>Which of the following have you used?</legend>
              <div role="combobox" id="trigger3"><span>Select an option</span></div>
            </fieldset>
          </div>""")
        page.wait_for_timeout(150)
        questn3 = located3._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        _, answers3, _e, _t = located3.extractQuestionInfo(questn3)
        raised3 = None
        try:
            located3.answerSelectApplicableCombobox(questn3, answers3, required=True)
        except main3.NeedsHumanError:
            raised3 = True
        except Exception:                 # noqa: BLE001
            raised3 = False
        check("a required question with no options to choose from stops for a person",
              raised3 is True, f"raised={raised3!r}")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL SELECT APPLICABLE COMBOBOX TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
