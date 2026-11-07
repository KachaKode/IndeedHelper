"""Builds an empty IndHelperDB.db: the full current schema and no rows.

IndHelperDB.db is gitignored (it holds real names, resumes and Indeed
credentials), so a fresh clone has no database at all and db_admin.py exits
with "Database not found". Run this once on the new machine:

    python tools/create_empty_db.py                 # creates ./IndHelperDB.db
    python tools/create_empty_db.py path/to/new.db  # or somewhere else

It never touches an existing database -- it refuses instead, so it cannot wipe
real data by accident. The file is built under a temporary name and only moved
into place once every step has succeeded, so a failed run leaves nothing behind
for the next run to trip over.

The base tables (users, Edu, Job, applications, applicationsOld) are written
here in the shape they had before any migration. dbgui/migrations.py then
brings them up to date, so the result is exactly what db_admin.py would have
healed an older database into.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbgui.data import IndeedDB  # noqa: E402
from dbgui import migrations  # noqa: E402


DB_PATH = ROOT / "IndHelperDB.db"


# Nothing in the code creates these: main3.py's CREATE TABLE for users is
# commented out, and Edu / Job were only ever made by hand. users.homePage is
# the legacy search blob that job_searches replaced; it is kept, not dropped.
BASE_SCHEMA = """
CREATE TABLE "users" (
    "id"                INTEGER,
    "FirstName"         TEXT,
    "LastName"          TEXT,
    "PhoneNumber"       TEXT,
    "email"             TEXT,
    "address"           TEXT,
    "areaSpec"          TEXT,
    "country"           TEXT,
    "zip"               TEXT,
    "IndeedEmail"       TEXT,
    "IndeedPass"        TEXT,
    "Home Page Index"   INTEGER DEFAULT 0,
    "homePage"          TEXT,
    "homePagePattern"   TEXT,
    "ProfilePath"       TEXT,
    "PositionInterests" TEXT,
    "AppsLeft"          INTEGER,
    "Active"            TEXT,
    "LifeSummary"       TEXT,
    "avoid"             BLOB,
    "skipped"           TEXT,
    PRIMARY KEY("id")
);

CREATE TABLE "Edu" (
    "userID"            INTEGER,
    "eduNum"            INTEGER,
    "level"             TEXT,
    "fieldOfStudy"      TEXT,
    "SchoolName"        TEXT,
    "areaSpec"          TEXT,
    "currentlyEnrolled" TEXT,
    "From"              TEXT,
    "To"                TEXT,
    "country"           TEXT,
    FOREIGN KEY("userID") REFERENCES "users"
);

CREATE TABLE "Job" (
    "userID"            INTEGER,
    "jobNum"            INTEGER,
    "JobTitle"          TEXT,
    "CompanyName"       TEXT,
    "CompanyType"       TEXT,
    "areaSpec"          TEXT,
    "currentPosition"   TEXT,
    "From"              TEXT,
    "To"                TEXT,
    "Description"       TEXT,
    "country"           TEXT,
    FOREIGN KEY("userID") REFERENCES "users"
);

CREATE TABLE applications
    (id INTEGER PRIMARY KEY, user_id INTEGER, DateTime TEXT, Platform TEXT,
     companyName TEXT, jobTitle TEXT, JobDescriptionText TEXT,
     fullName TEXT, headline TEXT, jobHist TEXT, eduHist TEXT,
     skills TEXT, resumeSummary TEXT, QsAndAs TEXT, cover_letter TEXT,
     FOREIGN KEY(user_id) REFERENCES users(id));

CREATE TABLE "applicationsOld" (
    "id"            INTEGER,
    "user_id"       INTEGER,
    "opening_info"  TEXT,
    "resume"        TEXT,
    "cover_letter"  TEXT,
    PRIMARY KEY("id"),
    FOREIGN KEY("user_id") REFERENCES "users"("id")
);
"""

# Same order db_admin.py applies them in (add_writing_sample first so the three
# users columns land in the order an older database got them).
COLUMN_MIGRATIONS = (
    migrations.add_writing_sample,
    migrations.add_target_position,
    migrations.add_avoid_employers,
    migrations.add_linkedin_profile,
    migrations.add_max_applications_per_search,
    migrations.add_search_id_to_applications,
    migrations.add_search_subrows,
    migrations.add_job_key_to_applications,
    migrations.add_search_snapshot_to_applications,
    migrations.add_outcome_tracking,
    migrations.add_keyword_info,
)


def build(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        with conn:
            conn.executescript(BASE_SCHEMA)
            migrations.ensure_schema(conn)
            migrations.ensure_vetted_questions_schema(conn)
    finally:
        conn.close()

    db = IndeedDB(path, project_root=ROOT)
    # Every migration snapshots the database before its first write. There is
    # nothing worth protecting in one that was created a moment ago.
    db._backed_up_this_session = True
    for migrate in COLUMN_MIGRATIONS:
        migrate(db)


def main(argv: list[str]) -> int:
    target = Path(argv[1]).resolve() if len(argv) > 1 else DB_PATH
    if target.exists():
        print(f"Refusing to overwrite {target}: it already exists.\n"
              "Move or delete it first if you really want a fresh one.", file=sys.stderr)
        return 1

    building = target.with_name(f"{target.stem}.building{target.suffix}")
    building.unlink(missing_ok=True)
    try:
        build(building)
        os.replace(building, target)
    except BaseException:
        building.unlink(missing_ok=True)
        raise

    conn = sqlite3.connect(target)
    try:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    finally:
        conn.close()
    print(f"Created {target} with {len(tables)} empty tables:")
    for name in tables:
        print(f"    {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
