"""A job page must still be recognised while Indeed shows its unread-message banner.

Indeed's script replaces the title of a hidden tab with "New message | Indeed"
while a message is unread. The job description rule insists on "Indeed.com" in the
title, so every job page the bot opened afterwards was an UNKNOWN PAGE and the
run stopped on it (Logs/Log56.txt, HTMLz/job_listing_page_stuck.html). Only
document.title is overwritten; <meta property="og:title"> still holds the real
one, and getCurrentEnv now reads it back.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402
import page_title  # noqa: E402
from playwright.sync_api import Error as PlaywrightError  # noqa: E402

failures: list[str] = []

# The page from Logs/Log56.txt, with the title it really had.
STUCK_URL = ("https://www.indeed.com/viewjob?cmp=Ark-Technology-Consultants&t=Developer"
             "&jk=e0394d218b114c7b&xpse=SoCq67I2cXg9ybyw3J0LbzkdCdPP")
BANNER = "New message | Indeed"
REAL_TITLE = "Palantir Developer - Remote - Indeed.com"


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


class FakePage:
    """Just enough of a Playwright page: url, title(), and evaluate()."""

    def __init__(self, url, title, og_title="", evaluate_error=None):
        self.url = url
        self._title = title
        self._og_title = og_title
        self._evaluate_error = evaluate_error
        self.evaluated = 0

    def title(self):
        return self._title

    def evaluate(self, _js):
        self.evaluated += 1
        if self._evaluate_error:
            raise self._evaluate_error
        return self._og_title


def read_env(page) -> str:
    helper = main3.PlaywrightWrap.__new__(main3.PlaywrightWrap)
    helper._page = page
    return helper.getCurrentEnv(quiet=True)


def matching_pattern(env: str):
    """The config rule that wins for env, the way envIsValid picks it."""
    helper = main3.PlaywrightWrap.__new__(main3.PlaywrightWrap)
    lines = [ln.strip() for ln in (ROOT / "config" / "ExpectedEnvironments.txt")
             .read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.strip().startswith("//")]
    for pattern in sorted(lines, key=len, reverse=True):
        rx = main3.PlaywrightWrap.escape_regex_special_chars(helper, pattern)
        if re.match(rx.lower(), env.lower()):
            return pattern
    return None


def main() -> int:
    print("--- which titles are the banner ---")
    for title in (BANNER, "new message | indeed", "  New message | Indeed ",
                  "(2) New message | Indeed", "2 new messages | Indeed"):
        check(f"{title!r} is the banner", page_title.is_message_banner(title))
    for title in (REAL_TITLE, "Messages | Indeed", "Senior Engineer - New message Corp | Indeed.com",
                  "Add or update your contact information | Indeed", "", None):
        check(f"{title!r} is not the banner", not page_title.is_message_banner(title))

    print()
    print("--- recovering the real title ---")
    page = FakePage(STUCK_URL, BANNER, og_title=f"  {REAL_TITLE} ")
    check("banner is swapped for og:title", page_title.recover_title(page, BANNER) == REAL_TITLE)

    page = FakePage(STUCK_URL, REAL_TITLE, og_title="something else")
    check("a real title is returned untouched", page_title.recover_title(page, REAL_TITLE) == REAL_TITLE)
    check("a real title costs no page round trip", page.evaluated == 0)

    check("no og:title -> banner kept",
          page_title.recover_title(FakePage(STUCK_URL, BANNER, og_title=""), BANNER) == BANNER)
    check("og:title that is itself the banner -> banner kept",
          page_title.recover_title(FakePage(STUCK_URL, BANNER, og_title=BANNER), BANNER) == BANNER)
    check("evaluate failing -> banner kept, no exception",
          page_title.recover_title(FakePage(STUCK_URL, BANNER, evaluate_error=PlaywrightError("gone")),
                                   BANNER) == BANNER)

    print()
    print("--- the stuck job page, end to end ---")
    banner_env = f"{STUCK_URL}|{BANNER}"
    check("with the banner as its title the page matches NO rule (the bug)",
          matching_pattern(banner_env) is None, f"matched {matching_pattern(banner_env)!r}")

    env = read_env(FakePage(STUCK_URL, BANNER, og_title=REAL_TITLE))
    check("getCurrentEnv reports the real title", env == f"{STUCK_URL}|{REAL_TITLE}", env)
    won = matching_pattern(env) or ""
    check("and the job description rule now matches", "viewjob" in won, f"got {won!r}")

    env = read_env(FakePage(STUCK_URL, REAL_TITLE))
    check("a normal job page is unchanged", env == f"{STUCK_URL}|{REAL_TITLE}", env)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL MESSAGE BANNER TITLE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
