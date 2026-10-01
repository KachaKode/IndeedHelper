"""Tests for dbgui/outcomes.py -- writing the outcome log and the review queue.

Runs against a COPY of the real database in a temp directory. The real database
is never written to.

The properties worth breaking the build over:

  * an outcome dated before its own application is refused
  * deleting a CAPTURED event marks its capture_item rejected, so the next sync
    does not simply recreate the row a human just removed
  * resolving a review item both writes the event and settles the item, and
    refuses an application belonging to a different user
  * the review queue only ever shows items that still need a decision

    python tools/test_outcomes.py
"""

from __future__ import annotations

import datetime
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbgui.data import IndeedDB  # noqa: E402
from dbgui import migrations, outcomes, stats  # noqa: E402
from dbgui.server import create_app  # noqa: E402

DB_PATH = ROOT / "IndHelperDB.db"
USER_ID = 9

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def eq(label: str, got, want) -> None:
    check(label, got == want, f"got {got!r}, want {want!r}")


def raises(label: str, fn, fragment: str = "") -> None:
    try:
        fn()
    except ValueError as exc:
        check(label, fragment.lower() in str(exc).lower(),
              f"message was {str(exc)!r}, expected to contain {fragment!r}")
        return
    check(label, False, "no ValueError raised")


def build(tmpdir: Path):
    copy = tmpdir / "IndHelperDB.db"
    shutil.copy2(DB_PATH, copy)
    db = IndeedDB(copy, project_root=tmpdir)
    migrations.add_job_key_to_applications(db)
    migrations.add_outcome_tracking(db)

    conn = sqlite3.connect(copy)
    conn.row_factory = sqlite3.Row
    try:
        old = conn.execute(
            "SELECT id, DateTime FROM applications WHERE user_id = ? "
            "AND DateTime < '2024-06-01' ORDER BY id LIMIT 2", (USER_ID,)).fetchall()
        other = conn.execute(
            "SELECT id FROM applications WHERE user_id != ? LIMIT 1", (USER_ID,)).fetchone()
    finally:
        conn.close()
    stats.clear_cache()
    return db, copy, [dict(r) for r in old], (int(other["id"]) if other else None)


def test_timestamps() -> None:
    print("\ntimestamps")
    eq("a bare date becomes midday, not midnight",
       outcomes.normalise_timestamp("2026-05-04"), "2026-05-04 12:00:00")
    eq("a full timestamp is kept",
       outcomes.normalise_timestamp("2026-05-04 09:30:00"), "2026-05-04 09:30:00")
    check("an empty value becomes now",
          len(outcomes.normalise_timestamp("")) == 19)
    raises("garbage is refused", lambda: outcomes.normalise_timestamp("garbage"), "not a timestamp")
    # Exactly ten characters, so it takes the date branch and is refused as a date.
    raises("an impossible date is refused",
           lambda: outcomes.normalise_timestamp("2026-13-99"), "not a date")
    raises("ten characters of nonsense is refused as a date",
           lambda: outcomes.normalise_timestamp("not a date"), "not a date")


def test_recording(db, old) -> None:
    print("\nrecording an outcome")
    app_id = old[0]["id"]
    record = outcomes.add_manual_event(db, app_id, "responded", occurred_at="2024-04-10")
    eq("the event is stored with the manual source", record["source"], "manual")
    eq("the date is normalised", record["occurred_at"], "2024-04-10 12:00:00")

    listed = outcomes.list_events_for_application(db, app_id)
    eq("it reads back", len(listed), 1)
    eq("and carries a human label", listed[0]["label"], "Real response")

    print("\nrefusing nonsense")
    raises("an unknown outcome type",
           lambda: outcomes.add_manual_event(db, app_id, "promoted"), "unknown outcome")
    raises("an unknown application",
           lambda: outcomes.add_manual_event(db, 99_999_999, "responded"), "no application")
    # An outcome cannot precede its own application; allowing it would compute a
    # negative time-to-response and silently poison the timing percentiles.
    raises("a date before the application was submitted",
           lambda: outcomes.add_manual_event(db, app_id, "responded", occurred_at="1999-01-01"),
           "before the application")

    print("\nthe same stage may be recorded twice")
    # Manual events carry external_id NULL, so the partial unique index does not
    # apply -- a second interview really is a second interview.
    outcomes.add_manual_event(db, app_id, "interviewed", occurred_at="2024-05-01")
    outcomes.add_manual_event(db, app_id, "interviewed", occurred_at="2024-05-20")
    eq("both rounds are kept", len(outcomes.list_events_for_application(db, app_id)), 3)


def test_deleting_a_captured_event(db, copy, old) -> None:
    print("\ndeleting a captured event is remembered")
    app_id = old[1]["id"]
    now = datetime.datetime.now().strftime(stats.TIMESTAMP_FORMAT)
    conn = sqlite3.connect(copy)
    try:
        conn.execute(
            "INSERT INTO capture_items (user_id, source, external_id, observed_at, company, "
            "title, classified_type, classifier, confidence, match_state, application_id, "
            "created_at) VALUES (?, 'indeed', 'ext-1', ?, 'Acme', 'Analyst', 'viewed', "
            "'indeed:viewed', 0.9, 'matched', ?, ?)",
            (USER_ID, "2024-05-02 09:00:00", app_id, now))
        cursor = conn.execute(
            "INSERT INTO application_events (user_id, application_id, event_type, occurred_at, "
            "source, confidence, external_id, note, created_at) "
            "VALUES (?, ?, 'viewed', ?, 'indeed', 0.9, 'ext-1', '', ?)",
            (USER_ID, app_id, "2024-05-02 09:00:00", now))
        event_id = int(cursor.lastrowid)
        conn.commit()
    finally:
        conn.close()

    check("the captured event was deleted", outcomes.delete_event(db, event_id))
    conn = sqlite3.connect(copy)
    try:
        state = conn.execute(
            "SELECT match_state FROM capture_items WHERE external_id = 'ext-1'").fetchone()[0]
    finally:
        conn.close()
    # Without this the next sync would re-insert the event, because the unique
    # index only blocks a duplicate while the original row still exists.
    eq("its capture item is marked rejected so a re-sync will not recreate it",
       state, "rejected")
    check("deleting it again reports nothing to delete",
          outcomes.delete_event(db, event_id) is False)


