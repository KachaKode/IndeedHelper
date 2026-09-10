"""End-to-end API tests against a COPY of the real database.

Covers the plan's verification items that can be asserted programmatically:
  - read-only enforcement on the applications tables (no write route exists)
  - rowid keying: editing one of the duplicate-jobNum rows leaves its twin alone
  - CRLF format preservation on a no-op save
  - static assets and every view's API actually respond

Never touches IndHelperDB.db -- everything runs on a throwaway copy.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbgui.data import IndeedDB  # noqa: E402
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
        client = create_app(db).test_client()

        # ---------------------------------------------------------- serving --
        check("GET / serves the app shell", client.get("/").status_code == 200)
        check("GET /css/app.css serves the stylesheet", client.get("/css/app.css").status_code == 200)
        check("GET /js/app.js serves the entry module", client.get("/js/app.js").status_code == 200)
        for module in ("core", "users", "searches", "history", "applications", "appdetail"):
            check(f"GET /js/{module}.js", client.get(f"/js/{module}.js").status_code == 200)

        # ------------------------------------------------------------- reads --
        users = client.get("/api/users").get_json()
        check("GET /api/users returns all users", len(users) == 10, f"got {len(users)}")
        check("users carry folder status", "_folderExists" in users[0])

        check("GET /api/meta", client.get("/api/meta").status_code == 200)
        check("meta offers only T/F for Active",
              [c["value"] for c in client.get("/api/meta").get_json()["activeChoices"]] == ["T", "F"])

        searches = client.get("/api/users/5/searches").get_json()
        check("user 5 has 7 job searches", len(searches) == 7, f"got {len(searches)}")
        check("searches are position-ordered",
              [s["position"] for s in searches] == sorted(s["position"] for s in searches))

        # Counts are NOT hard-coded here: every real run adds an application, so
        # a literal total fails the suite the next time the bot sends one.
        apps = client.get("/api/applications?page=1").get_json()
        check("applications paginate",
              apps["total"] > len(apps["rows"]) and len(apps["rows"]) == 50,
              f"total={apps['total']} rows={len(apps['rows'])}")
        check("the page count matches the total",
              apps["pages"] == -(-apps["total"] // 50),
              f"{apps['pages']} pages for {apps['total']} rows at 50/page")
        check("application search filters",
              client.get("/api/applications?search=Williams").get_json()["total"] < apps["total"])

        # The long columns hold Python repr, not JSON: `['a', 'b']` and
        # `[{'title': ...}]`, switching quote style around apostrophes
        # ("Bachelor's Degree"). The GUI showed them raw. They are parsed
        # server-side so the browser gets real arrays to lay out.
        detail = client.get(f"/api/applications/{apps['rows'][0]['id']}").get_json()
        check("the detail record carries parsed copies", "_parsed" in detail)
        check("the raw columns are still exactly as stored",
              isinstance(detail.get("skills"), (str, type(None))),
              "a raw column was replaced rather than supplemented")

        parsed_any, checked = 0, 0
        for row in client.get("/api/applications?page=1").get_json()["rows"][:15]:
            rec = client.get(f"/api/applications/{row['id']}").get_json()
            for name in ("skills", "jobHist", "eduHist", "QsAndAs"):
                raw = (rec.get(name) or "").strip()
                if not raw or raw == "[]":
                    continue
                checked += 1
                if isinstance(rec["_parsed"].get(name), list):
                    parsed_any += 1
        check("every stored list parses into a real list",
              checked > 0 and parsed_any == checked,
              f"{parsed_any} of {checked} parsed")

        # literal_eval must not choke on the quote-switching, and must refuse
        # anything that is not a plain literal.
        from dbgui.data import IndeedDB as _DB
        check("an apostrophe inside a value parses",
              _DB.parse_stored_literal("[{'level': \"Bachelor's Degree\"}]")
              == [{"level": "Bachelor's Degree"}])
        check("unparseable text yields None, not a crash",
              _DB.parse_stored_literal("not a literal at all") is None)
        check("a bare string is not treated as a record",
              _DB.parse_stored_literal("'just a string'") is None)
        check("GET /api/applications/<id> returns full record",
              "cover_letter" in client.get(f"/api/applications/{apps['rows'][0]['id']}").get_json())
        check("GET /api/applications-old", client.get("/api/applications-old").status_code == 200)
        check("GET /api/users/5/validate", client.get("/api/users/5/validate").status_code == 200)

        # ------------------------------------------- read-only enforcement --
        app_id = apps["rows"][0]["id"]
        for method, url in (
            ("post", "/api/applications"),
            ("put", f"/api/applications/{app_id}"),
            ("delete", f"/api/applications/{app_id}"),
            ("post", "/api/applications-old"),
            ("put", "/api/applications-old/1"),
            ("delete", "/api/applications-old/1"),
        ):
            status = getattr(client, method)(url, json={}).status_code
            check(f"{method.upper()} {url} is rejected ({status})", status in (404, 405),
                  f"expected 404/405, got {status}")

        # ------------------------------------------------ rowid row identity --
        # User 7 has two rows sharing jobNum 1; editing one must not touch the other.
        conn = sqlite3.connect(db_copy)
        conn.row_factory = sqlite3.Row
        dupes = conn.execute(
            'SELECT rowid, JobTitle FROM Job WHERE userID = 7 AND jobNum = 1 ORDER BY rowid'
        ).fetchall()
        conn.close()
        check("user 7 really has duplicate jobNum 1 rows", len(dupes) == 2, f"got {len(dupes)}")

        if len(dupes) == 2:
            target, twin = dupes[0], dupes[1]
            client.put(f"/api/jobs/{target['rowid']}", json={"JobTitle": "ROWID TEST MARKER"})
            conn = sqlite3.connect(db_copy)
            conn.row_factory = sqlite3.Row
            after = {r["rowid"]: r["JobTitle"] for r in conn.execute(
                'SELECT rowid, JobTitle FROM Job WHERE userID = 7 AND jobNum = 1').fetchall()}
            conn.close()
            check("edited row changed", after[target["rowid"]] == "ROWID TEST MARKER")
            check("duplicate twin untouched", after[twin["rowid"]] == twin["JobTitle"],
                  f"twin became {after[twin['rowid']]!r}")

        # ------------------------------------------- CRLF format preservation --
        conn = sqlite3.connect(db_copy)
        before = conn.execute(
            "SELECT PositionInterests, avoid, LifeSummary FROM users WHERE id = 5").fetchone()
        conn.close()

        current = client.get("/api/users/5").get_json()
        client.put("/api/users/5", json={k: current[k] for k in
                                         ("PositionInterests", "avoid", "LifeSummary")})

        conn = sqlite3.connect(db_copy)
        after = conn.execute(
            "SELECT PositionInterests, avoid, LifeSummary FROM users WHERE id = 5").fetchone()
        conn.close()

        for index, name in enumerate(("PositionInterests", "avoid", "LifeSummary")):
            check(f"no-op save preserves {name} byte-for-byte", before[index] == after[index],
                  f"CRLF before={before[index].count(chr(13))} after={after[index].count(chr(13))}")

        # ------------------------------------------------- legacy S migration --
        client.put("/api/users/8", json={"Active": "S"})
        conn = sqlite3.connect(db_copy)
        active8 = conn.execute("SELECT Active FROM users WHERE id = 8").fetchone()[0]
        conn.close()
        check("legacy 'S' is normalized to 'F' on save", active8 == "F", f"got {active8!r}")

        # ------------------------------------------------------ search CRUD --
        created = client.post("/api/users/5/searches",
                              json={"url": "https://example.com/x", "job_nums": "1"}).get_json()
        check("created a search", "id" in created)
        client.put(f"/api/searches/{created['id']}", json={"job_nums": "2,3"})
        updated = [s for s in client.get("/api/users/5/searches").get_json()
                   if s["id"] == created["id"]][0]
        check("search update persisted", updated["job_nums"] == "2,3")

        ids = [s["id"] for s in client.get("/api/users/5/searches").get_json()]
        client.post("/api/users/5/searches/reorder", json={"ids": list(reversed(ids))})
        reordered = [s["id"] for s in client.get("/api/users/5/searches").get_json()]
        check("reorder persisted", reordered == list(reversed(ids)),
              f"expected {list(reversed(ids))}, got {reordered}")

        client.delete(f"/api/searches/{created['id']}")
        after_delete = client.get("/api/users/5/searches").get_json()
        check("search deleted", created["id"] not in [s["id"] for s in after_delete])
        check("positions compacted after delete",
              [s["position"] for s in after_delete] == list(range(len(after_delete))),
              f"got {[s['position'] for s in after_delete]}")

        # ----------------------------------------------------- user lifecycle --
        new_user = client.post("/api/users", json={"FirstName": "Test", "LastName": "Person"}).get_json()
        fetched = client.get(f"/api/users/{new_user['id']}").get_json()
        check("new user starts Off", fetched["Active"] == "F", f"got {fetched['Active']!r}")
        check("delete user", client.delete(f"/api/users/{new_user['id']}").status_code == 200)
        check("deleted user is gone", client.get(f"/api/users/{new_user['id']}").status_code == 404)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL API TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
