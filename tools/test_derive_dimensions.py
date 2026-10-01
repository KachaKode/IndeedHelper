"""Tests for dbgui/derive.py -- job attributes mined out of stored text.

Pure string functions, so this needs no database, no network and no browser.
The cases below are real phrasings taken from applications.JobDescriptionText
and applications.jobTitle, not invented ones.

    python tools/test_derive_dimensions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbgui import derive  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def eq(label: str, got, want) -> None:
    check(label, got == want, f"got {got!r}, want {want!r}")


def test_salary_periods() -> None:
    print("\nsalary: the period after an amount decides what it means")
    eq("an explicit annual range takes both ends",
       derive.salary_band("Pay: $65,000.00 - $80,000.00 per year"), "$60k-$80k")
    eq("an hourly range is annualised at 2080 hours",
       derive.salary_band("Pay: $70.00 - $95.00 per hour"), "$160k+")
    eq("a single hourly rate is annualised",
       derive.salary_midpoint("Pay: From $17.00 per hour"), 17.0 * 2080)
    eq("a monthly figure is annualised",
       derive.salary_midpoint("$5,000 per month"), 60_000.0)
    eq("a weekly figure is annualised",
       derive.salary_midpoint("$1,500 a week"), 78_000.0)
    eq("the K suffix expands", derive.salary_midpoint("$80K - $100K a year"), 90_000.0)


def test_salary_rejects_non_pay_amounts() -> None:
    print("\nsalary: amounts that are not this job's pay stay out")
    # Real case: the range is the pay, the stipend is not. The median is what
    # keeps a stray figure from dragging the band.
    eq("a WFH stipend does not move the band",
       derive.salary_band("salary ranges from $66,000-$80,000 ... $300 one-time WFH stipend"),
       "$60k-$80k")
    eq("a bare mid-size amount with no period is discarded",
       derive.annual_salaries("a $5,000 signing bonus"), [])
    eq("a huge revenue figure is out of band",
       derive.annual_salaries("managed a $5,000,000 book of business"), [])
    eq("text with no dollar amount yields nothing",
       derive.salary_band("Competitive pay and great benefits"), None)


def test_salary_magnitude_fallback() -> None:
    print("\nsalary: an amount with no period is only trusted when unambiguous")
    # Real case: a Spanish-language posting, so no English period word is nearby.
    eq("a small bare amount reads as hourly",
       derive.salary_midpoint("Sueldo: $25.00 la hora"), 25.0 * 2080)
    eq("a large bare amount reads as annual",
       derive.salary_midpoint("$40,000+ salary, commensurate with experience"), 40_000.0)
    eq("an ambiguous mid-size bare amount is dropped",
       derive.annual_salaries("$800 for the equipment"), [])


def test_employment_type() -> None:
    print("\nemployment type: the narrower fact wins")
    eq("plain full-time", derive.employment_type("Job Type: Full-time"), "Full-time")
    eq("part-time", derive.employment_type("This is a part-time role"), "Part-time")
    eq("a full-time contract is a contract",
       derive.employment_type("Full-time contract position, W2"), "Contract")
    eq("corp-to-corp counts as contract",
       derive.employment_type("Open to corp-to-corp candidates"), "Contract")
    eq("an internship is not mistaken for full-time",
       derive.employment_type("Full-time summer internship"), "Internship")
    eq("silence yields None", derive.employment_type("We value teamwork."), None)

    # A labelled line is better evidence than prose mentioning another arrangement.
    eq("a labelled line beats an incidental mention elsewhere",
       derive.employment_type(
           "Job type: Full-time\nYou will support our contract negotiation team."),
       "Full-time")


def test_work_mode_is_conservative() -> None:
    print("\nwork mode: a bare mention of 'remote' proves nothing")
    # 81.6% of descriptions contain the word "remote" because the searches filter
    # on l=Remote. Counting those would make the dimension a restatement of which
    # search ran, so only explicit statements count.
    eq("an incidental mention is not a claim",
       derive.work_mode("We also support remote collaboration tools."), None)
    eq("an explicit phrase counts",
       derive.work_mode("This is a fully remote position."), "Remote")
    eq("hybrid is detected", derive.work_mode("Hybrid: 3 days in office"), "Hybrid")
    eq("a negation is read as on-site",
       derive.work_mode("This is not a remote position."), "On-site")
    eq("a labelled line is trusted",
       derive.work_mode("Work Location: Remote"), "Remote")
    # The search URL must never decide the answer, or every application from a
    # remote search would be labelled Remote and the cut would explain nothing.
    eq("a remote search URL alone does not set the mode",
       derive.work_mode("Great team, great benefits.",
                        "https://www.indeed.com/jobs?q=analyst&l=Remote"), None)


def test_title_cluster() -> None:
    print("\ntitle clustering: group the titles that actually occur")
    eq("seniority words are stripped so variants merge",
       derive.title_cluster("Senior Data Analyst"), derive.title_cluster("Data Analyst II"))
    eq("a leading bracketed tag is dropped",
       derive.title_cluster("[Volunteer] Grant Writer (at a Nonprofit)"), "grant writer")
    eq("a parenthetical prefix is dropped",
       derive.title_cluster("(Work from Home) Appointment Setter"), "appointment setter")
    # Taking the FIRST segment would yield "hour" here and "" for the slash case.
    eq("the longest segment wins, not the first",
       derive.title_cluster("$15/Hour - Healthcare Sales Associate - Remote"),
       "healthcare sales")
    check("a slash-joined seniority prefix does not empty the title",
          derive.title_cluster("Senior/Lead Forward Deployed AI Engineer") not in (None, ""))
    # A title made entirely of noise words must not vanish from the cut.
    check("an all-noise title still returns something",
          derive.title_cluster("Associate, Affiliate Marketing") not in (None, ""))
    eq("an empty title yields None", derive.title_cluster(""), None)


def test_no_derivation_crashes_on_real_data() -> None:
    """Every derive function must tolerate whatever is actually in the table."""
    print("\nrobustness: real rows, and the degenerate inputs around them")
    for value in ("", None, "   ", "$", "$$$", "$,", "$." , "abc"):
        try:
            derive.salary_band(value or "")
            derive.employment_type(value or "")
            derive.work_mode(value or "")
            derive.title_cluster(value or "")
        except Exception as exc:  # noqa: BLE001 - that is the thing being tested
            check(f"derivation survives {value!r}", False, repr(exc))
            return
    check("derivation survives empty and malformed input", True)

    db_path = ROOT / "IndHelperDB.db"
    if not db_path.exists():
        print("  [SKIP] no database present; skipped the real-row sweep")
        return

    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT jobTitle, JobDescriptionText FROM applications LIMIT 2000").fetchall()
    finally:
        conn.close()

    banded = 0
    for row in rows:
        description = row["JobDescriptionText"] or ""
        try:
            if derive.salary_band(description):
                banded += 1
            derive.employment_type(description)
            derive.work_mode(description)
            derive.title_cluster(row["jobTitle"] or "")
        except Exception as exc:  # noqa: BLE001
            check("every real row derives without raising", False,
                  f"{exc!r} on {row['jobTitle']!r}")
            return
    check(f"every one of {len(rows)} real rows derives without raising", True)
    # Coverage is a property worth pinning: if a regex change silently stops
    # matching, the page quietly fills with Unspecified instead of breaking.
    coverage = 100.0 * banded / len(rows) if rows else 0.0
    check(f"salary coverage stays plausible ({coverage:.1f}% banded)",
          40.0 <= coverage <= 90.0, f"{coverage:.1f}% is outside the expected 40-90% range")


def main() -> int:
    test_salary_periods()
    test_salary_rejects_non_pay_amounts()
    test_salary_magnitude_fallback()
    test_employment_type()
    test_work_mode_is_conservative()
    test_title_cluster()
    test_no_derivation_crashes_on_real_data()

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
