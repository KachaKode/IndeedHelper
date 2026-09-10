"""Check main3's page selectors against a saved copy of a real Indeed page.

Runs the actual PlaywrightWrap engine over a local file, so this exercises the
same find/filter code the bot uses rather than re-implementing it. Point it at a
fresh capture whenever Indeed changes their markup:

    venv\\Scripts\\python.exe tools/test_selectors.py [path-to.html]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

def capture(name: str) -> Path:
    """Find a saved page. Captures live in HTMLz/, with the older locations
    still searched so nothing breaks if one is left behind."""
    for candidate in (ROOT / "HTMLz" / name, ROOT / name, ROOT / "input" / name):
        if candidate.exists():
            return candidate
    return ROOT / "HTMLz" / name


HTML = Path(sys.argv[1]) if len(sys.argv) > 1 else capture("IndeedHTML.html")
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def main() -> int:
    if not HTML.exists():
        print(f"No HTML capture at {HTML}")
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.goto(HTML.as_uri())
        page.wait_for_timeout(400)

        # Drive the real wrapper, with its page wired to this local capture.
        wrap = main3.PlaywrightWrap.__new__(main3.PlaywrightWrap)
        main3.PlaywrightWrap.__init__(wrap, "", "", "user-data-dir=")
        wrap._page = page
        wrap._context = page.context

        cards = wrap.driver.find_elements(main3.By.CSS_SELECTOR, main3.IndeedHelper.JOB_CARD_SELECTOR)
        check("job card selector finds cards", len(cards) > 0,
              f"{main3.IndeedHelper.JOB_CARD_SELECTOR} matched nothing")
        print(f"         {len(cards)} cards matched")

        # Reproduce process_job_openings' own filter.
        kept = []
        for card in cards:
            try:
                text = card.text
                child_class = wrap.get_child(card).get_attribute("class") or ""
            except Exception:
                continue
            if text and "Easily apply" in text and "card" in child_class:
                kept.append(text.split("\n")[0][:44])

        check("filter keeps the easy-apply jobs", len(kept) > 0,
              "cards matched but none survived the Easily-apply/card filter")
        print(f"         {len(kept)} easy-apply jobs:")
        for k in kept:
            print(f"           - {k}")

        check("every kept card exposes a link to click",
              all(card.find_elements("xpath", ".//a") for card in cards[:5]))

        # The apply button only exists when an easy-apply job is open in the
        # right pane, so its absence here is information, not a failure.
        apply_hits = page.query_selector_all(f"xpath={main3.IndeedHelper.APPLY_BUTTON_XPATH}")
        print()
        print(f"[INFO] apply-button xpath matched {len(apply_hits)} element(s) on this capture")
        if not apply_hits:
            pane = page.query_selector(".jobsearch-RightPane")
            txt = (pane.inner_text()[:120].replace("\n", " ") if pane else "")
            print("       This capture has a non-easy-apply job open in the right pane,")
            print(f"       so no Indeed Apply button is present. Right pane says: {txt!r}")
            print("       Re-run against a capture with an Easily-apply job open to verify it.")
        else:
            for h in apply_hits[:3]:
                print(f"       <{h.evaluate('e => e.tagName')}> "
                      f"class={h.get_attribute('class')} text={h.inner_text()[:40]!r}")

        # ---- the opened job page, if a capture of one is present ----
        job_html = capture("OpeningHTML.html")
        if job_html.exists():
            print()
            print(f"--- job page: {job_html.name} ---")
            page.goto(job_html.as_uri())
            page.wait_for_timeout(300)

            hits = page.query_selector_all(f"xpath={main3.IndeedHelper.APPLY_BUTTON_XPATH}")
            check("apply button found on the job page", len(hits) > 0)
            if hits:
                print(f"         {len(hits)} match(es), first is <{hits[0].evaluate('e=>e.tagName')}> "
                      f"text={hits[0].inner_text().strip()[:30]!r}")

            # getPositionInfo's three lookups
            company = page.query_selector("xpath=//*[@data-testid='inlineHeader-companyName']")
            check("company name element found", company is not None)
            if company:
                print(f"         company={company.inner_text().strip()[:40]!r}")

            title = page.query_selector(
                "xpath=//h1[contains(@class,'jobsearch-JobInfoHeader-title')] | //h1")
            check("job title element found", title is not None)
            if title:
                print(f"         title={title.inner_text().strip().splitlines()[0][:40]!r}")

            desc = page.query_selector("xpath=//*[@id='jobDescriptionText']")
            check("job description element found", desc is not None)
            if desc:
                print(f"         description length={len(desc.inner_text())} chars")

            dead = page.query_selector_all("xpath=//span[contains(text(), '- job post')]")
            check("the retired '- job post' span really is gone", len(dead) == 0,
                  "it still exists, so removing that lookup may have been premature")

        # ---- the resume selection page, if a capture is present ----
        resume_html = capture("RESUME_SELECTION_PAGE_HTML.html")
        if resume_html.exists():
            print()
            print(f"--- resume selection: {resume_html.name} ---")
            page.goto(resume_html.as_uri())
            page.wait_for_timeout(300)

            for label, xpath in (
                ("Indeed-resume card", main3.IndeedHelper.RESUME_CARD_XPATH),
                ("Resume options menu", main3.IndeedHelper.RESUME_OPTIONS_XPATH),
                ("Edit resume details", main3.IndeedHelper.RESUME_EDIT_XPATH),
            ):
                hits = page.query_selector_all(f"xpath={xpath}")
                check(f"{label} found", len(hits) > 0)
                if hits:
                    print(f"         {len(hits)} match(es), first text="
                          f"{hits[0].inner_text().strip()[:38]!r}")

            # The edit link is inside a collapsed menu, so opening it is a real
            # step rather than an optional flourish.
            menu = page.query_selector(f"xpath={main3.IndeedHelper.RESUME_OPTIONS_XPATH}")
            check("options menu starts collapsed (so it must be opened)",
                  menu is not None and menu.get_attribute("aria-expanded") == "false",
                  f"aria-expanded={menu.get_attribute('aria-expanded') if menu else None}")

            check("the retired IndeedResumeCard really is gone",
                  len(page.query_selector_all('xpath=//*[@data-testid="IndeedResumeCard"]')) == 0,
                  "it still exists, so the rewrite may have been premature")

            # This page renders decoy Continue buttons; a text match would take
            # a hidden one and burn a click timeout.
            by_text = page.query_selector_all(
                "xpath=//button[normalize-space(.)='Continue']")
            by_testid = page.query_selector_all(
                f"xpath={main3.IndeedHelper.CONTINUE_BUTTON_XPATH}")
            check("there really are decoy Continue buttons", len(by_text) > 1,
                  f"only {len(by_text)} found -- the workaround may be unnecessary now")
            check("exactly one real Continue button", len(by_testid) == 1,
                  f"found {len(by_testid)} with data-testid=continue-button")
            if by_text and by_testid:
                first_text_match = by_text[0].get_attribute("data-testid")
                check("text matching would have picked a decoy",
                      first_text_match != "continue-button",
                      f"first text match is {first_text_match!r} -- it would have worked anyway")
                print(f"         text match #1 = {first_text_match!r}, "
                      f"real button = 'continue-button'")

        # ---- the resume editor page, if a capture is present ----
        editor_html = capture("Edit_Resume_HTML.html")
        if editor_html.exists():
            print()
            print(f"--- resume editor: {editor_html.name} ---")
            page.goto(editor_html.as_uri())
            page.wait_for_timeout(300)

            for label, xpath in (
                ("Edit contact info", main3.IndeedHelper.CONTACT_EDIT_XPATH),
                ("Edit summary", main3.IndeedHelper.SUMMARY_EDIT_XPATH),
                ("Continue applying", main3.IndeedHelper.FINISH_RESUME_XPATH),
            ):
                hits = page.query_selector_all(f"xpath={xpath}")
                check(f"{label} found", len(hits) > 0)
                if hits:
                    print(f"         aria={hits[0].get_attribute('aria-label')!r} "
                          f"testid={hits[0].get_attribute('data-testid')!r}")

            check("the retired id='edit-contact-info' really is gone",
                  len(page.query_selector_all('xpath=//*[contains(@id,"edit-contact-info")]')) == 0,
                  "it still exists, so the rewrite may have been premature")

            # These buttons carry no text at all, which is why text-based lookups
            # would silently find nothing here.
            btn = page.query_selector('xpath=//*[@data-testid="contact-info-edit-button"]')
            check("section buttons are icon-only (no text to match on)",
                  btn is not None and btn.inner_text().strip() == "",
                  f"text={btn.inner_text()!r}" if btn else "button missing")

        # ---- the resume sub-forms ----
        H = main3.IndeedHelper
        subforms = [
            ("About_You_Page.html", "contact form", [
                ("first name", f'//*[@data-testid="{H.CONTACT_FIELDS[0][0]}"]'),
                ("last name", f'//*[@data-testid="{H.CONTACT_FIELDS[1][0]}"]'),
                ("headline", f'//*[@data-testid="{H.CONTACT_FIELDS[2][0]}"]'),
                ("phone", f'//*[@data-testid="{H.CONTACT_FIELDS[3][0]}"]'),
                ("street address", f'//*[@data-testid="{H.CONTACT_FIELDS[4][0]}"]'),
                ("city/state", f'//*[@data-testid="{H.CONTACT_FIELDS[5][0]}"]'),
                ("postal code", f'//*[@data-testid="{H.CONTACT_FIELDS[6][0]}"]'),
                ("save", H.CONTACT_SAVE_XPATH),
            ]),
            ("Summary_Section.html", "summary editor", [
                ("save summary", H.SUMMARY_SAVE_XPATH),
                ("clear summary", H.SUMMARY_CLEAR_XPATH),
            ]),
            ("work_experience.html", "work experience form", [
                ("job title", f'//*[@data-testid="{H.WORK_TITLE_TESTID}"]'),
                ("company", f'//*[@data-testid="{H.WORK_COMPANY_TESTID}"]'),
                ("location", f'//*[@data-testid="{H.WORK_LOCATION_TESTID}"]'),
                ("currently-here toggle", H.WORK_CURRENT_TOGGLE),
                ("from month", H.WORK_FROM_MONTH),
                ("from year", H.WORK_FROM_YEAR),
                ("to month", H.WORK_TO_MONTH),
                ("to year", H.WORK_TO_YEAR),
                ("description editor", H.DESCRIPTION_XPATH),
                ("bulleted-list button", H.BULLET_LIST_XPATH),
                ("save", H.WORK_SAVE_XPATH),
            ]),
            ("education.html", "education form", [
                ("level", f'//*[@data-testid="{H.EDU_LEVEL_TESTID}"]'),
                ("field of study", f'//*[@data-testid="{H.EDU_FIELD_TESTID}"]'),
                ("school", f'//*[@data-testid="{H.EDU_SCHOOL_TESTID}"]'),
                ("location", f'//*[@data-testid="{H.EDU_LOCATION_TESTID}"]'),
                ("currently-enrolled toggle", H.EDU_CURRENT_TOGGLE),
                ("save", H.EDU_SAVE_XPATH),
            ]),
            ("Add_Skill.html", "add-skill form", [
                ("skill name", f'//*[@data-testid="{H.SKILL_NAME_TESTID}"]'),
                ("save skill", H.SKILL_SAVE_XPATH),
            ]),
            ("Add_contact_info_page_when_program_got_stuck.html", "apply contact step", [
                ("heading", H.APPLY_CONTACT_HEADING),
                ("first name", f'//*[@data-testid="{H.APPLY_FIRST_NAME_TESTID}"]'),
                ("last name", f'//*[@data-testid="{H.APPLY_LAST_NAME_TESTID}"]'),
                ("phone", H.APPLY_PHONE_XPATH),
            ]),
        ]

        for filename, label, fields in subforms:
            path = capture(filename)
            if not path.exists():
                continue
            print()
            print(f"--- {label}: {filename} ---")
            page.goto(path.as_uri())
            page.wait_for_timeout(250)
            for field_label, xpath in fields:
                found = len(page.query_selector_all(f"xpath={xpath}"))
                check(f"{label}: {field_label}", found > 0, f"no match for {xpath}")

            # The toggles report state through aria-checked rather than the
            # checked property, which is what setToggle() reads.
            toggle = page.query_selector('xpath=//*[@data-testid="is-current-toggle"]')
            if toggle is not None:
                check(f"{label}: toggle exposes aria-checked",
                      toggle.get_attribute("aria-checked") is not None,
                      "setToggle would not be able to tell if it is already on")

            # Date pickers are buttons opening a listbox, not <select>s -- the
            # options do not exist until expanded, which is why selectFromDropdown
            # looks for them only after clicking.
            # The heading this step keys off must NOT be the <h1>: the <h1> is
            # the job title now, and matching on it is what made the bot loop.
            if "contact_info" in filename:
                h1 = page.query_selector("xpath=//h1")
                check(f"{label}: the <h1> is NOT the contact heading",
                      h1 is not None and "contact information" not in (h1.inner_text() or ""),
                      "the h1 does contain it, so the old check would have worked")
                if h1:
                    print(f"         <h1> is {h1.inner_text().strip()[:44]!r}")
                heading = page.query_selector(f"xpath={H.APPLY_CONTACT_HEADING}")
                check(f"{label}: heading found outside the h1",
                      heading is not None and heading.evaluate("e => e.tagName") == "H2",
                      "expected the heading to be an h2")

            triggers = page.query_selector_all('xpath=//*[@data-testid="select-button"]')
            if triggers:
                check(f"{label}: date pickers are collapsed listboxes",
                      all(t.get_attribute("aria-expanded") == "false" for t in triggers),
                      "expected every date trigger to start collapsed")
                check(f"{label}: no options present while collapsed",
                      len(page.query_selector_all("xpath=//*[@role='option']")) == 0,
                      "options ARE in the DOM, so they could have been matched up front")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("SELECTOR CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
