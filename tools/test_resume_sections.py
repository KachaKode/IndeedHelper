"""Resume sections: clear what is already there, and confirm dropdowns took.

Covers four real defects from one run:
  1. existing work experience was never deleted, so a stale job the applicant
     never listed ("Ad Set Associate") was submitted with the application
  2. same for education
  3. one entry's "From month" stayed on its placeholder because the option was
     looked for before the listbox had rendered, and nothing checked afterwards
  4. after education the flow went back to contact info instead of skills

The delete loop is exercised against a live page that actually removes entries,
so the re-query-after-delete behaviour is tested rather than assumed.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def capture(name: str) -> Path:
    for candidate in (ROOT / "HTMLz" / name, ROOT / name, ROOT / "input" / name):
        if candidate.exists():
            return candidate
    return ROOT / "HTMLz" / name


# A resume page with three existing jobs, mirroring the real flow:
#   list -> Edit opens a form with its own "Delete" button
#        -> Delete raises a confirmation dialog whose button is ALSO "Delete"
#        -> only the dialog's Delete actually removes the entry
# The two identically-labelled buttons are the point: an unscoped
# //button[.='Delete'] can hit the wrong one.
DELETE_PAGE = """<!doctype html><html><body>
<div id="list"></div>
<div id="form" style="display:none">
  <button aria-label="Delete this work experience" onclick="askConfirm()">Delete</button>
</div>
<div id="dialog" role="dialog" aria-modal="true" style="display:none">
  <span>Are you sure you want to delete this work experience?</span>
  <button onclick="doDelete()">Delete</button>
  <button onclick="cancel()">Cancel</button>
</div>
<script>
  let entries = ['Alpha', 'Beta', 'Gamma'];
  let open = null;
  window.confirmsShown = 0;
  function render() {
    document.getElementById('list').innerHTML = entries.map((e,i) =>
      `<button aria-label="Edit ${e} work experience" onclick="openForm(${i})">${e}</button>`
    ).join('');
    document.getElementById('list').style.display = '';
    document.getElementById('form').style.display = 'none';
    document.getElementById('dialog').style.display = 'none';
  }
  function openForm(i) {
    open = i;
    document.getElementById('list').style.display = 'none';
    document.getElementById('form').style.display = '';
  }
  function askConfirm() {
    window.confirmsShown++;
    document.getElementById('dialog').style.display = '';
  }
  function doDelete() {
    entries.splice(open, 1);
    open = null;
    render();
  }
  function cancel() { render(); }
  render();
</script></body></html>"""

# The shape of a REAL resume that came back duplicated
# (HTMLz/Resume_left_over_work_exp.html). Three things there broke the old loop:
#
#   * two entries share one aria-label ("Edit Software Developer work
#     experience" twice), so checking that the name disappeared reported a
#     successful delete as a failure
#   * a deleted entry leaves an "X removed / Undo" banner on the page
#   * entries saved without their required fields are listed with no job title
#     in the label and carry their own Delete button, labelled WITHOUT "this"
REAL_SHAPE_PAGE = """<!doctype html><html><body>
<div id="section" data-testid="work-experience-section"></div>
<div id="form" style="display:none">
  <button aria-label="Delete this work experience" onclick="askConfirm()">Delete</button>
</div>
<div id="dialog" role="dialog" aria-modal="true" style="display:none">
  <button onclick="doDelete()">Delete</button>
  <button onclick="cancel()">Cancel</button>
