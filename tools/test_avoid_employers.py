"""avoidedEmployerReason() and its wiring into process_job_openings():
a company on the user's avoid-employers list should be skipped by plain
string comparison against self.companyName, with no AI call made for that
job at all -- unlike jobContainsForbiddenCharacteristics(), which needs one
model call per line of self.avoid.
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


def build_helper():
    return main3.IndeedHelper.__new__(main3.IndeedHelper)


def main() -> int:
    located = build_helper()

    print("--- avoidedEmployerReason ---")
    located.avoidEmployers = "Acme Corp\nBad Company LLC\n"

    r1 = located.avoidedEmployerReason("Acme Corp")
    check("an exact match returns a reason, not just True",
          r1 == 'employer "Acme Corp" is on the avoid-employers list', f"got {r1!r}")

    r2 = located.avoidedEmployerReason("acme corp")
    check("the match is case-insensitive", r2 is not None, f"got {r2!r}")

    r3 = located.avoidedEmployerReason("  Bad Company LLC  ")
    check("surrounding whitespace on the scraped name does not defeat the match",
          r3 is not None, f"got {r3!r}")

    r4 = located.avoidedEmployerReason("Some Other Employer")
    check("an employer not on the list is not flagged", r4 is None, f"got {r4!r}")

    located.avoidEmployers = ""
    r5 = located.avoidedEmployerReason("Acme Corp")
    check("an empty avoid list flags nothing", r5 is None, f"got {r5!r}")

    located.avoidEmployers = "Acme Corp\n"
    r6 = located.avoidedEmployerReason("")
    check("an empty company name is never treated as a match",
          r6 is None, f"got {r6!r}")

    print()
    print("--- the employer check runs before the AI characteristics check, "
          "and short-circuits the same way ---")
    src = (ROOT / "main3.py").read_text(encoding="utf-8")
    body = src[src.index("def process_job_openings("):src.index("\n    def ",
                                                                  src.index("def process_job_openings(") + 1)]
    employer_idx = body.find("employerReason = self.avoidedEmployerReason(self.companyName)")
    forbidden_idx = body.find("forbiddenReason = self.jobContainsForbiddenCharacteristics()")
    check("avoidedEmployerReason is called at all", employer_idx != -1)
    check("...and before jobContainsForbiddenCharacteristics, so a listed "
          "employer never reaches the AI call",
          -1 < employer_idx < forbidden_idx,
          f"employer_idx={employer_idx}, forbidden_idx={forbidden_idx}")
    check("a match is persisted via _recordSkippedJob, same as the AI-forbidden path",
          "_recordSkippedJob(jobId, employerReason)" in body)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL AVOID EMPLOYER TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
