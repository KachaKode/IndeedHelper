"""A job already in skipped.txt was being re-skipped in total silence:
backToStart() and continue, nothing printed anywhere. In the log this looked
exactly like the bot randomly abandoning the tab right after a Cloudflare
challenge cleared (Logs/log29.txt) -- two jobs in a row hit this the instant
getPositionInfo() finished, and there was nothing in the trace, or anywhere
else, saying why: skipped.txt only ever stored "{company} {title}", never
the reason a job landed there in the first place.

jobContainsForbiddenCharacteristics() now returns the model's own reason
(or None) instead of a bare bool, process_job_openings persists it next to
the job id via _recordSkippedJob, and _lookupSkippedReason reads it back out
when the SAME job is recognized again later -- so a re-skip can say why,
and an entry written before this existed (this user's real skipped.txt has
39 of them) still degrades to a clear "no reason recorded" rather than
crashing or misreading the next job's id line as a reason.
"""

from __future__ import annotations

import sys
import tempfile
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
    located = main3.IndeedHelper.__new__(main3.IndeedHelper)
    return located


def main() -> int:
    located = build_helper()

    print("--- _lookupSkippedReason ---")
    OLD_FORMAT = "USTSOL Technical Project Manager\nServiceNow Implementation Manager - Moveworks\n"
    reason = located._lookupSkippedReason("USTSOL Technical Project Manager\n", OLD_FORMAT)
    check("an entry written before reasons were tracked degrades to a clear "
          "explanation, not a crash or the next job's id",
          reason == "no reason recorded (skipped before this was tracked)",
          f"got {reason!r}")

    NEW_FORMAT = (
        "USTSOL Technical Project Manager\n"
        "\treason: YES, this role requires working in the office.\n"
        "ServiceNow Implementation Manager - Moveworks\n"
        "\treason: YES, compensation is commission-only.\n"
    )
    r1 = located._lookupSkippedReason("USTSOL Technical Project Manager\n", NEW_FORMAT)
    check("the reason recorded for the FIRST job is read back correctly",
          r1 == "YES, this role requires working in the office.", f"got {r1!r}")
    r2 = located._lookupSkippedReason("ServiceNow Implementation Manager - Moveworks\n", NEW_FORMAT)
    check("and the SECOND job's reason is not mixed up with the first",
          r2 == "YES, compensation is commission-only.", f"got {r2!r}")

    missing = located._lookupSkippedReason("Some Other Company Some Other Title\n", NEW_FORMAT)
    check("a job id that is not actually in the file at all still returns "
          "something sane instead of raising",
          missing == "reason unavailable", f"got {missing!r}")

    print()
    print("--- _recordSkippedJob writes one line for the id, one for the reason ---")
    with tempfile.TemporaryDirectory() as tmp:
        located.MY_PATH = str(Path(tmp)) + "\\"
        (Path(tmp) / "skipped.txt").write_text("", encoding="utf-8")

        located._recordSkippedJob("Acme Corp Widget Engineer\n",
                                  "YES, this role is commission-only.\nSee paragraph 3.")
        written = (Path(tmp) / "skipped.txt").read_text(encoding="utf-8")
        check("the job id is written as its own line",
              "Acme Corp Widget Engineer" in written.splitlines(), f"got {written!r}")
        check("a multi-line model reply is collapsed onto ONE reason line, so it "
              "cannot be mistaken for a second job's id line",
              "\treason: YES, this role is commission-only. See paragraph 3." in written.splitlines(),
              f"got {written!r}")

        roundTrip = located._lookupSkippedReason("Acme Corp Widget Engineer\n", written)
        check("and it round-trips through _lookupSkippedReason intact",
              roundTrip == "YES, this role is commission-only. See paragraph 3.",
              f"got {roundTrip!r}")

    print()
    print("--- jobContainsForbiddenCharacteristics returns the reason, not just True ---")

    class YesOnSecondLine:
        """No API key, no network. The real function sends one prompt per
        line of self.avoid and stops at the first "yes" -- this mimics that
        by saying no to the first, yes (with an explanation) to the second."""
        def __init__(self, *_args, **_kwargs):
            self.calls = 0

        def sendAll(self):
            return None

        def send(self, _prompt):
            self.calls += 1
            if self.calls == 1:
                return "NO"
            return "YES, the job requires being in the office five days a week."

    located.avoid = "Is it fully remote?\nIs it in-office?"
    located.JobDescriptionText = "A job description."
    original_myGPT2 = main3.myGPT2
    main3.myGPT2 = YesOnSecondLine
    try:
        result = located.jobContainsForbiddenCharacteristics()
    finally:
        main3.myGPT2 = original_myGPT2
    check("a match returns the model's OWN explanation, not a bare True",
          result == "YES, the job requires being in the office five days a week.",
          f"got {result!r}")

    class AlwaysNo:
        def __init__(self, *_args, **_kwargs):
            pass

        def sendAll(self):
            return None

        def send(self, _prompt):
            return "NO"

    main3.myGPT2 = AlwaysNo
    try:
        clean = located.jobContainsForbiddenCharacteristics()
    finally:
        main3.myGPT2 = original_myGPT2
    check("a job matching nothing returns None, not False",
          clean is None, f"got {clean!r}")

    print()
    print("--- the re-skip path actually reports why, instead of staying silent ---")
    src = (ROOT / "main3.py").read_text(encoding="utf-8")
    body = src[src.index("def process_job_openings("):src.index("\n    def ",
                                                                  src.index("def process_job_openings(") + 1)]
    check("the already-skipped branch looks up a reason",
          "_lookupSkippedReason(jobId, skippedCont)" in body)
    check("and reports it, rather than silently calling backToStart()",
          'self.reportAction(\n                        f"Skipping [{jobId.strip()}]' in body
          or 'self.reportAction(\n                    f"Skipping [{jobId.strip()}]' in body
          or 'Skipping [{jobId.strip()}]' in body)
    check("a newly forbidden job's reason is persisted via _recordSkippedJob, "
          "not a bare f.write(jobId)",
          "_recordSkippedJob(jobId, forbiddenReason)" in body)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL SKIP REASON TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
