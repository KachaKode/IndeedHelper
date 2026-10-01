"""Data access layer for the IndeedHelper database admin GUI.

Everything that touches IndHelperDB.db lives here so the UI layer never writes
raw SQL. Two things this module is deliberately strict about:

1.  Format preservation. The bot reads these columns back with plain string
    parsing (see main3.py: load_startup_info / split_into_substrings), so the
    stored format has to stay byte-compatible with what it already expects --
    CRLF line endings for the multi-line fields, and "<url> <jobNums> <eduNums>"
    space-delimited lines for homePage.

2.  Row identity. The Job and Edu tables have no declared primary key, and Job
    actually contains duplicate (userID, jobNum) pairs, so every update/delete
    keys off SQLite's implicit rowid instead of the business key.
"""

from __future__ import annotations

import ast
import datetime
import json
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DB_FILENAME = "IndHelperDB.db"

# Only 'T' is picked up by the bot's own query (main3.py loadUsersFromDB:
# "WHERE AppsLeft > 0 AND Active = 'T'"). 'S' is a legacy third value that
# behaved identically to 'F'; it is no longer offered, and any row still
# holding it is written back as 'F' the next time that user is saved.
ACTIVE_CHOICES = [
    ("Active - bot will run this user", "T"),
    ("Off", "F"),
]

LEGACY_ACTIVE_VALUES = {"S"}


def normalize_active(value: Any) -> str:
    """Collapse legacy/unknown Active values to 'F'. Only 'T' means active."""
    text = (str(value) if value is not None else "").strip().upper()
    return "T" if text == "T" else "F"

YES_NO_CHOICES = [("Yes", "Yes"), ("No", "No")]

# Fields on `users` that hold multi-line text and must round-trip as CRLF.
USER_MULTILINE_FIELDS = ("homePage", "PositionInterests", "avoid", "LifeSummary",
                         "WritingSample", "skipped", "avoidEmployers")

USER_EDITABLE_FIELDS = (
    "FirstName", "LastName", "PhoneNumber", "email", "address", "areaSpec",
    "country", "zip", "IndeedEmail", "IndeedPass", "homePage", "homePagePattern",
    "ProfilePath", "PositionInterests", "AppsLeft", "Active", "LifeSummary",
    "WritingSample", "avoid", "skipped", "avoidEmployers", "LinkedInProfile",
)

JOB_FIELDS = (
    "jobNum", "JobTitle", "CompanyName", "CompanyType", "areaSpec",
    "currentPosition", "From", "To", "Description", "country",
)

EDU_FIELDS = (
    "eduNum", "level", "fieldOfStudy", "SchoolName", "areaSpec",
    "currentlyEnrolled", "From", "To", "country",
)

APPLICATION_FIELDS = (
    "id", "user_id", "DateTime", "Platform", "companyName", "jobTitle",
    "JobDescriptionText", "fullName", "headline", "jobHist", "eduHist",
    "skills", "resumeSummary", "QsAndAs", "cover_letter",
)

# Screener-question types the vetted-questions system understands. DateFill
# (Indeed's date-picker widget) is deliberately absent -- a stored/vetted date
# answer is never correct on a later application, since the right answer is
# always "today", so DateFill is never seeded, matched, or recorded.
VETTED_QUESTION_TYPES = (
    "free_response", "free_response_long", "mult_choice", "select_applicable",
    "drop_down", "search_select", "select_applicable_combobox",
)

VETTED_STATUS_CHOICES = [("Vetted", "vetted"), ("Unvetted", "unvetted")]

VETTED_QUESTION_EDITABLE_FIELDS = ("question_text", "answer", "answer_bank", "status")

_TRAILING_WORD_MARKER_RE = re.compile(r"\s*\(?\b(?:required|optional)\b\)?\s*$", re.IGNORECASE)
_TRAILING_ASTERISK_RE = re.compile(r"\s*\*+\s*$")


def normalize_question_text(text: Any) -> str:
    """Canonical form of a screener-question label, for matching two questions
    as "the same" regardless of decoration.

    Indeed's own markup adds a trailing required-asterisk (often as a literal
    NBSP + "*", e.g. "LinkedIn Profile\xa0*") or a "(required)"/"(optional)"
    suffix -- sometimes both, in either order -- none of which changes what
    is actually being asked. Both the bot (main3.py) and this module import
    this exact function so they always agree on what counts as the same
    question -- see vetted_questions' unique constraint, which is keyed on
    this output.

    Stripped in a loop rather than one combined regex, since the two
    decorations can appear in either order or be repeated
    ("Question *\n(Required)" vs "Question (Required) *").
    """
    value = (str(text) if text is not None else "").replace("\xa0", " ")
    previous = None
    while previous != value:
        previous = value
        value = _TRAILING_WORD_MARKER_RE.sub("", value)
        value = _TRAILING_ASTERISK_RE.sub("", value)
    value = " ".join(value.split())
    return value.strip().casefold()


