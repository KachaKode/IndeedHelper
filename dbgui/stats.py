"""Application funnel statistics, computed on demand.

Nothing here is stored or cached: every number is derived per request from
applications, application_events and job_searches, the same way every other read
in dbgui hits SQLite fresh. At this volume (~1,700 applications for the active
user) a full pass costs well under a second, which is cheaper than keeping a
denormalised copy honest.

Two decisions shape every number below, and both exist to stop the page flattering
the operator:

1. ACKNOWLEDGEMENTS ARE NOT RESPONSES. "We received your application" and Indeed's
   "your application was viewed" are automated and near-universal. Counting them
   would report a response rate around 80% that means nothing. A response means a
   human asked for something: RESPONSE_RANK and above.

2. RATES EXCLUDE IMMATURE APPLICATIONS. An application sent three days ago has not
   been ignored; one from sixty days ago has. Leaving recent applications in the
   denominator makes every rate a function of WHEN you applied rather than WHAT you
   applied to -- and with 192 applications in the last month against 1,546 from
   2024, that effect would dominate everything. Applications younger than
   `maturity_days` are excluded from rates and reported separately, so the
   exclusion is visible rather than buried.

Small samples are the third trap. A 5% response rate over 1,700 applications is
~85 responses; split across ten salary bands that is single digits per cell, where
noise looks exactly like insight. Every rate therefore carries a Wilson score
interval, and any cell below `min_n` is flagged `enough: False` so the UI can show
the count instead of a meaningless percentage.
"""

from __future__ import annotations

import datetime
from math import sqrt
from typing import Any, Callable, Iterable, Sequence

from .data import IndeedDB
from . import derive

# --------------------------------------------------------------------------
# the stage ladder
# --------------------------------------------------------------------------

# Ranked, so "furthest stage reached" is a max(). Gaps are deliberate: an
# application that reaches `interviewed` without a recorded `screened` still
# counts as having responded and been screened, because the ladder is cumulative.
STAGE_RANK: dict[str, int] = {
    "acked": 1,
    "viewed": 2,
    "responded": 3,
    "screened": 4,
    "interviewed": 5,
    "final": 6,
    "offer": 7,
}

STAGE_LABELS: dict[str, str] = {
    "acked": "Acknowledged",
    "viewed": "Viewed by employer",
    "responded": "Real response",
    "screened": "Screening call",
    "interviewed": "Interview",
    "final": "Final round",
    "offer": "Offer",
}

# Off-ladder outcomes: they can arrive from any stage and do not imply progress.
TERMINAL_EVENTS = {"rejected", "withdrawn"}

# The line between "they sent a template" and "a human wants something".
RESPONSE_RANK = 3
SCREEN_RANK = 4
INTERVIEW_RANK = 5

UNSPECIFIED = "Unspecified"
UNATTRIBUTED = "Unattributed"

DEFAULT_MATURITY_DAYS = 21
DEFAULT_MIN_N = 15
DEFAULT_TOP_N = 12

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

AGE_BUCKETS: tuple[tuple[int | None, str], ...] = (
    (7, "0-7 days"),
    (21, "8-21 days"),
    (45, "22-45 days"),
    (90, "46-90 days"),
    (None, "90+ days"),
)

QUESTION_BUCKETS: tuple[tuple[int | None, str], ...] = (
    (0, "None"),
    (2, "1-2"),
    (5, "3-5"),
    (10, "6-10"),
    (None, "11+"),
)

COVER_LETTER_BUCKETS: tuple[tuple[int | None, str], ...] = (
    (0, "None"),
    (800, "Short (<800)"),
    (1600, "Medium (800-1600)"),
    (2600, "Long (1600-2600)"),
    (None, "Very long (2600+)"),
)

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


# --------------------------------------------------------------------------
# maths -- no numpy/scipy, dbgui has no such dependency
# --------------------------------------------------------------------------

def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """A 95% confidence interval for a proportion.

    Wilson rather than the textbook normal approximation because these counts are
    small and the rates are near zero, exactly where the normal approximation
    produces nonsense like a negative lower bound.
    """
    if total <= 0:
        return (0.0, 0.0)
    proportion = successes / total
    denominator = 1.0 + (z * z) / total
    centre = (proportion + (z * z) / (2.0 * total)) / denominator
    margin = (z / denominator) * sqrt(
        proportion * (1.0 - proportion) / total + (z * z) / (4.0 * total * total)
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Linear-interpolated percentile, or None for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return float(ordered[lower])
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))


