"""Vetted Questions -- Flask route round-trip against a seeded copy of the
database. Never touches IndHelperDB.db.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbgui.data import IndeedDB  # noqa: E402
from dbgui.migrations import ensure_vetted_questions_schema  # noqa: E402
from dbgui.server import create_app  # noqa: E402

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
        # A `with` block on a sqlite3.Connection only commits/rolls back on
        # exit -- it does NOT close it. Left as a bare local, `conn` stays
        # alive (and the file handle open) for the rest of this function,
        # which is exactly what made TemporaryDirectory's own cleanup below
        # race a lingering Windows file lock. Every IndeedDB method avoids
        # this by opening its own connection inside its own stack frame, so
        # it is unreachable the moment the method returns; closing explicitly
        # here gets the same effect for this one manually-opened connection.
        conn = db._connect()
        try:
            ensure_vetted_questions_schema(conn)
            conn.commit()
        finally:
            conn.close()
        user_id = db.add_user("Vetted", "ApiTester")
        vid = db.add_vetted_question(
            user_id, question_type="mult_choice", question_text="Are you authorized to work?",
            answer="Yes", answer_bank=["Yes", "No"], status="unvetted",
        )
        client = create_app(db).test_client()

        print("--- meta ---")
        meta = client.get("/api/meta").get_json()
        check("vettedQuestionTypes is exposed", "mult_choice" in meta.get("vettedQuestionTypes", []),
              f"got {meta.get('vettedQuestionTypes')!r}")
        check("vettedStatusChoices is exposed",
              {c["value"] for c in meta.get("vettedStatusChoices", [])} == {"vetted", "unvetted"},
              f"got {meta.get('vettedStatusChoices')!r}")

        print()
        print("--- list ---")
        rows = client.get(f"/api/users/{user_id}/vetted-questions").get_json()
        check("lists the seeded row", len(rows) == 1, f"got {len(rows)}")
        check("answer decoded from JSON", rows[0]["answer"] == "Yes")
        check("answer_bank decoded from JSON", rows[0]["answer_bank"] == ["Yes", "No"])

        print()
        print("--- editing the answer promotes to vetted, atomically, via one PUT ---")
        db.set_vetted_status(vid, "unvetted")
        resp = client.put(f"/api/vetted-questions/{vid}", json={"answer": "No"})
        check("PUT succeeds", resp.status_code == 200, f"status={resp.status_code}")
        after = client.get(f"/api/users/{user_id}/vetted-questions").get_json()[0]
        check("answer updated", after["answer"] == "No", f"got {after['answer']!r}")
        check("status auto-promoted to vetted by the same request",
              after["status"] == "vetted", f"got {after['status']!r}")

        print()
        print("--- the status route can demote independently of the answer ---")
        resp2 = client.post(f"/api/vetted-questions/{vid}/status", json={"status": "unvetted"})
        check("POST .../status succeeds", resp2.status_code == 200, f"status={resp2.status_code}")
        after2 = client.get(f"/api/users/{user_id}/vetted-questions").get_json()[0]
        check("status is unvetted again, answer unchanged",
              after2["status"] == "unvetted" and after2["answer"] == "No", f"got {after2!r}")

        print()
        print("--- no create route: rows only ever come from the seed script or the bot ---")
        resp3 = client.post(f"/api/users/{user_id}/vetted-questions", json={})
        check("POST to the list URL is rejected (405/404), not a silent create",
              resp3.status_code in (404, 405), f"status={resp3.status_code}")
        check("...and nothing was actually created",
              len(client.get(f"/api/users/{user_id}/vetted-questions").get_json()) == 1)

        print()
        print("--- delete ---")
        resp4 = client.delete(f"/api/vetted-questions/{vid}")
        check("DELETE succeeds", resp4.status_code == 200, f"status={resp4.status_code}")
        check("the row is gone",
              len(client.get(f"/api/users/{user_id}/vetted-questions").get_json()) == 0)

        print()
        print("--- status filter and sort query params ---")
        filter_user = db.add_user("Filter", "ApiTester")
        other_user = db.add_user("Other", "ApiTester")
        db.add_vetted_question(
            filter_user, question_type="free_response", question_text="Zebra question",
            answer="A", status="vetted",
        )
        db.add_vetted_question(
            filter_user, question_type="free_response", question_text="Apple question",
            answer="A", status="unvetted",
        )
        db.add_vetted_question(
            other_user, question_type="free_response", question_text="Other user question",
            answer="A", status="vetted",
        )

        vetted_resp = client.get(f"/api/users/{filter_user}/vetted-questions?status=vetted").get_json()
        check("?status=vetted returns only vetted rows for this user",
              [r["question_text"] for r in vetted_resp] == ["Zebra question"],
              f"got {[r['question_text'] for r in vetted_resp]}")

        unvetted_resp = client.get(f"/api/users/{filter_user}/vetted-questions?status=unvetted").get_json()
        check("?status=unvetted returns only unvetted rows for this user",
              [r["question_text"] for r in unvetted_resp] == ["Apple question"],
              f"got {[r['question_text'] for r in unvetted_resp]}")

        alpha_resp = client.get(f"/api/users/{filter_user}/vetted-questions?sort=alpha").get_json()
        check("?sort=alpha orders alphabetically",
              [r["question_text"] for r in alpha_resp] == ["Apple question", "Zebra question"],
              f"got {[r['question_text'] for r in alpha_resp]}")

        print()
        print("--- bulk delete ---")
        resp5 = client.delete(f"/api/users/{filter_user}/vetted-questions?status=vetted")
        check("bulk DELETE with ?status=vetted succeeds", resp5.status_code == 200,
              f"status={resp5.status_code}")
        after_bulk = client.get(f"/api/users/{filter_user}/vetted-questions").get_json()
        check("only the vetted row for this user was removed",
              [r["question_text"] for r in after_bulk] == ["Apple question"],
              f"got {[r['question_text'] for r in after_bulk]}")
        check("the other user's vetted row is untouched",
              len(client.get(f"/api/users/{other_user}/vetted-questions").get_json()) == 1)

        resp6 = client.delete(f"/api/users/{filter_user}/vetted-questions")
        check("bulk DELETE with no status succeeds", resp6.status_code == 200,
              f"status={resp6.status_code}")
        check("everything left for this user is gone",
              len(client.get(f"/api/users/{filter_user}/vetted-questions").get_json()) == 0)
        check("...and the other user is still untouched",
              len(client.get(f"/api/users/{other_user}/vetted-questions").get_json()) == 1)

        print()
        print("--- the new tab's static JS is actually served ---")
        check("GET /js/vetted.js", client.get("/js/vetted.js").status_code == 200)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL VETTED QUESTIONS API TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
