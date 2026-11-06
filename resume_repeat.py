"""Is the resume on the review page the one the last application already used?

Every application rewrites the resume's summary for the job in front of it, and
the rewritten resume is what Indeed then keeps on file. So a review page whose
summary matches the LAST submitted application's summary for this user is a
resume that was never rewritten for this job -- the edit step was skipped or
did not take -- and sending it would send the previous job's pitch.

The pure parts live here so they can be tested without a browser: how two
summaries are compared, and where "the last one" comes from.
"""

from __future__ import annotations

import html
import os
import re
import sqlite3
from pathlib import Path

DB_PATH = "IndHelperDB.db"


def fingerprint(text):
    """The letters and digits of text, lower-cased.

    The same summary reaches the two sides of the comparison in different
    clothes: the database holds it with newlines between sentences, the review
    page renders each sentence in its own <div> with a trailing non-breaking
    space, and either can carry HTML entities. None of that is a different
    summary, so only the words are compared.
    """
    return re.sub(r"[\W_]+", "", html.unescape(text or "")).lower()


def same_summary(shown, previous):
    """True when both summaries have words in them and the words are identical.

    An empty side never matches: a review page that showed no summary says
    nothing about whether the resume was edited.
    """
    wanted = fingerprint(shown)
    return bool(wanted) and wanted == fingerprint(previous)


def last_application_summary(user_id, db_path=DB_PATH):
    """(application id, resume summary) of the user's most recent application.

    None when there is no earlier application with a summary, or the database
    cannot be read. Opened read-only, so a wrong working directory reports
    "nothing found" instead of quietly creating an empty database file.
    """
    # abspath, not Path.resolve(): before Python 3.10 resolve() leaves a path
    # that does not exist relative on Windows, and as_uri() refuses those.
    uri = Path(os.path.abspath(db_path)).as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT id, resumeSummary FROM applications "
            "WHERE user_id = ? AND TRIM(COALESCE(resumeSummary, '')) <> '' "
            "ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return (row[0], row[1]) if row else None