</div>
<script>
  var entries = [
    {name: 'Software Developer',    complete: true},
    {name: 'Software Developer',    complete: true},
    {name: 'Head Systems Engineer', complete: true},
    {name: 'Head Systems Engineer', complete: true},
    {name: 'Software Consultant',   complete: false},
    {name: 'Software Consultant',   complete: false}
  ];
  var banner = null;
  var open = null;
  window.confirmsShown = 0;
  function render() {
    var html = '';
    if (banner) {
      html += '<div><span>' + banner + ' removed</span>'
            + '<button data-testid="deleted-item-banner-undo">Undo</button></div>';
    }
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];
      if (e.complete) {
        html += '<div><button aria-label="Edit ' + e.name + ' work experience"'
              + ' onclick="openForm(' + i + ')">' + e.name + '</button></div>';
      } else {
        html += '<div><button aria-label="Edit work experience"'
              + ' onclick="openForm(' + i + ')">' + e.name + '</button>'
              + '<button aria-label="Delete work experience"'
              + ' onclick="inlineDelete(' + i + ')">Delete</button></div>';
      }
    }
    document.getElementById('section').innerHTML = html;
    document.getElementById('section').style.display = '';
    document.getElementById('form').style.display = 'none';
    document.getElementById('dialog').style.display = 'none';
  }
  function openForm(i) {
    open = i;
    document.getElementById('section').style.display = 'none';
    document.getElementById('form').style.display = '';
  }
  function inlineDelete(i) { open = i; askConfirm(); }
  function askConfirm() {
    window.confirmsShown++;
    document.getElementById('dialog').style.display = '';
  }
  function doDelete() {
    banner = entries[open].name;
    entries.splice(open, 1);
    open = null;
    render();
  }
  function cancel() { render(); }
  render();
</script></body></html>"""


# What actually happened on the run that left four stale jobs behind: confirming
# a deletion navigates back to the resume page, and the section reads as EMPTY
# for a moment while it re-renders. The log caught it exactly --
#     removed existing work experience | Edit AI Consultant work experience (5 -> 0)
#     Removed 1 pre-existing work experience entry before adding this user's.
# -- 471ms after the confirm, with four jobs still on the resume.
SLOW_RERENDER_PAGE = """<!doctype html><html><body>
<div id="list"></div>
<div id="form" style="display:none">
  <button aria-label="Delete this work experience" onclick="askConfirm()">Delete</button>
</div>
<div id="dialog" role="dialog" aria-modal="true" style="display:none">
  <button onclick="doDelete()">Delete</button>
</div>
<script>
  var entries = ['Alpha', 'Beta', 'Gamma', 'Delta', 'Epsilon'];
  var open = null;
  function paint() {
    var html = '';
    for (var i = 0; i < entries.length; i++) {
      html += '<button aria-label="Edit ' + entries[i] + ' work experience"'
            + ' onclick="openForm(' + i + ')">' + entries[i] + '</button>';
    }
    document.getElementById('list').innerHTML = html;
    document.getElementById('list').style.display = '';
  }
  function openForm(i) {
    open = i;
    document.getElementById('list').style.display = 'none';
    document.getElementById('form').style.display = '';
  }
  function askConfirm() { document.getElementById('dialog').style.display = ''; }
  function doDelete() {
    entries.splice(open, 1);
    open = null;
    document.getElementById('form').style.display = 'none';
    document.getElementById('dialog').style.display = 'none';
    // The list is blank until the section re-renders 700ms later.
    document.getElementById('list').innerHTML = '';
    document.getElementById('list').style.display = '';
    setTimeout(paint, 700);
  }
  paint();
</script></body></html>"""


# Deleting an entry PREPENDS a "<name> removed / Undo" banner to the section,
# so every positional index below it moves. This is the shape that defeated the
# absolute-xpath round trip: three deletions, three banners, and the fourth
# entry's regenerated path pointing at nothing.
SHIFTING_PAGE = """<!doctype html><html><body>
<div id="section" data-testid="work-experience-section"><div id="banners"></div>
  <div id="list"></div></div>
<div id="form" style="display:none">
  <button aria-label="Delete this work experience" onclick="askConfirm()">Delete</button>
</div>
<div id="dialog" role="dialog" aria-modal="true" style="display:none">
  <button onclick="doDelete()">Delete</button>
