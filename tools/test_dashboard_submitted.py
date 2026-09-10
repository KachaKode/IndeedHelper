"""Some applications land on Indeed's own dashboard
(https://u.indeed.com/o/dashboard?workflowExecutionId=...) instead of
smartapply's post-apply page after submitting, but it is the same
confirmation: "Your application has been submitted!". Before this, only the
smartapply page's title was recognised
(config/ExpectedEnvironments.txt: "((.*))|your application has been
submitted"), so landing on the dashboard version instead meant an
unrecognised environment -- handleUnknownEnvironment() pausing and asking a
person, or worse, whatever "default" rule an unrelated pattern happened to
match instead.

Matched on the URL rather than the title deliberately: the dashboard's own
title is not confirmed to say anything distinctive, but
workflowExecutionId=<id> ties this specific visit to the apply flow that
just finished, which is exactly the same completed-a-submission signal the
title-based rule was already using for the other page.
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

    print("--- the exact URL reported is recognised and logs the application ---")
    env = ("https://u.indeed.com/o/dashboard?workflowExecutionId="
           "a20325fe-04a9-3ce7-a798-eb6ce97a11be|Indeed")
    pattern = sm.envIsValid(env)
    check("the dashboard URL resolves to a known environment",
          pattern is not None, "handleUnknownEnvironment would pause and ask a person")
    rules = sm.transitions.get(pattern, {})
    check("and its default rule commits the application and moves on, "
          "the same as the smartapply post-apply confirmation",
          rules.get("default") == ("doDbThenbackToStart", "initNewApp"),
          f"got {rules.get('default')!r}")

    print()
    print("--- a DIFFERENT workflowExecutionId also matches (a real wildcard, "
          "not one ID hardcoded) ---")
    env2 = ("https://u.indeed.com/o/dashboard?workflowExecutionId="
           "11111111-2222-3333-4444-555555555555|Indeed")
    pattern2 = sm.envIsValid(env2)
    check("matches regardless of the specific id",
          pattern2 == pattern, f"got {pattern2!r}, expected {pattern!r}")

    print()
    print("--- the original smartapply confirmation page is unaffected ---")
    env3 = ("https://smartapply.indeed.com/beta/indeedapply/form/post-apply"
            "|Your application has been submitted | Indeed")
    pattern3 = sm.envIsValid(env3)
    rules3 = sm.transitions.get(pattern3, {})
    check("still resolves to its own rule, matching the same handler",
          rules3.get("default") == ("doDbThenbackToStart", "initNewApp"),
          f"got {rules3.get('default')!r}")
    check("as a genuinely distinct pattern from the dashboard one, not "
          "accidentally merged into it",
          pattern3 != pattern, "these should be two separate config lines")

    print()
    print("--- an unrelated dashboard visit (no workflowExecutionId) does not "
          "get mistaken for a completed submission ---")
    env4 = "https://u.indeed.com/o/dashboard|Indeed"
    pattern4 = sm.envIsValid(env4)
    rules4 = sm.transitions.get(pattern4, {}) if pattern4 else {}
    check("does not resolve to the same completed-submission rule",
          rules4.get("default") != ("doDbThenbackToStart", "initNewApp"),
          f"pattern={pattern4!r} default={rules4.get('default')!r}")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL DASHBOARD SUBMITTED TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
