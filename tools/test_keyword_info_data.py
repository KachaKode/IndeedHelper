"""Keyword based information -- the table, the migration, and the GUI's CRUD.

Runs against throwaway copies of the database. Never touches IndHelperDB.db.

Not asserted on a copy of the live database: "the table does not exist yet".
Once db_admin.py has run against the real file it does, and a check written
that way fails for a reason that has nothing to do with the code (the vetted
questions data test has exactly this problem). Absence is tested on a
minimal database built here instead.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbgui import keywords  # noqa: E402
from dbgui.data import IndeedDB  # noqa: E402
from dbgui.migrations import add_keyword_info, keyword_info_schema_exists  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def table_info(db: IndeedDB) -> tuple[list[str], list[str]]:
    """(column names, index names) for keyword_info; connection closed."""
    conn = db._connect()
    try:
        cols = [row["name"] for row in conn.execute("PRAGMA table_info(keyword_info)")]
        idx = [row["name"] for row in conn.execute("PRAGMA index_list(keyword_info)")]
    finally:
        conn.close()
    return cols, idx


def main() -> int:
    print("--- normalize_keywords ---")
    n = keywords.normalize_keywords
    check("a comma separated string is split and trimmed",
          n("Python,  SQL ,Docker") == ["Python", "SQL", "Docker"])
    check("a list is accepted", n(["a", "b"]) == ["a", "b"])
    check("empties are dropped", n(" , ,a,, ") == ["a"] and n(["", "  "]) == [])
    check("duplicates go case-insensitively, first spelling kept",
          n(["Python", "python", "PYTHON", "SQL"]) == ["Python", "SQL"])
    check("inner whitespace is collapsed", n(["machine    learning"]) == ["machine learning"])
    check("a list item containing a comma stays one keyword", n(["Python, Django"]) == ["Python, Django"])
    check("None is an empty list", n(None) == [])
    for bad in (5, {"a": 1}, [1, 2], ["ok", None]):
        try:
            n(bad)
            check(f"{bad!r} is rejected", False, "no ValueError")
        except ValueError:
            check(f"{bad!r} is rejected", True)

    print()
    print("--- migration, on a minimal database ---")
    with tempfile.TemporaryDirectory() as tmp:
        minimal = Path(tmp) / "minimal.db"
        conn = sqlite3.connect(minimal)
        try:
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
            conn.commit()
        finally:
            conn.close()
        db = IndeedDB(minimal, project_root=tmp)

        conn = db._connect()
        try:
            check("the table is absent to begin with", not keyword_info_schema_exists(conn))
        finally:
            conn.close()

        report = add_keyword_info(db)
        check("the first run creates it", report == {"created": True}, f"got {report!r}")
        cols, idx = table_info(db)
        check("with the expected columns",
              cols == ["id", "user_id", "keywords", "info", "created_at", "updated_at"],
              f"got {cols!r}")
        check("and an index on user_id", "idx_keyword_info_user" in idx, f"got {idx!r}")
        check("the second run does nothing", add_keyword_info(db) == {"created": False})
        backups = list(Path(tmp).glob("minimal.backup_*.db"))
        check("a backup was taken before the first change", len(backups) == 1,
              f"found {len(backups)}")

        print()
        print("--- the GUI layer creates the table itself if it is missing ---")
        conn = db._connect()
        try:
            conn.execute("DROP TABLE keyword_info")
            conn.commit()
        finally:
            conn.close()
        check("listing against a missing table is an empty list, not an error",
              keywords.list_entries(db, 1) == [])
        cols, _ = table_info(db)
        check("and the table now exists", bool(cols))

    print()
    print("--- CRUD, on a copy of the real database ---")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "copy.db"
        shutil.copy2(ROOT / "IndHelperDB.db", copy)
        (Path(tmp) / "Users").mkdir()
        db = IndeedDB(copy, project_root=tmp)
        add_keyword_info(db)

        alice = db.add_user("Alice", "KeywordTester")
        bob = db.add_user("Bob", "KeywordTester")

        check("a new user has no entries", keywords.list_entries(db, alice) == [])

        blank = keywords.create_entry(db, alice)
        row = keywords.get_entry(db, blank)
        check("a blank entry can be created",
              row is not None and row["keywords"] == [] and row["info"] == "")
        check("with both timestamps set", bool(row["created_at"]) and bool(row["updated_at"]))

        ok = keywords.save_entry(db, blank, {"keywords": "Python, sql, python"})
        check("keywords given as a string are normalised on save", ok)
        check("and stored as a list",
              keywords.get_entry(db, blank)["keywords"] == ["Python", "sql"])

        keywords.save_entry(db, blank, {"keywords": ["Kafka", "Event Streaming"]})
        check("a list replaces the previous keywords",
              keywords.get_entry(db, blank)["keywords"] == ["Kafka", "Event Streaming"])

        keywords.save_entry(db, blank, {"info": "Ran a Kafka cluster."})
        after = keywords.get_entry(db, blank)
        check("info is saved without disturbing the keywords",
              after["info"] == "Ran a Kafka cluster." and after["keywords"] == ["Kafka", "Event Streaming"])
        check("a save with no recognised fields changes nothing and still finds the row",
              keywords.save_entry(db, blank, {"user_id": 999, "nonsense": 1}) is True
              and keywords.get_entry(db, blank)["user_id"] == alice)

        try:
            keywords.save_entry(db, blank, {"keywords": 12})
            check("a bad keywords payload is rejected", False, "no ValueError")
        except ValueError:
            check("a bad keywords payload is rejected", True)
        check("and leaves the stored keywords alone",
              keywords.get_entry(db, blank)["keywords"] == ["Kafka", "Event Streaming"])

        created = keywords.create_entry(db, alice, "Go, Rust", "Systems work.")
        check("an entry can be created with content",
              keywords.get_entry(db, created)["keywords"] == ["Go", "Rust"])

        other = keywords.create_entry(db, bob, ["Java"], "Bob's fact")
        check("each user sees only their own entries",
              [e["id"] for e in keywords.list_entries(db, alice)] == [blank, created]
              and [e["id"] for e in keywords.list_entries(db, bob)] == [other])
        check("entries come back in creation order",
              [e["id"] for e in keywords.list_entries(db, alice)] == sorted([blank, created]))

        check("saving a missing entry reports False", keywords.save_entry(db, 987654, {"info": "x"}) is False)
        check("deleting returns True", keywords.delete_entry(db, created) is True)
        check("deleting again returns False", keywords.delete_entry(db, created) is False)
        check("deleting one entry leaves the others",
              [e["id"] for e in keywords.list_entries(db, alice)] == [blank]
              and len(keywords.list_entries(db, bob)) == 1)

        print()
        print("--- the bot reads what the GUI wrote ---")
        import keyword_info as ki  # noqa: E402
        loaded = ki.load_keyword_info(copy, alice)
        check("the bot-side loader sees the GUI's entry",
              loaded == [{"keywords": ["Kafka", "Event Streaming"], "info": "Ran a Kafka cluster."}],
              f"got {loaded!r}")
        hits = ki.match_keyword_info(loaded, "We stream events with kafka.")
        check("and it matches a job description", [h["info"] for h in hits] == ["Ran a Kafka cluster."])

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for label in failures:
            print(f"  - {label}")
        return 1
    print("ALL KEYWORD INFO DATA TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