def _quote(name: str) -> str:
    """Quote an identifier -- several columns are SQL keywords (From, To) or
    contain spaces ("Home Page Index")."""
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def to_crlf(text: str | None) -> str:
    """Normalize to the CRLF convention the existing rows use."""
    if text is None:
        return ""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")


def to_display(text: Any) -> str:
    """CRLF -> LF for showing in a Qt text widget."""
    if text is None:
        return ""
    if not isinstance(text, str):
        return str(text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def split_lines(text: Any) -> list[str]:
    return [line for line in to_display(text).split("\n")]


@dataclass
class SearchRow:
    """One line of the users.homePage field.

    Stored on disk as "<url> <jobNums> <eduNums>", space-delimited, e.g.
        https://www.indeed.com/jobs?q=call+center&l=remote 1,2,3
    The trailing pieces are optional; the bot treats a missing piece as None,
    meaning "use every Job/Edu record for this user".
    """

    url: str = ""
    job_nums: str = ""
    edu_nums: str = ""

    def to_line(self) -> str:
        # Rebuild exactly the way split_into_substrings() expects to read it:
        # split(' ') -> [url, jobNums, eduNums]. Trailing empties are dropped so
        # a URL-only row stays a bare URL rather than picking up stray spaces.
        parts = [self.url.strip(), self.job_nums.strip(), self.edu_nums.strip()]
        while parts and not parts[-1]:
            parts.pop()
        return " ".join(parts)

    @classmethod
    def from_line(cls, line: str) -> "SearchRow":
        pieces = line.strip().split(" ")
        pieces += [""] * (3 - len(pieces))
        return cls(url=pieces[0], job_nums=pieces[1], edu_nums=pieces[2])


def parse_home_page(text: Any) -> list[SearchRow]:
    rows = []
    for line in split_lines(text):
        if not line.strip():
            continue
        rows.append(SearchRow.from_line(line))
    return rows


def format_home_page(rows: list[SearchRow]) -> str:
    lines = [row.to_line() for row in rows if row.url.strip()]
    return "\r\n".join(lines)


def list_searches_for_bot(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    """This user's job searches in the exact order the bot should run them:
    every main row (parent_id IS NULL) followed immediately by its own
    active alternate-URL sub-rows, before moving to the next main row.

    A sub-row's job_nums/edu_nums/target_position/max_applications are always
    resolved from its parent here -- those columns are never read off the
    sub-row itself, no matter what they happen to hold on it. Only `url` and
    `id` (for search_id on the applications it produces) are ever a sub-row's
    own. An inactive sub-row is left out entirely; a main row has no such
    switch and is always included.

    `parent_url` is the parent's own url (NULL for a main row, which has no
    parent) -- carried through so main3.py can snapshot it onto every
    application this search produces (applications.search_parent_url), which
    is what lets a past application's "what's different" still be computed
    later even if the sub-row itself is since edited or deleted.

    Takes a plain sqlite3.Connection (not an IndeedDB) so main3.py's own
    connection can be passed straight through.
    """
    return conn.execute(
        "SELECT js.id, js.user_id, js.url, js.parent_id, p.url AS parent_url, "
        "       CASE WHEN js.parent_id IS NULL THEN js.job_nums ELSE p.job_nums END AS job_nums, "
        "       CASE WHEN js.parent_id IS NULL THEN js.edu_nums ELSE p.edu_nums END AS edu_nums, "
        "       CASE WHEN js.parent_id IS NULL THEN js.target_position "
        "            ELSE p.target_position END AS target_position, "
        "       CASE WHEN js.parent_id IS NULL THEN js.max_applications "
        "            ELSE p.max_applications END AS max_applications "
        "FROM job_searches js "
        "LEFT JOIN job_searches p ON p.id = js.parent_id "
        "WHERE js.user_id = ? AND (js.parent_id IS NULL OR js.active = 1) "
        "ORDER BY COALESCE(p.position, js.position), (js.parent_id IS NULL) DESC, js.position",
        (user_id,),
    ).fetchall()


@dataclass
class ValidationIssue:
    """A data-quality problem worth showing the user but not worth blocking on.

    `action` names a fix the UI can offer inline (currently only "renameFolder"),
    with `actionData` carrying whatever that fix needs.
    """

    where: str
    message: str
    severity: str = "warning"
    action: str | None = None
    actionData: dict[str, Any] | None = None


# --------------------------------------------------------------- user folders --
# The bot derives a per-user folder from the name + id
# (main3.py load_startup_info: MY_PATH = "Users\{First} {Last} {id}\") and opens
# "output <timestamp>.txt" and "skipped.txt" inside it at startup. Renaming a user
# therefore silently orphans that folder, so the GUI has to keep the two in sync.

def user_folder_name(user: dict[str, Any]) -> str:
    return f"{user.get('FirstName', '')} {user.get('LastName', '')} {user.get('id', '')}".strip()


def user_folder_path(root: Path | str, user: dict[str, Any]) -> Path:
    return Path(root) / "Users" / user_folder_name(user)


def find_orphaned_user_folder(root: Path | str, user: dict[str, Any]) -> str | None:
    """Find this user's folder when it is sitting under a stale name.

    Folder names always end with the user id ("Marion Faith Agbor 5"), so after a
    rename the old folder is still identifiable by that suffix. This is what lets
    the UI offer to rename it instead of the user hunting for it by hand.
    """
    users_root = Path(root) / "Users"
    if not users_root.is_dir():
        return None
    expected = user_folder_name(user)
    suffix = f" {user.get('id')}"
    for entry in users_root.iterdir():
        if entry.is_dir() and entry.name.endswith(suffix) and entry.name != expected:
            return entry.name
    return None


def rename_user_folder(root: Path | str, old_name: str, new_name: str) -> bool:
    """Rename Users/<old_name> to Users/<new_name>. Returns False if there was
    nothing to rename; raises if the destination is already taken."""
    users_root = Path(root) / "Users"
    source = users_root / old_name
    target = users_root / new_name
    if not source.exists() or old_name == new_name:
        return False
    if target.exists():
        raise FileExistsError(f"Cannot rename: {target} already exists.")
    source.rename(target)
    return True


class IndeedDB:
    def __init__(self, db_path: Path | str, project_root: Path | str | None = None) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")
        # Used to locate the Users/<name> folders that the bot reads at startup.
        self.project_root = Path(project_root) if project_root else self.db_path.parent
        self._backed_up_this_session = False

    # ------------------------------------------------------------- plumbing --

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def backup(self) -> Path:
        """Snapshot the DB next to itself. Called before the first write of a
        session so a bad edit is always recoverable."""
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        target = self.db_path.with_name(f"{self.db_path.stem}.backup_{stamp}{self.db_path.suffix}")
        shutil.copy2(self.db_path, target)
        return target

    def _ensure_backup(self) -> Path | None:
        if self._backed_up_this_session:
            return None
        path = self.backup()
        self._backed_up_this_session = True
        return path

    # ---------------------------------------------------------------- users --

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY "
                "CASE Active WHEN 'T' THEN 0 ELSE 1 END, LastName, FirstName"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def save_user(self, user_id: int, values: dict[str, Any]) -> Path | None:
        payload = {}
        for key, value in values.items():
            if key not in USER_EDITABLE_FIELDS:
                continue
            if key in USER_MULTILINE_FIELDS:
                payload[key] = to_crlf(value)
            elif key == "AppsLeft":
                payload[key] = int(value or 0)
            elif key == "Active":
                # Writes back 'F' for any legacy 'S', migrating it lazily.
                payload[key] = normalize_active(value)
            else:
                payload[key] = value
        if not payload:
            return None
        backup = self._ensure_backup()
        assignments = ", ".join(f"{_quote(k)} = ?" for k in payload)
        params = list(payload.values()) + [user_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE users SET {assignments} WHERE id = ?", params)
        return backup

    def add_user(self, first_name: str = "New", last_name: str = "User") -> int:
        """Create a user that is Off by default, so a half-filled record can
        never be picked up by a running bot."""
        self._ensure_backup()
        with self._connect() as conn:
            cur = conn.execute(
                'INSERT INTO users (FirstName, LastName, PhoneNumber, email, address, areaSpec, '
                'country, zip, IndeedEmail, IndeedPass, homePage, homePagePattern, ProfilePath, '
                'PositionInterests, AppsLeft, Active, LifeSummary, avoid, skipped) '
                "VALUES (?, ?, '', '', '', '', 'United States', '', '', '', '', "
                "'https://(((www.)?))(((smartapply.)?))(((ca.)?))indeed.com/jobs?((.*))', "
                "'', '', 0, 'F', '', '', '')",
                (first_name, last_name),
            )
            return int(cur.lastrowid)

    def delete_user(self, user_id: int) -> Path | None:
        """Delete only the users row. Job/Edu/job_searches/applications rows for
        this id are intentionally left behind -- applications is a historical
        record the GUI treats as read-only, and silently cascading into it would
        destroy history."""
        backup = self._ensure_backup()
        with self._connect() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return backup

    def user_orphan_counts(self, user_id: int) -> dict[str, int]:
        """What would be left behind by delete_user -- shown in the confirm dialog."""
        counts = {}
        with self._connect() as conn:
            for label, sql in (
                ("work history", "SELECT COUNT(*) FROM Job WHERE userID = ?"),
                ("education", "SELECT COUNT(*) FROM Edu WHERE userID = ?"),
                ("job searches", "SELECT COUNT(*) FROM job_searches WHERE user_id = ?"),
                ("applications", "SELECT COUNT(*) FROM applications WHERE user_id = ?"),
            ):
                counts[label] = int(conn.execute(sql, (user_id,)).fetchone()[0])
        return counts

    # -------------------------------------------------------- job searches --
    # A row with parent_id NULL is a main search; a row with parent_id set is
    # one of that main row's alternate-URL sub-rows (same target position,
    # different search URL). Position is scoped to siblings: main rows are
    # ordered among themselves by `position` with parent_id IS NULL, and each
    # main row's sub-rows are ordered among themselves by `position` within
    # that parent_id -- the two sequences don't share numbering. See
    # list_searches_for_bot for how the two are woven into the bot's actual
    # run order (every main row followed immediately by its own sub-rows).

    def list_searches(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT js.id, js.user_id, js.position, js.url, js.job_nums, js.edu_nums, "
                "js.target_position, js.max_applications, js.parent_id, js.active "
                "FROM job_searches js "
                "LEFT JOIN job_searches p ON p.id = js.parent_id "
                "WHERE js.user_id = ? "
                "ORDER BY COALESCE(p.position, js.position), (js.parent_id IS NULL) DESC, js.position",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_search(self, user_id: int, url: str = "", job_nums: str = "", edu_nums: str = "",
                   target_position: str = "", max_applications: int = 0) -> int:
        self._ensure_backup()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(position) FROM job_searches WHERE user_id = ? AND parent_id IS NULL",
                (user_id,),
            ).fetchone()
            position = 0 if row[0] is None else int(row[0]) + 1
            cur = conn.execute(
                "INSERT INTO job_searches "
                "(user_id, position, url, job_nums, edu_nums, target_position, max_applications, "
                " parent_id, active) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 1)",
                (user_id, position, url, job_nums, edu_nums, target_position,
                 int(max_applications or 0)),
            )
            return int(cur.lastrowid)

    def add_subsearch(self, parent_id: int, url: str = "") -> int:
        """Add an alternate-URL sub-row under an existing main search row.

        job_nums/edu_nums/target_position/max_applications are deliberately
        left at their column defaults and never read back for a sub-row --
        list_searches_for_bot always resolves those four from the parent.
        """
        self._ensure_backup()
        with self._connect() as conn:
            parent = conn.execute(
                "SELECT user_id FROM job_searches WHERE id = ? AND parent_id IS NULL", (parent_id,)
            ).fetchone()
            if parent is None:
                raise ValueError(f"No main job search with id {parent_id}")
            row = conn.execute(
                "SELECT MAX(position) FROM job_searches WHERE parent_id = ?", (parent_id,)
            ).fetchone()
            position = 0 if row[0] is None else int(row[0]) + 1
            cur = conn.execute(
                "INSERT INTO job_searches (user_id, position, url, parent_id, active) "
                "VALUES (?, ?, ?, ?, 1)",
                (parent["user_id"], position, url, parent_id),
            )
            return int(cur.lastrowid)

    def save_search(self, search_id: int, values: dict[str, Any]) -> Path | None:
        payload = {}
        for key, value in values.items():
            if key == "max_applications":
                payload[key] = int(value or 0)
            elif key == "active":
                payload[key] = 1 if value else 0
            elif key in ("url", "job_nums", "edu_nums", "target_position"):
                payload[key] = value
        if not payload:
            return None
        backup = self._ensure_backup()
        assignments = ", ".join(f"{_quote(k)} = ?" for k in payload)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE job_searches SET {assignments} WHERE id = ?",
                list(payload.values()) + [search_id],
            )
        return backup

    def delete_search(self, search_id: int) -> Path | None:
        """Deleting a main row takes its sub-rows with it -- a sub-row without
        a parent has nothing to resolve job_nums/edu_nums/target_position/
        max_applications from, so an orphan is never a valid state."""
        backup = self._ensure_backup()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, parent_id FROM job_searches WHERE id = ?", (search_id,)
            ).fetchone()
            if row is None:
                return backup
            conn.execute("DELETE FROM job_searches WHERE parent_id = ?", (search_id,))
            conn.execute("DELETE FROM job_searches WHERE id = ?", (search_id,))
            if row["parent_id"] is None:
                self._compact_positions(conn, row["user_id"])
            else:
                self._compact_subrow_positions(conn, row["parent_id"])
        return backup

    def reorder_searches(self, user_id: int, ordered_ids: list[int]) -> Path | None:
        """Order is behavioural: the bot starts on position 0 and cycles from
        there, so this is a functional edit, not a cosmetic one. Scoped to
        main rows -- a sub-row's position lives in its own parent_id-scoped
        sequence and is reordered through reorder_subsearches instead."""
        backup = self._ensure_backup()
        with self._connect() as conn:
            for position, search_id in enumerate(ordered_ids):
                conn.execute(
                    "UPDATE job_searches SET position = ? "
                    "WHERE id = ? AND user_id = ? AND parent_id IS NULL",
                    (position, search_id, user_id),
                )
        return backup

    def reorder_subsearches(self, parent_id: int, ordered_ids: list[int]) -> Path | None:
        backup = self._ensure_backup()
        with self._connect() as conn:
            for position, search_id in enumerate(ordered_ids):
                conn.execute(
                    "UPDATE job_searches SET position = ? WHERE id = ? AND parent_id = ?",
                    (position, search_id, parent_id),
                )
        return backup

    def _compact_positions(self, conn: sqlite3.Connection, user_id: int) -> None:
        """Close gaps left by a delete so main-row positions stay 0..n-1."""
        rows = conn.execute(
            "SELECT id FROM job_searches WHERE user_id = ? AND parent_id IS NULL ORDER BY position",
            (user_id,),
        ).fetchall()
        for position, row in enumerate(rows):
            conn.execute("UPDATE job_searches SET position = ? WHERE id = ?", (position, row["id"]))

    def _compact_subrow_positions(self, conn: sqlite3.Connection, parent_id: int) -> None:
        """Close gaps left by a delete so one parent's sub-row positions stay 0..n-1."""
        rows = conn.execute(
            "SELECT id FROM job_searches WHERE parent_id = ? ORDER BY position", (parent_id,)
        ).fetchall()
        for position, row in enumerate(rows):
            conn.execute("UPDATE job_searches SET position = ? WHERE id = ?", (position, row["id"]))

    # ------------------------------------------------------- job / education --

    def _list_child(self, table: str, fields: tuple[str, ...], user_id: int, order_by: str) -> list[dict[str, Any]]:
        cols = ", ".join(_quote(f) for f in fields)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT rowid AS _rowid, {cols} FROM {_quote(table)} WHERE userID = ? ORDER BY {_quote(order_by)}, rowid",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_jobs(self, user_id: int) -> list[dict[str, Any]]:
        return self._list_child("Job", JOB_FIELDS, user_id, "jobNum")

    def list_edu(self, user_id: int) -> list[dict[str, Any]]:
        return self._list_child("Edu", EDU_FIELDS, user_id, "eduNum")

    def _save_child(self, table: str, fields: tuple[str, ...], rowid: int, values: dict[str, Any]) -> Path | None:
        payload = {k: v for k, v in values.items() if k in fields}
        if not payload:
            return None
        if "Description" in payload:
            payload["Description"] = to_crlf(payload["Description"])
        backup = self._ensure_backup()
        assignments = ", ".join(f"{_quote(k)} = ?" for k in payload)
        params = list(payload.values()) + [rowid]
        with self._connect() as conn:
            conn.execute(f"UPDATE {_quote(table)} SET {assignments} WHERE rowid = ?", params)
        return backup

    def save_job(self, rowid: int, values: dict[str, Any]) -> Path | None:
        return self._save_child("Job", JOB_FIELDS, rowid, values)

    def save_edu(self, rowid: int, values: dict[str, Any]) -> Path | None:
        return self._save_child("Edu", EDU_FIELDS, rowid, values)

    def _next_num(self, table: str, num_field: str, user_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT MAX({_quote(num_field)}) FROM {_quote(table)} WHERE userID = ?", (user_id,)
            ).fetchone()
        return int((row[0] or 0)) + 1

    def add_job(self, user_id: int) -> int:
        self._ensure_backup()
        num = self._next_num("Job", "jobNum", user_id)
        with self._connect() as conn:
            cur = conn.execute(
                'INSERT INTO Job (userID, jobNum, JobTitle, CompanyName, CompanyType, areaSpec, '
                'currentPosition, "From", "To", Description, country) '
                "VALUES (?, ?, '', '', '', '', 'No', '', '', '', 'United States')",
                (user_id, num),
            )
            return cur.lastrowid

    def add_edu(self, user_id: int) -> int:
        self._ensure_backup()
        num = self._next_num("Edu", "eduNum", user_id)
        with self._connect() as conn:
            cur = conn.execute(
                'INSERT INTO Edu (userID, eduNum, level, fieldOfStudy, SchoolName, areaSpec, '
                'currentlyEnrolled, "From", "To", country) '
                "VALUES (?, ?, '', '', '', '', 'No', '', '', 'United States')",
                (user_id, num),
            )
            return cur.lastrowid

    def delete_row(self, table: str, rowid: int) -> Path | None:
        if table not in {"Job", "Edu"}:
            raise ValueError(f"Refusing to delete from unexpected table: {table}")
        backup = self._ensure_backup()
        with self._connect() as conn:
            conn.execute(f"DELETE FROM {_quote(table)} WHERE rowid = ?", (rowid,))
        return backup

    # ------------------------------------------------------- vetted questions --
    # A per-user bank of screener-question answers a human has confirmed correct
    # (status='vetted') or that the bot has recorded on its own after answering
    # from scratch (status='unvetted'). main3.py checks this before calling the
    # LLM; see the "Vetted Questions" plan for the full design.

    def list_vetted_questions(
        self, user_id: int, *, status: str | None = None, sort: str = "default",
    ) -> list[dict[str, Any]]:
        where = "user_id = ?"
        params: list[Any] = [user_id]
        if status in ("vetted", "unvetted"):
            where += " AND status = ?"
            params.append(status)
        order = {
            "alpha": "question_text COLLATE NOCASE",
            "date_asc": "created_at ASC",
            "date_desc": "created_at DESC",
        }.get(sort, "status DESC, question_text")
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM vetted_questions WHERE {where} ORDER BY {order}", params,
            ).fetchall()
        return [self._decode_vetted_row(dict(r)) for r in rows]

    def get_vetted_question(self, vetted_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM vetted_questions WHERE id = ?", (vetted_id,)
            ).fetchone()
        return self._decode_vetted_row(dict(row)) if row else None

    @staticmethod
    def _decode_vetted_row(row: dict[str, Any]) -> dict[str, Any]:
        row["answer"] = json.loads(row["answer"]) if row.get("answer") is not None else None
        row["answer_bank"] = json.loads(row["answer_bank"]) if row.get("answer_bank") else None
        return row

    def add_vetted_question(
        self, user_id: int, *, question_type: str, question_text: str, answer: Any,
        answer_bank: Any = None, status: str = "unvetted",
        source_application_id: int | None = None,
    ) -> int:
        if question_type not in VETTED_QUESTION_TYPES:
            raise ValueError(f"Unknown vetted question type: {question_type!r}")
        self._ensure_backup()
        now = datetime.datetime.now().isoformat(" ", "seconds")
        normalized = normalize_question_text(question_text)
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO vetted_questions "
                "(user_id, question_type, question_text, normalized_question, answer, "
                " answer_bank, status, source_application_id, last_answered_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, question_type, question_text, normalized, json.dumps(answer),
                 json.dumps(answer_bank) if answer_bank is not None else None,
                 status, source_application_id, now, now, now),
            )
            return int(cur.lastrowid)

    def save_vetted_question(self, vetted_id: int, values: dict[str, Any]) -> Path | None:
        """Filtered update. Editing `answer` also promotes the row to 'vetted'
        in the same statement -- a human choosing a different answer IS the act
        of vetting it, per the feature's own spec, and doing this server-side
        (rather than as two sequential client calls) makes it atomic."""
        payload = {k: v for k, v in values.items() if k in VETTED_QUESTION_EDITABLE_FIELDS}
        if not payload:
            return None
        if "answer" in payload:
            payload["answer"] = json.dumps(payload["answer"])
            payload.setdefault("status", "vetted")
        if "answer_bank" in payload:
            payload["answer_bank"] = json.dumps(payload["answer_bank"]) if payload["answer_bank"] is not None else None
        if "status" in payload and payload["status"] not in ("vetted", "unvetted"):
            raise ValueError(f"Unknown vetted question status: {payload['status']!r}")
        if "question_text" in payload:
            payload["normalized_question"] = normalize_question_text(payload["question_text"])
        payload["updated_at"] = datetime.datetime.now().isoformat(" ", "seconds")
        backup = self._ensure_backup()
        assignments = ", ".join(f"{_quote(k)} = ?" for k in payload)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE vetted_questions SET {assignments} WHERE id = ?",
                list(payload.values()) + [vetted_id],
            )
        return backup

    def set_vetted_status(self, vetted_id: int, status: str) -> Path | None:
        if status not in ("vetted", "unvetted"):
            raise ValueError(f"Unknown vetted question status: {status!r}")
        backup = self._ensure_backup()
        with self._connect() as conn:
            conn.execute(
                "UPDATE vetted_questions SET status = ?, updated_at = ? WHERE id = ?",
                (status, datetime.datetime.now().isoformat(" ", "seconds"), vetted_id),
            )
        return backup

    def delete_vetted_question(self, vetted_id: int) -> Path | None:
        backup = self._ensure_backup()
        with self._connect() as conn:
            conn.execute("DELETE FROM vetted_questions WHERE id = ?", (vetted_id,))
        return backup

    def delete_vetted_questions(self, user_id: int, status: str | None = None) -> Path | None:
        if status is not None and status not in ("vetted", "unvetted"):
            raise ValueError(f"Unknown vetted question status: {status!r}")
        backup = self._ensure_backup()
        with self._connect() as conn:
            if status:
                conn.execute(
                    "DELETE FROM vetted_questions WHERE user_id = ? AND status = ?", (user_id, status),
                )
            else:
                conn.execute("DELETE FROM vetted_questions WHERE user_id = ?", (user_id,))
        return backup

    def find_vetted_answer(self, user_id: int, normalized_question: str) -> dict[str, Any] | None:
        """Level 1's lookup: an exact, normalized-text match among this user's
        VETTED (not unvetted) rows only."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM vetted_questions WHERE user_id = ? AND normalized_question = ? "
                "AND status = 'vetted'",
                (user_id, normalized_question),
            ).fetchone()
        return self._decode_vetted_row(dict(row)) if row else None

    def upsert_unvetted_question(
        self, user_id: int, *, question_type: str, question_text: str, answer: Any,
        answer_bank: Any = None, source_application_id: int | None = None,
    ) -> None:
        """The runtime hook: record an answer the bot just gave on its own.

        Update-in-place keyed on (user_id, normalized_question) rather than
        inserting a duplicate every time the same recurring question is
        answered again -- and never touches a row a human has already vetted:
        the WHERE on the conflict clause makes this a safe no-op against an
        already-'vetted' row (a vetted row should never reach this call in the
        first place, since that is a Level-1 hit; this is belt-and-suspenders).
        """
        if question_type not in VETTED_QUESTION_TYPES:
            raise ValueError(f"Unknown vetted question type: {question_type!r}")
        self._ensure_backup()
        now = datetime.datetime.now().isoformat(" ", "seconds")
        normalized = normalize_question_text(question_text)
        answer_json = json.dumps(answer)
        bank_json = json.dumps(answer_bank) if answer_bank is not None else None
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO vetted_questions "
                "(user_id, question_type, question_text, normalized_question, answer, "
                " answer_bank, status, source_application_id, last_answered_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'unvetted', ?, ?, ?, ?) "
                "ON CONFLICT(user_id, normalized_question) DO UPDATE SET "
                "question_type = excluded.question_type, "
                "question_text = excluded.question_text, "
                "answer = excluded.answer, "
                "answer_bank = excluded.answer_bank, "
                "source_application_id = excluded.source_application_id, "
                "last_answered_at = excluded.last_answered_at, "
                "updated_at = excluded.updated_at "
                "WHERE vetted_questions.status = 'unvetted'",
                (user_id, question_type, question_text, normalized, answer_json,
                 bank_json, source_application_id, now, now, now),
            )

    # --------------------------------------------------- applications (read) --

    def count_applications(self, user_id: int | None = None, search: str = "") -> int:
        where, params = self._application_filter(user_id, search)
        with self._connect() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM applications {where}", params).fetchone()[0])

    def list_applications(
        self, user_id: int | None = None, search: str = "", limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        where, params = self._application_filter(user_id, search)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT applications.id, applications.user_id, applications.DateTime, "
                "applications.Platform, applications.companyName, applications.jobTitle, "
                "applications.fullName, applications.headline, "
                # Prefer the permanent snapshot taken at submit time; only a
                # historical row saved before that column existed falls back to
                # the live join, which can drift if the search is edited/deleted.
                "COALESCE(applications.search_target_position, job_searches.target_position) "
                "AS searchLabel "
                "FROM applications "
                "LEFT JOIN job_searches ON job_searches.id = applications.search_id "
                f"{where} ORDER BY applications.id DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return [dict(r) for r in rows]

    def _application_filter(self, user_id: int | None, search: str) -> tuple[str, list[Any]]:
        # Columns are qualified with "applications." because list_applications
        # joins job_searches, which also has a user_id column -- an unqualified
        # "user_id = ?" would be ambiguous once that join is in play.
        clauses, params = [], []
        if user_id is not None:
            clauses.append("applications.user_id = ?")
            params.append(user_id)
        if search.strip():
            needle = f"%{search.strip()}%"
            clauses.append(
                "(applications.companyName LIKE ? OR applications.jobTitle LIKE ? OR "
                "applications.fullName LIKE ? OR applications.headline LIKE ? OR "
                "applications.DateTime LIKE ?)"
            )
            params.extend([needle] * 5)
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    # Columns the bot writes with str(some_list_of_dicts). They look like JSON
    # but are Python repr: single quotes, switching to double quotes around an
    # apostrophe ("Bachelor's Degree"). json.loads cannot read that.
    STRUCTURED_APPLICATION_FIELDS = ("skills", "jobHist", "eduHist", "QsAndAs")

    @staticmethod
    def parse_stored_literal(text: Any) -> list | dict | None:
        """Turn one of those columns back into real data, or None if it will not.

        literal_eval evaluates literals only -- no names, no calls, no code --
        so it is safe on stored text. Checked against every value in the table:
        19,912 of 19,912 parse.

        None means "render the raw text instead", which keeps a malformed or
        unexpected value visible rather than silently blanking it.
        """
        if not isinstance(text, str) or not text.strip():
            return None
        try:
            value = ast.literal_eval(text)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            return None
        return value if isinstance(value, (list, dict)) else None

    def get_application(self, app_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            # applications.* (not a bare SELECT *) so the join does not pull in
            # job_searches' own id/user_id columns under those same names and
            # silently overwrite the application's.
            row = conn.execute(
                # applications.* already carries search_target_position/search_url/
                # search_parent_url -- the permanent snapshot the GUI computes
                # "what's different" from. The live join is only a fallback for
                # rows saved before that snapshot existed.
                "SELECT applications.*, "
                "COALESCE(applications.search_target_position, job_searches.target_position) "
                "AS searchLabel "
                "FROM applications "
                "LEFT JOIN job_searches ON job_searches.id = applications.search_id "
                "WHERE applications.id = ?",
                (app_id,),
            ).fetchone()
        if row is None:
            return None

        record = dict(row)
        # Parsed copies for display. The raw columns are left exactly as stored --
        # this table is the permanent record of what was actually sent.
        parsed = {}
        for name in self.STRUCTURED_APPLICATION_FIELDS:
            value = self.parse_stored_literal(record.get(name))
            if value is not None:
                parsed[name] = value
        record["_parsed"] = parsed
        return record

    def list_applications_old(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, user_id, opening_info, resume, cover_letter FROM applicationsOld ORDER BY id DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ validation --

    def validate_user(self, user_id: int) -> list[ValidationIssue]:
        """Surface data problems that would silently misbehave at run time.

        These are reported, never auto-corrected -- the bot's behaviour depends
        on this data and a silent "fix" could change which jobs get applied to.
        """
        issues: list[ValidationIssue] = []
        user = self.get_user(user_id)
        if user is None:
            return issues

        jobs = self.list_jobs(user_id)
        edus = self.list_edu(user_id)
        valid_job_nums = {j["jobNum"] for j in jobs}
        valid_edu_nums = {e["eduNum"] for e in edus}

        seen_job_nums = set()
        for job in jobs:
            num = job["jobNum"]
            if num in seen_job_nums:
                issues.append(ValidationIssue(
                    f"Work History #{num}",
                    f"Duplicate job number {num}. Two records share this number, so a search "
                    f"referencing it is ambiguous.",
                ))
            seen_job_nums.add(num)
            for label, value in (("From", job.get("From")), ("To", job.get("To"))):
                if value and "{" in str(value):
                    issues.append(ValidationIssue(
                        f"Work History #{num}",
                        f"'{label}' still contains template placeholder text: {str(value)[:60]}",
                    ))

        for edu in edus:
            for label, value in (("From", edu.get("From")), ("To", edu.get("To"))):
                if value and "{" in str(value):
                    issues.append(ValidationIssue(
                        f"Education #{edu['eduNum']}",
                        f"'{label}' still contains template placeholder text: {str(value)[:60]}",
                    ))

        # Sub-rows never own job_nums/edu_nums (list_searches_for_bot always
        # resolves those from the parent), so only main rows are checked
        # against valid_job_nums/valid_edu_nums -- a sub-row is only ever
        # checked for having a real-looking URL.
        searches = self.list_searches(user_id)
        main_index = {row["id"]: i for i, row in enumerate(
            (r for r in searches if r["parent_id"] is None), start=1
        )}
        sub_counts: dict[int, int] = {}   # parent_id -> how many siblings seen so far
        sub_index: dict[int, int] = {}    # sub-row id -> its 1-based ordinal among siblings
        for row in searches:
            parent = row["parent_id"]
            if parent is not None:
                sub_counts[parent] = sub_counts.get(parent, 0) + 1
                sub_index[row["id"]] = sub_counts[parent]

        for row in searches:
            is_sub = row["parent_id"] is not None
            label = (f"Job Search #{main_index.get(row['parent_id'], '?')} alt URL "
                     f"#{sub_index.get(row['id'], '?')}") if is_sub else f"Job Search #{main_index.get(row['id'], '?')}"

            if not (row["url"] or "").strip().lower().startswith("http"):
                issues.append(ValidationIssue(
                    label, f"URL does not look like a web address: {row['url']!r}",
                ))
            if is_sub:
                continue
            for kind, raw, valid in (
                ("job", row["job_nums"], valid_job_nums),
                ("edu", row["edu_nums"], valid_edu_nums),
            ):
                if not (raw or "").strip():
                    continue
                for piece in raw.split(","):
                    piece = piece.strip()
                    if not piece:
                        continue
                    if not piece.isdigit():
                        issues.append(ValidationIssue(
                            label, f"{kind} numbers should be digits separated by commas, got {piece!r}.",
                        ))
                    elif int(piece) not in valid:
                        issues.append(ValidationIssue(
                            label, f"References {kind} #{piece}, but this user has no such record.",
                        ))

        if not main_index:
            issues.append(ValidationIssue(
                "Job Searches",
                "No job searches configured; the bot has nowhere to start and will refuse to run this user.",
                severity="error",
            ))

        profile_path = (user.get("ProfilePath") or "").strip()
        if profile_path and not Path(profile_path).exists():
            issues.append(ValidationIssue(
                "Chrome Profile",
                f"ProfilePath does not exist on this machine: {profile_path}",
            ))

        # The bot opens output/skipped files inside this folder at startup, so a
        # missing one is a hard failure the moment the user is run.
        expected_name = user_folder_name(user)
        if not user_folder_path(self.project_root, user).exists():
            orphan = find_orphaned_user_folder(self.project_root, user)
            if orphan:
                issues.append(ValidationIssue(
                    "User Folder",
                    f'This user\'s folder is still named "{orphan}", but after the name change '
                    f'the bot now looks for "{expected_name}". Rename it, or the bot will fail '
                    f'on startup for this user.',
                    severity="error",
                    action="renameFolder",
                    actionData={"from": orphan, "to": expected_name},
                ))
            else:
                issues.append(ValidationIssue(
                    "User Folder",
                    f"Expected folder does not exist: Users/{expected_name}. "
                    f"The bot writes its output and skipped.txt here and will fail on startup without it.",
                    severity="error",
                ))

        if str(user.get("Active") or "").strip().upper() in LEGACY_ACTIVE_VALUES:
            issues.append(ValidationIssue(
                "Status",
                "Status is the legacy value 'S'. It behaves the same as Off; saving this user will store 'Off'.",
                severity="info",
            ))

        return issues
