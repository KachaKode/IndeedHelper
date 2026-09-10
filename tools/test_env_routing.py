"""Every page in the apply flow must route to the RIGHT config rule.

envIsValid resolves ties by "longest pattern wins", which makes the rules
sensitive to each other in a way that is easy to get wrong. This exists because
of a real regression: relaxing the resume rules to ignore page titles made the
bare ".../resume((.*))" pattern match ".../resume-selection" too. Being longer,
it outranked the resume-selection rule, so the bot ran startContactInfo() on the
resume selection page and spun there.

Add a case here whenever a new page joins the flow.
"""

from __future__ import annotations

import re
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


def load(name: str) -> list[str]:
    return [ln.strip() for ln in (ROOT / "config" / name).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("//")]


# (label, environment string, a snippet that must appear in the winning pattern)
CASES = [
    ("job search results",
     "https://www.indeed.com/jobs?q=Technical+Project+Manager&l=Remote|Technical Project Manager Jobs, Employment | Indeed.com",
     "jobs?q"),
    ("job description page",
     "https://www.indeed.com/viewjob?jk=abc123&from=serp|Technical Project Manager - AlphaRidge | Indeed.com",
     "viewjob"),
    ("resume SELECTION (add a resume)",
     "https://smartapply.indeed.com/beta/indeedapply/form/resume-selection-module/resume-selection|Upload or create a resume for this application | Indeed",
     "a resume for this application"),
    ("resume EDITOR",
     "https://profile.indeed.com/resume?co=US&hl=en_US|Profile - Indeed",
     "resume((([/?]"),
    ("contact sub-page",
     "https://profile.indeed.com/resume/contact|About you",
     "resume/contact"),
    ("summary sub-page",
     "https://profile.indeed.com/resume/summary|Summary",
     "resume/summary"),
    ("work experience sub-page",
     "https://profile.indeed.com/resume/experience/add|Add work experience",
     "resume/experience/add"),
    ("education sub-page",
     "https://profile.indeed.com/resume/education/add|Add education",
     "resume/education/add"),
    ("skills sub-page",
     "https://profile.indeed.com/resume/skills/add|Add skill",
     "resume/skills/add"),
    ("bot check",
     "https://www.indeed.com/jobs?q=x|Just a moment...",
     "jobs?q"),          # handled by the interstitial guard before matching
    # Indeed rebuilt the cover letter page and its heading now reads "Add
    # supporting documents". Both wordings must route to the same rule, because
    # only the heading was captured -- the tab title was not.
    ("documents page, old wording",
     "https://smartapply.indeed.com/beta/indeedapply/form/documents"
     "|Add documents to support this application",
     "supporting documents"),
    # The Indeed profile page, reached when the resume editor's back arrow is
    # used from a bare /resume URL. Its rule must NOT swallow the resume pages,
    # which live on the same host.
    ("profile home (outside the application)",
     "https://profile.indeed.com/|Profile - Resume - Indeed",
     "Profile((.*))Indeed"),
    ("the resume editor is still the resume editor",
     "https://profile.indeed.com/resume|Edit your resume",
     "resume((([/?]"),
    ("the resume editor with its continue parameter",
     "https://profile.indeed.com/resume?co=US&hl=en_US&continue=https%3A%2F%2Fsmartapply"
     ".indeed.com%2Fbeta%2Findeedapply%2Fform|Edit your resume",
     "resume((([/?]"),
    ("documents page, new wording",
     "https://smartapply.indeed.com/beta/indeedapply/form/documents"
     "|Add supporting documents | Indeed",
     "supporting documents"),
    # This route's title never updates at all -- confirmed live, Logs/Log23.txt:
    # the URL settled to /tailored-resume/resume?draft_id=... in ~2 seconds,
    # but the title stayed whatever the PREVIOUS real page loaded with. Using
    # a stale title here on purpose, rather than a title actually describing
    # this page, is the point of the test.
    ("tailored resume review (title never updates, stays stale)",
     "https://profile.indeed.com/tailored-resume/resume?draft_id=be79ee12-6f3e-4e5f-b546-"
     "c35bf355c280-Y21o&continue=https%3A%2F%2Fsmartapply.indeed.com|"
     "Upload or create a resume for this application | Indeed",
     "tailored-resume/resume"),
]


def main() -> int:
    helper = main3.PlaywrightWrap.__new__(main3.PlaywrightWrap)
    envs = load("ExpectedEnvironments.txt")
    transitions = load("StateTransitions.txt")

    def winner(patterns, env):
        for pattern in sorted(patterns, key=len, reverse=True):
            rx = main3.PlaywrightWrap.escape_regex_special_chars(helper, pattern)
            try:
                if re.match(rx.lower(), env.lower()):
                    return pattern
            except re.error:
                continue
        return None

    print("--- ExpectedEnvironments.txt ---")
    for label, env, expected in CASES:
        won = winner(envs, env) or ""
        check(f"{label} routes correctly", expected in won,
              f"expected a pattern containing {expected!r}, got {won!r}")

    print()
    print("--- StateTransitions.txt agrees ---")
    for label, env, expected in CASES:
        won = winner([p for p in transitions if "|" in p], env) or ""
        check(f"{label} has a transition rule", expected in won,
              f"expected {expected!r}, got {won!r}")

    print()
    print("--- the specific trap: resume vs resume-selection ---")
    selection = ("https://smartapply.indeed.com/beta/indeedapply/form/"
                 "resume-selection-module/resume-selection|Upload or create a resume")
    bare = [p for p in envs if p.endswith("resume((([/?].*)?))|((.*))")]
    check("the bare resume rule still exists", len(bare) == 1, f"found {len(bare)}")
    if bare:
        rx = main3.PlaywrightWrap.escape_regex_special_chars(helper, bare[0])
        check("the bare resume rule does NOT swallow resume-selection",
              not re.match(rx.lower(), selection.lower()),
              "it matches, so it will outrank the resume-selection rule again")

    print()
    print("--- the specific trap: tailored-resume vs a stale 'upload a resume' title ---")
    # ((.*))|Upload or (build|create) a resume for this application((.*)) matches
    # ANY url. If the tailored-resume rule were matched on title instead of URL
    # (what it used to be) or were not specific enough to outrank this one on
    # length, a page that never updates its title would get handed to
    # startResume() -- clicking a "select a resume" radio card that does not
    # exist on this page at all (Logs/Log23.txt).
    tailored = ("https://profile.indeed.com/tailored-resume/resume?draft_id=be79ee12-6f3e-4e5f-"
                "b546-c35bf355c280-Y21o|Upload or create a resume for this application | Indeed")
    won = winner(envs, tailored) or ""
    check("the tailored-resume rule wins even with the stale resume-upload title",
          "tailored-resume/resume" in won, f"got {won!r}")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL ENV ROUTING TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
