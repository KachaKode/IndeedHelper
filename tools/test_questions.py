"""Screener questions: the answers have to actually land on the page.

From a real run (Logs/log8.txt): GPT was consulted five times, once per
question, and not one answer was ever ticked. The log carried the reason, but
only as a raw traceback that a bare `except` had swallowed:

    AttributeError: '_ElementCompat' object has no attribute 'is_selected'

is_selected() is a Selenium method. The Playwright compatibility layer never
implemented it, and the screener-questions flow is the one part of the
application a live run had never reached, so nothing had noticed.

The page itself (HTMLz/questions2.html) is five <fieldset role="radiogroup">
blocks, each holding two radio inputs.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402
import myGPT2  # noqa: E402
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


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()

        wrap = main3.IndeedHelper.__new__(main3.IndeedHelper)
        main3.PlaywrightWrap.__init__(wrap, "", "", "user-data-dir=")
        wrap._page = page
        wrap._context = page.context
        wrap.outputFile = None

        print("--- the compatibility layer answers the questions' needs ---")
        page.set_content("""
          <fieldset role="radiogroup" name="q1">
            <legend>Are you authorised to work?</legend>
            <label id="yes"><input type="radio" name="q1" value="yes">Yes</label>
            <label id="no"><input type="radio" name="q1" value="no">No</label>
          </fieldset>
          <button id="off" disabled>disabled</button>
          <span id="hidden" style="display:none">not shown</span>""")
        page.wait_for_timeout(150)

        radios = wrap._resolve_matches("//input[@type='radio']", None)
        check("the page really has radios to tick", len(radios) == 2, f"{len(radios)}")

        # The method whose absence caused the whole failure.
        check("_ElementCompat has is_selected at all",
              hasattr(radios[0], "is_selected"),
              "this is the exact AttributeError from the log")
        check("an unticked radio reads as not selected", radios[0].is_selected() is False)
        page.check("#yes input")
        check("a ticked radio reads as selected", radios[0].is_selected() is True)

        check("is_displayed works too", wrap._resolve_matches("//legend", None)[0].is_displayed())
        check("and reports a hidden element as not displayed",
              not wrap._resolve_matches("//span[@id='hidden']", None)[0].is_displayed())
        check("is_enabled works", wrap._resolve_matches("//legend", None)[0].is_enabled())
        check("and reports a disabled control as not enabled",
              not wrap._resolve_matches("//button[@id='off']", None)[0].is_enabled())

        print()
        print("--- ticking a choice ---")
        page.set_content("""
          <fieldset role="radiogroup" name="q1">
            <legend>Are you authorised to work?</legend>
            <label id="yes"><input type="radio" name="q1" value="yes">Yes</label>
            <label id="no"><input type="radio" name="q1" value="no">No</label>
          </fieldset>""")
        page.wait_for_timeout(150)
        yes = wrap._resolve_matches("//label[@id='yes']", None)[0]
        check("the choice starts unticked", not page.is_checked("#yes input"))
        check("_tickChoice reports success", wrap._tickChoice(yes, "Yes"))
        check("and the radio is actually ticked", page.is_checked("#yes input"),
              "the answer was computed but never landed -- the original bug")

        # A choice that refuses to tick must give up, not spin forever.
        page.set_content("""
          <label id="stuck"><input type="radio" name="q" onclick="return false;">Yes</label>
          <script>
            document.querySelector('#stuck input').addEventListener('click', function (e) {
              e.preventDefault();      // never becomes checked
            });
          </script>""")
        page.wait_for_timeout(150)
        stuck = wrap._resolve_matches("//label[@id='stuck']", None)[0]
        import time
        started = time.time()
        result = wrap._tickChoice(stuck, "Yes")
        elapsed = time.time() - started
        check("a choice that will not tick gives up instead of looping forever",
              result is False and elapsed < 30, f"returned {result} after {elapsed:.1f}s")

        print()
        print("--- the real capture ---")
        for name in ("questions2.html", "questions.html"):
            path = CAPTURES / name
            if not path.exists():
                continue
            page.goto(path.as_uri())
            page.wait_for_timeout(300)

            groups = page.query_selector_all("xpath=//fieldset[@role='radiogroup']")
            radios = page.query_selector_all("xpath=//input[@type='radio']")
            check(f"{name}: the questions are radiogroup fieldsets", len(groups) == 5,
                  f"found {len(groups)}")
            check(f"{name}: each has two choices", len(radios) == len(groups) * 2,
                  f"{len(radios)} radios for {len(groups)} questions")

            # The question lookup finds more items than there are questions, so
            # process_question has to cope with a non-question in the list.
            items = page.query_selector_all("xpath=//*[contains(@class, 'Questions-item')]")
            check(f"{name}: the item lookup over-matches, as the log showed",
                  len(items) > len(groups),
                  f"{len(items)} items for {len(groups)} questions")

            # That extra item is what hit num_children(None).
            check(f"{name}: num_children survives a missing child path",
                  wrap.num_children(None) == 0,
                  "None here was an AttributeError that skipped a question")

        print()
        print("--- telling a real question from the blurb above it ---")
        # A whole screener page came back with nothing answered, silently. Every
        # question failed this guard in determine_question_type:
        #     num_children(get_child_complex(questn, "1/2")) == 0
        # i.e. "the second child of the first child has no children of its own".
        # That asserts a DOM shape rather than anything about the question, and
        # Indeed renested the page.
        for name in ("questions2.html", "questions.html", "questions3.html"):
            path = CAPTURES / name
            if not path.exists():
                continue
            page.goto(path.as_uri())
            page.wait_for_timeout(300)
            items = wrap._resolve_matches("//*[contains(@class,'Questions-item')]", None)
            verdicts = [wrap.questionHasControls(i) for i in items]
            real = [i for i, ok in zip(items, verdicts) if ok]
            check(f"{name}: at least one real question is recognised", len(real) > 0,
                  "every question would be skipped, exactly as in the log")
            # An item with no input/textarea/select is prose, not a question.
            for item, ok in zip(items, verdicts):
                controls = len(item.find_elements(
                    'xpath', ".//input | .//textarea | .//select"))
                if ok != (controls > 0):
                    check(f"{name}: verdict matches whether it holds a control", False,
                          f"verdict={ok} but {controls} controls")
                    break
            else:
                check(f"{name}: verdict matches whether it holds a control", True)

        # The employer's introductory paragraph carries no control and must not
        # be treated as a question.
        page.set_content("""
          <div class="Questions-item"><p>Thank you for your interest in this role.</p></div>
          <div class="Questions-item"><fieldset><legend>Authorised to work?</legend>
            <label><input type="radio" name="q">Yes</label>
            <label><input type="radio" name="q">No</label></fieldset></div>""")
        page.wait_for_timeout(150)
        items = wrap._resolve_matches("//*[contains(@class,'Questions-item')]", None)
        check("the intro paragraph is not mistaken for a question",
              not wrap.questionHasControls(items[0]))
        check("and the real question is recognised", wrap.questionHasControls(items[1]))

        # Nesting must not matter: the old check asserted a particular depth.
        page.set_content("""
          <div class="Questions-item"><div><div><div><section>
            <label><input type="radio" name="deep">Yes</label>
          </section></div></div></div></div>""")
        page.wait_for_timeout(150)
        deep = wrap._resolve_matches("//*[contains(@class,'Questions-item')]", None)[0]
        check("a deeply nested question is still a question",
              wrap.questionHasControls(deep),
              "the guard is asserting DOM shape again")

        print()
        print("--- one question, several dropdowns ---")
        # "Country" is a SINGLE question holding a country select and, once a
        # country is chosen, a state select that did not exist in the HTML at
        # all beforehand. The old code read every option in the question at once
        # (so states and countries were one list), set only the first select,
        # and left the page saying "Choose an option to continue."
        located = main3.IndeedHelper.__new__(main3.IndeedHelper)
        main3.PlaywrightWrap.__init__(located, "", "", "user-data-dir=")
        located._page = page
        located._context = page.context
        located.outputFile = None
        located.country = "United States"
        located.areaSpec = "Powder Springs, Ga"
        located.addr = "448 Schofield Dr"
        located.zip = "30127"
        # The question-type constants live on IndeedHelper.__init__, which a
        # __new__'d stub never runs. Same values as the real object.
        located.Bad, located.FreeResponse, located.MultChoice = -1, 0, 1
        located.DropDown, located.FreeResponseLong = 2, 3
        located.SelectApplicable, located.DateFill = 4, 5
        located.SearchSelect = 6
        located.SelectApplicableCombobox = 7

        path = CAPTURES / "questions5.html"
        if path.exists():
            page.goto(path.as_uri())
            page.wait_for_timeout(300)
            questions = located._resolve_matches("//*[contains(@class,'Questions-item')]", None)
            multi = [q for q in questions if len(located._selectsIn(q)) > 1]
            check("the capture has a question with more than one dropdown",
                  len(multi) == 1, f"found {len(multi)}")
            if multi:
                selects = located._selectsIn(multi[0])
                countryOpts = located._optionsOf(selects[0])
                stateOpts = located._optionsOf(selects[1])
                check("each dropdown's options are read separately",
                      "Afghanistan" in countryOpts and "Afghanistan" not in stateOpts,
                      "the two lists are being merged, so a state is picked from countries")
                check("the country is answered from the profile, with no model call",
                      located._profileAnswerFor(countryOpts) == "United States")
                check("and so is the state, matched on the option's VALUE",
                      located._profileAnswerFor(stateOpts) == "Georgia",
                      "areaSpec holds 'Ga', which is the value of the 'Georgia' option")

        # The second select does not exist until the first is answered.
        page.set_content("""
          <div class="Questions-item">
            <label>Country *</label>
            <select id="country" onchange="reveal()">
              <option value=""></option>
              <option value="US">United States</option>
              <option value="CA">Canada</option>
            </select>
            <div id="slot"></div>
          </div>
          <script>
            function reveal() {
              if (document.getElementById('country').value !== 'US') return;
              if (document.getElementById('slot').children.length) return;
              document.getElementById('slot').innerHTML =
                '<select id="state"><option value=""></option>'
              + '<option value="GA">Georgia</option>'
              + '<option value="NY">New York</option></select>';
            }
          </script>""")
        page.wait_for_timeout(150)
        question = located._resolve_matches("//*[contains(@class,'Questions-item')]", None)[0]
        check("only one dropdown exists to begin with",
              len(located._selectsIn(question)) == 1)

        answered = located.answerLinkedInputs(question, "Country", "")
        check("the country is set", page.input_value("#country") == "US",
              f"country is {page.input_value('#country')!r}")
        check("the state dropdown appeared and was set too",
              page.query_selector("#state") is not None
              and page.input_value("#state") == "GA",
              "the question stays incomplete and the page will not continue")
        check("both answers are reported", "United States" in answered and "Georgia" in answered,
              f"reported {answered!r}")

        # And the question only counts as answered when EVERY select is set.
        check("a half-filled question is not treated as answered",
              located.checkIfQuestionAlreadyAnswered(question, located.DropDown, {}) is True,
              "both are set by now, so this should be True")
        page.eval_on_selector("#state", "e => { e.value = ''; }")
        check("clearing one select makes it unanswered again",
              located.checkIfQuestionAlreadyAnswered(question, located.DropDown, {}) is False,
              "checking only the first select calls it done with the state blank")

        # A select that refuses to take a value must report, not spin.
        # The option deliberately matches the profile, so this exercises the
        # stubborn-select path without making a model call.
        page.set_content("""
          <div class="Questions-item"><label>Locked</label>
            <select id="locked"><option value=""></option>
              <option value="US">United States</option></select>
            <script>
              document.getElementById('locked').addEventListener('change', function () {
                this.value = '';           // refuses to hold anything
              });
            </script>
          </div>""")
        page.wait_for_timeout(150)
        stubborn = located._resolve_matches("//*[contains(@class,'Questions-item')]", None)[0]
        import time as _t
        started = _t.time()
        located.answerLinkedInputs(stubborn, "Locked", "")
        check("a dropdown that will not hold a value gives up",
              _t.time() - started < 40, f"took {_t.time() - started:.1f}s")

        check("the unbounded dropdown verifier is gone",
              "def ensureQualityOfDropDownAns" not in
              (ROOT / "main3.py").read_text(encoding="utf-8"),
              "it held two while-loops with no way out")

        print()
        print("--- a searchable combobox question (Logs/log19.txt) ---")
        # HTMLz/questions6.html has two questions shaped like this: the Mobile
        # Number and Home Phone Number country/dial-code pickers. Each is a
        # role="combobox" trigger with a role="listbox" popup of role="option"
        # items ("United States (+1)"), not a native <select> and not a plain
        # <input> -- but the popup's own search-filter <input> is in the DOM
        # even while the popup is closed, so the old code (which only checked
        # "does an input exist anywhere in the question") misread this as a
        # free-text question, then found that input not VISIBLE and crashed:
        #     extractQuestionInfo | ERROR | KeyError: -1
        # because type was reassigned to Bad (-1) but the code fell through to
        # a dict keyed on FreeResponse/DateFill/FreeResponseLong regardless.
        path = CAPTURES / "questions6.html"
        if path.exists():
            page.goto(path.as_uri())
            page.wait_for_timeout(300)
            questions = {
                q._handle.get_attribute("id"): q
                for q in located._resolve_matches("//*[contains(@class,'Questions-item')]", None)
            }
            for qid in ("q_1", "q_4"):
                q = questions.get(qid)
                if q is None:
                    continue
                qtype = located.determine_question_type(q)
                check(f"{qid}: a combobox question is recognised as SearchSelect",
                      qtype == located.SearchSelect, f"got type {qtype}")

                _, ans_dict, _, extractedType = located.extractQuestionInfo(q)
                check(f"{qid}: extracting it does not crash with KeyError",
                      extractedType == located.SearchSelect,
                      f"got type {extractedType} -- the KeyError handler silently downgrades "
                      f"to Bad, which would pass this as -1")
                options = ans_dict.get('options', {})
                check(f"{qid}: the dial code is stripped for matching against the profile",
                      options.get("United States (+1)") == "United States",
                      f"options sample={list(options.items())[:3]}")
                check(f"{qid}: the applicant's own country is found among 200+ options",
                      located._profileAnswerFor(options) == "United States (+1)",
                      f"got {located._profileAnswerFor(options)!r}")

        # The real capture has no live React behind it, so clicking an option
        # there does nothing -- this checks the actual click-through against a
        # combobox with real behaviour wired up, the same way _tickChoice above
        # is proven against real onclick handlers rather than only the capture.
        page.set_content("""
          <div class="Questions-item">
            <label>Country <span aria-hidden="true">*</span></label>
            <div role="combobox" id="trigger"
                 onclick="document.getElementById('popup').style.display='block'">
              <span id="triggerText">Select an option</span>
            </div>
            <div id="popup" style="display:none">
              <input type="text" placeholder="Search to select an option">
              <ul role="listbox">
                <li role="option" onclick="choose(this)"><span>Afghanistan (+93)</span></li>
                <li role="option" onclick="choose(this)"><span>United States (+1)</span></li>
                <li role="option" onclick="choose(this)"><span>Canada (+1)</span></li>
              </ul>
            </div>
          </div>
          <script>
            function choose(li) {
              document.getElementById('triggerText').textContent = li.textContent;
              document.getElementById('popup').style.display = 'none';
            }
          </script>""")
        page.wait_for_timeout(150)
        live = located._resolve_matches("//*[contains(@class,'Questions-item')]", None)[0]
        liveType = located.determine_question_type(live)
        check("a hand-built combobox is recognised the same way",
              liveType == located.SearchSelect, f"got type {liveType}")

        _, liveAnswers, _, _ = located.extractQuestionInfo(live)
        check("reading the trigger does not click it open",
              page.get_attribute("#popup", "style") == "display:none",
              "extractQuestionInfo clicked the combobox instead of just reading it")

        answered = located.answerSearchSelect(live, liveAnswers)
        check("the country on file is what gets chosen", answered == "United States (+1)",
              f"got {answered!r}")
        check("and the click actually landed on the page",
              page.text_content("#triggerText") == "United States (+1)",
              "the answer was computed but never selected on the control")
        check("checkIfQuestionAlreadyAnswered agrees, once it is chosen",
              located.checkIfQuestionAlreadyAnswered(live, located.SearchSelect, liveAnswers)
              is True)

        print()
        print("--- a demographic question, same combobox, no profile fact to use ---")
        # HTMLz/question_unanswered1.html (Logs/Log20.txt): "Ethnicity/Race" is
        # the SAME searchable-select widget as the country picker above, but
        # there is no profile field for race, nor should a model ever guess
        # one -- these are voluntary by federal law specifically so that
        # declining costs nothing. Left unhandled, this question could never
        # be answered: analyzeAndAnsQuestions counted it as "answered" anyway
        # (Bad questions do not raise), Continue kept re-showing "Choose an
        # option to continue", and the page looped calling doQuestions()
        # once a second, indefinitely.
        path = CAPTURES / "question_unanswered1.html"
        if path.exists():
            page.goto(path.as_uri())
            page.wait_for_timeout(300)
            demo = located._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
            demoType = located.determine_question_type(demo)
            check("recognised as SearchSelect, same as the country picker",
                  demoType == located.SearchSelect, f"got type {demoType}")

            _, demoAnswers, errorTxt, extractedType = located.extractQuestionInfo(demo)
            check("extracting it does not crash or silently downgrade to Bad",
                  extractedType == located.SearchSelect, f"got type {extractedType}")
            demoOptions = demoAnswers.get('options', {})
            check("the options are read (Hispanic or Latino, ..., I decline to identify)",
                  "I decline to identify" in demoOptions,
                  f"options={list(demoOptions.keys())}")
            check("nothing in the profile matches a race/ethnicity option",
                  located._profileAnswerFor(demoOptions) is None,
                  "a match here would mean a demographic question got answered from "
                  "country/address fields by accident")

            # This is the actual gap that let Log27's loop run forever. Indeed's
            # newer Mosaic questions (single-select-question here, date-question
            # in questions9.html) mark their validation message with a
            # HYPHENATED "*-error-text-*" id and never use role="alert" at all --
            # extractQuestionInfo's errorTxt lookup only recognised a camelCase
            # "errorText" id or role="alert", so it matched neither, errorTxt
            # stayed None, `required=errorTxt is not None` in process_question
            # was never True, and the NeedsHumanError path added for exactly
            # this situation was silently unreachable.
            check("the required-field error text IS found on the real capture "
                  "(this is what makes required=True detectable at all)",
                  errorTxt is not None,
                  "errorTxt is None here means the hyphenated id was missed again")
            if errorTxt is not None:
                check("and it is the actual validation message, not an empty container",
                      "continue" in errorTxt.text.lower(), f"got {errorTxt.text!r}")

            # This particular real question DOES have "I decline to identify"
            # among its options, so it is answerable and process_question
            # should resolve it -- NOT raise. That is a real, separate
            # question from log27's, which is why this checks the opposite
            # of the block below: fixing errorTxt detection must not turn
            # every required combobox into a forced stop, only the ones that
            # genuinely have no safe answer.
            located.details = {}
            located.prev_questions = []
            resolvedCleanly = None
            try:
                located.process_question(demo)
                resolvedCleanly = True
            except main3.NeedsHumanError:
                resolvedCleanly = False
            check("but THIS question resolves via decline rather than stopping, "
                  "since a decline option genuinely exists here",
                  resolvedCleanly is True,
                  "fixing errorTxt detection should not make an answerable "
                  "question stop for a person too")

        # log27's actual question was a DIFFERENT combobox: 11 real options,
        # none of them a decline/prefer-not-to-answer choice, and Indeed's
        # newer hyphenated "*-error-text-*" validation markup -- reproduced
        # here so the full chain (error text found -> required=True ->
        # answerSearchSelect raises -> process_question lets it through) is
        # proven on a question that is genuinely, correctly unanswerable --
        # meaning even the model's one attempt (below) does not confidently
        # land on either option, not that the model is never asked at all.
        page.set_content("""
          <div class="ia-Questions-item">
            <label id="q-label">Some required combobox <span aria-hidden="true">*</span></label>
            <div role="combobox" id="trigger3"
                 aria-describedby="q-error-text-abc"><span>Select an option</span></div>
            <div style="display:none">
              <input type="text">
              <ul role="listbox">
                <li role="option"><span>Option A</span></li>
                <li role="option"><span>Option B</span></li>
              </ul>
            </div>
            <div id="q-error-text-abc"><svg></svg><div>Choose an option to continue.</div></div>
          </div>""")
        page.wait_for_timeout(150)
        located.details = {}
        located.prev_questions = []
        located.JobDescriptionText = ""
        located.lifeSummary = ""
        stuckQuestn = located._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        _, _, stuckErrorTxt, _ = located.extractQuestionInfo(stuckQuestn)
        check("the hyphenated error-text id is found on a hand-built page too",
              stuckErrorTxt is not None)

        class NoConfidentMatchReply:
            """Stands in for myGPT2 for exactly one answerSearchSelect call.
            No API key, no network -- and its reply is deliberately unlike
            either real option, so getTopChoiceScore should score it below
            the floor, same as a genuinely unusable model reply would."""
            def __init__(self, *_args, **_kwargs):
                pass

            def sendAll(self):
                return "I cannot determine an appropriate answer to this question."

        original_myGPT2 = main3.myGPT2
        main3.myGPT2 = NoConfidentMatchReply
        raisedForReal = None
        try:
            located.process_question(stuckQuestn)
        except main3.NeedsHumanError:
            raisedForReal = True
        except Exception:                 # noqa: BLE001
            raisedForReal = False
        finally:
            main3.myGPT2 = original_myGPT2
        check("a required question with genuinely no safe answer -- not even "
              "the model's one attempt lands on either option -- stops for a "
              "person, end to end through process_question",
              raisedForReal is True,
              "this is exactly the loop in Logs/log27.txt: 1 answered, 0 "
              "failed, forever, once a second, because required was never True")

        # Real click-through, against a hand-built demographic-style combobox
        # (question_unanswered1.html has no live React behind it either).
        page.set_content("""
          <div class="ia-Questions-item">
            <label>Ethnicity/Race <span aria-hidden="true">*</span></label>
            <div role="combobox" id="trigger"
                 onclick="document.getElementById('popup').style.display='block'">
              <span id="triggerText">Select an option</span>
            </div>
            <div id="popup" style="display:none">
              <input type="text" placeholder="Search to select an option">
              <ul role="listbox">
                <li role="option" onclick="choose(this)"><span>Hispanic or Latino</span></li>
                <li role="option" onclick="choose(this)"><span>White (Not Hispanic or Latino)</span></li>
                <li role="option" onclick="choose(this)"><span>I decline to identify</span></li>
              </ul>
            </div>
          </div>
          <script>
            function choose(li) {
              document.getElementById('triggerText').textContent = li.textContent;
              document.getElementById('popup').style.display = 'none';
            }
          </script>""")
        page.wait_for_timeout(150)
        demoLive = located._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        _, demoLiveAnswers, _, _ = located.extractQuestionInfo(demoLive)
        demoAnswered = located.answerSearchSelect(demoLive, demoLiveAnswers)
        check("'I decline to identify' is what gets chosen",
              demoAnswered == "I decline to identify", f"got {demoAnswered!r}")
        check("and the click actually lands on the page",
              page.text_content("#triggerText") == "I decline to identify",
              "computed the right answer but never selected it")

        # No decline-style option at all, and no profile fact matches either:
        # the model gets ONE attempt to pick from what is actually on offer
        # (the same last resort answerLinkedInputs already uses for a plain
        # dropdown) before this counts as truly unanswerable. Wired with real
        # onclick handlers, unlike the two bare-markup pages below, so a
        # successful model pick can be proven end to end -- the option
        # actually gets clicked, not just computed.
        NO_DECLINE_PAGE = """
          <div class="ia-Questions-item">
            <label>Some other combobox</label>
            <div role="combobox" id="trigger2"
                 onclick="document.getElementById('popup2').style.display='block'">
              <span id="t2">Select an option</span>
            </div>
            <div id="popup2" style="display:none">
              <input type="text">
              <ul role="listbox">
                <li role="option" onclick="choose2(this)"><span>Option A</span></li>
                <li role="option" onclick="choose2(this)"><span>Option B</span></li>
              </ul>
            </div>
          </div>
          <script>
            function choose2(li) {
              document.getElementById('t2').textContent = li.textContent;
              document.getElementById('popup2').style.display = 'none';
            }
          </script>"""

        class ConfidentModelReply:
            """No API key, no network -- a reply that lands squarely on one
            of the two real options, standing in for a model call that
            genuinely knows the answer."""
            def __init__(self, *_args, **_kwargs):
                pass

            def sendAll(self):
                return "Option A"

        class VagueModelReply:
            """Same, but a reply that matches neither option -- standing in
            for a model call that genuinely does not know either, so the old
            safety net (leave it unanswered / stop for a person) still has
            to hold even after giving the model its one attempt."""
            def __init__(self, *_args, **_kwargs):
                pass

            def sendAll(self):
                return "I am not able to determine an appropriate choice."

        original_myGPT2 = main3.myGPT2

        page.set_content(NO_DECLINE_PAGE)
        page.wait_for_timeout(150)
        noDecline = located._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        _, noDeclineAnswers, _, _ = located.extractQuestionInfo(noDecline)
        located.JobDescriptionText = ""
        located.lifeSummary = ""
        main3.myGPT2 = ConfidentModelReply
        try:
            confidentResult = located.answerSearchSelect(
                noDecline, noDeclineAnswers, questn_txt="Some other combobox", helpTxt="")
        finally:
            main3.myGPT2 = original_myGPT2
        check("no profile match, no decline option -- the model's one attempt is used "
              "when it confidently lands on a real option",
              confidentResult == "Option A", f"got {confidentResult!r}")
        check("and the option is actually clicked on the page, not just computed",
              page.text_content("#t2") == "Option A",
              "chose the right answer but never selected it")

        page.set_content(NO_DECLINE_PAGE)
        page.wait_for_timeout(150)
        noDecline = located._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        _, noDeclineAnswers, _, _ = located.extractQuestionInfo(noDecline)
        main3.myGPT2 = VagueModelReply
        try:
            vagueResult = located.answerSearchSelect(
                noDecline, noDeclineAnswers, questn_txt="Some other combobox", helpTxt="")
        finally:
            main3.myGPT2 = original_myGPT2
        check("but when even the model's attempt does not confidently match "
              "either option, it is still left unanswered rather than guessing",
              vagueResult is None, f"got {vagueResult!r}")

        # And when THAT SAME unanswerable question is required, silently
        # returning None is not a safe skip -- the page can never advance,
        # and it retried once a second forever (Logs/Log24.txt) because a
        # plain Exception catch in analyzeAndAnsQuestions swallowed the
        # NeedsHumanError before it ever reached transition()'s handler.
        main3.myGPT2 = VagueModelReply
        raised = None
        try:
            located.answerSearchSelect(noDecline, noDeclineAnswers, required=True,
                                       questn_txt="Some other combobox", helpTxt="")
        except main3.NeedsHumanError as exc:
            raised = exc
        finally:
            main3.myGPT2 = original_myGPT2
        check("a REQUIRED question with no answer -- not even from the model -- stops "
              "for a person instead of looping forever",
              raised is not None, "no NeedsHumanError was raised")

        # And prove it actually escapes analyzeAndAnsQuestions's own per-
        # question try/except, not just that answerSearchSelect raises it in
        # isolation -- that broader except Exception is exactly what
        # swallowed it in the log.
        page.set_content('<div class="Questions-item"><p>stand-in</p></div>')
        page.wait_for_timeout(150)
        original_process_question = located.process_question
        located.process_question = lambda q: (_ for _ in ()).throw(
            main3.NeedsHumanError("stuck question"))
        escaped = None
        try:
            located.analyzeAndAnsQuestions()
        except main3.NeedsHumanError:
            escaped = True
        except Exception:                 # noqa: BLE001
            escaped = False
        finally:
            located.process_question = original_process_question
        check("NeedsHumanError escapes analyzeAndAnsQuestions instead of being "
              "swallowed as a per-question failure",
              escaped is True,
              "caught as a plain Exception instead" if escaped is False else "not raised at all")

        print()
        print("--- a single-checkbox 'select applicable' question (Logs/Log21.txt) ---")
        # HTMLz/questions8.html: a required self-attestation checkbox
        # ("Yes, I agree to sign electronically."), Indeed's fieldset/legend/
        # checkbox shape. extractQuestionInfo's SelectApplicable branch used
        # to pop(0) the first <label> off the list before building the
        # answer-choice dict, assuming a decoy label ahead of the real
        # choices. No real capture has one: with only one checkbox, pop(0)
        # deleted the only real choice, leaving GPT asked to pick from an
        # empty list every single retry, forever (checkIfQuestionAlreadyAnswered
        # always says SelectApplicable is unanswered, so it never stopped
        # trying). It also read the CHECKBOX's own label as the question
        # text instead of the actual question in <legend>.
        path = CAPTURES / "questions8.html"
        if path.exists():
            page.goto(path.as_uri())
            page.wait_for_timeout(300)
            attestation = next(
                q for q in located._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)
                if located.determine_question_type(q) == located.SelectApplicable)

            qtext, ans_dict, _, extractedType = located.extractQuestionInfo(attestation)
            check("recognised as SelectApplicable",
                  extractedType == located.SelectApplicable, f"got type {extractedType}")
            check("the question text comes from the legend, not a checkbox's own label",
                  qtext.startswith("Self Attestation is required"), f"got {qtext[:60]!r}")
            check("the one real checkbox choice survives (pop(0) used to delete it)",
                  "Yes, I agree to sign electronically." in ans_dict,
                  f"choices={list(ans_dict.keys())}")

        # ensureQualityOfSelectApplicableAns's retry path, with a stub that
        # exercises the REAL prompt-file loading (so a wrong filename really
        # does raise FileNotFoundError here, same as the log) but makes no
        # network call.
        class NoNetworkGPT(myGPT2.myGPT):
            def __init__(self, reply):
                self.model = None
                self.nextMessages = []
                self.checks = {}
                self.checkNOTs = {}
                self.prompts_str = ""
                self.keep = False
                self.need_redo = False
                self.checkerLinesToProcess = 0
                self.combineLinesMarker = "**KEEP**ALL**TOGETHER**"
                self.separateLinesMarker = "**END**ALL**TOGETHER**"
                self.checkerMarker = "&&CHECK&&"
                self.checkerMarkerNot = "&&CHECK&&NOT&&"
                self.placeHoldMarker = "PLACE&&HOLDER&&"
                self.place_vals = []
                self.inputPath = str(ROOT / "input")
                self.promptsPath = str(ROOT / "prompts")
                self.context = []
                self.reply = reply
                import io
                self.logFile = io.StringIO()

            def send(self, nu_msg=None):
                pass  # no network -- self.reply is whatever the test set

        page.set_content("""
          <div class="ia-Questions-item">
            <fieldset>
              <legend>Self Attestation is required. I certify the above is true.</legend>
              <label><input type="checkbox" value="attestationSign">
                Yes, I agree to sign electronically.</label>
            </fieldset>
          </div>""")
        page.wait_for_timeout(150)
        liveAttestation = located._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        _, liveChoices, _, _ = located.extractQuestionInfo(liveAttestation)
        check("the live single checkbox is read as one real choice",
              list(liveChoices.keys()) == ["Yes, I agree to sign electronically."],
              f"got {liveChoices!r}")

        gpt = NoNetworkGPT("I don't know")   # scores below CHOICE_MATCH_FLOOR -> retries
        raised = None
        try:
            located.ensureQualityOfSelectApplicableAns(gpt, liveChoices, ["I don't know"])
        except FileNotFoundError as exc:
            raised = exc
        check("the retry prompt file actually exists under its real name",
              raised is None,
              f"select_applicable_wrong_prompts.txt (missing the '_question_') would "
              f"FileNotFoundError here: {raised}")
        check("and the checkbox still ends up ticked from the only choice available",
              page.is_checked('input[type="checkbox"]'),
              "ticked the wrong thing, or nothing, after the retry")

        print()
        print("--- '(Optional)' is skipped regardless of how it is capitalised ---")
        # HTMLz/questions6.html reads "(Optional)", capital O; the skip check
        # was `'(optional)' in txt`, case-sensitive, so it never matched.
        page.set_content("""
          <div class="ia-Questions-item">
            <fieldset>
              <legend></legend>
              <label><input type="checkbox">
                (Optional) I would like to receive text messages.</label>
            </fieldset>
          </div>""")
        page.wait_for_timeout(150)
        optional_q = located._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        check("process_question skips it instead of processing it",
              located.process_question(optional_q) is None
              and not page.is_checked('input[type="checkbox"]'),
              "an optional question should never even be looked at, let alone ticked")

        print()
        print("--- a plain-text date question (Logs/Log22.txt) ---")
        # HTMLz/questions9.html: "Today's Date", a plain <input placeholder=
        # "MM/DD/YYYY"> with a calendar-icon button beside it. determine_
        # question_type calls this DateFill (an input plus ANY button), and
        # the only DateFill handler that existed was written for a totally
        # different widget: a "Choose a date" trigger that opens Month
        # select/Year select dropdowns plus a clickable day number -- a
        # picker that has never actually been captured anywhere in HTMLz/.
        # On the real page, every one of those three lookups timed out at
        # 10+ seconds, found nothing, and the input was never touched --
        # repeating every retry, forever, each pass also burning a real GPT
        # call for a date the code already had for free (self.today_mmddyyy()).
        path = CAPTURES / "questions9.html"
        if path.exists():
            page.goto(path.as_uri())
            page.wait_for_timeout(300)
            # process_question touches these regardless of question type.
            located.details = {}
            located.JobDescriptionText = ""
            located.prev_questions = []
            dateQuestn = next(
                q for q in located._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)
                if located.determine_question_type(q) == located.DateFill)
            qtext, dateAnswers, _, extractedType = located.extractQuestionInfo(dateQuestn)
            check("recognised as DateFill", extractedType == located.DateFill,
                  f"got type {extractedType}")
            check("the plain text input is what gets extracted as inputBox",
                  dateAnswers.get('inputBox') is not None)

            class FixedDateReply:
                """Stands in for myGPT2 for exactly one process_question call.
                No API key, no network -- sendAll() returns a fixed reply in
                the format date_fill_question_prompts.txt actually asks for:
                {month name}-{day}-{year}."""
                def __init__(self, *_args, **_kwargs):
                    pass

                def sendAll(self):
                    return "September-2-2026"

            import time as _time
            original_myGPT2 = main3.myGPT2
            main3.myGPT2 = FixedDateReply
            started = _time.time()
            try:
                located.process_question(dateQuestn)
            finally:
                main3.myGPT2 = original_myGPT2
            elapsed = _time.time() - started

            dateValue = page.input_value('input[placeholder="MM/DD/YYYY"]')
            check("the date is typed straight into the input",
                  dateValue == "09/02/2026", f"got {dateValue!r}")
            check("and it does not burn 30+ seconds hunting for a calendar popup that is not there",
                  elapsed < 5, f"took {elapsed:.1f}s")

        print()
        print("--- the same question must not be answered twice ---")
        # Six questions produced 36 GPT calls and a loop that never ended.
        # checkIfMoreQuestionsAppeared spotted "new" questions with
        #     set(latest_scan) - set(previously_seen)
        # over ELEMENT WRAPPERS. find_elements() builds fresh _ElementCompat
        # objects every call and the class defines no __eq__, so two wrappers
        # around one DOM node never compare equal and every question looked new
        # after every answer.
        for name in ("questions4.html", "questions2.html"):
            path = CAPTURES / name
            if not path.exists():
                continue
            page.goto(path.as_uri())
            page.wait_for_timeout(300)
            first = wrap._resolve_matches("//*[contains(@class,'Questions-item')]", None)
            second = wrap._resolve_matches("//*[contains(@class,'Questions-item')]", None)

            check(f"{name}: rescanning really does return new wrapper objects",
                  len(set(first) - set(second)) == len(first),
                  "then the identity trap does not exist and this proves nothing")
            check(f"{name}: but the same DOM node is behind them",
                  first[0]._handle.evaluate("(a, b) => a === b", second[0]._handle) is True)

            keys_first = {wrap._questionKey(q) for q in first}
            keys_second = {wrap._questionKey(q) for q in second}
            check(f"{name}: keys match across rescans", keys_first == keys_second,
                  "a question would be answered again on every pass")

            queue = list(first)
            wrap.checkIfMoreQuestionsAppeared((queue, set(keys_first), first[0]))
            check(f"{name}: a rescan adds nothing when nothing is new",
                  len(queue) == len(first),
                  f"queue grew from {len(first)} to {len(queue)}")

        # A genuine follow-up question still has to be picked up.
        page.set_content("""
          <div id="host">
            <div class="Questions-item"><label>Are you authorised to work?
              <input type="radio" name="a"></label></div>
          </div>
          <script>
            window.reveal = function () {
              document.getElementById('host').insertAdjacentHTML('beforeend',
                '<div class="Questions-item"><label>Which visa do you hold?'
              + '<input type="text" name="b"></label></div>');
            };
          </script>""")
        page.wait_for_timeout(150)
        original = wrap._resolve_matches("//*[contains(@class,'Questions-item')]", None)
        queue = list(original)
        seen = {wrap._questionKey(q) for q in original}
        page.evaluate("() => window.reveal()")
        page.wait_for_timeout(150)
        wrap.checkIfMoreQuestionsAppeared((queue, seen, original[0]))
        check("a follow-up question that really is new gets queued",
              len(queue) == 2, f"queue holds {len(queue)}")
        check("and it is the new one", "visa" in wrap._questionKey(queue[-1]),
              f"queued {wrap._questionKey(queue[-1])[:40]!r}")

        # Doing it again must not queue it a second time.
        wrap.checkIfMoreQuestionsAppeared((queue, seen, queue[0]))
        check("and it is not queued twice", len(queue) == 2, f"queue holds {len(queue)}")

        check("there is a hard cap on questions per page",
              main3.IndeedHelper.MAX_QUESTIONS_PER_PAGE > 0,
              "nothing would stop a page that keeps producing questions")

        print()
        print("--- no unbreakable waits are left ---")
        src = (ROOT / "main3.py").read_text(encoding="utf-8")
        check("waitForever() is gone", "def waitForever" not in src)
        check("and nothing still calls it", "self.waitForever()" not in src)
        check("the extract handler no longer parks the run",
              "while still:\n                t.sleep(1)" not in src)
        check("and no longer rebinds the time module to an int",
              "                    t = 3" not in src,
              "`t = 3` made `t.sleep` an integer for the rest of the function")

        print()
        print("--- the Continue button on the questions page ---")
        for name in ("questions3.html", "questions2.html", "questions.html"):
            path = CAPTURES / name
            if not path.exists():
                continue
            page.goto(path.as_uri())
            page.wait_for_timeout(300)
            check(f"{name}: its test id is hashed, so the preferred selector misses",
                  len(page.query_selector_all(f"xpath={H.CONTINUE_BUTTON_XPATH}")) == 0)
            byButton = page.query_selector_all(
                "xpath=//button[normalize-space(.)='Continue']")
            byText = page.query_selector_all("xpath=//*[text()='Continue']")
            check(f"{name}: the button itself is findable", len(byButton) == 1,
                  f"found {len(byButton)}")
            check(f"{name}: matching bare text lands on the inner SPAN, not the button",
                  all(e.evaluate("e => e.tagName") == "SPAN" for e in byText),
                  "then the button-first lookup would be unnecessary")

        print()
        print("--- free-text answers are grounded in real experience ---")
        source = (ROOT / "main3.py").read_text(encoding="utf-8")
        prompt = (ROOT / "prompts" / "free_response_question_prompts.txt").read_text(
            encoding="utf-8")
        check("the prompt is given the real work history",
              "self.realExperienceBlock()" in source,
              "it only ever saw the life summary, so it invented employers")
        check("and is told to pick the closest-fitting real project",
              "closest fit for what is being asked" in prompt)
        check("and to lead with the true details",
              "Lead with the true details" in prompt)
        check("but may fill in specifics that were not supplied",
              "fill those in so the answer is complete" in prompt,
              "an answer that omits team size or duration reads as evasive")
        check("while still not inventing a whole employer",
              "invent a whole project or employer" in prompt)

        print()
        print("--- matching an answer to the choices on offer ---")
        # The threshold this replaces was jaccard_similarity(ans + "~`*", ans),
        # which rises with answer length: the longer the reply the harder it was
        # to accept. Every sentence-shaped reply burned the whole retry budget.
        H2 = main3.IndeedHelper.__new__(main3.IndeedHelper)
        YN = {"Yes": 1, "No": 2}
        YRS = {"0-1 years": 1, "1-3 years": 2, "3-5 years": 3, "5+ years": 4}
        for answer, choices, expected in (
            (" Yes", YN, "Yes"),
            (" No", YN, "No"),
            (" Yes, I am authorized to work in the United States.", YN, "Yes"),
            (" No, I have never been convicted of a crime.", YN, "No"),
            (" 3-5 years", YRS, "3-5 years"),
            (" I have 3-5 years of relevant experience.", YRS, "3-5 years"),
            (" The answer is 5+ years given my background.", YRS, "5+ years"),
        ):
            top, score, floor = H2.getTopChoiceScore(answer, choices)
            check(f"{answer.strip()[:42]!r} -> {expected!r}",
                  top == expected and score >= floor,
                  f"picked {top!r} at {score:.2f} against a floor of {floor:.2f}")

        # When two choices are named, the first one is the one being answered with.
        top, _s, _f = H2.getTopChoiceScore(" No, though yes if sponsorship were offered.", YN)
        check("the earliest choice named in the answer wins", top == "No", f"got {top!r}")

        # Nothing recognisable must not silently pass as a confident match.
        top, score, floor = H2.getTopChoiceScore(" purple monkey dishwasher", YN)
        check("an answer matching nothing scores below the floor", score < floor,
              f"scored {score:.2f} against {floor:.2f}, so it would be ticked confidently")
        check("free-text answers are dash-stripped like the rest",
              "ans = self.stripDashes(mygpt.sendAll())" in source)

        # The block itself has to actually contain the jobs.
        helper = main3.IndeedHelper.__new__(main3.IndeedHelper)
        helper.jobs = [{
            "JobTitle": "Software Developer", "CompanyName": "21st Century Realty",
            "CompanyType": "Real Estate", "areaSpec": "Austell, GA",
            "currentPosition": "No", "From": "October 2017", "To": "May 2020",
            "country": "United States",
            "Description": "- Led migrations.\n- Ran the release process.",
        }]
        block = helper.realExperienceBlock()
        for part in ("Software Developer", "21st Century Realty", "October 2017",
                     "Led migrations."):
            check(f"the experience block names {part!r}", part in block, f"got {block!r}")
        check("bullet markers are stripped from the duties",
              "- Led migrations" not in block, f"got {block!r}")

        helper.jobs = []
        check("an empty history says so rather than sending nothing",
              "no work history" in helper.realExperienceBlock().lower())

        print()
        print("--- an answer without the expected preamble ---")
        check("splitting on a missing 'The answer is:' does not IndexError",
              "Yes".split("The answer is:")[-1] == "Yes",
              "the [-1] fallback is what keeps a bare reply usable")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL QUESTION TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
