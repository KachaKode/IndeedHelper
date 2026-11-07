"""A brand-new user must be runnable without anyone creating folders by hand.

Used to be: the Run tab refused to start a user with no Chrome profile path or no
Users/<First Last id> folder ("Cannot start yet"), and the bot itself would have
crashed on either -- ProfilePath=None raised on `+=`, a missing folder raised on
opening the output file, and a folder with no skipped.txt raised on the first job.

Now: both are created when the run starts. Covers
  - ensure_user_workspace creates folder, skipped.txt and the Chrome profile, is
    idempotent, and never clobbers an existing skipped.txt
  - a user renamed after running is NOT given a fresh folder (it would abandon the
    skipped-jobs history in the old one) -- ensure raises, preflight blocks
  - preflight/GET endpoints create nothing on disk (the Run tab polls them)
  - runner.start() on a fresh user saves the default ProfilePath and has the
    folders in place before the child process is launched
  - the Users list tells "not created yet" apart from "needs rename"
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbgui.data import IndeedDB, user_folder_name  # noqa: E402
from dbgui.runner import PreflightError, RunnerManager  # noqa: E402
from dbgui.server import create_app  # noqa: E402
from dbgui.workspace import (  # noqa: E402
    WorkspaceError, default_profile_path, ensure_user_workspace, resolve_profile_path,
)

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        db_copy = root / "IndHelperDB.db"
        shutil.copy2(ROOT / "IndHelperDB.db", db_copy)
        db = IndeedDB(db_copy, project_root=root)

        # ---------------------------------------------------- the helper itself --
        user = {"id": 41, "FirstName": "Pat", "LastName": "Fresh", "ProfilePath": None}
        setup = ensure_user_workspace(root, user)
        folder = root / "Users" / "Pat Fresh 41"
        check("creates Users/ and the user's folder from nothing", folder.is_dir())
        check("creates skipped.txt", (folder / "skipped.txt").is_file())
        profile = default_profile_path(root, 41)
        check("creates the default Chrome profile for a blank ProfilePath", profile.is_dir())
        check("reports a new profile so the run can say to sign in", setup.new_profile)
        check("default profile is absolute and keyed by id, not by name",
              profile.is_absolute() and profile.name == "user_41")
        check("blank ProfilePath resolves to that default",
              resolve_profile_path(root, user) == str(profile))

        (folder / "skipped.txt").write_text("jk123\n\treason: not for me\n", encoding="utf-8")
        again = ensure_user_workspace(root, user)
        check("second call creates nothing", not again.created and not again.new_profile,
              f"created={again.created}")
        check("existing skipped.txt is left untouched",
              (folder / "skipped.txt").read_text(encoding="utf-8").startswith("jk123"))

        custom = root / "my_profiles" / "pat"
        ensure_user_workspace(root, {**user, "ProfilePath": str(custom)})
        check("a configured ProfilePath is used instead of the default, and created", custom.is_dir())

        # --------------------------------------------- renamed after running --
        renamed = {**user, "LastName": "Renamed"}
        raised = ""
        try:
            ensure_user_workspace(root, renamed)
        except WorkspaceError as exc:
            raised = str(exc)
        check("a renamed user's folder is not replaced with a fresh one", "Pat Fresh 41" in raised,
              f"raised={raised!r}")
        check("...and no new folder was made beside the old one",
              not (root / "Users" / "Pat Renamed 41").exists())

        # ------------------------------------------ an uncreatable location --
        blocker = root / "a_file"
        blocker.write_text("x", encoding="utf-8")
        raised = ""
        try:
            ensure_user_workspace(root, {**user, "id": 42, "FirstName": "No", "LastName": "Way",
                                         "ProfilePath": str(blocker / "inside")})
        except WorkspaceError as exc:
            raised = str(exc)
        check("an uncreatable profile path is a readable WorkspaceError", "Chrome profile" in raised,
              f"raised={raised!r}")

        # ---------------------------------- preflight / GETs stay read-only --
        # User 10: ProfilePath NULL, no folder -- the case from the bug report.
        db.add_search(10, "https://www.indeed.com/jobs?q=test")
        db.save_user(10, {"AppsLeft": 5})
        fresh = db.get_user(10)
        runner = RunnerManager(db, root)
        before = tree(root)
        problems = runner.preflight([10])
        client = create_app(db, runner).test_client()
        client.get("/api/run/preflight?user_ids=10")
        client.get("/api/users")
        client.get("/api/users/10")
        client.get("/api/users/10/validate")
        check("preflight no longer blocks on a missing profile or folder",
              not problems, f"problems={[p['message'] for p in problems]}")
        check("preflight and the GET endpoints create nothing on disk", tree(root) == before,
              f"new={tree(root) - before}")

        listed = {u["id"]: u for u in client.get("/api/users").get_json()}
        check("a not-yet-created folder is not flagged as needing rename",
              listed[10]["_folderExists"] is False and listed[10]["_folderOrphan"] is None)
        check("validate raises nothing about the missing folder or profile",
              not [i for i in client.get("/api/users/10/validate").get_json()
                   if i["where"] in ("User Folder", "Chrome Profile")])

        # Renamed user: the old folder is the one that matters.
        (root / "Users" / "Old Name 10").mkdir()
        problems = runner.preflight([10])
        check("preflight still blocks a folder left under an old name",
              len(problems) == 1 and problems[0]["blocking"] and "Old Name 10" in problems[0]["message"],
              f"problems={[p['message'] for p in problems]}")
        listed = {u["id"]: u for u in client.get("/api/users").get_json()}
        check("the Users list marks that case as needing a rename",
              listed[10]["_folderOrphan"] == "Old Name 10")
        issues = client.get("/api/users/10/validate").get_json()
        check("validate offers the rename action for it",
              any(i.get("action") == "renameFolder" for i in issues))
        try:
            runner.start([10])
            blocked = False
        except PreflightError:
            blocked = True
        check("start() refuses the renamed case rather than creating a second folder",
              blocked and not (root / "Users" / user_folder_name(fresh)).exists())
        (root / "Users" / "Old Name 10").rmdir()

        # --------------------------------------------- start() on a fresh user --
        # Stand in for main3.py: report what was on disk at the moment of launch.
        (root / "main3.py").write_text(
            "import sys, time, os, glob\n"
            "folder = glob.glob('Users/* 10')\n"
            "print('[CT]     0.0ms | start_up | ENTER | fake', flush=True)\n"
            "print('[CT]     1.0ms | reportAction | folder_at_launch=%s' % bool(folder), flush=True)\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        runner.start([10])
        time.sleep(2.0)

        after = db.get_user(10)
        expected_profile = str(default_profile_path(root, 10))
        check("start() saved the default ProfilePath to the database",
              after["ProfilePath"] == expected_profile, f"got {after['ProfilePath']!r}")
        check("start() created the Chrome profile directory", Path(expected_profile).is_dir())
        folder10 = root / "Users" / user_folder_name(after)
        check("start() created the bot folder and skipped.txt",
              folder10.is_dir() and (folder10 / "skipped.txt").is_file())
        status = runner.status()[0]
        check("the child saw the folder already in place when it launched",
              (status["lastActivity"] or "").endswith("folder_at_launch=True"),
              f"lastActivity={status['lastActivity']!r}")
        lines = "\n".join(status["lines"])
        check("the run log says what was created and to sign in",
              "[runner] Created folder" in lines and "sign in to Indeed" in lines, lines[:400])

        runner.stop(10)
        time.sleep(1.0)

        # A second run of the same user has nothing left to create.
        runner.start([10])
        time.sleep(1.0)
        lines = "\n".join(runner.status()[0]["lines"])
        check("a second start creates nothing and does not repeat the sign-in note",
              "[runner] Created" not in lines and "sign in to Indeed" not in lines, lines[:400])
        runner.stop_all()
        time.sleep(1.0)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL WORKSPACE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
