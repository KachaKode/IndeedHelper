"""Reading a page's real title when Indeed has overwritten it.

The state machine routes a page by "<url>|<title>", and several rules insist on
"Indeed.com" in the title (the job description page, for one). Indeed's script
swaps document.title for a "New message | Indeed" banner while a message is
unread and the tab is hidden -- and the bot's tabs are always hidden, because it
works behind its own window. From then on every www.indeed.com page it opens
reports that banner instead of its title, the rules no longer match, and a job
page the bot has handled hundreds of times is an UNKNOWN PAGE
(Logs/Log56.txt: "Ark Technology Consultants", title "New message | Indeed").

Only document.title is overwritten. The server-rendered <meta property="og:title">
still holds the real one -- "Palantir Developer - Remote - Indeed.com", checked on
the live stuck tab -- so the banner is swapped back for that. The pure parts live
here so they can be tested without a browser.
"""

from __future__ import annotations

import re

from playwright.sync_api import Error as PlaywrightError

# "New message | Indeed", tolerating an unread count in front ("(2) ..." / "2 new
# messages | ...") in case Indeed starts showing one.
_MESSAGE_BANNER = re.compile(
    r"^\s*(?:\(\d+\)\s*)?(?:\d+\s+)?new\s+messages?\s*\|\s*indeed(?:\.com)?\s*$",
    re.IGNORECASE)

_REAL_TITLE_JS = """() => {
    const meta = document.querySelector('meta[property="og:title"], meta[name="twitter:title"]');
    return meta && meta.content ? meta.content : "";
}"""


def is_message_banner(title):
    """True when title is Indeed's unread-message banner, not a page's own."""
    return bool(_MESSAGE_BANNER.match(title or ""))


def recover_title(page, title):
    """The page's real title if `title` is the message banner, else `title`.

    Falls back to the banner when the page offers nothing better (or cannot be
    asked), so reading the environment never fails because of this.
    """
    if not is_message_banner(title):
        return title
    try:
        real = page.evaluate(_REAL_TITLE_JS)
    except PlaywrightError:
        return title
    real = real.strip() if isinstance(real, str) else ""
    return real if real and not is_message_banner(real) else title
