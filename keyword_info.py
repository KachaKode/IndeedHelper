"""Keyword based information, bot side.

The Keyword Info tab in the database GUI stores entries of (keywords, info).
While the bot works on a listing, any entry with a keyword that appears in the
job description has its info added to what the model is told.

This module is deliberately pure -- no browser, no OpenAI, no IndeedDB -- so it
can be tested on its own. It reads the table with raw sqlite3, the way the other
bot-side loaders do (main3.py avoids IndeedDB because that class backs up the
whole database on its first write, which is wrong for a runtime hook).

How it reaches a prompt: a prompt file carries a line holding KEYWORD_MARKER
inside one of its KEEP blocks, and myGPT2 swaps it for the text built here. It
is a named marker rather than another PLACE&&HOLDER&& because placeholders are
filled strictly by position, so a new one would shift every value after it in
nine prompt files. When nothing matched the replacement is the empty string,
which is why the marker has to sit in a block that has other content.
"""

from __future__ import annotations

import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

KEYWORD_MARKER = "KEYWORD&&INFO&&"

HEADER = (
    "ADDITIONAL INFORMATION ABOUT ME, matched to keywords in this job description. "
    "These are true facts I supplied. Work a fact in only where it genuinely fits "
    "what you are writing, and use it as given. Do not add detail to it, do not "
    "attribute it to a job, project or employer it does not belong to, and do not "
    "say that it was supplied to you."
)


def load_keyword_info(db_path: str | Path, user_id: int) -> list[dict[str, Any]]:
    """This user's entries as `{"keywords": [...], "info": "..."}`.

    Returns [] when the database or the table does not exist yet: the bot must
    keep working on a database the GUI has not migrated.
    """
    path = Path(db_path)
    if not path.exists():
        return []
    try:
        conn = sqlite3.connect(str(path))
        try:
            rows = conn.execute(
                "SELECT keywords, info FROM keyword_info WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.OperationalError:
        return []

    entries = []
    for raw_keywords, info in rows:
        try:
            keywords = json.loads(raw_keywords or "[]")
        except (TypeError, ValueError):
            continue
        if not isinstance(keywords, list):
            continue
        entries.append({
            "keywords": [str(word) for word in keywords],
            "info": str(info or ""),
        })
    return entries


@lru_cache(maxsize=512)
def _pattern(keyword: str) -> re.Pattern[str]:
    """A whole-token, case-insensitive matcher for one keyword or phrase.

    \\b is not usable here: it needs a word character on the edge it guards,
    so it fails on C++, C# and .NET. Instead each edge is guarded only when the
    keyword's own edge character is a word character. That keeps "Java" from
    matching inside "JavaScript" while still letting ".NET" match "ASP.NET" and
    "C++" match "C++11". Runs of whitespace inside a phrase match any run of
    whitespace, so a phrase broken across a line in the posting still matches.
    """
    words = keyword.split()
    body = r"\s+".join(re.escape(word) for word in words)
    start = r"(?<!\w)" if re.match(r"\w", words[0][0]) else ""
    end = r"(?!\w)" if re.match(r"\w", words[-1][-1]) else ""
    return re.compile(start + body + end, re.IGNORECASE)


def match_keyword_info(entries: Iterable[dict[str, Any]], text: str | None) -> list[dict[str, Any]]:
    """The entries that apply to `text`, each with the keywords that fired.

    An entry applies when ANY of its keywords is found. Entries with no
    keywords or no info are skipped: a blank row created by the GUI's Add
    button must never reach a prompt.
    """
    if not text:
        return []
    hits = []
    for entry in entries:
        info = str(entry.get("info") or "").strip()
        if not info:
            continue
        found = []
        for keyword in entry.get("keywords") or []:
            keyword = str(keyword).strip()
            if keyword and _pattern(keyword).search(text):
                found.append(keyword)
        if found:
            hits.append({"keywords": found, "info": info})
    return hits


def format_keyword_info_block(matches: list[dict[str, Any]]) -> str:
    """The text that replaces KEYWORD_MARKER. Empty when nothing matched."""
    if not matches:
        return ""
    lines = [HEADER]
    for match in matches:
        info = match["info"].replace("\r\n", "\n").replace("\n", "\n  ")
        lines.append(f"- When the job description mentions {', '.join(match['keywords'])}: {info}")
    return "\n".join(lines)


def summarize_matches(matches: list[dict[str, Any]]) -> str:
    """One short line for the run log."""
    if not matches:
        return "no keyword info matched"
    parts = ["/".join(match["keywords"]) for match in matches]
    noun = "entry" if len(matches) == 1 else "entries"
    return f"keyword info matched {len(matches)} {noun}: " + "; ".join(parts)
