"""What keyword info did for one job application, in words, for the run log.

keyword_info.py decides WHAT to add to a prompt. This module records, per job
application: which entries matched and where in the posting, which prompts
were actually given the text, what each result looked like, and a summary when
the application ends. It only builds text; main3.py decides when to write it.

What "effect" can honestly mean. Whether the info CHANGED an output cannot be
proven without generating the output a second time without the info, which
would double the model cost of every application. What can be checked cheaply
is whether the output carries traces of the info: terms that came ONLY from the
keyword info (not from the job description, the life summary, the question, or
the entry's own keywords, all of which the model had anyway) and that appear in
the result. That is strong evidence it was used. Its absence does not prove it
was ignored, so the report says "not visibly reflected", never "not used".

Choice questions (multiple choice, drop downs) return a pick from a fixed list,
so there is nothing to look in. For those the report gives the answer next to
the info that was supplied and says plainly that the effect cannot be isolated.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from keyword_info import _pattern, format_keyword_info_block, match_keyword_info

TAG = "[KW-INFO]"

# Where in each prompt the text lands, in words. Every prompt file that carries
# the marker needs an entry here (a test enforces it).
KEYWORD_PLACEMENT = {
    "cover_letter_prompts2.txt": "applicant details message, right after their life details",
    "job_desc_prompts2.txt": "main instruction message, right after the writing rules",
    "summary_prompts2.txt": "projects and jobs reference message (the cover letter still decides scope)",
    "headline_prompts2.txt": "instruction message, right after the job description",
    "skills_prompts2.txt": "life details message, so it feeds the applicant's own skills",
    "free_response_question_prompts.txt": "after the applicant's real work history, before the question",
    "mult_choice_question_prompts.txt": "after the current question, before the answer choices",
    "select_applicable_question_prompts.txt": "after the current question, before the answer choices",
    "drop_down_question_prompts.txt": "after the personal details and life summary, before the answer choices",
}

SCREENER_PROMPTS = (
    "free_response_question_prompts.txt",
    "mult_choice_question_prompts.txt",
    "select_applicable_question_prompts.txt",
    "drop_down_question_prompts.txt",
)

# Prompts whose output is free text, so reflected terms can be looked for. The
# rest return a pick from a fixed list, where there is nothing to look in.
TEXT_OUTPUT_PROMPTS = (frozenset(KEYWORD_PLACEMENT) - frozenset(SCREENER_PROMPTS)
                       | {"free_response_question_prompts.txt"})

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#]*(?:[.'\-][A-Za-z0-9+#]+)*")

_STOPWORDS = frozenset("""
about above after again also been before being between both could did does done each from
have having here into just like made make many more most much must only other over same
should since some such than that their them then there these they this those through under
until upon very want were what when where which while whom will with within without would
your yours you our ours year years experience experienced work worked working using used use
including include includes role team teams strong good great""".split())


def _stem(token: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text or "")


def distinctive_terms(info: str, keywords: Iterable[str], baseline: str, limit: int = 5000) -> list[str]:
    """Terms in `info` the model could ONLY have learned from it.

    Drops short and filler words, the entry's own keywords, and anything that
    also appears in `baseline` (the job description, life summary and so on).

    Every such term is returned, not a sample. An earlier version stopped at
    the first 12 in reading order; against a 35,000 character entry that
    meant judging the whole text by "Story", "fact" and "halves", and the log
    then claimed "not visibly reflected" for outputs that were full of terms
    (bronze, silver, backtests, auditable) found nowhere but in the entry.
    """
    known = {_stem(tok.lower()) for tok in _tokens(baseline)}
    for keyword in keywords:
        known.update(_stem(tok.lower()) for tok in _tokens(keyword))
    found: list[str] = []
    seen: set[str] = set()
    for token in _tokens(info):
        low = token.lower()
        significant = (len(low) >= 4 and low not in _STOPWORDS) or (
            len(low) >= 2 and any(ch.isdigit() for ch in low))
        stem = _stem(low)
        if not significant or stem in known or stem in seen:
            continue
        seen.add(stem)
        found.append(token)
        if len(found) >= limit:
            break
    return found


def assess_effect(matches: list[dict[str, Any]], output: str, baseline: str) -> list[dict[str, Any]]:
    """For each matched entry: which of its unique terms show up in `output`."""
    out_stems = {_stem(tok.lower()) for tok in _tokens(output)}
    results = []
    for match in matches:
        terms = distinctive_terms(match["info"], match["keywords"], baseline)
        # Longest first: a long word is far less likely to turn up by
        # coincidence than a short one, so it is the better thing to show.
        reflected = sorted((t for t in terms if _stem(t.lower()) in out_stems), key=len, reverse=True)
        if not terms:
            verdict = "cannot tell"
        elif len(reflected) >= 2:
            verdict = "reflected"
        elif reflected:
            # One shared word across a long entry can be chance.
            verdict = "possibly reflected"
        else:
            verdict = "not visibly reflected"
        results.append({"keywords": match["keywords"], "terms": terms,
                        "reflected": reflected, "verdict": verdict})
    return results


def _squash(text: Any, limit: int) -> str:
    flat = " ".join(str(text if text is not None else "").split())
    return flat if len(flat) <= limit else flat[: limit - 3].rstrip() + "..."


def _label(keywords: Iterable[str]) -> str:
    return "[" + ", ".join(keywords) + "]"


def _all_keywords(matches: list[dict[str, Any]]) -> list[str]:
    return [word for match in matches for word in match["keywords"]]


def jd_snippet(text: str, keyword: str, width: int = 70) -> str:
    """The job description around the first occurrence of `keyword`."""
    found = _pattern(keyword.strip()).search(text or "")
    if not found:
        return ""
    start, end = max(0, found.start() - width), min(len(text), found.end() + width)
    return ("..." if start else "") + " ".join(text[start:end].split()) + ("..." if end < len(text) else "")


class KeywordUsageLog:
    """The story of ONE job application, built up as it runs.

    reset() when a new listing starts; begin() once the listing is known;
    note_send() is called by myGPT2 each time a prompt actually took keyword
    info; record_use() after a result exists; summary() when the application
    ends. Each returns the text to log, or None when there is nothing to say.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.identity = ""
        self.entries_on_file = 0
        self.matches: list[dict[str, Any]] = []
        self.baseline = ""
        self.events: list[dict[str, Any]] = []
        self.pending: list[str] = []

    def note_send(self, prompt_file: str, _text: str = "") -> None:
        """myGPT2's listener: this prompt really was built with keyword info."""
        self.pending.append(prompt_file)

    def drop_pending(self) -> None:
        self.pending.clear()

    # ---------------------------------------------------------------- begin
    def begin(self, identity: str, entries: list[dict[str, Any]], matches: list[dict[str, Any]],
              job_description: str, life_summary: str = "") -> str:
        self.reset()
        self.identity = identity
        self.entries_on_file = len(entries)
        self.matches = matches
        self.baseline = f"{job_description or ''} {life_summary or ''}"

        head = f"{TAG} {identity} :: "
        if not entries:
            return head + "no keyword info on file for this user, nothing added to any prompt"
        if not matches:
            return head + (f"0 of {len(entries)} keyword entries match this job description, "
                           f"nothing added to any prompt")

        # The posting size is here so a truncated or empty capture is visible:
        # a keyword that is on the page but not in what the bot read cannot match.
        lines = [head + f"{len(matches)} of {len(entries)} keyword entries match this job description "
                        f"(the bot read {len(job_description or '')} characters of posting)"]
        unmatched, blank = [], 0
        for entry in entries:
            words = [w for w in entry.get("keywords") or [] if str(w).strip()]
            hit = match_keyword_info([entry], job_description)
            if hit:
                fired = hit[0]["keywords"]
                lines.append(f"    MATCHED {_label(fired)}")
                for keyword in fired:
                    lines.append(f"        '{keyword}' found in the posting: "
                                 f"\"{jd_snippet(job_description, keyword)}\"")
                silent = [w for w in words if w not in fired]
                if silent:
                    lines.append(f"        keywords on this entry that were NOT in the posting: {_label(silent)}")
                lines.append(f"        info: {_squash(hit[0]['info'], 600)}")
            elif not words or not str(entry.get("info") or "").strip():
                blank += 1
            else:
                unmatched.append(_label(words))
        if unmatched:
            more = f" and {len(unmatched) - 12} more" if len(unmatched) > 12 else ""
            lines.append("    not matched (keyword absent from the posting): " + " ".join(unmatched[:12]) + more)
        if blank:
            lines.append(f"    skipped {blank} entr{'y' if blank == 1 else 'ies'} with no keywords or no info")
        lines.append("    exact text the model is given wherever a prompt takes keyword info:")
        lines.extend("        " + line for line in format_keyword_info_block(matches).splitlines())
        return "\n".join(lines)

    # ------------------------------------------------------------ record_use
    def record_use(self, label: str, output: Any, prompts: Iterable[str], extra_context: str = "",
                   expect_send: bool = False) -> str | None:
        """Log one result. `prompts` are the prompt files that could have produced
        it; only a send actually noted for one of them counts as "used".

        expect_send is for generators that always take keyword info: if entries
        matched but nothing was sent, that is a bug worth a loud line.
        """
        prompts = tuple(prompts)
        sent = [name for name in self.pending if name in prompts]
        self.pending.clear()
        if not self.identity:
            # begin() never ran for this application (a run resumed part way
            # through): there is no listing to attribute this to.
            return None
        head = f"{TAG} {self.identity} :: {label}: "

        if not sent:
            if expect_send and self.matches:
                self.events.append({"label": label, "status": "not sent"})
                return head + (f"WARNING keyword info {_label(_all_keywords(self.matches))} matched but "
                               f"was not given to this prompt ({', '.join(prompts)} has no keyword "
                               f"marker, or the call did not pass it)")
            return None

        prompt = sent[0]
        where = KEYWORD_PLACEMENT.get(prompt, "inside the prompt")
        used = _label(_all_keywords(self.matches))

        if prompt in TEXT_OUTPUT_PROMPTS:
            effect = assess_effect(self.matches, str(output or ""), f"{self.baseline} {extra_context}")
            overall = next((v for v in ("reflected", "possibly reflected", "not visibly reflected")
                            if any(item["verdict"] == v for item in effect)), "cannot tell")
            lines = [head + f"used keyword info {used}, effect: {overall}",
                     f"    given to: {prompt} ({where})"]
            for item in effect:
                shown_terms = ", ".join(item["reflected"][:10])
                more = f" and {len(item['reflected']) - 10} more" if len(item["reflected"]) > 10 else ""
                if item["verdict"] == "reflected":
                    detail = (f"{len(item['reflected'])} terms that only the info supplied appear in the "
                              f"result: {shown_terms}{more}")
                elif item["verdict"] == "possibly reflected":
                    detail = (f"1 term that only the info supplied appears in the result ({shown_terms}); "
                              f"one shared word can be chance")
                elif item["verdict"] == "not visibly reflected":
                    detail = (f"none of the {len(item['terms'])} terms that only the info supplied appear in "
                              f"the result; it may still have shaped the wording")
                else:
                    detail = ("everything in this info was already in the posting or life summary, "
                              "so its effect cannot be told apart")
                lines.append(f"    {_label(item['keywords'])}: {item['verdict'].upper()}, {detail}")
            lines.append(f"    result: {_squash(output, 400)}")
            self.events.append({"label": label, "status": "used", "overall": overall, "effect": effect})
            return "\n".join(lines)

        answer = _squash(output, 160)
        lines = [head + f"used keyword info {used}, answer given: {answer}",
                 f"    given to: {prompt} ({where})",
                 "    effect: a pick from fixed choices, so the effect cannot be separated from the "
                 "rest of the context; compare the answer with the info that was given:"]
        lines.extend(f"        {_label(match['keywords'])}: {_squash(match['info'], 200)}"
                     for match in self.matches)
        self.events.append({"label": label, "status": "used", "overall": "choice", "answer": answer})
        return "\n".join(lines)

    # --------------------------------------------------------------- summary
    def summary(self) -> str | None:
        """The one-glance answer for this application, written when it ends."""
        if not self.identity:
            return None
        head = f"{TAG} {self.identity} :: SUMMARY: "
        if not self.entries_on_file:
            return head + "no keyword info on file, none used"
        if not self.matches:
            return head + f"none of the {self.entries_on_file} keyword entries matched this posting, none used"

        used = [event for event in self.events if event["status"] == "used"]
        warned = [event for event in self.events if event["status"] == "not sent"]
        plural = "" if len(used) == 1 else "s"
        lines = [head + f"keyword info {_label(_all_keywords(self.matches))} was given to "
                        f"{len(used)} output{plural} of this application"]
        for event in used:
            if event["overall"] == "choice":
                lines.append(f"    {event['label']}: answered {event['answer']}")
            elif event["overall"] in ("reflected", "possibly reflected"):
                terms = sorted({term for item in event["effect"] for term in item["reflected"]},
                               key=len, reverse=True)
                more = f" +{len(terms) - 6} more" if len(terms) > 6 else ""
                lines.append(f"    {event['label']}: {event['overall']} ({', '.join(terms[:6])}{more})")
            else:
                lines.append(f"    {event['label']}: {event['overall']}")
        lines.extend(f"    {event['label']}: WARNING matched but not given the info" for event in warned)
        if not used and not warned:
            lines.append("    (it matched, but no generator that takes keyword info ran for this application)")
        return "\n".join(lines)
