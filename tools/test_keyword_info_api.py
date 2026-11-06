"""Keyword based information -- Flask route round-trip against a copy of the
database, plus the static wiring the tab needs. Never touches IndHelperDB.db.
"""

from __future__ import annotations

import shutil
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
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "test.db"
        shutil.copy2(ROOT / "IndHelperDB.db", copy)
        (Path(tmp) / "Users").mkdir()
        db = IndeedDB(copy, project_root=tmp)
        user_id = db.add_user("Keyword", "ApiTester")
        other_id = db.add_user("Other", "ApiTester")
        client = create_app(db).test_client()

        print("--- list and create ---")
        listed = client.get(f"/api/users/{user_id}/keyword-info")
        check("listing works before any entry exists, even if the table was never created",
              listed.status_code == 200 and listed.get_json() == [],
              f"status={listed.status_code} body={listed.get_data(as_text=True)[:120]}")

        created = client.post(f"/api/users/{user_id}/keyword-info", json={})
        check("POST with an empty body creates a blank entry (201)",
              created.status_code == 201 and "id" in created.get_json(),
              f"status={created.status_code}")
        entry_id = created.get_json()["id"]
        rows = client.get(f"/api/users/{user_id}/keyword-info").get_json()
        check("it is listed, blank",
              len(rows) == 1 and rows[0]["id"] == entry_id
              and rows[0]["keywords"] == [] and rows[0]["info"] == "", f"got {rows!r}")

        seeded = client.post(f"/api/users/{user_id}/keyword-info",
                             json={"keywords": "Go, Rust", "info": "Systems."})
        check("POST can carry content",
              seeded.status_code == 201
              and client.get(f"/api/users/{user_id}/keyword-info").get_json()[1]["keywords"] == ["Go", "Rust"])

        print()
        print("--- update ---")
        resp = client.put(f"/api/keyword-info/{entry_id}",
                          json={"keywords": ["Kafka", "kafka", " Spark "], "info": "Ran Kafka."})
        check("PUT succeeds", resp.status_code == 200, f"status={resp.status_code}")
        row = client.get(f"/api/users/{user_id}/keyword-info").get_json()[0]
        check("keywords are normalised", row["keywords"] == ["Kafka", "Spark"], f"got {row['keywords']!r}")
        check("info is saved", row["info"] == "Ran Kafka.")

        resp = client.put(f"/api/keyword-info/{entry_id}", json={"info": "Changed."})
        row = client.get(f"/api/users/{user_id}/keyword-info").get_json()[0]
        check("a partial PUT leaves the other field alone",
              row["info"] == "Changed." and row["keywords"] == ["Kafka", "Spark"])

        resp = client.put(f"/api/keyword-info/{entry_id}", json={"keywords": 42})
        check("a bad keywords payload is a 400 with a message, not a 500",
              resp.status_code == 400 and bool((resp.get_json() or {}).get("error")),
              f"status={resp.status_code} body={resp.get_data(as_text=True)[:120]}")
        resp = client.post(f"/api/users/{user_id}/keyword-info", json={"keywords": {"a": 1}})
        check("and the same on create", resp.status_code == 400)

        resp = client.put("/api/keyword-info/987654", json={"info": "x"})
        check("updating a missing entry is a 404", resp.status_code == 404)

        print()
        print("--- scoping and delete ---")
        check("another user sees none of it",
              client.get(f"/api/users/{other_id}/keyword-info").get_json() == [])
        resp = client.delete(f"/api/keyword-info/{entry_id}")
        check("DELETE succeeds", resp.status_code == 200)
        check("and removes only that entry",
              [r["id"] for r in client.get(f"/api/users/{user_id}/keyword-info").get_json()]
              == [seeded.get_json()["id"]])
        check("deleting it again is a 404", client.delete(f"/api/keyword-info/{entry_id}").status_code == 404)

        print()
        print("--- the tab is wired into the page ---")
        js = client.get("/js/keywords.js")
        check("/js/keywords.js is served", js.status_code == 200)
        js.close()
        index = client.get("/").get_data(as_text=True)
        check("the sidebar has a Keyword Info button that needs a user",
              'data-view="keywords" data-needs-user' in index and 'id="count-keywords"' in index)
        app_js = (ROOT / "dbgui" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        check("app.js registers the view",
              "renderKeywords" in app_js and "'keywords':" in app_js)
        check("and requires a user for it", "'keywords'," in app_js.split("NEEDS_USER")[1].split("\n")[0])
        check("and counts it", "setCount('keywords'" in app_js)
        check("the module's own file stays under the 1000 line limit",
              len((ROOT / "dbgui" / "static" / "js" / "keywords.js").read_text(encoding="utf-8").splitlines()) < 1000)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for label in failures:
            print(f"  - {label}")
        return 1
    print("ALL KEYWORD INFO API TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
