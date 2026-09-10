"""Drives the real GUI in a browser, against a COPY of the database.

The API tests cannot catch this class of bug. Clicking a row in Applications
worked perfectly -- the request fired, the record came back, the card was built
-- and still looked completely dead, because the detail card is appended below a
50-row table and re-rendering resets the scroll to the top. It landed 1662px
below an 800px viewport. "Renders correctly" and "the user sees it" are
different claims, and only a browser can check the second one.

Never touches IndHelperDB.db.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
from pathlib import Path
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbgui.data import IndeedDB  # noqa: E402
from dbgui.server import create_app  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

failures: list[str] = []

VIEWPORT = {"width": 1280, "height": 800}


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


# Is the node inside the viewport of the scroller it actually lives in?
JS_VISIBLE = """
node => {
    const r = node.getBoundingClientRect();
    return r.top < window.innerHeight && r.bottom > 0;
}
"""

JS_DISTANCE_BELOW = """
node => Math.round(node.getBoundingClientRect().top - window.innerHeight)
"""


def serve(tmpdir: Path):
    db_copy = tmpdir / "test.db"
    shutil.copy2(ROOT / "IndHelperDB.db", db_copy)
    (tmpdir / "Users").mkdir(exist_ok=True)
    app = create_app(IndeedDB(db_copy, project_root=str(tmpdir)))
    httpd = make_server("127.0.0.1", 0, app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def row_id(tr) -> str:
    """The id out of a row's first cell, which also holds the expand caret."""
    return "".join(c for c in tr.query_selector("td").inner_text() if c.isdigit())


def open_tab(page, view: str) -> None:
    page.click(f'.nav-item[data-view="{view}"]')
    page.wait_for_timeout(1800)


