"""Keyword based information -- the bot side: matching, the prompt marker, and
that every generator actually passes the text along.

Makes no network calls and never touches IndHelperDB.db.

Three things here are regressions with a real failure behind them:

1. A marker alone in its own KEEP block would send an EMPTY message to the
   model whenever nothing matched, which is the usual case.
2. Placeholders are filled strictly by position. The job description prompt was
   rewritten and lost two placeholders while its call kept passing eight
   values, so the style guide never reached it and the job title took its
   slot. Work history was being rewritten without the writing rules.
3. With nothing matched, every prompt must come out EXACTLY as it did before
   the feature existed, or the common case silently changed.
"""

from __future__ import annotations

import ast
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import keyword_info as ki  # noqa: E402
import main3  # noqa: E402
import myGPT2  # noqa: E402
from dbgui.migrations import ensure_keyword_info_schema  # noqa: E402

PROMPTS = ROOT / "prompts"
MARKER = ki.KEYWORD_MARKER
PLACEHOLDER = "PLACE&&HOLDER&&"

# prompt file -> how many places main3.py calls it
EXPECTED_CALL_SITES = {
    "cover_letter_prompts2.txt": 1,
    "job_desc_prompts2.txt": 2,       # process_job_record and its unused file twin
    "summary_prompts2.txt": 1,
    "headline_prompts2.txt": 1,
    "skills_prompts2.txt": 1,
    "free_response_question_prompts.txt": 1,
    "mult_choice_question_prompts.txt": 1,
    "select_applicable_question_prompts.txt": 2,
    "drop_down_question_prompts.txt": 2,
}

# Deliberately without the marker -- see the plan: a date, a filter, a tidy-up
# pass over a finished list, and retry follow-ups sent on the same conversation.
MUST_NOT_CARRY_MARKER = [
    "date_fill_question_prompts.txt",
    "avoid_job_characteristics_prompts2.txt",
    "skills_prompts_cleaning.txt",
    "date_wrong_prompts.txt",
    "free_resp_choice_wrong_prompts.txt",
    "mult_choice_wrong_prompts.txt",
    "select_applicable_question_wrong_prompts.txt",
]

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def effective_placeholders(path: Path) -> int:
    """Placeholders myGPT2 will consume: comments and the two lines after a
    &&CHECK&& are skipped before substitution."""
    total, skip = 0, 0
    keep = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line and not keep:
            continue
        if skip > 0:
            skip -= 1
            continue
        if line[:2] == "//":
            continue
        total += line.count(PLACEHOLDER)
        if "**KEEP**ALL**TOGETHER**" in line:
            keep = True
        if "**END**ALL**TOGETHER**" in line:
            keep = False
        if "&&CHECK&&" in line:
            skip = 2
    return total


# ----------------------------------------------------------------- real myGPT

class Quiet(myGPT2.myGPT):
    """The real class and the real prompt-file parser, minus the API key."""

    def loadAPIKey(self):
        pass


def build_messages(prompts_dir: Path, name: str, keyword_info: str, version: int) -> list[str]:
    """Every message the model would be sent, in order, for one prompt file."""
    values = [f"<V{n}>" for n in range(1, 25)]
    previous = os.getcwd()
    with tempfile.TemporaryDirectory() as scratch:
        os.chdir(scratch)          # myGPT opens logger.txt in the cwd
        gpt = None
        try:
            gpt = Quiet(name, *values, promptsPath=str(prompts_dir), version=version,
                        keyword_info=keyword_info)
            return [m["content"] for m in gpt.context] + list(gpt.nextMessages)
        finally:
            if gpt is not None:
                gpt.logFile.close()
            os.chdir(previous)


def version_for(name: str) -> int:
    # The screener prompts are loaded with version=1 by main3.py.
    return 1 if name.endswith("_question_prompts.txt") else 2


# ------------------------------------------------------- reading main3.py calls

def myGPT2_calls(tree: ast.AST) -> list[ast.Call]:
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "myGPT2" and node.args
            and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)]


