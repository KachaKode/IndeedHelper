"""Vetted Questions -- the DB layer: schema, CRUD, the upsert's dedup/no-
clobber guarantees, normalize_question_text, and the seed script's logic
(dbgui.migrations.seed_vetted_questions).

Never touches IndHelperDB.db -- everything runs on a throwaway copy, per
this codebase's established test convention.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbgui.data import IndeedDB, normalize_question_text  # noqa: E402
from dbgui.migrations import (  # noqa: E402
    ensure_vetted_questions_schema, seed_vetted_questions, vetted_questions_schema_exists,
)

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_copy = Path(tmpdir) / "test.db"
        shutil.copy2(ROOT / "IndHelperDB.db", db_copy)
        (Path(tmpdir) / "Users").mkdir()

        db = IndeedDB(db_copy, project_root=tmpdir)

        print("--- normalize_question_text ---")
        check("strips a bare trailing asterisk (the real LinkedIn-field case)",
              normalize_question_text("LinkedIn Profile\xa0*") == "linkedin profile")
        check("strips a trailing 'required' marker after the asterisk",
              normalize_question_text("Are you authorized?\xa0*\nrequired")
              == "are you authorized?")
        check("strips '(optional)' with no asterisk at all",
              normalize_question_text("Question* (optional)") == "question")
        check("a plain question with no decoration is unchanged but casefolded",
              normalize_question_text("What is your zip code?") == "what is your zip code?")

        print()
        print("--- schema ---")
        # Explicitly closed rather than left as a bare local: a `with` block
        # on a sqlite3.Connection only commits/rolls back on exit, it does
        # NOT close it, so an unclosed `conn` here would stay alive (and its
        # Windows file handle open) for the rest of this function, racing
        # TemporaryDirectory's own cleanup at the end. Every IndeedDB method
        # avoids this by opening its own connection inside its own stack
        # frame instead.
        conn = db._connect()
        try:
            check("vetted_questions does not exist before the migration",
                  not vetted_questions_schema_exists(conn))
            ensure_vetted_questions_schema(conn)
            check("vetted_questions exists after ensure_vetted_questions_schema",
                  vetted_questions_schema_exists(conn))
            # Idempotent -- calling it again must not raise.
            ensure_vetted_questions_schema(conn)
            conn.commit()
        finally:
            conn.close()

        print()
        print("--- CRUD ---")
        user_id = db.add_user("Vetted", "Tester")

        vid = db.add_vetted_question(
            user_id, question_type="mult_choice", question_text="Are you authorized to work?",
            answer="Yes", answer_bank=["Yes", "No"], status="unvetted",
        )
        rows = db.list_vetted_questions(user_id)
        check("add_vetted_question + list_vetted_questions round-trips one row",
              len(rows) == 1, f"got {len(rows)}")
        check("answer comes back JSON-decoded, not a raw string", rows[0]["answer"] == "Yes")
        check("answer_bank comes back JSON-decoded as a list",
              rows[0]["answer_bank"] == ["Yes", "No"], f"got {rows[0]['answer_bank']!r}")
        check("starts unvetted", rows[0]["status"] == "unvetted")

        check("get_vetted_question reads the same row", db.get_vetted_question(vid)["question_text"]
              == "Are you authorized to work?")

        print()
        print("--- editing the answer auto-promotes to vetted (server-side, atomic) ---")
        db.save_vetted_question(vid, {"answer": "No"})
        row = db.get_vetted_question(vid)
        check("the answer was updated", row["answer"] == "No", f"got {row['answer']!r}")
        check("status flipped to vetted as part of the same save",
              row["status"] == "vetted", f"got {row['status']!r}")

        print()
        print("--- the status route can also demote back to unvetted on its own ---")
        db.set_vetted_status(vid, "unvetted")
        check("status is unvetted again", db.get_vetted_question(vid)["status"] == "unvetted")
        db.save_vetted_question(vid, {"question_text": "Are you authorized to work?"})
        check("editing ONLY the question text does not force-vet it",
              db.get_vetted_question(vid)["status"] == "unvetted")

        print()
        print("--- upsert_unvetted_question: the runtime hook's dedup/no-clobber guarantees ---")
        q2 = "List your top skills"
        db.upsert_unvetted_question(user_id, question_type="select_applicable",
                                    question_text=q2, answer=["Python"])
        rows2 = db.list_vetted_questions(user_id)
        check("first call inserts a new row", len(rows2) == 2, f"got {len(rows2)}")

        db.upsert_unvetted_question(user_id, question_type="select_applicable",
                                    question_text=q2, answer=["Python", "SQL"])
        rows3 = db.list_vetted_questions(user_id)
        check("re-answering the SAME question updates in place, not a duplicate row",
              len(rows3) == 2, f"got {len(rows3)}")
        updated = next(r for r in rows3 if r["question_text"] == q2)
        check("...with the newer answer", updated["answer"] == ["Python", "SQL"],
              f"got {updated['answer']!r}")

        db.set_vetted_status(updated["id"], "vetted")
        db.upsert_unvetted_question(user_id, question_type="select_applicable",
                                    question_text=q2, answer=["Rust"])
        after_vet = db.get_vetted_question(updated["id"])
        check("a VETTED row is never touched by the runtime upsert (belt-and-suspenders)",
              after_vet["answer"] == ["Python", "SQL"] and after_vet["status"] == "vetted",
              f"got {after_vet!r}")

        print()
        print("--- delete ---")
        before_delete = len(db.list_vetted_questions(user_id))
        db.delete_vetted_question(vid)
        check("delete removes exactly that row",
              len(db.list_vetted_questions(user_id)) == before_delete - 1)

        print()
        print("--- list_vetted_questions: status filter and sort ---")
        filter_user = db.add_user("Filter", "Tester")
        other_user = db.add_user("Other", "User")

        # Explicit created_at timestamps -- seconds-precision auto-timestamps
        # from back-to-back add_vetted_question calls in a fast test loop
        # aren't reliably distinct, so insert directly for deterministic order.
        conn = db._connect()
        try:
            rows_to_add = [
                ("Zebra question", "vetted", "2026-01-03 00:00:00"),
                ("Apple question", "unvetted", "2026-01-01 00:00:00"),
                ("Mango question", "vetted", "2026-01-02 00:00:00"),
            ]
            for question_text, status, created_at in rows_to_add:
                conn.execute(
                    "INSERT INTO vetted_questions "
                    "(user_id, question_type, question_text, normalized_question, answer, "
                    " answer_bank, status, source_application_id, last_answered_at, created_at, updated_at) "
                    "VALUES (?, 'free_response', ?, ?, ?, NULL, ?, NULL, ?, ?, ?)",
                    (filter_user, question_text, question_text.lower(), json.dumps("A"),
                     status, created_at, created_at, created_at),
                )
            # A row for a different user, to confirm filter/sort/delete stay scoped per-user.
            conn.execute(
                "INSERT INTO vetted_questions "
                "(user_id, question_type, question_text, normalized_question, answer, "
                " answer_bank, status, source_application_id, last_answered_at, created_at, updated_at) "
                "VALUES (?, 'free_response', 'Other user question', 'other user question', ?, NULL, "
                "'vetted', NULL, '2026-01-01 00:00:00', '2026-01-01 00:00:00', '2026-01-01 00:00:00')",
                (other_user, json.dumps("A")),
            )
            conn.commit()
        finally:
            conn.close()

        vetted_only = db.list_vetted_questions(filter_user, status="vetted")
        check("status='vetted' filter returns only vetted rows",
              {r["question_text"] for r in vetted_only} == {"Zebra question", "Mango question"},
              f"got {[r['question_text'] for r in vetted_only]}")

        unvetted_only = db.list_vetted_questions(filter_user, status="unvetted")
        check("status='unvetted' filter returns only unvetted rows",
              [r["question_text"] for r in unvetted_only] == ["Apple question"],
              f"got {[r['question_text'] for r in unvetted_only]}")

        alpha = db.list_vetted_questions(filter_user, sort="alpha")
        check("sort='alpha' orders alphabetically by question_text",
              [r["question_text"] for r in alpha] == ["Apple question", "Mango question", "Zebra question"],
              f"got {[r['question_text'] for r in alpha]}")

        date_asc = db.list_vetted_questions(filter_user, sort="date_asc")
        check("sort='date_asc' orders oldest first",
              [r["question_text"] for r in date_asc] == ["Apple question", "Mango question", "Zebra question"],
              f"got {[r['question_text'] for r in date_asc]}")

        date_desc = db.list_vetted_questions(filter_user, sort="date_desc")
        check("sort='date_desc' orders newest first",
              [r["question_text"] for r in date_desc] == ["Zebra question", "Mango question", "Apple question"],
              f"got {[r['question_text'] for r in date_desc]}")

        print()
        print("--- delete_vetted_questions: bulk delete respects status filter and user scope ---")
        db.delete_vetted_questions(filter_user, status="vetted")
        after_vetted_clear = db.list_vetted_questions(filter_user)
        check("status='vetted' bulk delete removes only vetted rows",
              [r["question_text"] for r in after_vetted_clear] == ["Apple question"],
              f"got {[r['question_text'] for r in after_vetted_clear]}")
        check("another user's row is untouched by this user's bulk delete",
              len(db.list_vetted_questions(other_user)) == 1)

        db.delete_vetted_questions(filter_user)
        check("bulk delete with no status removes everything left for that user",
              len(db.list_vetted_questions(filter_user)) == 0)
        check("...still without touching the other user's row",
              len(db.list_vetted_questions(other_user)) == 1)

        try:
            db.delete_vetted_questions(filter_user, status="bogus")
            check("delete_vetted_questions rejects an unknown status", False, "did not raise")
        except ValueError:
            check("delete_vetted_questions rejects an unknown status", True)

        print()
        print("--- seed_vetted_questions: dedup keeps the MOST RECENT answer, "
              "skips DateFill/blank, infers select_applicable from shape ---")
        seed_user = db.add_user("Seed", "User")
        rows_to_insert = [
            # (DateTime, QsAndAs) -- inserted in this order, so ascending id
            # order matches ascending recency, exactly as seed_vetted_questions
            # relies on.
            ("2026-01-01 10:00:00",
             str([{"Question": "Are you authorized to work in the US?", "Answer": "Yes"}])),
            ("2026-02-01 10:00:00",
             str([{"Question": "Are you authorized to work in the US?", "Answer": "No"}])),
            ("2026-03-01 10:00:00",
             str([{"Question": "List your top skills", "Answer": str(["Python", "SQL"])},
                  {"Question": "Today's Date", "Answer": None}])),
            ("2026-04-01 10:00:00", "this is not a python literal at all -- unparseable"),
        ]
        conn = db._connect()
        try:
            for date_time, qsandas in rows_to_insert:
                conn.execute(
                    "INSERT INTO applications (user_id, DateTime, QsAndAs) VALUES (?, ?, ?)",
                    (seed_user, date_time, qsandas),
                )
            conn.commit()
        finally:
            conn.close()

        # The copied DB carries real historical applications alongside these
        # 4 synthetic rows, so the report's totals reflect ALL of that --
        # only per_user[seed_user] (a freshly created, otherwise-empty user)
        # is meaningful to assert on directly.
        dry_report = seed_vetted_questions(db, dry_run=True)
        check("dry run does not create any rows",
              len(db.list_vetted_questions(seed_user)) == 0)
        check("dry run still computes this user's 2 unique questions (report is write-free)",
              dry_report["per_user"].get(seed_user) == 2,
              f"got {dry_report['per_user'].get(seed_user)!r}")

        real_report = seed_vetted_questions(db, dry_run=False)
        seeded = db.list_vetted_questions(seed_user)
        check("exactly 2 unique questions survive (the recurring one deduped, DateFill excluded)",
              len(seeded) == 2, f"got {len(seeded)}: {[r['question_text'] for r in seeded]}")

        auth_row = next((r for r in seeded if "authorized" in r["question_text"].lower()), None)
        check("the recurring question kept the MOST RECENT answer (No), not the first (Yes)",
              auth_row is not None and auth_row["answer"] == "No",
              f"got {auth_row!r}")
        check("it starts unvetted", auth_row is not None and auth_row["status"] == "unvetted")

        skills_row = next((r for r in seeded if "skills" in r["question_text"].lower()), None)
        check("a list-shaped legacy answer is inferred as select_applicable",
              skills_row is not None and skills_row["question_type"] == "select_applicable",
              f"got {skills_row!r}")
        check("...with the list parsed back out, not left as a stringified repr",
              skills_row is not None and skills_row["answer"] == ["Python", "SQL"],
              f"got {skills_row['answer']!r}" if skills_row else "no row")
        check("seeded rows have no answer_bank -- history never recorded the offered choices",
              skills_row is not None and skills_row["answer_bank"] is None)
        check("no DateFill/blank row was seeded",
              not any("today" in r["question_text"].lower() for r in seeded))

        print()
        print("--- re-running the seed script does not clobber a since-vetted answer ---")
        db.set_vetted_status(auth_row["id"], "vetted")
        db.save_vetted_question(auth_row["id"], {"answer": "Yes"})  # a human corrected it
        seed_vetted_questions(db, dry_run=False)
        after_reseed = db.get_vetted_question(auth_row["id"])
        check("a human-vetted correction survives re-running the seed script",
              after_reseed["answer"] == "Yes" and after_reseed["status"] == "vetted",
              f"got {after_reseed!r}")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL VETTED QUESTIONS DATA TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