def parse_timestamp(text: Any) -> datetime.datetime | None:
    """applications.DateTime and application_events.occurred_at are both stored as
    'YYYY-MM-DD HH:MM:SS' local time -- verified 19 characters on every row."""
    if not isinstance(text, str) or len(text) < 19:
        return None
    try:
        return datetime.datetime.strptime(text[:19], TIMESTAMP_FORMAT)
    except ValueError:
        return None


def _bucket(value: float, buckets: Iterable[tuple[int | None, str]]) -> str:
    for ceiling, label in buckets:
        if ceiling is None or value <= ceiling:
            return label
    return UNSPECIFIED


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def _load_applications(
    db: IndeedDB, user_id: int, since: str | None, until: str | None
) -> list[dict[str, Any]]:
    """Every application for one user, with the fields the cuts below need.

    Columns are qualified with `applications.` because the join to job_searches
    introduces a second user_id, exactly as data._application_filter warns.
    cover_letter is measured in SQL rather than fetched: only its length is ever
    used, and the text is large.
    """
    where = ["applications.user_id = ?"]
    params: list[Any] = [user_id]
    if since:
        where.append("applications.DateTime >= ?")
        params.append(since)
    if until:
        where.append("applications.DateTime <= ?")
        params.append(until)

    sql = (
        "SELECT applications.id, applications.DateTime, applications.companyName, "
        "applications.jobTitle, applications.JobDescriptionText, applications.search_id, "
        "applications.job_key, applications.QsAndAs, "
        "LENGTH(COALESCE(applications.cover_letter, '')) AS coverLetterLen, "
        "job_searches.target_position AS searchLabel "
        "FROM applications "
        "LEFT JOIN job_searches ON job_searches.id = applications.search_id "
        f"WHERE {' AND '.join(where)}"
    )
    with db._connect() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _load_events(db: IndeedDB, user_id: int) -> tuple[dict[int, list[dict]], int]:
    """Events grouped by application_id, plus the count that could not be attributed.

    Unattributed events (application_id NULL) are real outcomes we could not tie to
    a row. They are reported in `meta` rather than dropped, so the page never
    quietly understates what happened.
    """
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT application_id, event_type, occurred_at FROM application_events "
            "WHERE user_id = ?",
            (user_id,),
        ).fetchall()

    grouped: dict[int, list[dict]] = {}
    unattributed = 0
    for row in rows:
        app_id = row["application_id"]
        if app_id is None:
            unattributed += 1
            continue
        grouped.setdefault(int(app_id), []).append(
            {"type": row["event_type"], "at": parse_timestamp(row["occurred_at"])}
        )
    return grouped, unattributed


# --------------------------------------------------------------------------
# per-application enrichment
# --------------------------------------------------------------------------

# Derived dimensions, keyed by application id.
#
# Safe to cache for the life of the process because an applications row is
# WRITE-ONCE: there is no "UPDATE applications" anywhere in the codebase, main3.py
# only ever inserts, and dbgui exposes the table as read-only. So a derived value
# for a given id can never go stale -- new applications simply get new ids.
#
# This matters because deriving is the expensive part (~1.6s of regex over 6.8 MB
# for the active user), and the page is reloaded every time a filter changes.
# Bounded in practice by the number of applications ever submitted.
_DERIVED_CACHE: dict[int, dict[str, Any]] = {}


def clear_cache() -> None:
    """Drop the derived-dimension cache. For tests, and for a caller that has
    reason to believe stored text changed under it."""
    _DERIVED_CACHE.clear()


def _derived(app: dict[str, Any]) -> dict[str, Any]:
    app_id = int(app["id"])
    cached = _DERIVED_CACHE.get(app_id)
    if cached is None:
        description = app.get("JobDescriptionText") or ""
        questions = IndeedDB.parse_stored_literal(app.get("QsAndAs"))
        cached = {
            "salaryBand": derive.salary_band(description),
            "employmentType": derive.employment_type(description),
            "workMode": derive.work_mode(description),
            "titleCluster": derive.title_cluster(app.get("jobTitle") or ""),
            "questionCount": len(questions) if isinstance(questions, list) else 0,
        }
        _DERIVED_CACHE[app_id] = cached
    return cached


