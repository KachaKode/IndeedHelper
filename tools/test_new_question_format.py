"""Radio-card screener questions (HTMLz/questions_page_new_type.html).

Indeed started serving single-choice screener questions as a
<fieldset role="radiogroup"> of "radio cards" whose choices are whole sentences:

    Per client requirements, this role requires U.S. Citizenship. Are you
    currently a U.S. Citizen? *
        Yes, I am a U.S. Citizen  /  No, I am not a U.S. Citizen

    This position requires an active DoW Secret clearance or higher. Which best
    describes your current status? *
        Active Secret / Active Top Secret / Active Top Secret with SCI
        eligibility (TS/SCI) / Interim Secret or Top Secret / I do not currently
        have a clearance

The page structure needed no new handling -- it is the same fieldset/legend/
radio shape as questions2.html, so it already classifies as MultChoice. What the
sentence-style choices did expose was answer matching:

  * "Active Top Secret" is a prefix of "Active Top Secret with SCI eligibility
    (TS/SCI)". Both matched at position 0 and the tie was broken on the choice
    text, so a TS/SCI answer ticked plain Top Secret -- the wrong clearance.
  * A bare "Yes" scored 0.14 against "Yes, I am a U.S. Citizen", under the 0.30
    floor, so each such question spent all four GPT retries before ticking the
    right card by luck.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

CAPTURE = ROOT / "HTMLz" / "questions_page_new_type.html"
ITEMS = "//*[contains(@class,'ia-Questions-item')]"

CITIZEN = {"Yes, I am a U.S. Citizen": 1, "No, I am not a U.S. Citizen": 2}
CLEARANCE = {
    "Active Secret": 1,
    "Active Top Secret": 2,
    "Active Top Secret with SCI eligibility (TS/SCI)": 3,
    "Interim Secret or Top Secret": 4,
    "I do not currently have a clearance": 5,
}

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


class StubModel:
    """Stands in for myGPT2. No API key, no network; counts how often it is asked."""
    reply = ""
    calls = 0

    def __init__(self, *_args, **_kwargs):
        pass

    def sendAll(self):
        StubModel.calls += 1
        return StubModel.reply

    def sendFromFile(self, *_args, **_kwargs):
        StubModel.calls += 1
        return StubModel.reply


def build_helper(page):
    helper = main3.IndeedHelper.__new__(main3.IndeedHelper)
    main3.PlaywrightWrap.__init__(helper, "", "", "user-data-dir=")
    helper._page = page
    helper._context = page.context
    helper.outputFile = None
    # The question-type constants live on IndeedHelper.__init__, which a
    # __new__'d stub never runs. Same values as the real object.
    helper.Bad, helper.FreeResponse, helper.MultChoice = -1, 0, 1
    helper.DropDown, helper.FreeResponseLong = 2, 3
    helper.SelectApplicable, helper.DateFill = 4, 5
    helper.SearchSelect = 6
    helper.SelectApplicableCombobox = 7
    helper.details = {}
    helper.prev_questions = []
    helper.JobDescriptionText = ""
    helper.lifeSummary = ""
    # Side channels process_question reports to; nothing here is under test.
    helper.keywordInfoBlock = lambda: ""
    helper.recordUnvettedQuestion = lambda *a, **k: None
    helper.logKeywordEffect = lambda *a, **k: None
    helper._keywordLog = lambda: type("K", (), {"drop_pending": lambda self: None})()
    return helper


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        helper = build_helper(page)

        print("--- the radio-card capture is recognised as multiple choice ---")
        page.goto(CAPTURE.as_uri())
        page.wait_for_timeout(300)
        items = {q._handle.get_attribute("id"): q for q in helper._resolve_matches(ITEMS, None)}

        for qid, startsWith, choices in (
            ("q_0", "Per client requirements", list(CITIZEN)),
            ("q_1", "This position requires an active DoW Secret clearance", list(CLEARANCE)),
        ):
            question = items.get(qid)
            check(f"{qid}: present in the capture", question is not None)
            if question is None:
                continue
            check(f"{qid}: classified as MultChoice",
                  helper.determine_question_type(question) == helper.MultChoice)
            text, answers, _err, extractedType = helper.extractQuestionInfo(question)
            check(f"{qid}: extraction keeps the type", extractedType == helper.MultChoice,
                  f"got {extractedType}")
            check(f"{qid}: question text comes from the legend",
                  text.startswith(startsWith), f"got {text[:60]!r}")
            check(f"{qid}: every card is an answer choice, in order",
                  list(answers.keys()) == choices, f"got {list(answers.keys())}")
            check(f"{qid}: nothing is ticked yet, so it is not 'already answered'",
                  helper.checkIfQuestionAlreadyAnswered(question, extractedType, answers) is False)

        check("the prefilled text fields beside them stay free-response",
              helper.determine_question_type(items["q_2"]) == helper.FreeResponse
              and helper.determine_question_type(items["q_3"]) == helper.FreeResponse)

        print()
        print("--- a nested choice is not shadowed by its own prefix ---")
        for answer, choices, expected in (
            (" Active Top Secret with SCI eligibility (TS/SCI)", CLEARANCE,
             "Active Top Secret with SCI eligibility (TS/SCI)"),
            (" Active Top Secret", CLEARANCE, "Active Top Secret"),
            (" Active Secret", CLEARANCE, "Active Secret"),
            (" Interim Secret or Top Secret", CLEARANCE, "Interim Secret or Top Secret"),
            (" I do not currently have a clearance.", CLEARANCE,
             "I do not currently have a clearance"),
            # Same shape in any other question: the longer, more specific choice wins.
            (" Yes, with sponsorship", {"Yes": 1, "Yes, with sponsorship": 2},
             "Yes, with sponsorship"),
            (" Yes", {"Yes": 1, "Yes, with sponsorship": 2}, "Yes"),
        ):
            top, score, floor = helper.getTopChoiceScore(answer, choices)
            check(f"{answer.strip()!r} -> {expected!r}",
                  top == expected and score >= floor,
                  f"picked {top!r} at {score:.2f} against a floor of {floor:.2f}")

        # The existing rule must survive: when two DIFFERENT choices are named,
        # the one named first is the one being answered with.
        top, _s, _f = helper.getTopChoiceScore(" No, though yes if sponsored.", {"Yes": 1, "No": 2})
        check("the earliest choice named still wins", top == "No", f"got {top!r}")

        print()
        print("--- a bare yes/no matches the sentence-style choice it opens ---")
        for answer, expected in (
            (" Yes", "Yes, I am a U.S. Citizen"),
            (" yes.", "Yes, I am a U.S. Citizen"),
            (" No", "No, I am not a U.S. Citizen"),
        ):
            top, score, floor = helper.getTopChoiceScore(answer, CITIZEN)
            check(f"{answer.strip()!r} -> {expected!r} at or above the floor",
                  top == expected and score >= floor,
                  f"picked {top!r} at {score:.2f} against a floor of {floor:.2f}")

        # Ambiguity must not be claimed as a certain match: two choices open
        # with "Yes", so the opening word alone cannot say which was meant. A
        # certain match scores 1.0; this falls back to word overlap like before.
        _top, score, _floor = helper.getTopChoiceScore(
            " Yes", {"Yes, I am authorized": 1, "Yes, with sponsorship": 2, "No": 3})
        check("two choices opening with 'yes' are not claimed as a certain match",
              score < 1.0, f"scored {score:.2f}")

        # And a bare "Yes" must not be forced onto a choice that merely contains it.
        _top, score, floor = helper.getTopChoiceScore(
            " Yes", {"Maybe, yes if relocated": 1, "No": 2})
        check("'yes' in the middle of a choice is not an opening 'yes'",
              score < floor, f"scored {score:.2f}")

        print()
        print("--- end to end: the right card is ticked, with no wasted retries ---")
        main3.myGPT2 = StubModel

        def run(qid: str, reply: str):
            page.goto(CAPTURE.as_uri())
            page.wait_for_timeout(300)
            question = next(q for q in helper._resolve_matches(ITEMS, None)
                            if q._handle.get_attribute("id") == qid)
            StubModel.reply, StubModel.calls = reply, 0
            helper.prev_questions = []
            helper.process_question(question)
            ticked = page.evaluate(
                f"() => [...document.querySelectorAll('#{qid} input[type=radio]')]"
                ".filter(i => i.checked).map(i => i.closest('label').innerText.trim())")
            return ticked, StubModel.calls

        ticked, calls = run("q_0", "The answer is: Yes, I am a U.S. Citizen")
        check("citizenship: the full choice ticks the Yes card",
              ticked == ["Yes, I am a U.S. Citizen"], f"ticked {ticked}")

        ticked, calls = run("q_0", "The answer is: Yes")
        check("citizenship: a bare 'Yes' ticks the Yes card",
              ticked == ["Yes, I am a U.S. Citizen"], f"ticked {ticked}")
        check("and asks the model once, not once plus four retries", calls == 1,
              f"{calls} model calls")

        ticked, _ = run("q_1", "The answer is: I do not currently have a clearance")
        check("clearance: 'no clearance' ticks that card",
              ticked == ["I do not currently have a clearance"], f"ticked {ticked}")

        ticked, calls = run("q_1", "The answer is: Active Top Secret with SCI eligibility (TS/SCI)")
        check("clearance: TS/SCI ticks the TS/SCI card, not plain Top Secret",
              ticked == ["Active Top Secret with SCI eligibility (TS/SCI)"], f"ticked {ticked}")
        check("and in a single model call", calls == 1, f"{calls} model calls")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL NEW-QUESTION-FORMAT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
