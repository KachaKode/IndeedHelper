"""The bot's own trace was "just a soup of text" -- hundreds of same-weight
selector-probe lines with nothing marking where a new page or a new question
started, or what that question even was. ct_section() (main3.py) prints a
plain-text banner for both, and indents everything else under a question
until the next banner resets it. run.js's log box recognises the same
banner text and colors it; the auto-scroll fix that stopped resetting the
user's scroll position on every 3-second poll is a separate, DOM-only change
that this file does not re-test (there is no DOM here to test it against).

These tests pin:
  - ct_section()'s output shape, and that indentation is self-correcting
    (a question's indent never leaks into an unrelated later page).
  - that none of dbgui/runner.py's UserRun.note() state-parsing substrings
    are tripped by the new banner lines themselves.
  - end to end, that process_question() on a REAL captured question actually
    announces the question's real text before doing anything else with it.
  - that transition() calls the PAGE banner in the right place, source-order,
    the same way test_captcha_viewjob.py already pins process_job_openings.
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

CAPTURES = ROOT / "HTMLz"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def main() -> int:
    print("--- ct_section() prints a banner, and indentation self-corrects ---")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main3.ct_section("PAGE", "doQuestions()", "https://smartapply.indeed.com/x",
                          '"Answer screener questions | Indeed.com"')
        main3.ct_print("smartClick", "ENTER", "//fieldset")
        main3.ct_section("QUESTION", "Ethnicity/Race",
                          "type=searchable select, flagged required by Indeed", indent=1)
        main3.ct_print("smartClick", "ENTER", "//div[@role='combobox']")
        main3.ct_print("smartClick", "EXIT", "result=found")
        main3.ct_section("PAGE", "confirmTailoredResume()", "https://profile.indeed.com/y", '"Resume"')
        main3.ct_print("smartClick", "ENTER", "//button")
    out = buf.getvalue()
    lines = out.splitlines()

    check("the page banner names the function", any(">>> PAGE: doQuestions()" in l for l in lines))
    check("and carries the url as its own detail line",
          any("smartapply.indeed.com/x" in l for l in lines))
    check("and the page title too",
          any("Answer screener questions" in l for l in lines))
    check("the question banner names the real question text",
          any(">>> QUESTION: Ethnicity/Race" in l for l in lines))
    check("and says why it is flagged required",
          any("flagged required by Indeed" in l for l in lines))
    check("a divider rule is printed (some run of dashes)",
          any(l.strip().count("-") > 20 for l in lines))

    def indent_of(line: str) -> int:
        after_where = line.split("| ", 2)
        # "[CT]   12.3ms | <indent><where> | <what>" -- indent lives right
        # after the elapsed-time column.
        rest = line.split("ms | ", 1)[1] if "ms | " in line else ""
        return len(rest) - len(rest.lstrip(" "))

    smart_click_lines = [l for l in lines if "smartClick" in l and "ms |" in l]
    check("smartClick lines exist to check indentation on", len(smart_click_lines) >= 3)
    before_question = indent_of(smart_click_lines[0])
    inside_question = indent_of(smart_click_lines[1])
    after_next_page = indent_of(smart_click_lines[3]) if len(smart_click_lines) > 3 else None
    check("a line before any question banner is not indented", before_question == 0,
          f"got indent={before_question}")
    check("a line after the QUESTION banner IS indented, so it visually nests under it",
          inside_question == 2, f"got indent={inside_question}")
    check("a line after the NEXT page banner is back to unindented -- the question's "
          "indent does not leak into an unrelated later page",
          after_next_page == 0, f"got indent={after_next_page}")

    print()
    print("--- an indent left dangling by a question that never 'closes' still resets ---")
    # process_question can exit through many paths (return, raise, skip as
    # optional) and none of them explicitly restores indent -- ct_section's
    # own design is what has to make that safe, by resetting unconditionally
    # on the very next banner rather than relying on anyone popping a stack.
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        main3.ct_section("QUESTION", "Some question", indent=1)
        main3.ct_print("x", "ENTER")          # simulate the question exploding here
        main3.ct_section("PAGE", "nextFunc()", "u", "t")
        main3.ct_print("y", "ENTER")
    lines2 = buf2.getvalue().splitlines()
    last_line_indent = indent_of([l for l in lines2 if '"y"' not in l and "y |" in l][0])
    check("the very next page banner resets indent regardless of how the "
          "previous question exited", last_line_indent == 0, f"got indent={last_line_indent}")

    print()
    print("--- dbgui's UserRun.note() is not confused by the new banner lines ---")
    from dbgui import runner  # noqa: E402

    run = runner.UserRun.__new__(runner.UserRun)
    run._log_file = None
    run.lines = __import__("collections").deque(maxlen=200)
    run.state = "starting"
    run.last_error = None
    run.attention_reason = None
    run.last_activity = None

    # A genuine error line comes last, so any false-positive state change
    # from an earlier banner would already have shown up in `run.state`
    # before this point.
    for line in out.splitlines():
        run.note(line)
    check("banners alone do not flip state to error",
          run.state not in ("error", "attention"), f"state={run.state!r} after banners only")
    check("banners alone do not set an attention reason",
          run.attention_reason is None)

    real_error_line = "[CT]    2.0ms | reportAction | ERROR | Choose an option to continue."
    run.note(real_error_line)
    # ("| ERROR |" is main3's real marker; run.note() extracts the text after
    #  it. It only ends up in this exact spot because reportAction's ct_print
    #  call is `ct_print("reportAction", ...)`, so `what` here is what carries
    #  the error text in the wild -- this line is shaped to match that.)

    check("all lines, banners included, are kept for display",
          len(run.lines) == len(out.splitlines()) + 1, f"got {len(run.lines)} lines")

    print()
    print("--- process_question announces the REAL question, end to end ---")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()

        located = main3.IndeedHelper.__new__(main3.IndeedHelper)
        main3.PlaywrightWrap.__init__(located, "", "", "user-data-dir=")
        located._page = page
        located._context = page.context
        located.outputFile = None
        located.country = "United States"
        located.areaSpec = "Powder Springs, Ga"
        located.addr = "448 Schofield Dr"
        located.zip = "30127"
        located.Bad, located.FreeResponse, located.MultChoice = -1, 0, 1
        located.DropDown, located.FreeResponseLong = 2, 3
        located.SelectApplicable, located.DateFill = 4, 5
        located.SearchSelect = 6
        located.SelectApplicableCombobox = 7
        located.details = {}
        located.prev_questions = []

        path = CAPTURES / "question_unanswered1.html"
        if path.exists():
            page.goto(path.as_uri())
            page.wait_for_timeout(300)
            demo = located._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]

            buf3 = io.StringIO()
            with contextlib.redirect_stdout(buf3):
                try:
                    located.process_question(demo)
                except main3.NeedsHumanError:
                    pass
            out3 = buf3.getvalue()
            check("a QUESTION banner was printed at all", ">>> QUESTION:" in out3)
            check("carrying the real question's own text (Ethnicity/Race), not "
                  "just a generic 'processing a question' line",
                  "Ethnicity/Race" in out3, out3[:400])
            check("and it names the real widget type",
                  "searchable select" in out3)
        else:
            check("question_unanswered1.html capture is present", False,
                  "cannot run the end-to-end banner check without it")

        browser.close()

    print()
    print("--- transition() prints the PAGE banner right where the function call "
          "itself is decided, not buried somewhere later ---")
    src = (ROOT / "main3.py").read_text(encoding="utf-8")
    body = src[src.index("def transition("):src.index("\n    def ", src.index("def transition(") + 1)]
    calling_at = body.find('reportAction(f"Calling function:')
    section_at = body.find('ct_section("PAGE"')
    execute_at = body.find("self.executeFunc(funcName)")
    check("ct_section(\"PAGE\", ...) is called in transition()", section_at != -1)
    check("it comes after the function to call has been decided (reportAction line)",
          calling_at != -1 and section_at != -1 and calling_at < section_at,
          "otherwise funcName is not settled yet")
    check("and before the function actually runs",
          section_at != -1 and execute_at != -1 and section_at < execute_at,
          "a banner printed after the call already ran describes the wrong thing "
          "if executeFunc raises")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL LOG READABILITY TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
