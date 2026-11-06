"""Tests for dbgui/stats.py -- the funnel and the honesty rules around it.

Runs against a COPY of the real database in a temp directory, seeded with known
application_events, so the assertions are about real row shapes but the numbers
are ones we chose. The real database is never touched.

The four properties worth breaking the build over:

  * an acknowledgement or a "viewed" is NOT a response
  * applications younger than the maturity window are excluded from every rate
  * a bucket below the minimum sample size is flagged, not rated
  * every dimension's buckets still sum to the mature total (the "Other" rollup
    must not quietly drop rows, or every rate on the page is wrong)

    python tools/test_stats_funnel.py
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
from dbgui import migrations, stats  # noqa: E402
from dbgui.server import create_app  # noqa: E402

DB_PATH = ROOT / "IndHelperDB.db"
USER_ID = 9

# Everything is computed against this instant so the tests are not a function of
# the day they run on.
NOW = datetime.datetime(2026, 9, 25, 12, 0, 0)

INSERT_EVENT = (
    "INSERT INTO application_events (user_id, application_id, event_type, occurred_at, "
    "source, confidence, external_id, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def eq(label: str, got, want) -> None:
    check(label, got == want, f"got {got!r}, want {want!r}")


def add_event(conn, app_id, event_type, occurred_at, source="indeed", external_id=None):
    conn.execute(INSERT_EVENT, (USER_ID, app_id, event_type, occurred_at, source, 1.0,
                                external_id, "", "2026-09-25 12:00:00"))


def build(tmpdir: Path) -> tuple[IndeedDB, list[int], int]:
    """A copy of the DB with the outcome schema applied and known events seeded.

    Returns (db, the mature application ids we attached events to, the id of a
    deliberately-too-recent application).
    """
    copy = tmpdir / "IndHelperDB.db"
    shutil.copy2(DB_PATH, copy)
    db = IndeedDB(copy, project_root=tmpdir)
    migrations.add_job_key_to_applications(db)
    migrations.add_outcome_tracking(db)

    conn = sqlite3.connect(copy)
    conn.row_factory = sqlite3.Row
    try:
        # The copy may already carry real events -- outcomes recorded by hand in
        # the app. Everything below is asserted as a DELTA from this baseline;
        # hardcoding absolute counts breaks the moment one more is recorded.
        baseline_events = int(conn.execute(
            "SELECT COUNT(*) FROM application_events").fetchone()[0])
        # Six old (definitely mature) applications to attach outcomes to.
        rows = conn.execute(
            "SELECT id FROM applications WHERE user_id = ? AND DateTime < '2024-06-01' "
            "ORDER BY id LIMIT 7", (USER_ID,)).fetchall()
        ids = [int(r["id"]) for r in rows]
        assert len(ids) == 7, "need seven historical applications to seed"

        # One acknowledgement, one "viewed" -- neither is a response.
        add_event(conn, ids[0], "acked", "2024-04-02 09:00:00", external_id="e-ack")
        add_event(conn, ids[1], "viewed", "2024-04-03 09:00:00", external_id="e-view")
        # A real response five days after applying.
        applied = conn.execute("SELECT DateTime FROM applications WHERE id = ?",
                               (ids[2],)).fetchone()["DateTime"]
        applied_at = datetime.datetime.strptime(applied[:19], "%Y-%m-%d %H:%M:%S")
        add_event(conn, ids[2], "responded",
                  (applied_at + datetime.timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"),
                  external_id="e-resp")
        # An interview, which implies a response even with no 'responded' row.
        add_event(conn, ids[3], "interviewed", "2024-05-02 09:00:00", external_id="e-int")
        # An explicit rejection: not a response, but not ghosted either.
        add_event(conn, ids[4], "rejected", "2024-05-03 09:00:00", external_id="e-rej")
        # An offer, the top of the ladder.
        add_event(conn, ids[5], "offer", "2024-05-04 09:00:00", external_id="e-off")
        # An online assessment and nothing else: an optional stage, and the only
        # application that actually sat one.
        add_event(conn, ids[6], "assessment", "2024-05-06 09:00:00", external_id="e-assess")
        # An outcome we could not attribute to any application.
        add_event(conn, None, "responded", "2024-05-05 09:00:00", external_id="e-orphan")

        # An application from yesterday: real, but far too recent to judge.
        recent = (NOW - datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.execute(
            "INSERT INTO applications (user_id, DateTime, Platform, companyName, jobTitle, "
            "JobDescriptionText, QsAndAs, cover_letter, job_key) "
            "VALUES (?, ?, 'Indeed', 'Too Recent Inc', 'Data Analyst', ?, '[]', '', 'jk-new')",
            (USER_ID, recent, "Pay: $90,000.00 - $100,000.00 per year"))
        recent_id = int(cursor.lastrowid)
        conn.commit()
    finally:
        conn.close()

    stats.clear_cache()
    return db, ids, recent_id, baseline_events


def test_response_definition(db, ids, baseline_events) -> None:
    print("\nan acknowledgement is not a response")
    out = stats.compute(db, USER_ID, now=NOW)
    f = out["funnel"]

    # ids[2] responded, ids[3] interviewed, ids[5] offer, and ids[6] assessment.
    # An assessment counts: someone actively put work in front of you, which is a
    # real response in a way an automated acknowledgement is not.
    # ids[0] acked and ids[1] viewed must NOT count.
    eq("acknowledgements and views are excluded, assessments included",
       f["responded"], 4)
    stage = {s["key"]: s["count"] for s in f["stages"]}
    # Five, not six: `rejected` is OFF the ladder, so the application that only
    # ever got a rejection has no ladder rank at all. It is counted under
    # `rejected` instead -- a rejection is not evidence of an acknowledgement.
    eq("acked counts everything at rank 1 and above", stage["acked"], 6)
    eq("viewed counts rank 2 and above", stage["viewed"], 5)
    eq("responded counts rank 3 and above", stage["responded"], 4)
    eq("screened counts only the two that got that far", stage["screened"], 2)
    eq("interviewed counts the interview and the offer", stage["interviewed"], 2)
    eq("offer counts only the offer", stage["offer"], 1)
    # Built from the live ladder so adding a stage does not silently skip this.
    required = [name for name in
                sorted(stats.STAGE_RANK, key=lambda k: stats.STAGE_RANK[k])
                if name not in stats.OPTIONAL_STAGES]
    check("the required ladder is monotonically non-increasing",
          all(stage[a] >= stage[b] for a, b in zip(required, required[1:])),
          str(stage))

    print("\noptional stages are counted from what actually happened")
    # Nothing seeded an assessment or a one-way interview, yet two applications
    # reached interview and offer. Counting cumulatively would wrongly report
    # that those candidates sat an assessment.
    by_key = {s["key"]: s for s in f["stages"]}
    for name in sorted(stats.OPTIONAL_STAGES):
        check(f"{name} is flagged optional", by_key[name]["optional"] is True)
        check(f"{name} reports no conversion from the previous rung",
              by_key[name]["fromPrevious"] is None)
    eq("the one seeded assessment is counted", by_key["assessment"]["count"], 1)
    # Two applications reached interview and offer, which are ranked ABOVE the
    # assessment. Cumulative counting would report 3 here.
    eq("a one-way interview nobody sat stays at zero", by_key["one_way"]["count"], 0)
    check("required stages still report a conversion",
          by_key["screened"]["fromPrevious"] is not None)

    print("\nrejections and ghosting are distinguished")
    eq("the explicit rejection is counted", f["rejected"], 1)
    # Ghosted = mature, no response, and no explicit rejection. The rejected one
    # and the three responders are all excluded.
    eq("ghosted excludes both responders and explicit rejections",
       f["ghosted"], f["applied"] - 4 - 1)

    print("\nunattributed outcomes are reported, not dropped")
    eq("the orphan event is surfaced in meta", out["meta"]["unattributedEvents"], 1)
    eq("the eight seeded events are all counted",
       out["meta"]["eventCount"] - baseline_events, 8)


def test_maturity_window(db, recent_id) -> None:
    print("\nimmature applications are excluded from rates")
    out = stats.compute(db, USER_ID, now=NOW, maturity_days=21)
    meta = out["meta"]
    check("yesterday's application is not mature",
          meta["mature"] + meta["excludedTooRecent"] == meta["totalApplications"])
    check("at least the one we just inserted is excluded", meta["excludedTooRecent"] >= 1)
    eq("the maturity window is reported", meta["maturityDays"], 21)

    # Raising the window must move applications out of the denominator, never in.
    wide = stats.compute(db, USER_ID, now=NOW, maturity_days=365)
    check("a longer window never grows the mature set",
          wide["meta"]["mature"] <= meta["mature"],
          f"{meta['mature']} -> {wide['meta']['mature']}")

    # maturity_days=0 means "judge everything", which must include the recent row.
    everything = stats.compute(db, USER_ID, now=NOW, maturity_days=0)
    eq("a zero window includes every application",
       everything["meta"]["mature"], everything["meta"]["totalApplications"])
    eq("and excludes none", everything["meta"]["excludedTooRecent"], 0)


def test_timing(db, ids) -> None:
    print("\ntiming is measured from the application date")
    out = stats.compute(db, USER_ID, now=NOW)
    response = out["timing"]["response"]
    check("time-to-response has a sample", response["n"] >= 1, str(response))
    # ids[2]'s response was seeded exactly five days after it was submitted.
    check("the seeded five-day gap is in range",
          response["median"] is not None and 0 <= response["median"] <= 400,
          str(response))
    check("p90 is at least the median",
          response["p90"] >= response["median"], str(response))


def test_small_samples(db) -> None:
    print("\nsmall samples are flagged, not rated")
    out = stats.compute(db, USER_ID, now=NOW, min_n=10_000)
    for name in ("bySalaryBand", "byEmploymentType", "byTitle", "byCompany"):
        rows = out[name]
        check(f"{name}: every bucket is flagged as too small with an absurd min_n",
              all(not r["enough"] for r in rows),
              f"{[r['label'] for r in rows if r['enough']]}")

    out = stats.compute(db, USER_ID, now=NOW, min_n=1)
    check("with min_n=1 non-empty buckets are rated",
          all(r["enough"] for r in out["bySalaryBand"] if r["n"] >= 1))


def test_wilson() -> None:
    print("\nconfidence intervals behave")
    low, high = stats.wilson_interval(0, 100)
    check("zero successes gives a lower bound of exactly 0", low == 0.0, str(low))
    check("zero successes still gives a non-zero upper bound", high > 0.0, str(high))
    low, high = stats.wilson_interval(5, 100)
    check("the interval brackets the point estimate", low < 0.05 < high, f"{low}-{high}")
    low, high = stats.wilson_interval(50, 100)
    check("a wide interval stays inside [0, 1]", 0.0 <= low and high <= 1.0, f"{low}-{high}")
    # A smaller sample at the same rate must be less certain.
    narrow = stats.wilson_interval(50, 1000)
    wide = stats.wilson_interval(5, 100)
    check("a larger sample gives a tighter interval",
          (narrow[1] - narrow[0]) < (wide[1] - wide[0]))
    eq("an empty sample is not a crash", stats.wilson_interval(0, 0), (0.0, 0.0))
    eq("percentile of nothing is None", stats.percentile([], 0.5), None)
    eq("percentile of one value is that value", stats.percentile([4.0], 0.9), 4.0)


def test_denominators(db) -> None:
    print("\nevery dimension accounts for every mature application")
    out = stats.compute(db, USER_ID, now=NOW, top_n=5)
    mature = out["meta"]["mature"]
    for name in ("bySearch", "bySalaryBand", "byEmploymentType", "byWorkMode",
                 "byTitle", "byCompany", "byQuestionCount", "byCoverLetter", "byWeekday"):
        total = sum(r["n"] for r in out[name])
        eq(f"{name} sums to the mature total", total, mature)
    check("the truncated dimensions really did spill into an Other row",
          any(r["label"].startswith("Other (") for r in out["byTitle"]),
          str([r["label"] for r in out["byTitle"]]))


def test_http(db) -> None:
    print("\nover HTTP")
    client = create_app(db, None).test_client()
    res = client.get(f"/api/users/{USER_ID}/stats")
    eq("GET /stats is 200", res.status_code, 200)
    payload = res.get_json()
    check("the payload carries meta, funnel and the cuts",
          all(k in payload for k in ("meta", "funnel", "timing", "pipeline",
                                     "volume", "coverage", "bySearch")))
    eq("a negative maturity is rejected",
       client.get(f"/api/users/{USER_ID}/stats?maturity=-1").status_code, 400)
    eq("a zero minN is rejected",
       client.get(f"/api/users/{USER_ID}/stats?minN=0").status_code, 400)
    eq("a non-numeric maturity falls back to the default",
       client.get(f"/api/users/{USER_ID}/stats?maturity=abc")
       .get_json()["meta"]["maturityDays"], stats.DEFAULT_MATURITY_DAYS)
    # A user with no applications must render, not 500.
    empty = client.get("/api/users/424242/stats")
    eq("an unknown user is an empty result, not an error", empty.status_code, 200)
    eq("and reports zero applications",
       empty.get_json()["meta"]["totalApplications"], 0)


def test_cache_is_not_a_lie(db) -> None:
    print("\nthe derived-dimension cache does not change answers")
    stats.clear_cache()
    cold = stats.compute(db, USER_ID, now=NOW)
    warm = stats.compute(db, USER_ID, now=NOW)
    # computedAt is wall-clock, everything else must be identical.
    cold["meta"]["computedAt"] = warm["meta"]["computedAt"] = "pinned"
    check("a warm computation equals a cold one", cold == warm)


def main() -> int:
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}", file=sys.stderr)
        return 1

    test_wilson()
    with tempfile.TemporaryDirectory() as tmpdir:
        db, ids, recent_id, baseline_events = build(Path(tmpdir))
        test_response_definition(db, ids, baseline_events)
        test_maturity_window(db, recent_id)
        test_timing(db, ids)
        test_small_samples(db)
        test_denominators(db)
        test_http(db)
        test_cache_is_not_a_lie(db)

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