def _enrich(
    applications: list[dict[str, Any]],
    events: dict[int, list[dict]],
    now: datetime.datetime,
    maturity_days: int,
) -> None:
    """Attach outcome and derived-dimension fields to each application in place."""
    for app in applications:
        applied_at = parse_timestamp(app.get("DateTime"))
        app["_appliedAt"] = applied_at
        # Clamped at zero: an application cannot be negatively old. A future
        # DateTime means clock skew (or a pinned `now` in tests), and letting the
        # age go negative would drop those rows even at maturity_days=0, breaking
        # the contract that a zero window judges everything.
        age_days = max(0, (now - applied_at).days) if applied_at else None
        app["_ageDays"] = age_days
        app["_mature"] = age_days is not None and age_days >= maturity_days

        own = events.get(int(app["id"]), [])
        ranks = [STAGE_RANK[e["type"]] for e in own if e["type"] in STAGE_RANK]
        app["_maxRank"] = max(ranks) if ranks else 0
        app["_rejected"] = any(e["type"] == "rejected" for e in own)
        app["_withdrawn"] = any(e["type"] == "withdrawn" for e in own)

        app["_responded"] = app["_maxRank"] >= RESPONSE_RANK
        app["_screened"] = app["_maxRank"] >= SCREEN_RANK
        app["_interviewed"] = app["_maxRank"] >= INTERVIEW_RANK
        app["_offer"] = app["_maxRank"] >= STAGE_RANK["offer"]

        # Ghosted is derived, never stored: nothing beyond an automated
        # acknowledgement, no explicit rejection, and old enough to judge.
        app["_ghosted"] = (
            app["_mature"] and not app["_responded"]
            and not app["_rejected"] and not app["_withdrawn"]
        )

        app["_daysTo"] = {}
        if applied_at:
            for label, threshold in (("response", RESPONSE_RANK),
                                     ("screen", SCREEN_RANK),
                                     ("interview", INTERVIEW_RANK)):
                reached = [
                    e["at"] for e in own
                    if e["at"] and STAGE_RANK.get(e["type"], 0) >= threshold
                ]
                if reached:
                    app["_daysTo"][label] = max(
                        0.0, (min(reached) - applied_at).total_seconds() / 86400.0)

        dimensions = _derived(app)
        app["_salaryBand"] = dimensions["salaryBand"]
        app["_employmentType"] = dimensions["employmentType"]
        app["_workMode"] = dimensions["workMode"]
        app["_titleCluster"] = dimensions["titleCluster"]
        app["_questionCount"] = dimensions["questionCount"]

        # The description is the largest column in the row and nothing downstream
        # needs it once the dimensions are derived. Dropping it here keeps the
        # response payload small rather than shipping ~7 MB of prose to the UI.
        app["JobDescriptionText"] = None
        app["QsAndAs"] = None


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------

def _rate_row(label: str, group: list[dict[str, Any]], min_n: int) -> dict[str, Any]:
    total = len(group)
    responded = sum(1 for a in group if a["_responded"])
    interviewed = sum(1 for a in group if a["_interviewed"])
    low, high = wilson_interval(responded, total)
    return {
        "label": label,
        "n": total,
        "responded": responded,
        "rate": (responded / total) if total else 0.0,
        "ciLow": low,
        "ciHigh": high,
        "interviewed": interviewed,
        "interviewRate": (interviewed / total) if total else 0.0,
        # False means "show the count, not the percentage" -- the sample is too
        # small for the rate to mean anything.
        "enough": total >= min_n,
    }


