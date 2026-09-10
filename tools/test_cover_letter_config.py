"""No submitted application has ever included a generated cover letter --
grep every Logs/*.txt ever captured and "Calling function: addDocs()" (the
function that actually fills in the cover letter text, main3.py's
addDocs() -> do_cover_letter()) appears ZERO times, in any of them.

Root cause, in config/StateTransitions.txt's "review the contents of this
job application" block:

    finishedEditSkills -- clickAddDocs() -- clickedAddDocs
    clickedAddDocs
    submittedApplication
    finishedAddingDocs -- submitApp() -- submittedApplication
    hitApply -- hitEditFromReviewPage() -- didContactInfo

load_transitions() (main3.py) treats a bare state name with no "--" as
PENDING: it inherits whatever the next "--" rule specifies. "clickedAddDocs"
and "submittedApplication" were BOTH left bare here, so both of them
inherited "finishedAddingDocs -- submitApp() -- submittedApplication" --
meaning reaching state clickedAddDocs on the review page called submitApp()
directly, skipping addDocs() (and therefore the cover letter) entirely. The
"Add documents" page's OWN block already had the correct, explicit
"clickedAddDocs -- addDocs() -- finishedAddingDocs" line -- but clickAddDocs()
almost never actually navigates there (its "Add supporting documents"
button is not present in the review page's real DOM in every capture
checked), so the review page's own (buggy) rule is what actually fired,
every time.

This is necessary but NOT sufficient on its own: clickAddDocs() still could
not find a real "Add supporting documents" control anywhere in
HTMLz/review_application.html's live DOM (only inside a read-only preview
iframe, which has no interactive controls at all) when this was written.
That is a separate, still-open question about where -- if anywhere --
Indeed currently offers a cover letter for these applications; this test
only pins the config authoring mistake, which was real and wrong regardless.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def build_state_machine():
    helper = main3.IndeedHelper.__new__(main3.IndeedHelper)
    helper.configPath = str(ROOT / "config") + "\\"
    sm = main3.StateMachine.__new__(main3.StateMachine)
    sm.helper = helper
    sm.expected_environments = sm.load_environments("ExpectedEnvironments.txt")
    sm.transitions = sm.load_transitions("StateTransitions.txt")
    return sm


def main() -> int:
    sm = build_state_machine()

    review_env = ("https://smartapply.indeed.com/beta/indeedapply/form/review-module"
                  "|Review the contents of this job application | Indeed")
    pattern = sm.envIsValid(review_env)
    check("the review page resolves to the 'review the contents...' rule block",
          pattern is not None and "review the contents" in pattern, f"got {pattern!r}")

    rules = sm.transitions.get(pattern, {})

    check("clickedAddDocs calls addDocs() on the review page, not submitApp()",
          rules.get("clickedAddDocs") == ("addDocs", "finishedAddingDocs"),
          f"got {rules.get('clickedAddDocs')!r} -- this is the exact bug: reaching "
          f"clickedAddDocs used to skip straight to submitApp(), and the cover "
          f"letter was never written")

    check("submittedApplication still self-loops through submitApp() as before "
          "-- confirms the fix did not disturb its own, correctly-bare pending state",
          rules.get("submittedApplication") == ("submitApp", "submittedApplication"),
          f"got {rules.get('submittedApplication')!r}")

    check("finishedAddingDocs -> submitApp() is unchanged",
          rules.get("finishedAddingDocs") == ("submitApp", "submittedApplication"),
          f"got {rules.get('finishedAddingDocs')!r}")

    print()
    print("--- the dedicated 'Add supporting documents' page still works as before ---")
    docs_env = ("https://smartapply.indeed.com/beta/indeedapply/form/documents"
                "|Add supporting documents | Indeed")
    docs_pattern = sm.envIsValid(docs_env)
    check("the dedicated Add-documents page resolves to its own rule block",
          docs_pattern is not None and "add" in docs_pattern.lower(), f"got {docs_pattern!r}")
    docs_rules = sm.transitions.get(docs_pattern, {})
    check("clickedAddDocs calls addDocs() there too, unaffected by this fix",
          docs_rules.get("clickedAddDocs") == ("addDocs", "finishedAddingDocs"),
          f"got {docs_rules.get('clickedAddDocs')!r}")
    check("passedQuestions also still calls addDocs() there, unaffected",
          docs_rules.get("passedQuestions") == ("addDocs", "finishedAddingDocs"),
          f"got {docs_rules.get('passedQuestions')!r}")

    print()
    print("--- before this fix, no submitted application ever actually called "
          "addDocs() -- a fixed, historical snapshot, not an ongoing invariant ---")
    # These are the logs that existed BEFORE config/StateTransitions.txt was
    # fixed -- grepped at the time this bug was diagnosed, every one of them
    # showing "Calling function: clickAddDocs()" followed by "no 'Add
    # supporting documents' control" and nothing else. Logs captured AFTER
    # the fix (Log34.txt, first) are expected -- and have been confirmed --
    # to show addDocs() actually running, so this list is intentionally not
    # a live glob over Logs/*.txt: a future log showing addDocs() is the
    # fix working, not a regression.
    PRE_FIX_LOGS = (
        "log6.txt", "Log23.txt", "Log24.txt", "Log25.txt", "Log28.txt",
        "Log30.txt", "Log31.txt", "Log32.txt", "Log33.txt",
    )
    logs_dir = ROOT / "Logs"
    ever_called = False
    checked = 0
    for name in PRE_FIX_LOGS:
        log_file = logs_dir / name
        if not log_file.exists():
            continue
        checked += 1
        text = log_file.read_text(encoding="utf-8", errors="replace")
        if "Calling function: addDocs()" in text:
            ever_called = True
            print(f"         found in {log_file.name}")
    check(f"confirms the historical symptom, across {checked} pre-fix log file(s): "
          f"addDocs() (the cover letter step) was never once reached before this fix",
          not ever_called and checked == len(PRE_FIX_LOGS),
          "either a pre-fix log now shows addDocs() running (this list should never "
          "change), or one of these files went missing")

    print()
    print("--- and a POST-fix log confirms addDocs() actually runs now ---")
    log34 = logs_dir / "Log34.txt"
    check("Log34.txt (captured after the fix) exists to check",
          log34.exists(), "expected this file to be present")
    if log34.exists():
        check("and it shows addDocs() actually being called",
              "Calling function: addDocs()" in log34.read_text(encoding="utf-8", errors="replace"))

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL COVER LETTER CONFIG TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
