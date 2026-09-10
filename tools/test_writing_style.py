"""The generated prose has to sound like the applicant, not like a model.

Three separate things are checked here:

  1. no em dash or en dash survives into anything the bot writes -- asking the
     model nicely is not enough, so it is enforced on the way out too
  2. the writing sample and the life details actually reach the prompts
  3. the placeholder counts in the prompt files still match the arguments
     passed to them. myGPT2 fills placeholders by popping them off the front in
     file order, so one extra PLACE&&HOLDER&& silently shifts every value after
     it into the wrong slot.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402

failures: list[str] = []
H = main3.IndeedHelper
PROMPTS = ROOT / "prompts"
MARKER = "PLACE&&HOLDER&&"


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def effective_placeholders(path: Path) -> int:
    """Count placeholders the way myGPT2 consumes them: comment lines and the
    two lines following a &&CHECK&& are skipped before substitution."""
    total, checker_skip = 0, 0
    keep = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line and not keep:
            continue
        if checker_skip > 0:
            checker_skip -= 1
            continue
        if line[:2] == "//":
            continue
        total += line.count(MARKER)
        if "**KEEP**ALL**TOGETHER**" in line:
            keep = True
        if "**END**ALL**TOGETHER**" in line:
            keep = False
        if "&&CHECK&&" in line:
            checker_skip = 2
    return total


def helper_with(sample: str = "", life: str = "") -> main3.IndeedHelper:
    wrap = main3.IndeedHelper.__new__(main3.IndeedHelper)
    wrap.writingSample = sample
    wrap.lifeSummary = life
    return wrap


def main() -> int:
    print("--- em dashes never reach the page ---")
    cases = [
        ("I built a scraper — it saved hours.", "I built a scraper, it saved hours."),
        ("Three roles—all remote—since 2019.", "Three roles, all remote, since 2019."),
        ("I led the team – and shipped it.", "I led the team, and shipped it."),
    ]
    for raw, expected in cases:
        got = H.stripDashes(raw)
        check(f"{raw[:34]!r} is cleaned", got == expected, f"got {got!r}")

    check("a date range keeps a hyphen rather than gaining a comma",
          H.stripDashes("2019 — 2025") == "2019-2025",
          f"got {H.stripDashes('2019 - 2025')!r}")
    check("no dash survives a long passage",
          "—" not in H.stripDashes("a—b—c—d") and "–" not in H.stripDashes("a–b–c"))
    check("text without dashes is left alone",
          H.stripDashes("Nothing to do here.") == "Nothing to do here.")
    check("empty input is handled", H.stripDashes("") == "" and H.stripDashes(None) is None)
    check("a dash before punctuation does not leave a stray comma",
          H.stripDashes("I did the work — .").endswith("."),
          f"got {H.stripDashes('I did the work — .')!r}")

    print()
    print("--- the style guide says the things that matter ---")
    guide = helper_with().styleGuide()
    check("it forbids em dashes explicitly", "em dash" in guide.lower())
    check("it names the AI tells rather than just saying 'sound natural'",
          "proven track record" in guide and "passionate about" in guide)
    check("it asks for specifics", "specific" in guide.lower())
    check("with no sample it still gives a tone instruction",
          "no writing sample was provided" in guide.lower())
    check("and it never contains an em dash itself",
          "—" not in guide and "–" not in guide,
          "the instruction would be demonstrating the thing it forbids")

    sample = "I don't do buzzwords. I built the thing, it worked, here's what broke."
    guided = helper_with(sample=sample).styleGuide()
    check("a supplied sample is included verbatim", sample in guided)
    check("and it is marked off so the model does not copy its content",
          "BEGIN WRITING SAMPLE" in guided and "END WRITING SAMPLE" in guided)
    check("the model is told to imitate the voice, not the content",
          "do not copy its content" in guided.lower())

    print()
    print("--- prompt placeholders still match their call sites ---")
    source = (ROOT / "main3.py").read_text(encoding="utf-8")
    expected_counts = {
        # prompt file: how many values main3 passes to it
        "cover_letter_prompts2.txt": 13,
        "summary_prompts2.txt": 3,
        "job_desc_prompts2.txt": 8,
        "headline_prompts2.txt": 1,
        "skills_prompts2.txt": 3,
    }
    for name, expected in expected_counts.items():
        path = PROMPTS / name
        if not path.exists():
            check(f"{name} exists", False)
            continue
        actual = effective_placeholders(path)
        check(f"{name} has {expected} placeholders", actual == expected,
              f"file has {actual}; a mismatch shifts every later value into the wrong slot")

    check("the cover letter prompt receives the style guide",
          "cover_letter_prompts2.txt" in source and "self.today(), self.styleGuide()" in source)
    check("the summary prompt receives the life details as well as the cover letter",
          "summary_prompts2.txt\", self.coverLetter, self.lifeSummary" in source)

    # Relevance is decided ONCE, in the cover letter. Neither prompt may then
    # sweep the whole life summary back in.
    letter = (PROMPTS / "cover_letter_prompts2.txt").read_text(encoding="utf-8")
    check("the cover letter selects by relevance before anything else",
          "First decide which of my projects and jobs actually match" in letter
          and "Leave the rest out completely" in letter,
          "it would work through every project regardless of the job")
    check("and the original 'not all of my life details' filter is still there",
          "you don't need to incorporate ALL of my life details" in letter)

    summary = (PROMPTS / "summary_prompts2.txt").read_text(encoding="utf-8")
    check("the summary treats the cover letter as the scope",
          "Do not introduce any" in summary and "the cover letter left out" in summary,
          "the summary could reintroduce projects the letter deliberately dropped")
    check("and uses the life details only for concrete detail",
          "only to get the concrete" in summary)
    check("both job-description call sites receive the style guide",
          source.count("infoDict['compType'],\n                      self.styleGuide())") == 2,
          "one of the two was missed")

    print()
    print("--- generated text is cleaned before it is stored ---")
    for what in ("self.coverLetter = self.stripDashes(",
                 "self.resumeSummary = self.stripDashes(",
                 "jobDesc = self.stripDashes("):
        check(f"{what.split('=')[0].strip()} is sanitised", what in source)

    print()
    print("--- the model is no longer a 2023 model hard-coded in the source ---")
    gpt = (ROOT / "myGPT2.py").read_text(encoding="utf-8")
    check("gpt-3.5-turbo is not hard-coded into the completion call",
          "model='gpt-3.5-turbo-0125'" not in gpt)
    check("the model is read from configuration", "configured_model()" in gpt)
    import myGPT2
    check("a model name resolves", bool(myGPT2.configured_model()),
          "nothing would be sent to the API")
    print(f"         configured model: {myGPT2.configured_model()}")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL WRITING STYLE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
