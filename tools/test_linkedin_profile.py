"""A LinkedIn profile field in the GUI's Identity section, used directly
whenever a screener question asks for one -- the same canned-fact lookup
main3.py's setDetails()/checkIfAPreMadeAnswerFits() already use for phone,
email and zip, rather than leaving the model to guess or invent a URL.

Fixing checkIfAPreMadeAnswerFits() to actually FIRE was necessary, not
optional: relevantSubStr() also required the WHOLE question text to be
shorter than 1.5x the detail key's own length -- "linkedin" (8 chars)
needed a question under 12 characters, "zip" (3 chars) needed one under 5.
No real screener question is that short ("What is your zip code?" is 23),
so this canned-answer path silently never fired for ANY detail key before
this fix, LinkedIn included -- every one of these questions was already
falling through to a model-generated answer, which is a real risk for a
must-be-exact fact like a profile URL. Never touches IndHelperDB.db --
everything runs on a throwaway copy.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402
from dbgui.data import IndeedDB  # noqa: E402
from dbgui.migrations import add_linkedin_profile  # noqa: E402
from dbgui.server import create_app  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def build_helper(page):
    located = main3.IndeedHelper.__new__(main3.IndeedHelper)
    main3.PlaywrightWrap.__init__(located, "", "", "user-data-dir=")
    located._page = page
    located._context = page.context
    located.outputFile = None
    located.Bad, located.FreeResponse, located.MultChoice = -1, 0, 1
    located.DropDown, located.FreeResponseLong = 2, 3
    located.SelectApplicable, located.DateFill = 4, 5
    located.SearchSelect, located.SelectApplicableCombobox = 6, 7
    return located


def main() -> int:
    print("--- relevantSubStr: realistic-length questions now actually match ---")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        located = build_helper(page)

        check("'linkedin' matches a realistic LinkedIn question",
              located.relevantSubStr("linkedin", "please provide the url to your linkedin profile"))
        check("'linkedin profile' (a longer key) matches too",
              located.relevantSubStr("linkedin profile",
                                     "what is the link to your linkedin profile?"))
        check("'zip' matches a realistic zip-code question -- this was ALSO "
              "broken before, for every detail key, not just linkedin",
              located.relevantSubStr("zip", "what is your zip code?"))
        check("'city' still does NOT match 'electricity' -- a substring of an "
              "unrelated longer word must not count",
              not located.relevantSubStr("city", "which electricity provider do you use?"))
        check("'name' still does NOT match a question that merely contains it "
              "as part of another word",
              not located.relevantSubStr("name", "have you ever used a pseudonymously "
                                                  "registered account?"))

        print()
        print("--- setDetails() populates linkedin from self.linkedin ---")
        located.firstName, located.lastName = "Tommy", "Orok"
        located.phone_num, located.email = "555-555-5555", "t@example.com"
        located.linkedin = "https://www.linkedin.com/in/tommyorok"
        located.addr = "123 Main St"
        located.areaSpec = "Atlanta, GA"
        located.country = "United States"
        located.zip = "30301"
        located.setDetails()
        check("'linkedin' key holds the stored profile URL",
              located.details.get("linkedin") == located.linkedin)
        check("'linkedin profile' key also holds it",
              located.details.get("linkedin profile") == located.linkedin)
        check("'linkedin profile url' key also holds it",
              located.details.get("linkedin profile url") == located.linkedin)

        print()
        print("--- end to end: a real LinkedIn question gets the exact stored "
              "URL, not a model-generated guess ---")
        page.set_content('<div class="ia-Questions-item"><input type="text"></div>')
        page.wait_for_timeout(150)
        questn = located._resolve_matches("//*[contains(@class,'ia-Questions-item')]", None)[0]
        inputBox = located.findAndClick(located.WHOLE, located.WHOLE, ".//input", findFrom=questn)
        filled = located.checkIfAPreMadeAnswerFits(
            "Please share the URL to your LinkedIn profile.",
            located.FreeResponse, {"inputBox": inputBox})
        check("checkIfAPreMadeAnswerFits recognises the question and handles it",
              filled is True)
        check("and the input box now holds the exact stored LinkedIn URL",
              inputBox.get_attribute("value") == located.linkedin,
              f"got {inputBox.get_attribute('value')!r}")

        browser.close()

    print()
    print("--- database: users.LinkedInProfile migration and GUI editing ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_copy = Path(tmpdir) / "test.db"
        shutil.copy2(ROOT / "IndHelperDB.db", db_copy)
        (Path(tmpdir) / "Users").mkdir()

        db = IndeedDB(db_copy, project_root=tmpdir)
        added = add_linkedin_profile(db)
        check("the migration adds the column on a database that lacks it",
              added["added"] is True, f"got {added!r}")

        added_again = add_linkedin_profile(db)
        check("running it again is a no-op (idempotent)",
              added_again["added"] is False, f"got {added_again!r}")

        client = create_app(db).test_client()
        users = client.get("/api/users").get_json()
        user_id = users[0]["id"]
        check("a fresh column reads back as an empty string, not missing/None",
              users[0].get("LinkedInProfile", "MISSING") == "",
              f"got {users[0].get('LinkedInProfile', 'MISSING')!r}")

        resp = client.put(f"/api/users/{user_id}",
                          json={"LinkedInProfile": "https://www.linkedin.com/in/example"})
        check("PUT accepts LinkedInProfile as an editable field",
              resp.status_code == 200, f"status={resp.status_code} body={resp.get_data(as_text=True)}")

        reread = client.get(f"/api/users/{user_id}").get_json()
        check("the saved value round-trips back out",
              reread.get("LinkedInProfile") == "https://www.linkedin.com/in/example",
              f"got {reread.get('LinkedInProfile')!r}")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL LINKEDIN PROFILE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