# ------------------------------------------------------------ generator stubs

class Capture:
    """Stands in for myGPT2 and remembers how it was called."""

    calls: list[tuple[str, tuple, dict]] = []

    def __init__(self, name, *args, **kwargs):
        Capture.calls.append((name, args, kwargs))

    def sendAll(self):
        return "The headline is: A Headline\nHere are the 3 points:- a\n- b\n- c"

    need_redo = False


def helper(**attrs):
    obj = main3.IndeedHelper.__new__(main3.IndeedHelper)
    for key, value in attrs.items():
        setattr(obj, key, value)
    return obj


def run_with_capture(fn):
    original = main3.myGPT2
    main3.myGPT2 = Capture
    Capture.calls = []
    try:
        fn()
    finally:
        main3.myGPT2 = original
    return list(Capture.calls)


def main() -> int:
    # ------------------------------------------------------------- matching
    print("--- matching ---")
    entries = [
        {"keywords": ["Java"], "info": "Java fact"},
        {"keywords": ["C++", "C#"], "info": "C family fact"},
        {"keywords": [".NET"], "info": "dotnet fact"},
        {"keywords": ["machine learning"], "info": "ML fact"},
        {"keywords": ["python", "sql"], "info": "data fact"},
        {"keywords": [], "info": "blank keywords"},
        {"keywords": ["Kubernetes"], "info": "   "},
    ]

    def fired(text):
        return [m["info"] for m in ki.match_keyword_info(entries, text)]

    check("a keyword does not match inside a longer word (Java vs JavaScript)",
          fired("We use JavaScript and TypeScript.") == [])
    check("but it does match as a whole word", fired("Strong Java skills.") == ["Java fact"])
    check("matching ignores case", fired("we need JAVA people") == ["Java fact"])
    check("C++ matches", "C family fact" in fired("Experience with C++ required."))
    check("C# matches", "C family fact" in fired("Experience with C# required."))
    check("a symbol keyword is not blocked by what precedes it (ASP.NET for .NET)",
          fired("Build ASP.NET services") == ["dotnet fact"])
    check("a multi-word phrase matches", fired("Applied machine learning work") == ["ML fact"])
    check("and across a line break or doubled space in the posting",
          fired("applied machine\n   learning work") == ["ML fact"])
    check("a phrase does not match when its words are apart",
          fired("machine shop and learning") == [])
    check("any one keyword is enough",
          fired("SQL only") == ["data fact"] and fired("python only") == ["data fact"])
    check("the keywords that fired are reported, not all of them",
          ki.match_keyword_info(entries, "python and C#")[0]["keywords"] == ["C#"]
          or ki.match_keyword_info(entries, "python and C#")[1]["keywords"] == ["C#"])
    check("an entry with no keywords never fires", "blank keywords" not in fired("anything at all"))
    check("an entry with blank info never fires", "   " not in fired("We run Kubernetes."))
    check("empty or missing text matches nothing",
          ki.match_keyword_info(entries, "") == [] and ki.match_keyword_info(entries, None) == [])
    check("a keyword full of regex characters is taken literally",
          ki.match_keyword_info([{"keywords": ["(a+b)*"], "info": "x"}], "a(a+b)*b") != [])

    print()
    print("--- the block ---")
    check("it is empty when nothing matched", ki.format_keyword_info_block([]) == "")
    block = ki.format_keyword_info_block(ki.match_keyword_info(entries, "Java and python"))
    check("it carries the information", "Java fact" in block and "data fact" in block)
    check("it names the keyword that fired", "mentions Java" in block and "mentions python" in block)
    check("it tells the model not to invent or misattribute",
          "Do not add detail" in block and "does not belong to" in block)
    check("it contains no em or en dash (the prompts forbid them)",
          "—" not in block and "–" not in block)
    multi = ki.format_keyword_info_block([{"keywords": ["x"], "info": "line one\nline two"}])
    check("a multi-line entry stays one bullet", multi.count("\n- ") == 1 and "line two" in multi)
    check("the log line says what matched",
          "Java" in ki.summarize_matches(ki.match_keyword_info(entries, "Java"))
          and ki.summarize_matches([]) == "no keyword info matched")

    # --------------------------------------------------------------- loading
    print()
    print("--- loading from the database ---")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "t.db"
        conn = sqlite3.connect(db_path)
        try:
            check("a database without the table reads as no entries",
                  ki.load_keyword_info(db_path, 1) == [])
            ensure_keyword_info_schema(conn)
            conn.executemany(
                "INSERT INTO keyword_info (user_id, keywords, info, created_at, updated_at) "
                "VALUES (?, ?, ?, 'now', 'now')",
                [(1, '["Python", "SQL"]', "mine"), (2, '["Go"]', "someone else's"),
                 (1, "not json", "corrupt"), (1, '"scalar"', "wrong shape")],
            )
            conn.commit()
        finally:
            conn.close()
        loaded = ki.load_keyword_info(db_path, 1)
        check("only this user's rows come back", [e["info"] for e in loaded] == ["mine"],
              f"got {loaded!r}")
        check("keywords are decoded", loaded[0]["keywords"] == ["Python", "SQL"])
        check("a corrupt row is skipped rather than failing the run", len(loaded) == 1)

        missing = Path(tmp) / "does_not_exist.db"
        check("a missing database reads as no entries", ki.load_keyword_info(missing, 1) == [])
        check("and is not created as a side effect", not missing.exists())

    # ------------------------------------------------------ the prompt files
    print()
    print("--- prompt files ---")
    for name in EXPECTED_CALL_SITES:
        text = (PROMPTS / name).read_text(encoding="utf-8")
        check(f"{name} carries the marker exactly once", text.count(MARKER) == 1,
              f"found {text.count(MARKER)}")
    for name in MUST_NOT_CARRY_MARKER:
        path = PROMPTS / name
        check(f"{name} does not carry the marker",
              path.exists() and MARKER not in path.read_text(encoding="utf-8"))

    for name in EXPECTED_CALL_SITES:
        version = version_for(name)
        with_marker = build_messages(PROMPTS, name, "", version)
        with tempfile.TemporaryDirectory() as bare:
            # Bytes, not text: write_text would turn each \r\n into \r\r\n on
            # Windows and double every blank line in the baseline.
            raw = (PROMPTS / name).read_bytes()
            kept = [line for line in raw.split(b"\r\n") if line.strip() != MARKER.encode()]
            (Path(bare) / name).write_bytes(b"\r\n".join(kept))
            without_marker = build_messages(Path(bare), name, "", version)
        check(f"{name}: with nothing matched the prompt is exactly what it was before",
              with_marker == without_marker)
        check(f"{name}: and no message is empty",
              all(m.strip() for m in with_marker),
              "an empty message goes to the model as a blank turn")

        sentinel = "KWINFO-SENTINEL line one"
        supplied = build_messages(PROMPTS, name, sentinel, version)
        holders = [m for m in supplied if sentinel in m]
        check(f"{name}: matched text reaches exactly one message", len(holders) == 1,
              f"{len(holders)} messages contain it")
        if holders:
            check(f"{name}: and sits inside a block with other content, not alone",
                  len(holders[0].strip()) > len(sentinel) + 20)
        check(f"{name}: no marker is left behind",
              not any(MARKER in m for m in supplied + with_marker))

    # ------------------------------------------------- main3.py call sites
    print()
    print("--- call sites in main3.py ---")
    source = (ROOT / "main3.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = myGPT2_calls(tree)
    by_file: dict[str, list[ast.Call]] = {}
    for call in calls:
        by_file.setdefault(call.args[0].value, []).append(call)

    for name, expected in EXPECTED_CALL_SITES.items():
        found = by_file.get(name, [])
        check(f"{name}: {expected} call site(s)", len(found) == expected, f"found {len(found)}")
        for call in found:
            kws = {k.arg: ast.unparse(k.value) for k in call.keywords}
            check(f"{name} line {call.lineno}: passes keyword_info=self.keywordInfoBlock()",
                  kws.get("keyword_info") == "self.keywordInfoBlock()", f"keywords: {kws}")

    print()
    print("--- positional values still match placeholders ---")
    # Equal where the file has no spare slots; at least as many where the call
    # passes extras the prompt has commented out (free response: zip/phone/email).
    for name in EXPECTED_CALL_SITES:
        placeholders = effective_placeholders(PROMPTS / name)
        for call in by_file.get(name, []):
            supplied = len(call.args) - 1
            check(f"{name} line {call.lineno}: {supplied} values for {placeholders} placeholders",
                  supplied >= placeholders if name.startswith("free_response") else supplied == placeholders,
                  "a mismatch shifts every later value into the wrong slot")

    for call in by_file.get("job_desc_prompts2.txt", []):
        sixth = ast.unparse(call.args[6]) if len(call.args) > 6 else None
        check(f"job_desc line {call.lineno}: the style guide is the last positional value",
              sixth == "self.styleGuide()",
              f"got {sixth!r} -- the job title used to land here and the style guide was dropped")

    # --------------------------------------------- generators, end to end
    print()
    print("--- generators hand the text to the model ---")
    rows = [{"keywords": ["Kafka"], "info": "I ran a Kafka cluster at 40k msgs/s."}]
    matching = dict(keywordRows=rows, JobDescriptionText="Looking for Kafka experience.")
    nothing = dict(keywordRows=rows, JobDescriptionText="Looking for Cobol experience.")
    expected_text = ki.format_keyword_info_block(ki.match_keyword_info(rows, matching["JobDescriptionText"]))
    check("the helper produces the block for a matching listing",
          helper(**matching).keywordInfoBlock() == expected_text and expected_text != "")
    check("and nothing for a listing that does not match",
          helper(**nothing).keywordInfoBlock() == "")
    check("a helper that never loaded entries simply gets nothing",
          helper(JobDescriptionText="Kafka").keywordInfoBlock() == "")
    check("loading is a no-op without a real user, touching no database",
          helper(user_id=-1).loadKeywordInfo() is None)

    def base(**extra):
        values = dict(
            jobTitle="Engineer", companyName="Acme", firstName="T", lastName="U",
            lifeSummary="life", phone_num="1", email="e@x", areaSpec="Remote",
            writingSample="", coverLetter="the letter", _addDocsAttempts=0,
        )
        values.update(extra)
        return values

    generators = {
        "cover_letter_prompts2.txt": lambda h: h.generateCL(),
        "summary_prompts2.txt": lambda h: h.generateSummary(),
        "headline_prompts2.txt": lambda h: h.generateHeadline(),
        "job_desc_prompts2.txt": lambda h: h.process_job_record({
            "JobTitle": "Dev", "CompanyName": "Co", "CompanyType": "Tech",
            "areaSpec": "X", "currentPosition": "No", "From": "2020", "To": "2021",
            "country": "US", "Description": "- built things"}),
    }
    for name, run in generators.items():
        got = run_with_capture(lambda: run(helper(**base(**matching))))
        kws = [kw for file, _a, kw in got if file == name]
        check(f"{name}: a matching listing sends the keyword text",
              bool(kws) and kws[0].get("keyword_info") == expected_text,
              f"calls: {got!r}"[:300])
        got = run_with_capture(lambda: run(helper(**base(**nothing))))
        kws = [kw for file, _a, kw in got if file == name]
        check(f"{name}: a non-matching listing sends an empty string",
              bool(kws) and kws[0].get("keyword_info") == "", f"calls: {got!r}"[:300])

    print()
    print(f"main3.py is {len(source.splitlines())} lines (it was over the 1000 line limit already; "
          f"the new logic lives in keyword_info.py)")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for label in failures:
            print(f"  - {label}")
        return 1
    print("ALL KEYWORD INFO MATCH TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
