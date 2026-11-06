"""Keyword info logging: the run log must say which keyword info a job
application used, where it went, and what showed up in the result.

Makes no network calls and never touches IndHelperDB.db.

The point of most checks below is honesty. A log that says "keyword info was
used" when it was not, or "reflected" on evidence the model had anyway, is
worse than no log:

* "used" only counts for a prompt that REALLY took the text (myGPT2 reports
  that itself), never for a generator that merely ran.
* "reflected" only counts terms that came from the keyword info alone. A term
  also in the job description, the life summary, the question or the entry's
  own keywords proves nothing, because the model had it regardless.
* A pick from fixed choices says plainly that its effect cannot be isolated.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import keyword_report as kr  # noqa: E402
import main3  # noqa: E402
import myGPT2  # noqa: E402
from keyword_info import KEYWORD_MARKER, format_keyword_info_block, match_keyword_info  # noqa: E402

PROMPTS = ROOT / "prompts"
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


JD = ("Data Engineer. We need strong Kafka experience and Python. "
      "You will build streaming pipelines for our platform team.")
LIFE = "I like building things and I have written Python for years."
KAFKA = {"keywords": ["Kafka", "Event Streaming"],
         "info": "Ran a Kafka cluster handling 40k msgs per second, with zero downtime."}
GO = {"keywords": ["Golang"], "info": "Wrote Go services."}
BLANK = {"keywords": [], "info": "orphan text"}
ENTRIES = [KAFKA, GO, BLANK]
IDENT = "Acme Corp | Data Engineer | jk=abc123"


def new_log(entries=ENTRIES, jd=JD):
    log = kr.KeywordUsageLog()
    begun = log.begin(IDENT, entries, match_keyword_info(entries, jd), jd, LIFE)
    return log, begun


class FakeGPT(myGPT2.myGPT):
    """Real class, real prompt-file parsing, real marker handling and listener.
    Only the API key and the network reply are replaced."""

    reply = "The headline is: Kafka cluster engineer"
    need_redo = False

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("promptsPath", str(PROMPTS))
        super().__init__(*args, **kwargs)
        self.logFile.close()

    def loadAPIKey(self):
        pass

    def sendAll(self):
        return type(self).reply


def helper(**attrs):
    obj = main3.IndeedHelper.__new__(main3.IndeedHelper)
    base = dict(companyName="Acme Corp", jobTitle="Data Engineer", currentJobKey="abc123",
                JobDescriptionText=JD, lifeSummary=LIFE, user_id=-1, firstName="T", lastName="U",
                phone_num="1", email="e@x", areaSpec="Remote", writingSample="",
                coverLetter="A letter.", _addDocsAttempts=0, keywordRows=list(ENTRIES))
    base.update(attrs)
    for key, value in base.items():
        setattr(obj, key, value)
    obj.logged = []
    obj.reportAction = lambda message, *a, **k: obj.logged.append(message)
    return obj


def main() -> int:
    # -------------------------------------------------- distinctive terms
    print("--- what counts as evidence the info was used ---")
    terms = kr.distinctive_terms(KAFKA["info"], KAFKA["keywords"], JD + " " + LIFE)
    check("terms only the info supplied are kept", {"cluster", "40k", "downtime"} <= set(terms), f"got {terms}")
    check("the entry's own keyword is not evidence (the posting says it)", "Kafka" not in terms)
    check("words from the job description are not evidence", "Python" not in kr.distinctive_terms(
        "Python everywhere", [], JD))
    check("words from the life summary are not evidence", "building" not in kr.distinctive_terms(
        "building things", [], LIFE))
    check("filler and short words are dropped",
          kr.distinctive_terms("with that from the was", [], "") == [])
    check("a plural counts as the same word as its singular",
          kr.distinctive_terms("clusters", [], "cluster") == [])

    cases = {
        "reflected": "I ran a cluster for Kafka and reached 40k msgs.",
        "not visibly reflected": "I build pipelines.",
    }
    for want, output in cases.items():
        got = kr.assess_effect([KAFKA], output, JD + LIFE)[0]["verdict"]
        check(f"an output that {'carries' if want == 'reflected' else 'lacks'} the info's own terms is "
              f"{want!r}", got == want, f"got {got!r}")
    check("a single shared word is only 'possibly reflected': it can be chance",
          kr.assess_effect([KAFKA], "I ran a cluster for Kafka at scale.", JD + LIFE)[0]["verdict"]
          == "possibly reflected")
    check("terms that were only in the posting cannot be told apart",
          kr.assess_effect([{"keywords": ["Kafka"], "info": "Kafka and Python"}], "Kafka Python",
                           JD)[0]["verdict"] == "cannot tell")
    check("the keyword appearing in the result alone is NOT counted as reflected",
          kr.assess_effect([KAFKA], "I know Kafka and event streaming.", JD + LIFE)[0]["verdict"]
          == "not visibly reflected")

    # The real failure (Log53, application 5228): a 35,000 character entry.
    # Only its first 12 distinctive words were checked, all of them filler from
    # the opening ("Story", "fact", "halves"), so every output was reported as
    # "not visibly reflected" although the cover letter was full of terms that
    # exist nowhere except in that entry.
    filler = " ".join(f"opener{n}word" for n in range(1, 40))
    long_info = (f"Story {filler}. " + "Then the real substance: built bronze silver gold tables with "
                 "backtests, reproducible lineage and auditable governance.")
    verdict = kr.assess_effect([{"keywords": ["Databricks"], "info": long_info}],
                               "I built bronze and silver tables with auditable lineage.", JD + LIFE)[0]
    check("terms late in a long entry count, not just the first dozen",
          verdict["verdict"] == "reflected" and {"bronze", "silver", "auditable", "lineage"} <= set(verdict["reflected"]),
          f"got {verdict['verdict']!r} {verdict['reflected']}")
    check("every distinctive term is considered, not a sample", len(verdict["terms"]) > 40,
          f"only {len(verdict['terms'])}")

    # ------------------------------------------------------------- begin
    print()
    print("--- the match report ---")
    log, begun = new_log()
    print(begun)
    check("it names the application", IDENT in begun)
    check("it says how many entries match", "1 of 3 keyword entries match" in begun)
    check("it names the keywords that fired",
          "MATCHED [Kafka]" in begun)
    check("and says plainly which other keywords on that entry were NOT in the posting",
          "were NOT in the posting: [Event Streaming]" in begun,
          "without this, 'why did Databricks not fire?' has no visible answer")
    check("it says how much posting the bot actually read",
          f"the bot read {len(JD)} characters of posting" in begun)
    check("it shows where in the posting each keyword was found",
          "'Kafka' found in the posting" in begun and "strong Kafka experience" in begun)
    check("a keyword that did not fire is not claimed", "'Event Streaming' found" not in begun)
    check("it shows the info", "40k msgs per second" in begun)
    check("it lists entries that did not match", "[Golang]" in begun and "not matched" in begun)
    check("it counts entries skipped for having no keywords", "skipped 1 entry" in begun)
    check("it prints the exact text the model is given",
          format_keyword_info_block(log.matches).splitlines()[0] in begun)

    _, none = new_log(jd="We use Cobol only.")
    check("no match is stated, not silent",
          "0 of 3 keyword entries match" in none and "nothing added to any prompt" in none and IDENT in none)
    _, empty = new_log(entries=[])
    check("no entries on file is stated", "no keyword info on file" in empty)

    # --------------------------------------------------------- record_use
    print()
    print("--- one result ---")
    log, _ = new_log()
    check("a generator whose prompt never took the info logs nothing",
          log.record_use("cover letter", "text", ("cover_letter_prompts2.txt",)) is None)

    log.note_send("cover_letter_prompts2.txt")
    used = log.record_use("cover letter", "I ran a cluster at 40k msgs.", ("cover_letter_prompts2.txt",))
    print(used)
    check("a prompt that took the info is logged with the application's identity",
          used is not None and IDENT in used)
    check("it says which keywords were used (only the ones that fired)",
          "used keyword info [Kafka]," in used and "Event Streaming" not in used)
    check("it says which prompt and where in it", "cover_letter_prompts2.txt" in used
          and "applicant details" in used)
    check("it says the effect, with the terms as evidence",
          "effect: reflected" in used and "cluster" in used and "40k" in used)
    check("it shows the result", "result: I ran a cluster" in used)
    check("a second call does not reuse the same send",
          log.record_use("again", "x", ("cover_letter_prompts2.txt",)) is None)

    log.note_send("summary_prompts2.txt")
    miss = log.record_use("resume summary", "I build pipelines.", ("summary_prompts2.txt",))
    check("an output without traces of the info says so, without claiming it was ignored",
          "NOT VISIBLY REFLECTED" in miss and "may still have shaped" in miss)

    log.note_send("headline_prompts2.txt")
    check("a send for a different prompt is not credited to this generator",
          log.record_use("cover letter", "x", ("cover_letter_prompts2.txt",)) is None)
    check("and does not linger to be credited to a later one",
          log.record_use("headline", "x", ("headline_prompts2.txt",)) is None)

    log.note_send("mult_choice_question_prompts.txt")
    picked = log.record_use("screener question 'Years of Kafka?'", "5+ years", kr.SCREENER_PROMPTS,
                            extra_context="Years of Kafka?")
    print(picked)
    check("a choice answer shows the answer and the info side by side",
          "answer given: 5+ years" in picked and "40k msgs per second" in picked)
    check("and says its effect cannot be isolated", "cannot be separated" in picked)

    warn = log.record_use("resume headline", "x", ("headline_prompts2.txt",), expect_send=True)
    check("a generator that must take the info but did not is flagged loudly",
          warn is not None and "WARNING" in warn and "was not given" in warn)
    check("a screener answer that never reached the model is simply absent",
          log.record_use("screener", "Yes", kr.SCREENER_PROMPTS) is None)
    check("no match means no warning even if nothing was sent",
          new_log(jd="Cobol")[0].record_use("x", "y", ("headline_prompts2.txt",), expect_send=True) is None)
    check("an application that never began is not attributed",
          kr.KeywordUsageLog().record_use("x", "y", ("headline_prompts2.txt",)) is None)

    # ------------------------------------------------------------ summary
    print()
    print("--- the summary ---")
    summary = log.summary()
    print(summary)
    check("it names the application and the keywords that fired", IDENT in summary and "keyword info [Kafka] " in summary)
    check("it counts the outputs", "given to 3 outputs" in summary)
    check("it lists each output with its effect",
          "cover letter: reflected" in summary and "resume summary: not visibly reflected" in summary
          and "answered 5+ years" in summary)
    check("it carries forward the warning", "resume headline: WARNING" in summary)
    check("no match is summarised as none used",
          "none used" in (new_log(jd="Cobol")[0].summary() or ""))
    check("a summary before any application is nothing", kr.KeywordUsageLog().summary() is None)

    # --------------------------------------------------- placement table
    print()
    print("--- bookkeeping ---")
    carrying = {p.name for p in PROMPTS.glob("*.txt")
                if KEYWORD_MARKER in p.read_text(encoding="utf-8", errors="replace")}
    check("every prompt that carries the marker has a placement description",
          carrying == set(kr.KEYWORD_PLACEMENT), f"markers: {sorted(carrying)}")
    check("only free text outputs are searched for reflected terms",
          kr.TEXT_OUTPUT_PROMPTS == carrying - {"mult_choice_question_prompts.txt",
                                                "select_applicable_question_prompts.txt",
                                                "drop_down_question_prompts.txt"})

    # ------------------------------------------------- myGPT2's listener
    print()
    print("--- myGPT2 reports what it really built ---")
    seen: list[tuple] = []
    previous = myGPT2.keyword_info_listener
    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as scratch:
        os.chdir(scratch)          # myGPT opens logger.txt in the cwd
        try:
            myGPT2.keyword_info_listener = lambda name, text: seen.append((name, text))
            values = [f"v{n}" for n in range(1, 20)]
            FakeGPT("headline_prompts2.txt", "jd", keyword_info="FACT TEXT")
            check("a prompt with the marker and text reports it",
                  seen == [("headline_prompts2.txt", "FACT TEXT")], f"got {seen}")
            seen.clear()
            FakeGPT("headline_prompts2.txt", "jd", keyword_info="")
            check("no text, no report", seen == [])
            FakeGPT("date_fill_question_prompts.txt", *values, version=1, keyword_info="FACT TEXT")
            check("a prompt without the marker reports nothing even if given text", seen == [])

            def explode(_name, _text):
                raise RuntimeError("reporting broke")
            myGPT2.keyword_info_listener = explode
            try:
                gpt = FakeGPT("headline_prompts2.txt", "jd", keyword_info="FACT TEXT")
                survived = bool(gpt.nextMessages)
            except Exception:
                survived = False
            check("a failing listener cannot stop a prompt being built", survived)

            # ------------------------------ end to end through main3
            print()
            print("--- end to end: real prompts, real listener, stubbed reply ---")
            original_gpt = main3.myGPT2
            main3.myGPT2 = FakeGPT
            try:
                h = helper()
                h.loadKeywordInfo()                      # resets the log, installs the listener
                h.keywordRows = list(ENTRIES)            # user_id=-1 loads nothing; supply rows
                h.logKeywordMatches()
                FakeGPT.reply = "The headline is: Kafka cluster engineer"
                h.generateHeadline()
                FakeGPT.reply = "A cover letter about building pipelines."
                h.generateCL()
                h.coverLetter = "A cover letter about building pipelines."
                FakeGPT.reply = "I build pipelines."
                h.generateSummary()
                FakeGPT("mult_choice_question_prompts.txt", *values, version=1,
                        keyword_info=h.keywordInfoBlock())
                h.logKeywordEffect("screener question 'Years of Kafka?'", "5+ years",
                                   kr.SCREENER_PROMPTS, extra_context="Years of Kafka?")
                h.logKeywordEffect("screener question 'Authorized to work?'", "Yes", kr.SCREENER_PROMPTS)
                h.logKeywordSummary()
            finally:
                main3.myGPT2 = original_gpt
            text = "\n".join(h.logged)
            print(text)

            check("the log opens with the match report", h.logged[0].startswith("[KW-INFO] " + IDENT))
            check("the headline is logged with its evidence (one shared word, so only 'possibly')",
                  "resume headline: used keyword info" in text and "effect: possibly reflected" in text
                  and "cluster" in text)
            check("the cover letter is logged as not visibly reflected",
                  "cover letter: used keyword info" in text and "NOT VISIBLY REFLECTED" in text)
            check("each logged line names the prompt it went into",
                  "headline_prompts2.txt" in text and "cover_letter_prompts2.txt" in text
                  and "summary_prompts2.txt" in text)
            check("the screener answer that went through the model is logged",
                  "Years of Kafka?" in text and "answer given: 5+ years" in text)
            check("the screener answer that never reached the model is not",
                  "Authorized to work" not in text)
            check("the summary closes the story",
                  any("SUMMARY: keyword info [Kafka] was given to 4 outputs" in m
                      for m in h.logged), text[-400:])
            check("nothing was logged twice for one send",
                  sum("resume headline: used keyword info" in m for m in h.logged) == 1)

            # A job description with nothing in it for this user.
            main3.myGPT2 = FakeGPT
            try:
                quiet = helper(JobDescriptionText="We use Cobol only.")
                quiet.loadKeywordInfo()
                quiet.keywordRows = list(ENTRIES)
                quiet.logKeywordMatches()
                FakeGPT.reply = "The headline is: Cobol person"
                quiet.generateHeadline()
                quiet.logKeywordSummary()
            finally:
                main3.myGPT2 = original_gpt
            check("a listing with no match logs the fact once and the outputs not at all",
                  len(quiet.logged) == 2 and "0 of 3 keyword entries match" in quiet.logged[0]
                  and "none used" in quiet.logged[1], "\n".join(quiet.logged))

            # A generator that should have taken the info but was handed a stub that did not.
            class NoListener:
                def __init__(self, *a, **k):
                    pass

                def sendAll(self):
                    return "The headline is: x"
                need_redo = False
            main3.myGPT2 = NoListener
            try:
                broken = helper()
                broken.loadKeywordInfo()
                broken.keywordRows = list(ENTRIES)
                broken.logKeywordMatches()
                broken.generateHeadline()
            finally:
                main3.myGPT2 = original_gpt
            check("matched info that never reached the prompt produces a WARNING in the log",
                  any("WARNING" in m and "resume headline" in m for m in broken.logged),
                  "\n".join(broken.logged))

            # Through the REAL reportAction into a file: the console copy is cut to
            # 200 characters, so the run's output file is where the whole account lives.
            import io
            real = helper()
            del real.reportAction          # fall back to the class's own method
            real.outputFile = io.StringIO()
            real.loadKeywordInfo()
            real.keywordRows = list(ENTRIES)
            real.logKeywordMatches()
            written = real.outputFile.getvalue()
            check("the real log file gets the full match report, not the 200 character console cut",
                  "exact text the model is given" in written and "40k msgs per second" in written
                  and "strong Kafka experience" in written and len(written) > 600,
                  f"wrote {len(written)} chars")

            # Reporting must never be able to end the run.
            safe = helper()
            safe.loadKeywordInfo()
            try:
                safe.logKeywordEffect("x", None, 5)
                safe.logKeywordMatches()
                ok = True
            except Exception as exc:
                ok = False
                print("raised:", exc)
            check("a failure inside the keyword log is swallowed, not raised", ok)
        finally:
            myGPT2.keyword_info_listener = previous
            os.chdir(original_cwd)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for label in failures:
            print(f"  - {label}")
        return 1
    print("ALL KEYWORD INFO LOG TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
