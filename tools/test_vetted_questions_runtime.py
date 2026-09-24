"""Vetted Questions, Level 1 and the merged Level 2/3 context -- runtime side.

Level 1 (tryVettedLevel1) has to intercept process_question BEFORE any GPT
call for a genuine hit, apply the stored answer with the exact same DOM
primitives the GPT path already uses, and cleanly fall through (never
partially apply, never raise) the moment even one item of a stored
choice-based answer is not among the CURRENT question's live options --
Indeed can offer a different set of choices for what is otherwise the same
question text across two different postings.

Level 2/3 no longer exist as separate calls (see the "Design correction:
Level 2" section of the Vetted Questions plan): every non-DateFill GPT call
site now gets the user's whole vetted corpus prepended ahead of
self.prev_questions (vettedContextForPrompt), so the model can reason from
vetted answers exactly as readily as it already reasons from this
application's own running history -- and degrades to byte-identical
Level-3 behaviour when nothing is vetted yet.

DateFill is entirely out of scope by explicit instruction (a stored date is
never correct on a later application, since the right answer is always
"today") -- never checked, never recorded.

IMPORTANT: process_question's real per-type branches now call
recordUnvettedQuestion, which writes to IndHelperDB.db. build_helper stubs
that out to an in-memory list on every helper this file creates, so nothing
here ever touches the real database, matching this codebase's existing
"never touches IndHelperDB.db" test convention even though this is a new
runtime code path that did not exist before.
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


def build_helper(page):
    located = main3.IndeedHelper.__new__(main3.IndeedHelper)
    main3.PlaywrightWrap.__init__(located, "", "", "user-data-dir=")
    located._page = page
    located._context = page.context
    located.outputFile = None
    # __new__ skips IndeedHelper.__init__, which is where these type
    # constants normally get set -- same values as the real object.
    located.Bad, located.FreeResponse, located.MultChoice = -1, 0, 1
    located.DropDown, located.FreeResponseLong = 2, 3
    located.SelectApplicable, located.DateFill = 4, 5
    located.SearchSelect, located.SelectApplicableCombobox = 6, 7

    located.details = {}
    located.prev_questions = []
    located.JobDescriptionText = ""
    located.vetted_questions = {}
    located.vetted_questions_list = []
    located.user_id = -1

    # Never let a test reach the real database: process_question's real
    # per-type branches call this on any answer that was NOT a Level-1 hit.
    located._recorded = []
    located.recordUnvettedQuestion = (
        lambda qtype, qtext, answer, answer_bank=None:
            located._recorded.append({"question_type": qtype, "question_text": qtext,
                                      "answer": answer, "answer_bank": answer_bank})
    )
    return located


class GPTMustNotBeCalled:
    """Constructing this at all fails the test -- used to prove a Level-1
    hit never reaches the LLM."""
    def __init__(self, *_args, **_kwargs):
        raise AssertionError("GPT must not be called on a Level-1 hit")


class ReturnsYes:
    calls = 0

    def __init__(self, *_args, **_kwargs):
        ReturnsYes.calls += 1

    def sendAll(self):
        return "The answer is: Yes"


class ReturnsPythonSql:
    calls = 0

    def __init__(self, *_args, **_kwargs):
        ReturnsPythonSql.calls += 1

    def sendAll(self):
        return "Python\nSQL"


def with_stub_gpt(stub_cls, fn):
    original = main3.myGPT2
    main3.myGPT2 = stub_cls
    try:
        return fn()
    finally:
        main3.myGPT2 = original


MULT_CHOICE_PAGE = """
  <div class="ia-Questions-item">
    <fieldset>
      <legend>Are you authorized to work in the US?</legend>
      <label><input type="radio" name="q1" value="yes">Yes</label>
      <label><input type="radio" name="q1" value="no">No</label>
    </fieldset>
  </div>"""

SELECT_APPLICABLE_PAGE = """
  <div class="ia-Questions-item">
    <fieldset>
      <legend>List your top skills</legend>
      <label><input type="checkbox" name="q1" value="python">Python</label>
      <label><input type="checkbox" name="q1" value="sql">SQL</label>
      <label><input type="checkbox" name="q1" value="java">Java</label>
    </fieldset>
  </div>"""

FREE_RESPONSE_PAGE = """
  <div class="ia-Questions-item">
    <label>What is your LinkedIn profile?<input type="text"></label>
  </div>"""

# Same shape test_select_applicable_combobox.py uses for the real widget:
# fieldset/legend, role="combobox" trigger, role="dialog" popup of
# role="menuitemcheckbox" items.
COMBOBOX_PAGE = """
  <div class="ia-Questions-item">
    <fieldset>
      <legend>Which of the following have you used?</legend>
      <div role="combobox" id="trigger" aria-expanded="false"
           onclick="document.getElementById('popup').style.display='block'">
        <span>Select an option</span>
      </div>
      <div id="popup" role="dialog" style="display:none">
        <input placeholder="Search to select an option">
        <ul role="menu">
          <li role="menuitemcheckbox" aria-checked="false"
              onclick="this.setAttribute('aria-checked', this.getAttribute('aria-checked')!=='true')">
            <span>PostgreSQL</span></li>
          <li role="menuitemcheckbox" aria-checked="false"
              onclick="this.setAttribute('aria-checked', this.getAttribute('aria-checked')!=='true')">
            <span>MongoDB</span></li>
          <li role="menuitemcheckbox" aria-checked="false"
              onclick="this.setAttribute('aria-checked', this.getAttribute('aria-checked')!=='true')">
            <span>MySQL</span></li>
        </ul>
      </div>
    </fieldset>
  </div>"""

SEARCH_SELECT_PAGE = """
  <div class="ia-Questions-item">
    <label for="trig">Country</label>
    <div role="combobox" id="trig">Select an option</div>
    <ul role="listbox">
      <li role="option" onclick="document.getElementById('trig').textContent=this.textContent">United States</li>
      <li role="option" onclick="document.getElementById('trig').textContent=this.textContent">Canada</li>
    </ul>
  </div>"""

DROPDOWN_ONE_SELECT_PAGE = """
  <div class="ia-Questions-item">
    <select>
      <option value="">Select an option</option>
      <option value="a">Option A</option>
      <option value="b">Option B</option>
    </select>
  </div>"""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()

        # ---------------------------------------------------------- MultChoice
        print("--- MultChoice: Level-1 hit answers with no GPT call ---")
        located = build_helper(page)
        page.set_content(MULT_CHOICE_PAGE)
        page.wait_for_timeout(150)
        qtext = "Are you authorized to work in the US?"
        located.vetted_questions[main3.normalize_question_text(qtext)] = {
            "question_type": "mult_choice", "question_text": qtext, "answer": "Yes",
        }
        questn = located._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]

        raised = None
        try:
            with_stub_gpt(GPTMustNotBeCalled, lambda: located.process_question(questn))
        except Exception as exc:  # noqa: BLE001
            raised = exc
        check("no exception, and no GPT call was attempted", raised is None, f"raised {raised!r}")
        yes_checked = page.eval_on_selector("input[value='yes']", "el => el.checked")
        check("the vetted answer (Yes) got ticked", yes_checked is True)
        check("recorded to prev_questions, not to the unvetted table (already vetted)",
              located.prev_questions == [{"Question": qtext, "Answer": "Yes"}]
              and located._recorded == [], f"prev_questions={located.prev_questions!r} recorded={located._recorded!r}")

        print()
        print("--- MultChoice: a vetted answer NOT among the live choices is a clean miss ---")
        located2 = build_helper(page)
        page.set_content(MULT_CHOICE_PAGE)
        page.wait_for_timeout(150)
        located2.vetted_questions[main3.normalize_question_text(qtext)] = {
            "question_type": "mult_choice", "question_text": qtext, "answer": "Maybe",
        }
        questn2 = located2._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]

        ReturnsYes.calls = 0
        raised2 = None
        try:
            with_stub_gpt(ReturnsYes, lambda: located2.process_question(questn2))
        except Exception as exc:  # noqa: BLE001
            raised2 = exc
        check("no exception on the fallback path", raised2 is None, f"raised {raised2!r}")
        check("a non-matching vetted answer falls through to the GPT call",
              ReturnsYes.calls == 1, f"calls={ReturnsYes.calls}")
        yes_checked2 = page.eval_on_selector("input[value='yes']", "el => el.checked")
        check("the GPT-decided answer still got ticked", yes_checked2 is True)
        check("the GPT-decided answer got recorded as a new unvetted row",
              len(located2._recorded) == 1 and located2._recorded[0]["answer"] == "Yes",
              f"recorded={located2._recorded!r}")

        # ------------------------------------------------------ SelectApplicable
        print()
        print("--- SelectApplicable: a multi-item Level-1 hit ticks every stored item ---")
        located3 = build_helper(page)
        page.set_content(SELECT_APPLICABLE_PAGE)
        page.wait_for_timeout(150)
        sa_qtext = "List your top skills"
        located3.vetted_questions[main3.normalize_question_text(sa_qtext)] = {
            "question_type": "select_applicable", "question_text": sa_qtext,
            "answer": ["Python", "SQL"],
        }
        questn3 = located3._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        raised3 = None
        try:
            with_stub_gpt(GPTMustNotBeCalled, lambda: located3.process_question(questn3))
        except Exception as exc:  # noqa: BLE001
            raised3 = exc
        check("no exception, no GPT call", raised3 is None, f"raised {raised3!r}")
        py_checked = page.eval_on_selector("input[value='python']", "el => el.checked")
        sql_checked = page.eval_on_selector("input[value='sql']", "el => el.checked")
        java_checked = page.eval_on_selector("input[value='java']", "el => el.checked")
        check("Python ticked", py_checked is True)
        check("SQL ticked", sql_checked is True)
        check("Java (not in the stored answer) left alone", java_checked is False)
        check("final_answer keeps the legacy stringified-list format",
              located3.prev_questions == [{"Question": sa_qtext, "Answer": "['Python', 'SQL']"}],
              f"got {located3.prev_questions!r}")

        print()
        print("--- SelectApplicable: ANY missing item makes the whole answer a miss ---")
        located4 = build_helper(page)
        page.set_content(SELECT_APPLICABLE_PAGE)
        page.wait_for_timeout(150)
        located4.vetted_questions[main3.normalize_question_text(sa_qtext)] = {
            "question_type": "select_applicable", "question_text": sa_qtext,
            "answer": ["Python", "Rust"],  # Rust is not offered on this page
        }
        questn4 = located4._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        ReturnsPythonSql.calls = 0
        raised4 = None
        try:
            with_stub_gpt(ReturnsPythonSql, lambda: located4.process_question(questn4))
        except Exception as exc:  # noqa: BLE001
            raised4 = exc
        check("no exception", raised4 is None, f"raised {raised4!r}")
        check("falls through to the GPT call rather than ticking a partial answer",
              ReturnsPythonSql.calls == 1, f"calls={ReturnsPythonSql.calls}")
        py_checked2 = page.eval_on_selector("input[value='python']", "el => el.checked")
        sql_checked2 = page.eval_on_selector("input[value='sql']", "el => el.checked")
        check("the GPT fallback answer (Python, SQL) got ticked instead",
              py_checked2 is True and sql_checked2 is True)

        # ---------------------------------------------------------- FreeResponse
        print()
        print("--- FreeResponse: Level-1 hit fills the input with no GPT call ---")
        located5 = build_helper(page)
        page.set_content(FREE_RESPONSE_PAGE)
        page.wait_for_timeout(150)
        fr_qtext = "What is your LinkedIn profile?"
        located5.vetted_questions[main3.normalize_question_text(fr_qtext)] = {
            "question_type": "free_response", "question_text": fr_qtext,
            "answer": "https://www.linkedin.com/in/example",
        }
        questn5 = located5._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        raised5 = None
        try:
            with_stub_gpt(GPTMustNotBeCalled, lambda: located5.process_question(questn5))
        except Exception as exc:  # noqa: BLE001
            raised5 = exc
        check("no exception, no GPT call", raised5 is None, f"raised {raised5!r}")
        value = page.eval_on_selector("input[type='text']", "el => el.value")
        check("the stored URL was filled in verbatim",
              value == "https://www.linkedin.com/in/example", f"got {value!r}")

        # ------------------------------------------------------- SelectApplicableCombobox
        print()
        print("--- SelectApplicableCombobox: tryVettedLevel1 direct hit and miss ---")
        located6 = build_helper(page)
        page.set_content(COMBOBOX_PAGE)
        page.wait_for_timeout(150)
        questn6 = located6._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        trigger = located6.findAndClick(located6.WHOLE, located6.WHOLE, "//*[@role='combobox']",
                                        findFrom=questn6, txtCond="*()")
        optionElements = located6.findAndClick(
            located6.WHOLE, located6.WHOLE, "//li[@role='menuitemcheckbox']",
            findFrom=questn6, indInList=located6.ALL)
        options = {(el.text or "").strip(): el for el in optionElements if (el.text or "").strip()}
        answer_choices6 = {"trigger": trigger, "options": options}

        located6.vetted_questions[main3.normalize_question_text("Which of the following have you used?")] = {
            "question_type": "select_applicable_combobox",
            "question_text": "Which of the following have you used?",
            "answer": ["PostgreSQL", "MongoDB"],
        }
        result6 = located6.tryVettedLevel1(questn6, "Which of the following have you used?",
                                           located6.SelectApplicableCombobox, answer_choices6)
        check("combobox Level-1 hit returns the comma-joined answer",
              result6 == "PostgreSQL, MongoDB", f"got {result6!r}")

        def combo_checked(label):
            return page.eval_on_selector(
                f"xpath=//li[.//span[text()='{label}']]", "el => el.getAttribute('aria-checked')")
        check("PostgreSQL actually ticked", combo_checked("PostgreSQL") == "true")
        check("MongoDB actually ticked", combo_checked("MongoDB") == "true")
        check("MySQL (not in the stored answer) left alone", combo_checked("MySQL") == "false")

        page.set_content(COMBOBOX_PAGE)
        page.wait_for_timeout(150)
        located7 = build_helper(page)
        questn7 = located7._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        trigger7 = located7.findAndClick(located7.WHOLE, located7.WHOLE, "//*[@role='combobox']",
                                         findFrom=questn7, txtCond="*()")
        optionElements7 = located7.findAndClick(
            located7.WHOLE, located7.WHOLE, "//li[@role='menuitemcheckbox']",
            findFrom=questn7, indInList=located7.ALL)
        options7 = {(el.text or "").strip(): el for el in optionElements7 if (el.text or "").strip()}
        located7.vetted_questions[main3.normalize_question_text("Which of the following have you used?")] = {
            "question_type": "select_applicable_combobox",
            "question_text": "Which of the following have you used?",
            "answer": ["PostgreSQL", "Redis"],  # Redis is not offered here
        }
        result7 = located7.tryVettedLevel1(questn7, "Which of the following have you used?",
                                           located7.SelectApplicableCombobox,
                                           {"trigger": trigger7, "options": options7})
        check("a partially-unavailable combobox answer is a clean miss, not a partial tick",
              result7 is None, f"got {result7!r}")

        # ------------------------------------------------------------- SearchSelect
        print()
        print("--- SearchSelect: tryVettedLevel1 direct hit and miss ---")
        located8 = build_helper(page)
        page.set_content(SEARCH_SELECT_PAGE)
        page.wait_for_timeout(150)
        questn8 = located8._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        trigger8 = located8.findAndClick(located8.WHOLE, located8.WHOLE, "//*[@role='combobox']",
                                         findFrom=questn8, txtCond="*()")
        optionElements8 = located8.findAndClick(located8.WHOLE, located8.WHOLE, "//li[@role='option']",
                                                findFrom=questn8, indInList=located8.ALL)
        options8 = {(el.text or "").strip(): (el.text or "").strip() for el in optionElements8}
        located8.vetted_questions[main3.normalize_question_text("Country")] = {
            "question_type": "search_select", "question_text": "Country", "answer": "Canada",
        }
        result8 = located8.tryVettedLevel1(questn8, "Country", located8.SearchSelect,
                                           {"trigger": trigger8, "options": options8})
        check("search-select Level-1 hit returns the chosen label", result8 == "Canada", f"got {result8!r}")
        trigger_text = page.eval_on_selector("#trig", "el => el.textContent")
        check("the trigger no longer reads the placeholder",
              "select an option" not in trigger_text.lower(), f"got {trigger_text!r}")

        page.set_content(SEARCH_SELECT_PAGE)
        page.wait_for_timeout(150)
        located9 = build_helper(page)
        questn9 = located9._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        trigger9 = located9.findAndClick(located9.WHOLE, located9.WHOLE, "//*[@role='combobox']",
                                         findFrom=questn9, txtCond="*()")
        optionElements9 = located9.findAndClick(located9.WHOLE, located9.WHOLE, "//li[@role='option']",
                                                findFrom=questn9, indInList=located9.ALL)
        options9 = {(el.text or "").strip(): (el.text or "").strip() for el in optionElements9}
        located9.vetted_questions[main3.normalize_question_text("Country")] = {
            "question_type": "search_select", "question_text": "Country", "answer": "Mexico",
        }
        result9 = located9.tryVettedLevel1(questn9, "Country", located9.SearchSelect,
                                           {"trigger": trigger9, "options": options9})
        check("a vetted answer not on offer is a clean miss", result9 is None, f"got {result9!r}")

        # ----------------------------------------------------------------- DropDown
        print()
        print("--- DropDown: tryVettedLevel1 direct hit and count-mismatch miss ---")
        located10 = build_helper(page)
        page.set_content(DROPDOWN_ONE_SELECT_PAGE)
        page.wait_for_timeout(150)
        questn10 = located10._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        located10.vetted_questions[main3.normalize_question_text("Pick one")] = {
            "question_type": "drop_down", "question_text": "Pick one", "answer": ["Option B"],
        }
        result10 = located10.tryVettedLevel1(questn10, "Pick one", located10.DropDown, {})
        check("a single-select Level-1 hit returns the chosen option", result10 == "Option B",
              f"got {result10!r}")
        selected_text = page.eval_on_selector(
            "select", "el => el.selectedOptions.length ? el.selectedOptions[0].text : ''")
        check("the <select> was actually set to it", selected_text == "Option B", f"got {selected_text!r}")

        page.set_content(DROPDOWN_ONE_SELECT_PAGE)
        page.wait_for_timeout(150)
        located11 = build_helper(page)
        questn11 = located11._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        located11.vetted_questions[main3.normalize_question_text("Pick one")] = {
            # Two stored items against a question that only has ONE live
            # select -- a structurally different question, must miss.
            "question_type": "drop_down", "question_text": "Pick one",
            "answer": ["Option A", "Option B"],
        }
        result11 = located11.tryVettedLevel1(questn11, "Pick one", located11.DropDown, {})
        check("a stored-answer/live-select count mismatch is a clean miss", result11 is None,
              f"got {result11!r}")
        selected_text2 = page.eval_on_selector(
            "select", "el => el.selectedOptions.length ? el.selectedOptions[0].text : ''")
        check("and nothing was selected as a side effect",
              selected_text2 in ("", "Select an option"), f"got {selected_text2!r}")

        browser.close()

    # -------------------------------------------------- merged context (pure)
    print()
    print("--- vettedContextForPrompt: merges the vetted corpus ahead of prev_questions ---")
    bare = main3.IndeedHelper.__new__(main3.IndeedHelper)
    bare.prev_questions = [{"Question": "Q-live", "Answer": "A-live"}]
    bare.vetted_questions_list = []
    check("degrades to exactly prev_questions when nothing is vetted yet",
          bare.vettedContextForPrompt() == bare.prev_questions,
          f"got {bare.vettedContextForPrompt()!r}")

    bare.vetted_questions_list = [
        {"question_type": "free_response", "question_text": "Q-vetted", "answer": "A-vetted"},
        {"question_type": "select_applicable", "question_text": "Q-list", "answer": ["X", "Y"]},
        {"question_type": "drop_down", "question_text": "Q-dd", "answer": ["Georgia", "USA"]},
    ]
    merged = bare.vettedContextForPrompt()
    check("vetted rows come first, in order, followed by prev_questions",
          merged == [
              {"Question": "Q-vetted", "Answer": "A-vetted"},
              {"Question": "Q-list", "Answer": "['X', 'Y']"},
              {"Question": "Q-dd", "Answer": "Georgia, USA"},
              {"Question": "Q-live", "Answer": "A-live"},
          ], f"got {merged!r}")

    # ------------------------------------------------------- DateFill guard
    print()
    print("--- DateFill: never checked, never recorded, unchanged prompt context ---")
    guard = main3.IndeedHelper.__new__(main3.IndeedHelper)
    guard.DateFill = 5
    guard.vetted_questions = {
        # Even a colliding entry under the exact right key must not matter.
        main3.normalize_question_text("Today's Date"): {
            "question_type": "free_response", "question_text": "Today's Date", "answer": "should never be used",
        },
    }
    check("tryVettedLevel1 returns None immediately for DateFill regardless of vetted_questions content",
          guard.tryVettedLevel1(None, "Today's Date", guard.DateFill, {}) is None)

    src = (ROOT / "main3.py").read_text(encoding="utf-8")
    date_fill_line = next(
        (line for line in src.splitlines() if 'myGPT2("date_fill_question_prompts.txt"' in line), None)
    check("DateFill's own GPT call site was left untouched (still plain prev_questions)",
          date_fill_line is not None and "str(self.prev_questions)" in date_fill_line
          and "vettedContextForPrompt" not in date_fill_line,
          f"line={date_fill_line!r}")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL VETTED QUESTIONS RUNTIME TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