def _slice(
    applications: list[dict[str, Any]],
    key: Callable[[dict[str, Any]], str | None],
    min_n: int,
    *,
    order: Sequence[str] | None = None,
    top: int | None = None,
    unspecified_label: str = UNSPECIFIED,
) -> list[dict[str, Any]]:
    """Group by one dimension and rate each bucket.

    A None key becomes an explicit bucket rather than being dropped, so the page
    always shows how much of the data a dimension actually covers.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for app in applications:
        buckets.setdefault(key(app) or unspecified_label, []).append(app)

    rows = [_rate_row(label, group, min_n) for label, group in buckets.items()]

    if order:
        rank = {label: i for i, label in enumerate(order)}
        rows.sort(key=lambda r: (rank.get(r["label"], len(rank)), -r["n"]))
    else:
        rows.sort(key=lambda r: (-r["n"], r["label"]))

    if top is not None and len(rows) > top:
        kept, spilled = rows[:top], rows[top:]
        # Roll the tail into one row rather than truncating: the denominator has
        # to keep adding up to the total or every rate on the page is wrong.
        #
        # Read straight out of `buckets`. Re-scanning `applications` and calling
        # key() again is what made this the slowest thing in the module: with ~990
        # title clusters, the tail is ~980 labels and the scan is 1,566 x 980.
        remainder_apps = [app for row in spilled for app in buckets[row["label"]]]
        if remainder_apps:
            kept.append(_rate_row(f"Other ({len(spilled)} more)", remainder_apps, min_n))
        rows = kept
    return rows


def _funnel(mature: list[dict[str, Any]], min_n: int) -> dict[str, Any]:
    total = len(mature)
    stages = []
    previous = total
    for name in sorted(STAGE_RANK, key=lambda k: STAGE_RANK[k]):
        rank = STAGE_RANK[name]
        reached = sum(1 for a in mature if a["_maxRank"] >= rank)
        stages.append({
            "key": name,
            "label": STAGE_LABELS[name],
            "rank": rank,
            "count": reached,
            "ofApplied": (reached / total) if total else 0.0,
            "fromPrevious": (reached / previous) if previous else 0.0,
        })
        previous = reached or previous

    rejected = sum(1 for a in mature if a["_rejected"])
    withdrawn = sum(1 for a in mature if a["_withdrawn"])
    ghosted = sum(1 for a in mature if a["_ghosted"])
    responded = sum(1 for a in mature if a["_responded"])
    low, high = wilson_interval(responded, total)

    return {
        "applied": total,
        "stages": stages,
        "rejected": rejected,
        "withdrawn": withdrawn,
        "ghosted": ghosted,
        "ghostRate": (ghosted / total) if total else 0.0,
        "responded": responded,
        "responseRate": (responded / total) if total else 0.0,
        "responseCiLow": low,
        "responseCiHigh": high,
        "enough": total >= min_n,
    }


def _timing(mature: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label in ("response", "screen", "interview"):
        samples = [a["_daysTo"][label] for a in mature if label in a["_daysTo"]]
        out[label] = {
            "n": len(samples),
            "median": percentile(samples, 0.5),
            "p90": percentile(samples, 0.9),
        }
    return out


def _pipeline(applications: list[dict[str, Any]]) -> dict[str, Any]:
    """Applications still plausibly alive, bucketed by age.

    "Open" excludes an explicit rejection, a withdrawal and an offer; everything
    else is still waiting, whether or not it ever will be.
    """
    open_apps = [
        a for a in applications
        if not a["_rejected"] and not a["_withdrawn"] and not a["_offer"]
    ]
    counts = {label: 0 for _, label in AGE_BUCKETS}
    for app in open_apps:
        if app["_ageDays"] is None:
            continue
        counts[_bucket(app["_ageDays"], AGE_BUCKETS)] += 1
    return {
        "open": len(open_apps),
        "awaitingResponse": sum(1 for a in open_apps if not a["_responded"]),
        "inProgress": sum(1 for a in open_apps if a["_responded"]),
        "byAge": [{"label": label, "count": counts[label]} for _, label in AGE_BUCKETS],
    }


def _volume(applications: list[dict[str, Any]], now: datetime.datetime) -> dict[str, Any]:
    by_month: dict[str, int] = {}
    by_day: dict[str, int] = {}
    cutoff = now - datetime.timedelta(days=60)
    for app in applications:
        applied_at = app["_appliedAt"]
        if not applied_at:
            continue
        by_month[applied_at.strftime("%Y-%m")] = by_month.get(applied_at.strftime("%Y-%m"), 0) + 1
        if applied_at >= cutoff:
            key = applied_at.strftime("%Y-%m-%d")
            by_day[key] = by_day.get(key, 0) + 1

    companies = {(a.get("companyName") or "").strip() for a in applications}
    companies.discard("")
    return {
        "byMonth": [{"label": k, "count": by_month[k]} for k in sorted(by_month)],
        "byDay": [{"label": k, "count": by_day[k]} for k in sorted(by_day)],
        "uniqueCompanies": len(companies),
        "repeatApplications": max(0, len(applications) - len(companies)),
    }


def _coverage(applications: list[dict[str, Any]], field: str) -> float:
    if not applications:
        return 0.0
    known = sum(1 for a in applications if a.get(field))
    return known / len(applications)


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def compute(
    db: IndeedDB,
    user_id: int,
    *,
    since: str | None = None,
    until: str | None = None,
    maturity_days: int = DEFAULT_MATURITY_DAYS,
    min_n: int = DEFAULT_MIN_N,
    top_n: int = DEFAULT_TOP_N,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Everything the Stats page shows, as one JSON-serialisable blob."""
    now = now or datetime.datetime.now()
    maturity_days = max(0, int(maturity_days))
    min_n = max(1, int(min_n))

    applications = _load_applications(db, user_id, since, until)
    events, unattributed = _load_events(db, user_id)
    _enrich(applications, events, now, maturity_days)

    mature = [a for a in applications if a["_mature"]]
    immature = len(applications) - len(mature)
    # Recorded outcomes sitting on applications too recent to rate. Excluding
    # these is correct -- counting a recent RESPONDER while excluding recent
    # non-responders would bias every rate upward -- but it is also surprising
    # ("I just recorded a reply and nothing moved"), so it is reported rather
    # than left for the user to discover.
    immature_with_outcome = sum(
        1 for a in applications if not a["_mature"] and a["_maxRank"] >= RESPONSE_RANK)
    timestamps = [a["_appliedAt"] for a in applications if a["_appliedAt"]]

    return {
        "meta": {
            "userId": user_id,
            "totalApplications": len(applications),
            # Stated on the page, not hidden: every rate below is over `mature`
            # only, and this is how much was held back and why.
            "maturityDays": maturity_days,
            "mature": len(mature),
            "excludedTooRecent": immature,
            "excludedWithOutcome": immature_with_outcome,
            "minN": min_n,
            "eventCount": sum(len(v) for v in events.values()) + unattributed,
            "unattributedEvents": unattributed,
            "firstApplication": min(timestamps).strftime(TIMESTAMP_FORMAT) if timestamps else None,
            "lastApplication": max(timestamps).strftime(TIMESTAMP_FORMAT) if timestamps else None,
            "since": since,
            "until": until,
            "computedAt": now.strftime(TIMESTAMP_FORMAT),
        },
        "funnel": _funnel(mature, min_n),
        "timing": _timing(mature),
        "pipeline": _pipeline(applications),
        "volume": _volume(applications, now),
        "coverage": {
            "salaryBand": _coverage(applications, "_salaryBand"),
            "employmentType": _coverage(applications, "_employmentType"),
            "workMode": _coverage(applications, "_workMode"),
            "searchAttributed": _coverage(applications, "search_id"),
            "jobKey": _coverage(applications, "job_key"),
        },
        "bySearch": _slice(mature, lambda a: (a.get("searchLabel") or "").strip() or None,
                           min_n, top=top_n, unspecified_label=UNATTRIBUTED),
        "bySalaryBand": _slice(mature, lambda a: a["_salaryBand"], min_n,
                               order=derive.SALARY_BAND_ORDER),
        "byEmploymentType": _slice(mature, lambda a: a["_employmentType"], min_n,
                                   order=derive.EMPLOYMENT_TYPE_ORDER),
        "byWorkMode": _slice(mature, lambda a: a["_workMode"], min_n,
                             order=derive.WORK_MODE_ORDER),
        "byTitle": _slice(mature, lambda a: a["_titleCluster"], min_n, top=top_n),
        "byCompany": _slice(mature, lambda a: (a.get("companyName") or "").strip() or None,
                            min_n, top=top_n),
        "byQuestionCount": _slice(
            mature, lambda a: _bucket(a["_questionCount"], QUESTION_BUCKETS), min_n,
            order=[label for _, label in QUESTION_BUCKETS]),
        "byCoverLetter": _slice(
            mature, lambda a: _bucket(a.get("coverLetterLen") or 0, COVER_LETTER_BUCKETS),
            min_n, order=[label for _, label in COVER_LETTER_BUCKETS]),
        "byWeekday": _slice(
            mature,
            lambda a: WEEKDAYS[a["_appliedAt"].weekday()] if a["_appliedAt"] else None,
            min_n, order=list(WEEKDAYS)),
    }