</div>
<script>
  var entries = ['Alpha', 'Beta', 'Gamma', 'Delta'];
  var open = null;
  window.bannersAdded = 0;
  function paint() {
    document.getElementById('list').innerHTML = entries.map(function (e, i) {
      return '<div><button aria-label="Edit ' + e + ' work experience"'
           + ' onclick="openForm(' + i + ')">' + e + '</button></div>';
    }).join('');
    document.getElementById('section').style.display = '';
    document.getElementById('form').style.display = 'none';
    document.getElementById('dialog').style.display = 'none';
  }
  function openForm(i) {
    open = i;
    document.getElementById('section').style.display = 'none';
    document.getElementById('form').style.display = '';
  }
  function askConfirm() { document.getElementById('dialog').style.display = ''; }
  function doDelete() {
    var name = entries[open];
    entries.splice(open, 1);
    open = null;
    // Prepended, so everything after it shifts by one.
    var banner = document.createElement('div');
    banner.innerHTML = '<span>' + name + ' removed</span>'
      + '<button data-testid="deleted-item-banner-undo">Undo</button>';
    document.getElementById('banners').prepend(banner);
    window.bannersAdded++;
    paint();
  }
  paint();
</script></body></html>"""


# Skills, the way Indeed actually does them: chips on the resume page, and a
# modal behind any one of them holding the only delete controls that exist.
# Deleting a row swaps it for "<name> removed / Undo" rather than removing it,
# and "Delete resume" sits on the resume page waiting to be mistaken for a
# skill delete.
SKILLS_PAGE = """<!doctype html><html><body>
<div id="resume">
  <div data-testid="skills-section"><div id="chips"></div></div>
  <button aria-label="Add skill">Add skill</button>
  <button data-testid="delete-resume-button" aria-label="Delete resume"
          onclick="window.resumeDeleted = true;">Delete resume</button>
</div>
<div id="modal" style="display:none">
  <button data-testid="modal-back-button" onclick="back()"></button>
  <div id="list"></div>
</div>
<script>
  var skills = ['Alpha', 'Beta', 'Gamma'];
  window.wentBack = false;
  window.undone = 0;
  window.resumeDeleted = false;
  window.remaining = function () { return skills; };

  function paintChips() {
    document.getElementById('chips').innerHTML = skills.map(function (s, i) {
      return '<button data-testid="edit-chip-' + i + '" aria-label="Edit ' + s + '"'
           + ' onclick="openModal()">' + s + '</button>';
    }).join('');
  }
  function openModal() {
    document.getElementById('resume').style.display = 'none';
    document.getElementById('modal').style.display = '';
    paintList();
  }
  function paintList() {
    document.getElementById('list').innerHTML = skills.map(function (s) {
      return '<div><span>' + s + '</span>'
           + '<button aria-label="Delete ' + s + '" onclick="drop(\\'' + s + '\\')"></button>'
           + '</div>';
    }).join('');
  }
  function drop(s) {
    skills = skills.filter(function (x) { return x !== s; });
    paintList();
    document.getElementById('list').innerHTML +=
      '<div><span>' + s + ' removed</span>'
      + '<button aria-label="Undo remove ' + s + '" onclick="window.undone++">Undo</button></div>';
  }
  function back() {
    window.wentBack = true;
    document.getElementById('modal').style.display = 'none';
    document.getElementById('resume').style.display = '';
    paintChips();
  }
  paintChips();
</script></body></html>"""


# A dropdown that ignores the first click, the way a slow-rendering listbox does.
FLAKY_DROPDOWN = """<!doctype html><html><body>
<button data-testid="select-button" aria-label="From month" id="trig"
        aria-expanded="false" onclick="openList()">Month</button>
<div id="list"></div>
<script>
  let opens = 0;
  function openList() {
    opens++;
    if (opens < 2) return;              // first attempt renders nothing
    document.getElementById('list').innerHTML =
      ['January','February','March'].map(m =>
        `<div role="option" onclick="pick('${m}')">${m}</div>`).join('');
  }
  function pick(m) {
    document.getElementById('trig').textContent = m;
    document.getElementById('list').innerHTML = '';
  }
