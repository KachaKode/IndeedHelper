"""Refilling OpenAI credits: the top-up is ADDED to the estimated leftover.

Logs/Log55.txt: the OpenAI balance hit zero mid-run, the person topped up on
OpenAI's site, and the GUI had no way to be told. The Admin tab's only entry
("last amount purchased") also replaced the baseline outright, so topping up
while some credit remained would have thrown that remainder away.

Covers dbgui/billing.record_refill and the /api/admin/refill + /api/admin/grant
routes. Never touches OpenAI: the Costs API call is replaced throughout, and
everything runs against a temporary project root and a COPY of the database.
"""

from __future__ import annotations

import datetime
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbgui import billing  # noqa: E402
from dbgui.data import IndeedDB  # noqa: E402
from dbgui.server import create_app  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def costs_returning(total_spend: float, seen: list):
    def fake(project_root, start_time=None):
        seen.append(start_time)
        return {"configured": True, "totalSpend": total_spend, "currency": "usd",
                "series": [], "since": start_time.isoformat() if start_time else None}
    return fake


def grant_file(root: Path) -> Path:
    return root / "input" / billing.GRANT_FILE


def seed_grant(root: Path, amount: float) -> dict:
    return billing.set_credit_grant(root, amount)


def test_record_refill(root: Path) -> None:
    real = billing.fetch_costs
    try:
        # ------------------------------------------------- nothing on file --
        seen: list = []
        billing.fetch_costs = costs_returning(99, seen)
        first = billing.record_refill(root, 20)
        check("first top-up with no baseline: balance is just the top-up",
              first["amount"] == 20 and first["carried"] == 0 and first["added"] == 20, str(first))
        check("...and nothing to look up, so no Costs call", seen == [], str(seen))
        check("...carriedKnown is True (there was nothing to carry)", first["carriedKnown"] is True)
        stored = billing.get_credit_grant(root)
        check("...persisted with its breakdown",
              stored is not None and stored["amount"] == 20 and stored["added"] == 20
              and stored["carried"] == 0, str(stored))
        check("...carriedKnown is a response field, not stored",
              "carriedKnown" not in json.loads(grant_file(root).read_text()))

        # ----------------------------------------- exhausted: leftover is 0 --
        seed_grant(root, 20)
        seen = []
        billing.fetch_costs = costs_returning(1.0, seen)
        dry = billing.record_refill(root, 10, was_exhausted=True)
        check("account seen empty: leftover is exactly 0, whatever the estimate said",
              dry["amount"] == 10 and dry["carried"] == 0, str(dry))
        check("...and the estimate is not even consulted", seen == [], str(seen))

        # ------------------------------------------ not exhausted: carry over --
        previous = seed_grant(root, 20)
        seen = []
        billing.fetch_costs = costs_returning(7.5, seen)
        topped = billing.record_refill(root, 10)
        check("top-up while credit remains: leftover is carried over",
              topped["carried"] == 12.5 and topped["amount"] == 22.5, str(topped))
        check("...spend was looked up from the previous baseline's own timestamp",
              len(seen) == 1 and seen[0] == datetime.datetime.fromisoformat(previous["at"]), str(seen))
        check("...and the new baseline restarts the clock",
              datetime.datetime.fromisoformat(topped["at"]) >= datetime.datetime.fromisoformat(previous["at"]))

        # -------------------------------------------------------- overspent --
        seed_grant(root, 5)
        billing.fetch_costs = costs_returning(8.0, [])
        over = billing.record_refill(root, 10)
        check("estimate says overspent: leftover floors at 0, never negative",
              over["carried"] == 0 and over["amount"] == 10, str(over))

        # ----------------------------------------- spend cannot be fetched --
        seed_grant(root, 20)
        billing.fetch_costs = lambda *a, **k: {"configured": False}
        unconfigured = billing.record_refill(root, 10)
        check("no admin key: top-up saved alone, flagged as not carried over",
              unconfigured["amount"] == 10 and unconfigured["carriedKnown"] is False, str(unconfigured))

        seed_grant(root, 20)
        billing.fetch_costs = lambda *a, **k: {"configured": True, "error": "403"}
        errored = billing.record_refill(root, 10)
        check("Costs API error: same, rather than guessing a leftover",
              errored["amount"] == 10 and errored["carriedKnown"] is False, str(errored))

        # ------------------------------------------------- file compatibility --
        grant_file(root).write_text(json.dumps({"amount": 12.0, "at": "2026-10-01T00:00:00+00:00"}))
        old = billing.get_credit_grant(root)
        check("a baseline from before top-ups were tracked still loads",
              old == {"amount": 12.0, "at": "2026-10-01T00:00:00+00:00"}, str(old))
        replaced = billing.set_credit_grant(root, 3)
        check("correcting the balance replaces it and drops the old breakdown",
              "added" not in replaced and billing.get_credit_grant(root)["amount"] == 3)
    finally:
        billing.fetch_costs = real