def main() -> int:
    tmpdir = Path(tempfile.mkdtemp())
    httpd, port = serve(tmpdir)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport=VIEWPORT)

        crashes: list[str] = []
        page.on("pageerror", lambda e: crashes.append(str(e)))

        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_timeout(2500)

        # ------------------------------------------------------- applications --
        print("--- Applications: clicking a row ---")
        open_tab(page, "applications")

        rows = page.query_selector_all("#view-root tbody tr")
        check("the applications list renders rows", len(rows) > 0, "no rows at all")
        if not rows:
            browser.close()
            httpd.shutdown()
            print("cannot continue without rows")
            return 1

        # The ID cell carries a caret as well as the number.
        first_id = row_id(rows[0])
        rows[0].click()
        page.wait_for_timeout(2500)

        titles = [t.inner_text() for t in
                  page.query_selector_all("#view-root .row-detail__title")]
        check("a record is built for the clicked row",
              any(f"#{first_id}" in t for t in titles), f"titles are {titles}")
        check("the clicked row is marked as selected",
              len(page.query_selector_all("#view-root tr.is-selected")) == 1)

        detail = page.query_selector(
            f'#view-root .row-detail__title:text-is("Application #{first_id}")')
        check("the record exists in the DOM", detail is not None)
        if detail:
            visible = detail.evaluate(JS_VISIBLE)
            check("AND THE USER CAN ACTUALLY SEE IT", visible,
                  f"it is {detail.evaluate(JS_DISTANCE_BELOW)}px below the fold -- "
                  f"this is the bug: the click works and nothing appears to happen")

        # It must open DIRECTLY under the row that was clicked -- not below the
        # whole table, which meant scrolling past 50 rows and back for each one.
        placement = page.evaluate("""() => {
            const open = document.querySelector('#view-root tr.row-detail');
            if (!open) return { ok: false, why: 'no expanded row' };
            const prev = open.previousElementSibling;
            const body = open.parentElement;
            return {
                ok: !!prev && prev.classList.contains('is-selected'),
                why: prev ? 'previous row is ' + prev.className : 'nothing before it',
                indexFromEnd: body.children.length - Array.from(body.children).indexOf(open),
                totalRows: body.children.length,
            };
        }""")
        check("the record opens directly beneath its own row", placement["ok"],
              f"{placement['why']}")
        check("and not dumped at the end of the table",
              placement.get("indexFromEnd", 0) > 2,
              "it is the last thing in the table again")

        # Clicking the row again closes it.
        rows = page.query_selector_all("#view-root tbody tr:not(.row-detail)")
        rows[0].click()
        page.wait_for_timeout(700)
        check("clicking the same row again collapses it",
              len(page.query_selector_all("#view-root tr.row-detail")) == 0)

        # Opening a second record replaces the first, rather than stacking.
        rows[2].click()
        page.wait_for_timeout(2200)
        check("only one record is open at a time",
              len(page.query_selector_all("#view-root tr.row-detail")) == 1)

        print()
        print("--- the record is laid out, not dumped as raw text ---")
        raw_markers = page.evaluate("""() => {
            const t = (document.querySelector('#view-root tr.row-detail') || {}).innerText || '';
            return {
                pythonList: /\\[\\s*'/.test(t) || /\\[\\{'/.test(t),
                dictKeys: t.includes("'title':") || t.includes("'fieldOfStudy':"),
                sample: t.slice(0, 120),
            };
        }""")
        check("no Python list syntax is shown to the user",
              not raw_markers["pythonList"], f"saw: {raw_markers['sample']!r}")
        check("no raw dictionary keys are shown to the user",
              not raw_markers["dictKeys"], f"saw: {raw_markers['sample']!r}")

        shape = page.evaluate("""() => {
            const d = document.querySelector('#view-root tr.row-detail');
            return {
                chips: d.querySelectorAll('.chip').length,
                entries: d.querySelectorAll('.entry').length,
                entryTitles: d.querySelectorAll('.entry__title').length,
                facts: d.querySelectorAll('.facts dt').length,
            };
        }""")
        check("skills render as chips", shape["chips"] > 0, f"{shape}")

        check("work history renders as titled entries",
              shape["entries"] > 0 and shape["entryTitles"] > 0, f"{shape}")
        check("the summary facts are laid out as a list", shape["facts"] > 0, f"{shape}")

        # Paging must not yank the view around -- only picking a record scrolls.
        # The button is dispatched from script rather than clicked through
        # Playwright, which scrolls a control into view before clicking it and
        # would be measuring its own side effect.
        print()
        print("--- paging does not scroll to the record ---")
        page.evaluate("""() => {
            document.querySelector('.content').scrollTop = 0;
            const next = Array.from(
                document.querySelectorAll('#view-root .pager__controls button'))
                .find(b => b.textContent.trim() === 'Next');
            next.click();
        }""")
        page.wait_for_timeout(2500)
        scrolled = page.evaluate("document.querySelector('.content').scrollTop")
        check("the page stays put when paging", scrolled < 200,
              f"jumped to {scrolled}px -- paging should not scroll to the record")

        # -------------------------------------------------------------- legacy --
        print()
        # Screener questions and the answers given must be visible on a sent
        # application. Checked against a record that HAS them -- most
        # applications ask none, so a record with an empty list proves nothing.
        # Search filters on company/title/name, NOT on id, so the company name
        # is what gets typed and the id is used to pick the row out afterwards.
        with_qa = page.evaluate("""async () => {
            const list = await (await fetch('/api/applications?page=1&search=Vyve')).json();
            for (const row of list.rows) {
                const rec = await (await fetch('/api/applications/' + row.id)).json();
                const qa = (rec._parsed || {}).QsAndAs;
                if (Array.isArray(qa) && qa.length) {
                    return { id: String(row.id), company: row.companyName || 'Vyve' };
                }
            }
            return null;
        }""")
        if with_qa:
            page.evaluate("""(company) => {
                const box = document.querySelector('#view-root input[type=search]');
                box.value = company;
                box.dispatchEvent(new Event('change'));
            }""", with_qa["company"])
            page.wait_for_timeout(2200)
            rows = [r for r in page.query_selector_all("#view-root tbody tr:not(.row-detail)")
                    if row_id(r) == with_qa["id"]]
            check("the application with screener answers is findable",
                  bool(rows), f"no row for #{with_qa['id']} after searching "
                              f"{with_qa['company']!r}")
            if rows:
                rows[0].click()
                page.wait_for_timeout(2500)
                detail = page.query_selector("#view-root tr.row-detail")
                text = (detail.inner_text() if detail else "").lower()
                pairs = len(detail.query_selector_all(".qa__item")) if detail else 0
                check("screener questions are shown on a sent application",
                      "screening questions" in text, "the section is missing entirely")
                check("each question is paired with the answer that was given",
                      pairs > 0 and bool(detail.query_selector(".qa__a")),
                      f"{pairs} question/answer pairs rendered")
                check("and not dumped as a raw python list",
                      "[{'question'" not in text)
        else:
            print("       (skipped: no application in the sample stores screener answers)")

        print()
        print("--- Legacy applications: clicking a row ---")
        open_tab(page, "applications-old")
        legacy_rows = page.query_selector_all("#view-root tbody tr")
        check("the legacy list renders rows", len(legacy_rows) > 0)
        if legacy_rows:
            legacy_id = row_id(legacy_rows[0])
            legacy_rows[0].click()
            page.wait_for_timeout(1500)
            card = page.query_selector(
                f'#view-root .row-detail__title:text-is("Legacy record #{legacy_id}")')
            check("a legacy record is built", card is not None)
            if card:
                check("and the user can see that one too", card.evaluate(JS_VISIBLE),
                      f"it is {card.evaluate(JS_DISTANCE_BELOW)}px below the fold")
            check("the legacy record also opens beneath its own row",
                  page.evaluate("""() => {
                      const open = document.querySelector('#view-root tr.row-detail');
                      return !!open && !!open.previousElementSibling
                             && open.previousElementSibling.classList.contains('is-selected');
                  }"""))

        check("no uncaught javascript errors along the way", not crashes,
              "; ".join(crashes))

        browser.close()

    httpd.shutdown()
    shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL GUI INTERACTION TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