</script></body></html>"""


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "del.html").write_text(DELETE_PAGE, encoding="utf-8")
    (tmp / "drop.html").write_text(FLAKY_DROPDOWN, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        # IndeedHelper, not PlaywrightWrap: the section logic lives on the
        # subclass along with the selector constants it needs.
        wrap = main3.IndeedHelper.__new__(main3.IndeedHelper)
        main3.PlaywrightWrap.__init__(wrap, "", "", "user-data-dir=")
        wrap._page = page
        wrap._context = page.context
        wrap.outputFile = None

        H = main3.IndeedHelper

        # --- 1/2. the selectors exist on the real captures --------------------
        for filename, entry_xpath, delete_xpath, label in (
            ("Edit_Resume_HTML.html", H.WORK_ENTRY_XPATH, None, "work entry on resume page"),
            ("Edit_Resume_HTML.html", H.EDU_ENTRY_XPATH, None, "education entry on resume page"),
            ("Individual_work_experience.html", None, H.WORK_DELETE_XPATH, "work delete button"),
            ("education.html", None, H.EDU_DELETE_XPATH, "education delete button"),
        ):
            path = capture(filename)
            if not path.exists():
                continue
            page.goto(path.as_uri())
            page.wait_for_timeout(200)
            xpath = entry_xpath or delete_xpath
            found = len(page.query_selector_all(f"xpath={xpath}"))
            check(f"{label} found", found > 0, f"no match for {xpath}")

        # The Add buttons must not be mistaken for existing entries.
        page.goto(capture("Edit_Resume_HTML.html").as_uri())
        page.wait_for_timeout(200)
        entries = page.query_selector_all(f"xpath={H.WORK_ENTRY_XPATH}")
        labels = [e.get_attribute("aria-label") for e in entries]
        check("entry lookup excludes the Add button",
              all("Add work experience" != l for l in labels), f"got {labels}")
        check("entry lookup finds the stale job that was being left behind",
              any("Ad Set Associate" in (l or "") for l in labels), f"got {labels}")

        # --- deleting actually clears the list -------------------------------
        page.goto((tmp / "del.html").as_uri())
        page.wait_for_timeout(200)
        before = len(page.query_selector_all(f"xpath={H.WORK_ENTRY_XPATH}"))
        removed = wrap.deleteExistingEntries(
            H.WORK_ENTRY_XPATH, H.WORK_DELETE_XPATH, "work experience")
        after = len(page.query_selector_all(f"xpath={H.WORK_ENTRY_XPATH}"))
        check("delete loop starts with entries present", before == 3, f"got {before}")
        check("delete loop removes every entry", after == 0, f"{after} left")
        check("and reports how many it removed", removed == 3, f"reported {removed}")
        check("each deletion went through the confirmation dialog",
              page.evaluate("window.confirmsShown") == 3,
              f"dialog shown {page.evaluate('window.confirmsShown')} times for 3 deletions")

        # The confirm selector must not be able to hit the form's own Delete.
        page.goto((tmp / "del.html").as_uri())
        page.wait_for_timeout(200)
        page.click("xpath=//button[@aria-label='Edit Alpha work experience']")
        page.wait_for_timeout(150)
        page.click(f"xpath={H.WORK_DELETE_XPATH}")     # opens the dialog
        page.wait_for_timeout(150)
        loose = page.query_selector_all("xpath=//button[normalize-space(.)='Delete']")
        scoped = page.query_selector_all(f"xpath={H.CONFIRM_DELETE_XPATH}")
        check("an unscoped Delete lookup is ambiguous here", len(loose) > 1,
              f"only {len(loose)} found -- scoping would be unnecessary")
        check("the dialog-scoped lookup finds exactly one", len(scoped) == 1,
              f"found {len(scoped)}")
        check("and it is inside the dialog",
              scoped and scoped[0].evaluate(
                  "e => !!e.closest('[role=dialog]')"),
              "the scoped match is not within the dialog")

        # A deletion that silently fails must stop, not spin -- and must NOT let
        # the adding run afterwards, which is what duplicated the resume.
        page.goto((tmp / "del.html").as_uri())
        page.wait_for_timeout(200)
        page.evaluate("window.doDelete = function() { /* broken: removes nothing */ }")
        raised = None
        try:
            wrap.deleteExistingEntries(
                H.WORK_ENTRY_XPATH, H.WORK_DELETE_XPATH, "work experience")
        except BaseException as exc:      # noqa: BLE001 -- the type is the point
            raised = exc
        still = len(page.query_selector_all(f"xpath={H.WORK_ENTRY_XPATH}"))
        check("a section that will not clear raises instead of adding on top",
              isinstance(raised, main3.NeedsHumanError),
              f"raised {type(raised).__name__ if raised else 'nothing'}")
        check("and the entries are left alone", still == 3, f"{still} remain")

        # --- deleting when each removal shifts the DOM ------------------------
        # A run cleared three of four jobs and could not touch the fourth.
        # smartClick(element=...) used to convert the handle into an ABSOLUTE
        # POSITIONAL xpath and look it up again:
        #     /html/body[1]/.../div[3]/div[2]/div[2]/.../div[3]/button[1]
        # Every deletion inserts a "<name> removed / Undo" banner, so after
        # three of them every div[N] index had moved and that path matched
        # nothing. The click never landed and the entry survived.
        (tmp / "shifting.html").write_text(SHIFTING_PAGE, encoding="utf-8")
        page.goto((tmp / "shifting.html").as_uri())
        page.wait_for_timeout(250)
        started = len(page.query_selector_all(f"xpath={H.WORK_ENTRY_XPATH}"))
        gone = wrap.deleteExistingEntries(
            H.WORK_ENTRY_XPATH, H.WORK_DELETE_XPATH, "work experience")
        left = page.query_selector_all(f"xpath={H.WORK_ENTRY_XPATH}")
        check("the shifting page starts with four entries", started == 4, f"got {started}")
        check("every entry is removed even as banners shift the DOM", gone == 4,
              f"removed {gone} of 4")
        check("and none is left behind", len(left) == 0,
              f"{[e.get_attribute('aria-label') for e in left]} survived")
        check("the banners really were inserted, which is what shifts the indices",
              page.evaluate("() => window.bannersAdded") == 4,
              "then the fixture is not reproducing the conditions")

        # Clicking a handle must not depend on where it sits in the document.
        page.set_content("""
          <div id="host">
            <button id="target" onclick="document.title='clicked'">click me</button>
          </div>""")
        page.wait_for_timeout(120)
        target = wrap._resolve_matches("//button[@id='target']", None)[0]
        page.evaluate("""() => {
            const host = document.getElementById('host');
            for (let i = 0; i < 5; i++) host.prepend(document.createElement('div'));
        }""")
        page.wait_for_timeout(120)
        wrap.smartClick(element=target)
        check("a held element is still clickable after the DOM shifts around it",
              page.title() == "clicked",
              "the positional path would have been recomputed and missed")

        # --- the real duplicated-resume shape ---------------------------------
        (tmp / "real.html").write_text(REAL_SHAPE_PAGE, encoding="utf-8")
        page.goto((tmp / "real.html").as_uri())
        page.wait_for_timeout(200)
        start = len(page.query_selector_all(f"xpath={H.WORK_ENTRY_XPATH}"))
        cleared = wrap.deleteExistingEntries(
            H.WORK_ENTRY_XPATH, H.WORK_DELETE_XPATH, "work experience",
            inlineDeleteXpath=H.WORK_INLINE_DELETE_XPATH)
        left = page.query_selector_all(f"xpath={H.WORK_ENTRY_XPATH}")
        check("the real page starts with six entries", start == 6, f"got {start}")
        check("duplicate names do not stop the loop early", cleared == 6,
              f"removed only {cleared} of 6 -- a duplicate label read as a failed delete")
        check("the section really is empty afterwards", len(left) == 0,
              f"{[e.get_attribute('aria-label') for e in left]} left behind")
        check("the 'removed / Undo' banner is not counted as an entry",
              len(page.query_selector_all(
                  "xpath=//*[@data-testid='deleted-item-banner-undo']")) > 0,
              "the fixture never showed the banner, so this proves nothing")

        # --- the list that reads empty while it re-renders --------------------
        (tmp / "slow.html").write_text(SLOW_RERENDER_PAGE, encoding="utf-8")
        page.goto((tmp / "slow.html").as_uri())
        page.wait_for_timeout(200)
        began = len(page.query_selector_all(f"xpath={H.WORK_ENTRY_XPATH}"))
        gone = wrap.deleteExistingEntries(
            H.WORK_ENTRY_XPATH, H.WORK_DELETE_XPATH, "work experience")
        survived = page.query_selector_all(f"xpath={H.WORK_ENTRY_XPATH}")
        check("the slow-rerender page starts with five entries", began == 5, f"got {began}")
        check("an empty read during re-render is not believed", gone == 5,
              f"removed {gone} of 5 -- it stopped as soon as the list looked empty")
        check("nothing is left on the resume", len(survived) == 0,
              f"{[e.get_attribute('aria-label') for e in survived]} left behind")

        # --- dates stored as a bare year --------------------------------------
        # user 9's Software Consultant row holds From '2019', To '2025'. The old
        # split returned (None, None) for those, so both dropdowns were skipped
        # in silence and the entry saved as "Missing dates."
        check("a full date still splits normally",
              H._dateParts("February 2008") == ("February", "2008"),
              f"got {H._dateParts('February 2008')}")
        check("a bare year keeps the year instead of discarding it",
              H._dateParts("2019") == (None, "2019"), f"got {H._dateParts('2019')}")
        check("an empty date is still empty", H._dateParts("") == (None, None))
        check("a non-year single token is not mistaken for a year",
              H._dateParts("Present") == (None, None), f"got {H._dateParts('Present')}")

        # --- skills -----------------------------------------------------------
        # startSkills() ran do_skiils(), which looked for id="skillName" and for
        # a delete control with "delete" in its id. Both match ZERO elements on
        # the real page, so every skill failed with "Could not find the field
        # skillName to fill." A modernised fillSkills() existed but nothing
        # called it.
        print()
        print("--- skills ---")
        for name in ("Add_Skill_stuck.html", "Add_Skill.html"):
            path = capture(name)
            if not path.exists():
                continue
            page.goto(path.as_uri())
            page.wait_for_timeout(200)
            check(f"{name}: the OLD skill field selector is dead",
                  len(page.query_selector_all("xpath=//*[contains(@id,'skillName')]")) == 0,
                  "it still matches, so it did not need replacing")
            check(f"{name}: the skill name field is found",
                  len(page.query_selector_all(
                      f'xpath=//*[@data-testid="{H.SKILL_NAME_TESTID}"]')) == 1)
            check(f"{name}: the skill Save button is found",
                  len(page.query_selector_all(f"xpath={H.SKILL_SAVE_XPATH}")) > 0)

        # Skills live on the resume page as chips labelled "Edit <skill name>".
        # The word "skill" is never in the label, so a work/edu-shaped selector
        # ("Edit ... skill") matches nothing -- it only ever worked by accident,
        # on a resume whose skill was literally named "Organizational skills".
        for name in ("Edit_resume_2.html", "Edit_Resume_HTML.html"):
            path = capture(name)
            if not path.exists():
                continue
            page.goto(path.as_uri())
            page.wait_for_timeout(200)
            entries = page.query_selector_all(f"xpath={H.SKILL_ENTRY_XPATH}")
            labels = [e.get_attribute("aria-label") for e in entries]
            check(f"{name}: skill chips are found", len(entries) > 0, f"got {labels}")
            check(f"{name}: the old work/edu-shaped selector would have found none",
                  not any("skill" in (l or "").lower() for l in labels)
                  or name == "Edit_Resume_HTML.html",
                  f"got {labels}")
            check(f"{name}: the Add button is not mistaken for a chip",
                  all((l or "") not in ("Add skill", "Add skills") for l in labels))
            check(f"{name}: work and education entries are not picked up",
                  all("work experience" not in (l or "") and "education" not in (l or "")
                      for l in labels), f"got {labels}")
            check(f"{name}: the Add control is found",
                  len(page.query_selector_all(f"xpath={H.ADD_SKILL_XPATH}")) >= 1)

            # The trap: on the resume page "Delete resume" starts with "Delete ".
            deletes = page.query_selector_all(f"xpath={H.SKILL_MODAL_DELETE_XPATH}")
            check(f"{name}: 'Delete resume' is NOT treated as a skill delete",
                  all((e.get_attribute("aria-label") or "") != "Delete resume"
                      for e in deletes),
                  "clicking it would destroy the whole resume")

        # The modal reached by clicking a chip: this is the only place skills
        # can actually be removed.
        path = capture("skills.html")
        if path.exists():
            page.goto(path.as_uri())
            page.wait_for_timeout(200)
            deletes = page.query_selector_all(f"xpath={H.SKILL_MODAL_DELETE_XPATH}")
            check("the skills modal lists a delete per skill", len(deletes) > 1,
                  f"found {len(deletes)}")
            check("every one of them is a 'Delete <skill>' button",
                  all((e.get_attribute("aria-label") or "").startswith("Delete ")
                      for e in deletes))
            check("the modal's back arrow is found",
                  len(page.query_selector_all(f"xpath={H.SKILL_MODAL_BACK_XPATH}")) == 1)
            check("there are no chips in the modal",
                  len(page.query_selector_all(f"xpath={H.SKILL_ENTRY_XPATH}")) == 0,
                  "the chip lookup would re-open a modal from inside the modal")

        # The whole route, end to end: chips -> modal -> delete each -> back.
        # Deleting replaces a row in place, leaving an Undo behind, so the loop
        # has to re-read the list each pass and must never click the Undo.
        (tmp / "skills.html").write_text(SKILLS_PAGE, encoding="utf-8")
        page.goto((tmp / "skills.html").as_uri())
        page.wait_for_timeout(250)
        check("the fixture starts with three skill chips",
              len(page.query_selector_all(f"xpath={H.SKILL_ENTRY_XPATH}")) == 3)

        cleared = wrap.clearSkills()
        check("every skill is removed", cleared == 3, f"removed {cleared}")
        check("the skills section really is empty",
              len(page.query_selector_all(f"xpath={H.SKILL_ENTRY_XPATH}")) == 0,
              f"{page.evaluate('() => window.remaining')} left")
        check("it backed out of the modal afterwards",
              page.evaluate("() => window.wentBack") is True,
              "the run would carry on with the modal still covering the page")
        check("no Undo was ever clicked",
              page.evaluate("() => window.undone") == 0,
              "a deleted skill was put straight back")

        # Nothing to do: no chips means no modal to open.
        page.set_content("<div data-testid='skills-section'></div>")
        page.wait_for_timeout(120)
        check("an already-empty skills section is a no-op", wrap.clearSkills() == 0)

        # The "and" trim must not eat real words.
        check("a leading 'and ' is trimmed off a skill",
              H._cleanSkill("and Python") == "Python", f"got {H._cleanSkill('and Python')!r}")
        check("'Android' is NOT mangled into 'oid'",
              H._cleanSkill("Android") == "Android", f"got {H._cleanSkill('Android')!r}")
        check("an ordinary skill is left alone",
              H._cleanSkill(" Project Management ") == "Project Management")

        # --- 3. dropdown verification ----------------------------------------
        page.goto((tmp / "drop.html").as_uri())
        page.wait_for_timeout(200)
        result = wrap.selectFromDropdown(
            "//*[@aria-label='From month']", "February", "from month")
        shown = page.text_content("#trig")
        check("a dropdown that ignores the first attempt still gets set",
              shown == "February", f"trigger shows {shown!r}")
        check("and the selection is returned, not None", result is not None)

        # It must give up rather than claim success for a value that is absent.
        page.goto((tmp / "drop.html").as_uri())
        page.wait_for_timeout(200)
        wrap.DROPDOWN_ATTEMPTS = 2
        missing = wrap.selectFromDropdown(
            "//*[@aria-label='From month']", "Smarch", "from month")
        check("an impossible value reports failure instead of silently passing",
              missing is None, "returned something for a month that does not exist")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL RESUME SECTION TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
