"""Logs/Log51.txt / HTMLz/work_stuck2.html: a failed delete left the run sitting
inside a wide-open edit form, and nothing noticed.

The chain, from the log:

1. deleteExistingEntries clicked "Edit Software Developer work experience" to
   open that entry so it could delete it (line 3235).
2. It waited for the form's "Delete this work experience" button and timed out
   -- 15.6s of wall time inside one 8s wait, the page still rendering (3238).
   The capture taken later proves the button does exist; it was simply late.
3. _deleteOneEntry called _leaveEntryForm to back out. _leaveEntryForm asks
   _formIsOpen "is there a form to close?", and _formIsOpen answered by looking
   for... the delete button. The very element whose absence brought it there.
   So it said "no form open", closed nothing, and returned success.
4. From then on the edit form covered the page. Every read of the entry list
   came back empty (the entries are visible-filtered, and a form was over
   them), so the leftover check concluded the section was already clear and
   raised nothing.
5. do_work_exp went on to add: "Add work experience" matched 1 element but was
   hidden behind the open form, so it gave up and returned None.
6. The state machine was now parked on /resume/experience/<id> "Edit work
   experience", where the only configured action is nextResumeSection() --
   which hunts for a "Save and continue" button that page does not have. 10s
   timeout, no progress, forever, until it beeped (4671).

Fixed by giving _formIsOpen a marker that does not depend on the delete button
(the form's own Save button), and by making deleteExistingEntries refuse to
read an empty list as "cleared" while a form is still covering it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

main3.t.sleep = lambda *_a, **_k: None

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def build_helper(page):
    wrap = main3.IndeedHelper.__new__(main3.IndeedHelper)
    main3.PlaywrightWrap.__init__(wrap, "", "", "user-data-dir=")
    wrap._page = page
    wrap._context = page.context
    wrap.outputFile = None
    return wrap


# An entry list whose edit form opens WITHOUT its delete button -- the state the
# run was actually in at Log51 line 3238. `escapeCloses` decides whether the
# form can be backed out of at all.
def stranding_page(escapeCloses: bool, deleteAppearsAfterMs: int | None = None) -> str:
    return f"""
  <div id="list">
    <button aria-label="Edit Alpha work experience" onclick="openForm()">Alpha</button>
    <button aria-label="Edit Beta work experience" onclick="openForm()">Beta</button>
    <button aria-label="Add work experience">Add work experience</button>
  </div>
  <div id="form" style="display:none">
    <input data-testid="job-title-input-autocomplete-input" required value="Software Developer">
    <button aria-label="Save this work experience">Save</button>
    <div id="lateDelete"></div>
  </div>
  <script>
    function openForm() {{
      document.getElementById('list').style.display = 'none';
      document.getElementById('form').style.display = 'block';
      {"" if deleteAppearsAfterMs is None else f'''
      setTimeout(() => {{
        const b = document.createElement('button');
        b.setAttribute('aria-label', 'Delete this work experience');
        b.onclick = () => {{
          document.querySelectorAll('[aria-label^="Edit Alpha"]').forEach(e => e.remove());
          closeForm();
        }};
        document.getElementById('lateDelete').appendChild(b);
      }}, {deleteAppearsAfterMs});'''}
    }}
    function closeForm() {{
      document.getElementById('form').style.display = 'none';
      document.getElementById('list').style.display = 'block';
      document.getElementById('lateDelete').innerHTML = '';
    }}
    {"document.addEventListener('keydown', e => { if (e.key === 'Escape') closeForm(); });"
     if escapeCloses else "/* nothing closes this form */"}
  </script>"""


def main() -> int:
    H = main3.IndeedHelper
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        wrap = build_helper(page)

        print("--- _formIsOpen can tell an open form from a closed one ---")
        page.set_content(stranding_page(escapeCloses=True))
        page.wait_for_timeout(100)
        page.click("xpath=//button[@aria-label='Edit Alpha work experience']")
        page.wait_for_timeout(150)
        check("the delete button really is absent, as it was at Log51 line 3238",
              len(page.query_selector_all(f"xpath={H.WORK_DELETE_XPATH}")) == 0)
        check("judging by the delete button alone reports NO form open -- the old blind spot",
              wrap._formIsOpen(H.WORK_DELETE_XPATH) is False)
        check("with the form's own Save button as the marker, the open form is seen",
              wrap._formIsOpen(H.WORK_DELETE_XPATH, H.WORK_FORM_OPEN_XPATH) is True)
        check("and the entry list is genuinely hidden behind it, so counting entries lies",
              len(wrap._liveEntries(H.WORK_ENTRY_XPATH)) == 0,
              "the list should be invisible while the form covers it")

        print()
        print("--- a form that will not close stops the run instead of reporting 'cleared' ---")
        page.set_content(stranding_page(escapeCloses=False))
        page.wait_for_timeout(100)
        raised = None
        try:
            wrap.deleteExistingEntries(
                H.WORK_ENTRY_XPATH, H.WORK_DELETE_XPATH, "work experience",
                formOpenXpath=H.WORK_FORM_OPEN_XPATH)
        except BaseException as exc:            # noqa: BLE001 -- the type is the point
            raised = exc
        check("it raises NeedsHumanError rather than returning a false all-clear",
              isinstance(raised, main3.NeedsHumanError),
              f"raised {type(raised).__name__ if raised else 'nothing'}")
        check("and says the form is what is in the way",
              isinstance(raised, main3.NeedsHumanError) and "form is open" in str(raised),
              f"message was {str(raised)[:120]!r}")

        print()
        print("--- a delete button that arrives late is used, not given up on ---")
        page.set_content(stranding_page(escapeCloses=True, deleteAppearsAfterMs=2500))
        page.wait_for_timeout(100)
        before = len(page.query_selector_all(f"xpath={H.WORK_ENTRY_XPATH}"))
        raised2 = None
        try:
            wrap.deleteExistingEntries(
                H.WORK_ENTRY_XPATH, H.WORK_DELETE_XPATH, "work experience",
                formOpenXpath=H.WORK_FORM_OPEN_XPATH, stopIfNotCleared=False)
        except BaseException as exc:            # noqa: BLE001
            raised2 = exc
        alphaGone = len(page.query_selector_all(
            "xpath=//button[@aria-label='Edit Alpha work experience']")) == 0
        check("the list started with entries", before >= 2, f"got {before}")
        check("the late delete button was found on the second look and used",
              alphaGone, "the entry was never deleted, so the retry did not happen")
        check("no exception along the way", raised2 is None, f"raised {raised2!r}")

        print()
        print("--- and afterwards the list is reachable again ---")
        check("the 'Add work experience' button is visible, not buried under a form",
              len(wrap._visible_only(wrap.driver.find_elements(
                  'xpath', H.ADD_WORK_XPATH))) == 1,
              "a form left open here is what made the Add button unclickable")

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL STRANDED-IN-ENTRY-FORM TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