def test_routes(client, root: Path) -> None:
    real = billing.fetch_costs
    try:
        billing.fetch_costs = costs_returning(4.0, [])
        if grant_file(root).exists():
            grant_file(root).unlink()

        for label, body in (("omitted", {}), ("null", {"amount": None}), ("blank", {"amount": ""})):
            res = client.post("/api/admin/refill", json=body)
            check(f"refill with amount {label}: accepted, nothing recorded",
                  res.status_code == 200 and res.get_json()["grant"] is None
                  and not grant_file(root).exists(), f"{res.status_code} {res.get_json()}")

        for bad in ("abc", -5, 0, "nan", "inf", [1]):
            res = client.post("/api/admin/refill", json={"amount": bad})
            check(f"refill rejects amount={bad!r}",
                  res.status_code == 400 and not grant_file(root).exists(),
                  f"{res.status_code} {res.get_json()}")

        res = client.post("/api/admin/refill", json={"amount": 15, "wasExhausted": True})
        grant = (res.get_json() or {}).get("grant") or {}
        check("refill after exhaustion records exactly the top-up",
              res.status_code == 200 and grant.get("amount") == 15 and grant.get("carried") == 0,
              f"{res.status_code} {res.get_json()}")

        res = client.post("/api/admin/refill", json={"amount": "10.5"})
        grant = (res.get_json() or {}).get("grant") or {}
        check("refill while credit remains adds to the estimated leftover (15 - 4 + 10.5)",
              res.status_code == 200 and grant.get("carried") == 11 and grant.get("amount") == 21.5,
              f"{res.status_code} {res.get_json()}")

        before = grant_file(root).read_text()
        for bad in ("nan", "inf", -1, "abc"):
            res = client.put("/api/admin/grant", json={"amount": bad})
            check(f"set-balance rejects amount={bad!r}", res.status_code == 400,
                  f"{res.status_code} {res.get_json()}")
        check("...and left the file alone", grant_file(root).read_text() == before)
        res = client.put("/api/admin/grant", json={"amount": 0})
        check("set-balance still accepts 0 (an empty account is a valid correction)",
              res.status_code == 200 and billing.get_credit_grant(root)["amount"] == 0)
    finally:
        billing.fetch_costs = real


def test_assets(client) -> None:
    check("GET /js/credits.js serves the banner module", client.get("/js/credits.js").status_code == 200)
    page = client.get("/").get_data(as_text=True)
    for element_id in ("credit-alert-amount", "credit-alert-refilled", "credit-alert-save",
                       "credit-alert-dismiss", "credit-alert-goto"):
        check(f"index.html has #{element_id}", f'id="{element_id}"' in page)
    app_js = client.get("/js/app.js").get_data(as_text=True)
    check("app.js wires the banner through credits.js", "./credits.js" in app_js)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "input").mkdir()
        (root / "Users").mkdir()
        db_copy = root / "test.db"
        shutil.copy2(ROOT / "IndHelperDB.db", db_copy)
        client = create_app(IndeedDB(db_copy, project_root=tmpdir)).test_client()

        test_record_refill(root)
        test_routes(client, root)
        test_assets(client)

    print()
    if failures:
        print(f"{len(failures)} FAILED:")
        for label in failures:
            print(f"  - {label}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