def test_review_queue(db, copy, old, other_user_app) -> None:
    print("\nthe review queue")
    now = datetime.datetime.now().strftime(stats.TIMESTAMP_FORMAT)
    conn = sqlite3.connect(copy)
    try:
        for ext, state in (("open-1", "ambiguous"), ("open-2", "unmatched"),
                           ("done-1", "confirmed"), ("done-2", "ignored")):
            conn.execute(
                "INSERT INTO capture_items (user_id, source, external_id, observed_at, "
                "company, title, subject, classified_type, classifier, confidence, "
                "match_state, created_at) VALUES (?, 'gmail', ?, ?, 'Acme', 'Analyst', "
                "'Following up', 'responded', 'rule:interview', 0.5, ?, ?)",
                (USER_ID, ext, "2024-05-10 09:00:00", state, now))
        conn.commit()
    finally:
        conn.close()

    queue = outcomes.review_queue(db, USER_ID)
    ids = {item["external_id"] for item in queue}
    eq("only items still needing a decision are queued", ids, {"open-1", "open-2"})
    counts = outcomes.review_counts(db, USER_ID)
    eq("the open count matches", counts["open"], 2)

    print("\nresolving an item")
    item = next(i for i in queue if i["external_id"] == "open-1")
    resolved = outcomes.resolve_item(db, item["id"], application_id=old[0]["id"])
    eq("it is marked confirmed", resolved["match_state"], "confirmed")
    eq("and takes the classifier's type when none is given",
       resolved["event_type"], "responded")
    events = outcomes.list_events_for_application(db, old[0]["id"])
    check("an event was written for it",
          any(e["source"] == "gmail" for e in events), str(events))

    print("\nrefusing a bad resolution")
    other = next(i for i in outcomes.review_queue(db, USER_ID) if i["external_id"] == "open-2")
    if other_user_app:
        raises("an application belonging to another user",
               lambda: outcomes.resolve_item(db, other["id"], application_id=other_user_app),
               "different user")
    raises("no application and no ignore flag",
           lambda: outcomes.resolve_item(db, other["id"]), "pick an application")

    print("\nignoring an item")
    ignored = outcomes.resolve_item(db, other["id"], ignore=True)
    eq("it is marked ignored", ignored["match_state"], "ignored")
    eq("and leaves the queue", len(outcomes.review_queue(db, USER_ID)), 0)


def test_feeds_the_funnel(db, old) -> None:
    print("\nrecorded outcomes reach the Stats funnel")
    # Pinned well after the seeded events so the applications count as mature.
    now = datetime.datetime(2026, 9, 25, 12, 0, 0)
    out = stats.compute(db, USER_ID, now=now)
    check("the funnel counts the recorded response", out["funnel"]["responded"] >= 1,
          str(out["funnel"]["responded"]))
    check("interviews are counted", out["funnel"]["stages"][4]["count"] >= 1)
    check("time-to-response has a sample", out["timing"]["response"]["n"] >= 1)
    check("meta reports the events", out["meta"]["eventCount"] >= 1)


def test_http(db, old) -> None:
    print("\nover HTTP")
    client = create_app(db, None).test_client()
    eq("GET /api/outcome-types is 200", client.get("/api/outcome-types").status_code, 200)
    types = client.get("/api/outcome-types").get_json()
    check("every ladder stage plus the terminals is offered",
          {t["value"] for t in types} == set(outcomes.EVENT_TYPES), str(types))

    app_id = old[0]["id"]
    created = client.post(f"/api/applications/{app_id}/events",
                          json={"event_type": "screened", "occurred_at": "2024-06-01"})
    eq("POST an outcome is 201", created.status_code, 201)
    bad = client.post(f"/api/applications/{app_id}/events", json={"event_type": "nope"})
    eq("POST a bad type is 400", bad.status_code, 400)
    check("and explains why", "unknown outcome" in bad.get_json()["error"].lower())

    eq("DELETE a missing event is 404",
       client.delete("/api/application-events/99999999").status_code, 404)
    eq("DELETE the one just made is 200",
       client.delete(f"/api/application-events/{created.get_json()['id']}").status_code, 200)

    payload = client.get(f"/api/users/{USER_ID}/outcomes").get_json()
    check("the outcomes payload carries events, review and counts",
          all(k in payload for k in ("events", "review", "counts")))
    eq("resolving a missing item is 400",
       client.post("/api/capture-items/99999999/resolve", json={"ignore": True}).status_code, 400)


def main() -> int:
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}", file=sys.stderr)
        return 1

    test_timestamps()
    with tempfile.TemporaryDirectory() as tmpdir:
        db, copy, old, other_user_app = build(Path(tmpdir))
        test_recording(db, old)
        test_deleting_a_captured_event(db, copy, old)
        test_review_queue(db, copy, old, other_user_app)
        test_feeds_the_funnel(db, old)
        test_http(db, old)

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED ({len(failures)})")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
