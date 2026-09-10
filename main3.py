# main3.py
#
# Same IndeedHelper/StateMachine application logic as main.py, but with the
# browser-automation layer replaced: SeleniumWrap -> PlaywrightWrap (drives a
# real Chrome window over the Chrome DevTools Protocol, the same way
# birdcatcher_py/bird_automation.py's PlaywrightSession does), and the
# top-level run loop rebuilt around birdcatcher_py/console_trace.py-style
# always-visible tracing plus classified, non-silent error handling instead
# of main.py's bare "except: pass" retry loop.
#
# `By` and `Keys` are reused from selenium.webdriver.common as plain constant
# namespaces (e.g. By.CSS_SELECTOR == "css selector") -- no Selenium browser
# driver is used anywhere in this file. Selenium's exception classes are
# reused the same way, purely so the isinstance(...) checks already present
# in IndeedHelper's logic keep working unchanged.

import pygetwindow as gw
import pyttsx3
import pyautogui
from threading import Thread
import datetime
import traceback
import sys
import itertools
import json
import os, re
import sqlite3
import urllib.parse
import inspect
import time as t
from pathlib import Path

from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    NoSuchWindowException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
)

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
    Error as PlaywrightError,
)

from myGPT import myGPT
from myGPT2 import myGPT as myGPT2
from myGPT2 import configured_fast_model

log = None


# =====================================================================================
#  console_trace  --  ported from birdcatcher_py/console_trace.py
#  Always prints (flush=True), so progress/errors are visible live in the
#  terminal instead of silently going only to a log file, which is what made
#  main.py's failures invisible.
# =====================================================================================

_last_print_time = 0.0

# Indentation for the granular ct_print noise (smartClick probes, waits, etc.)
# so it visually nests under whichever page/question banner (ct_section, below)
# most recently printed. Deliberately NOT a push/pop stack: a page always
# resets it to 0 and a question always resets it to 1, so a question that
# exits through some path that forgets to "close" it can never leave stale
# indentation bleeding into unrelated later lines -- the next banner always
# re-synchronizes it.
_ct_indent = 0


def _elapsed_ms() -> float:
    global _last_print_time
    now = t.time()
    if _last_print_time == 0.0:
        _last_print_time = now
        return 0.0
    elapsed = (now - _last_print_time) * 1000
    _last_print_time = now
    return elapsed


def ct_print(where, what, extra=None):
    elapsed = _elapsed_ms()
    suffix = f" | {extra}" if extra else ""
    indent = "  " * _ct_indent
    print(f"[CT] {elapsed:7.1f}ms | {indent}{where} | {what}{suffix}", flush=True)


_CT_SECTION_RULE = "-" * 78


def ct_section(kind, title, *detail_lines, indent=0):
    """A banner marking the start of a new page/step or a new question.

    The surrounding trace is hundreds of same-weight selector-probe lines, so
    without this there is no way to tell -- short of reading every line --
    when a new page or question started and what it actually was. Printed as
    plain, undecorated lines (no elapsed-time column) so the banner itself
    stands out from the ct_print noise around it, and in plain text (no ANSI)
    since this has to stay readable both in the saved .txt log and in the
    dbgui log box, neither of which renders terminal color codes -- the GUI
    colors these markers itself, by matching this same text (run.js: logLines).
    """
    global _ct_indent
    _ct_indent = indent
    prefix = "  " * indent
    print(f"\n[CT] {prefix}{_CT_SECTION_RULE}", flush=True)
    print(f"[CT] {prefix}>>> {kind}: {title}", flush=True)
    for line in detail_lines:
        if line:
            print(f"[CT] {prefix}    {line}", flush=True)
    print(f"[CT] {prefix}{_CT_SECTION_RULE}", flush=True)


def _beep():
    """One audible alert. Never allowed to break the run.

    Module-level (not a StateMachine method) so IndeedHelper can also call it
    directly -- IndeedHelper has no back-reference to the StateMachine that
    holds it, only the other way around.
    """
    try:
        import winsound
        winsound.Beep(880, 250)
    except Exception:
        # Non-Windows, or no audio device: the terminal bell is the fallback.
        try:
            print("\a", end="", flush=True)
        except Exception:
            pass


def ct_enter(where, extra=None):
    ct_print(where, "ENTER", extra)


def ct_loop(where, iteration, extra=None):
    suffix = f" iter={iteration}" if extra is None else f" iter={iteration} | {extra}"
    ct_print(where, "LOOP", suffix)


def ct_wait(where, waiting_for, current_value=None):
    value_str = f" sees={current_value!r}" if current_value is not None else ""
    ct_print(where, "WAIT", f"for={waiting_for}{value_str}")


def ct_exit(where, result=None):
    extra = f" result={result}" if result else ""
    ct_print(where, "EXIT", extra)


def ct_error(where, exc):
    ct_print(where, "ERROR", f"{type(exc).__name__}: {exc}")


RUNTIME_DIR = Path(__file__).resolve().parent / "runtime"


class RunControl:
    """Commands from the GUI to a running bot, passed through a small JSON file.

    The GUI is the only writer and the bot is the only reader, so there is no
    locking to get wrong and no port to manage. A missing or unreadable file
    reads as "paused" -- that is what makes a freshly launched run open the
    browser, land on the home page, and then wait for you instead of
    immediately applying to jobs.

    File shape:  {"mode": "paused"|"running", "command": "home"|null, "seq": N}

    `seq` only ever increases; the bot remembers the last one it acted on so a
    one-shot command fires once rather than on every poll.
    """

    def __init__(self, user_id, root=None):
        # `root` is the project root, matching RunnerManager.project_root on the
        # GUI side, so both ends resolve to the same <root>/runtime directory.
        base = (Path(root) / "runtime") if root else RUNTIME_DIR
        self.path = base / f"control_{user_id}.json"
        self._handled_seq = 0

    def _read(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def mode(self):
        mode = self._read().get("mode")
        return mode if mode in ("running", "paused") else "paused"

    def seq(self):
        """Write counter. Rises on every instruction from the GUI, which is how
        a fresh "keep going" is told apart from the mode simply already being
        'running' -- they look identical otherwise."""
        try:
            return int(self._read().get("seq") or 0)
        except (TypeError, ValueError):
            return 0

    def pending_command(self):
        data = self._read()
        try:
            seq = int(data.get("seq") or 0)
        except (TypeError, ValueError):
            return None
        command = data.get("command")
        if command and seq > self._handled_seq:
            self._handled_seq = seq
            return command
        return None


class ConfigMismatch(Exception):
    """The States/ExpectedEnvironments/StateTransitions files disagree.

    A plain Exception on purpose, so the worker thread's handler catches it and
    reports it rather than the run vanishing.
    """


class BadPost(Exception):
    """Custom exception class for a specific error condition."""

    def __init__(self, message="An error occurred in my application"):
        self.message = message
        super().__init__(self.message)

class StartFromTop(Exception):
    def __init__(self, message="An error occurred in my application"):
        self.message = message
        super().__init__(self.message)


# =====================================================================================
#  Selenium-shaped compatibility layer, backed by Playwright.
#
#  IndeedHelper (below) still calls things like self.driver.execute_script(...),
#  element.get_attribute(...), element.send_keys(Keys.CONTROL, "a") etc. -- exactly
#  as it did against Selenium. These small wrapper classes give it that same surface
#  while every actual browser action goes through Playwright underneath.
# =====================================================================================

class NoAlertPresentException(Exception):
    pass


_KEY_NAME_MAP = {
    Keys.CONTROL: "Control",
    Keys.ENTER: "Enter",
    Keys.TAB: "Tab",
    Keys.END: "End",
    Keys.HOME: "Home",
    Keys.ESCAPE: "Escape",
    Keys.BACKSPACE: "Backspace",
    Keys.DELETE: "Delete",
    Keys.SHIFT: "Shift",
}


def _selector_for_playwright(by, selector):
    if by in (By.XPATH, "xpath"):
        return f"xpath={selector}"
    if by == By.CSS_SELECTOR:
        return f"css={selector}"
    if by == By.TAG_NAME:
        return f"css={selector}"
    if by == By.ID:
        return f"css=#{selector}"
    if by == By.CLASS_NAME:
        return f"css=.{selector}"
    return f"css={selector}"


class _ElementCompat:
    """Wraps a Playwright ElementHandle so it quacks like a Selenium WebElement."""

    def __init__(self, handle, wrap):
        self._handle = handle
        self._wrap = wrap

    @property
    def text(self):
        try:
            return (self._handle.inner_text() or "").strip()
        except PlaywrightError as exc:
            ct_error("_ElementCompat.text", exc)
            return ""

    @property
    def tag_name(self):
        try:
            return self._handle.evaluate("el => el.tagName.toLowerCase()")
        except PlaywrightError as exc:
            ct_error("_ElementCompat.tag_name", exc)
            return ""

    def get_attribute(self, name):
        try:
            if name == "value":
                value = self._handle.evaluate("el => el.value")
                if value is not None:
                    return value
            return self._handle.get_attribute(name)
        except PlaywrightError as exc:
            ct_error("_ElementCompat.get_attribute", exc)
            return None

    # Selenium's three state queries. is_selected() was missing, and the
    # screener-questions flow -- the last part of the application never
    # exercised by a live run -- calls it on every multiple-choice answer:
    #     AttributeError: '_ElementCompat' object has no attribute 'is_selected'
    # A bare `except` upstream swallowed that, so GPT worked out an answer for
    # every question and not one of them was ever ticked. The other two are here
    # because a missing method in this class is not a wrong answer, it is a
    # crash that reaches RunUser and closes the browser.
    def is_selected(self):
        try:
            return bool(self._handle.is_checked())
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            ct_error("_ElementCompat.is_selected", exc)
            return False

    def is_displayed(self):
        try:
            return bool(self._handle.is_visible())
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            ct_error("_ElementCompat.is_displayed", exc)
            return False

    def is_enabled(self):
        try:
            return bool(self._handle.is_enabled())
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            ct_error("_ElementCompat.is_enabled", exc)
            return False

    def click(self):
        self._handle.scroll_into_view_if_needed(timeout=3000)
        self._handle.click(timeout=5000)

    def send_keys(self, *values):
        handle = self._handle
        try:
            handle.scroll_into_view_if_needed(timeout=3000)
        except PlaywrightError:
            pass
        page = self._wrap._page
        # focus() rather than click(): fillMoveOn() calls send_keys() repeatedly on the
        # same element to type in chunks, and re-clicking each time would reset the
        # cursor position instead of continuing where the previous chunk left off.
        handle.focus()
        if len(values) == 2 and values[0] == Keys.CONTROL:
            page.keyboard.press(f"Control+{values[1]}")
            return
        if len(values) == 1 and values[0] in _KEY_NAME_MAP:
            page.keyboard.press(_KEY_NAME_MAP[values[0]])
            return
        text = "".join(values)
        page.keyboard.type(text)

    def find_element(self, by, selector):
        elements = self.find_elements(by, selector)
        if not elements:
            raise NoSuchWindowException(f"No element found for {by}={selector}")
        return elements[0]

    def find_elements(self, by, selector):
        pw_selector = _selector_for_playwright(by, selector)
        try:
            handles = self._handle.query_selector_all(pw_selector)
        except PlaywrightError as exc:
            ct_error("_ElementCompat.find_elements", exc)
            return []
        return [_ElementCompat(h, self._wrap) for h in handles]


class _AlertCompat:
    def __init__(self, dialog):
        self._dialog = dialog

    @property
    def text(self):
        return self._dialog.message

    def accept(self):
        try:
            self._dialog.accept()
        except PlaywrightError:
            pass

    def dismiss(self):
        try:
            self._dialog.dismiss()
        except PlaywrightError:
            pass


class _SwitchToCompat:
    def __init__(self, wrap):
        self._wrap = wrap

    def window(self, handle):
        self._wrap._switch_to_page(handle)

    @property
    def alert(self):
        raise NoAlertPresentException("No alert is present.")


class _DriverCompat:
    """Selenium-WebDriver-shaped facade over the active Playwright Page."""

    def __init__(self, wrap):
        self._wrap = wrap

    @property
    def current_url(self):
        return self._wrap._page.url

    @property
    def title(self):
        try:
            return self._wrap._page.title()
        except PlaywrightError:
            return ""

    @property
    def window_handles(self):
        return list(self._wrap._context.pages)

    @property
    def current_window_handle(self):
        return self._wrap._page

    @property
    def switch_to(self):
        return _SwitchToCompat(self._wrap)

    def find_element(self, by, selector):
        elements = self.find_elements(by, selector)
        if not elements:
            raise NoSuchWindowException(f"No element found for {by}={selector}")
        return elements[0]

    def find_elements(self, by, selector):
        pw_selector = _selector_for_playwright(by, selector)
        try:
            handles = self._wrap._page.query_selector_all(pw_selector)
        except PlaywrightError as exc:
            ct_error("_DriverCompat.find_elements", exc)
            return []
        return [_ElementCompat(h, self._wrap) for h in handles]

    def execute_script(self, script, *args):
        # Selenium scripts reference "arguments[0]", "arguments[1]", ... just like a
        # classic JS function body -- Playwright ElementHandles passed inside the args
        # array are automatically unwrapped back into real DOM nodes on the page side.
        arg_values = [a._handle if isinstance(a, _ElementCompat) else a for a in args]
        js_function = "(arguments) => { " + script + " }"
        return self._wrap._page.evaluate(js_function, arg_values)

    def refresh(self):
        self._wrap._page.reload()

    def get(self, url):
        self._wrap._page.goto(url)

    def back(self):
        self._wrap._page.go_back()

    def close(self):
        self._wrap._close_current_page()

    def maximize_window(self):
        pass  # Chrome is launched with --start-maximized already.


class RecoverableBrowserError(Exception):
    """A browser/session problem where the whole run should restart cleanly."""


class StaleElementError(Exception):
    """A captured element has been detached from the page by a re-render.

    Handles go stale constantly on these pages: React replaces a whole section
    after a save or a delete, and anything grabbed from the outgoing render tree
    is left pointing into a subtree that is no longer in the document. The fix
    is always to re-query, never to keep using the old handle.
    """


class NeedsHumanError(Exception):
    """A control the bot expected is not on the page, and only a person can say why.

    Distinct from RecoverableBrowserError on purpose. Restarting is the right
    answer when the *browser* is broken, but it is the wrong answer when the
    browser is fine and the page has simply changed shape: it closes Chrome,
    throws away the part-finished application, and lands back on the same page
    to fail again. Raising this pauses and beeps instead -- the same treatment a
    bot check and an unrecognised page already get -- so the page is still on
    screen to be looked at.
    """


_DEAD_PAGE_MARKERS = (
    "Target page, context or browser has been closed",
    "Target closed",
    "Connection closed",
    "has been closed",
)


class PlaywrightWrap:

    def __init__(self, home_url, home_url_pattern, profile):
        self.chrome_profile = profile
        self.CONTAINS = "contains"
        self.MATCH = "matched"
        self.WHOLE = "whole"
        self.TXT = "text()"
        self.ID = "@id"
        self.CLASS = "@class"
        self.BUTTON = "//button"
        self.LABEL = "//label"
        self.INPUT = "//input"
        self.P = "//p"
        self.SELECT = "//select"
        self.LIST = "//ul"
        self.OPTION = "//option"
        self.LIST_ELEMENT = "//li"
        self.TXTAREA = '//textarea'
        self.LINK = '//a'
        self.ARIA_LABEL = '@aria-label'
        self.H1 = "//h1"
        self.SVG = "//svg"
        self.DELTA_WAIT = .2
        self.ALL = float('inf')
        self.home_url = home_url
        self.home_url_pattern = home_url_pattern

        self.driver = _DriverCompat(self)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._chrome_process = None
        self._debug_port = None

    # ------------------------------------------------------------------ lifecycle --

    def _find_chrome_executable(self):
        candidates = [
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        ]
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate
        raise RuntimeError("Could not find chrome.exe. Install Google Chrome or update _find_chrome_executable().")

    def _free_port(self):
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def _wait_for_debug_endpoint(self, timeout_seconds=20.0):
        from urllib.request import urlopen
        from urllib.error import URLError
        endpoint = f"http://127.0.0.1:{self._debug_port}/json/version"
        deadline = t.time() + timeout_seconds
        attempt = 0
        while t.time() < deadline:
            ct_wait("start_up", f"chrome DevTools endpoint {endpoint}", f"attempt={attempt}")
            attempt += 1
            try:
                with urlopen(endpoint, timeout=1.5) as response:
                    if response.status == 200:
                        return True
            except (URLError, OSError):
                t.sleep(0.5)
        return False

    def start_up(self):
        import subprocess
        ct_enter("start_up", self.home_url)

        chrome_path = self._find_chrome_executable()
        user_data_dir = self.chrome_profile
        if user_data_dir.startswith("user-data-dir="):
            user_data_dir = user_data_dir[len("user-data-dir="):]
        os.makedirs(user_data_dir, exist_ok=True)

        self._debug_port = self._free_port()
        launch_args = [
            chrome_path,
            f"--remote-debugging-port={self._debug_port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
            self.home_url,
        ]
        ct_print("start_up", "launching chrome.exe", f"profile={user_data_dir} port={self._debug_port}")
        self._chrome_process = subprocess.Popen(launch_args)

        if not self._wait_for_debug_endpoint(timeout_seconds=20.0):
            raise RecoverableBrowserError(
                f"Chrome launched (pid {self._chrome_process.pid}) but its DevTools endpoint never came up on "
                f"127.0.0.1:{self._debug_port}. This usually means another Chrome window is already using the "
                f"profile at \"{user_data_dir}\" -- close every Chrome window for that profile and try again."
            )

        self._playwright = sync_playwright().start()
        endpoint = f"http://127.0.0.1:{self._debug_port}"
        self._browser = self._playwright.chromium.connect_over_cdp(endpoint)
        if not self._browser.contexts:
            raise RecoverableBrowserError("Chrome connected over CDP, but no browser context was available.")
        self._context = self._browser.contexts[0]
        self._page = self._context.pages[-1] if self._context.pages else self._context.new_page()
        self._page.on("dialog", self._on_dialog)
        self._page.bring_to_front()
        ct_exit("start_up", self._page.url)

    def _on_dialog(self, dialog):
        self.reportAction(f"Auto-accepting a JS dialog: {dialog.message}", False)
        try:
            dialog.accept()
        except PlaywrightError:
            pass

    def _switch_to_page(self, page):
        if page in self._context.pages:
            self._page = page
            page.bring_to_front()

    def _close_current_page(self):
        closing = self._page
        remaining = [p for p in self._context.pages if p is not closing]
        try:
            closing.close()
        except PlaywrightError:
            pass
        if remaining:
            self._page = remaining[-1]

    def close(self):
        try:
            if self._browser is not None:
                self._browser.close()
        except PlaywrightError:
            pass
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:
            pass
        if self._chrome_process is not None:
            try:
                self._chrome_process.terminate()
            except Exception:
                pass

    # -------------------------------------------------------------- xpath finding --

    def _resolve_matches(self, elementXpath, findFrom):
        if findFrom is None or findFrom is self.driver:
            handles = self._page.query_selector_all(f"xpath={elementXpath}")
        elif isinstance(findFrom, _ElementCompat):
            handles = findFrom._handle.query_selector_all(f"xpath={elementXpath}")
        else:
            handles = findFrom.query_selector_all(f"xpath={elementXpath}")
        return [_ElementCompat(h, self) for h in handles]

    def _isAttached(self, element):
        """False once an element has been removed from the document."""
        if element is None:
            return False
        try:
            return bool(element._handle.evaluate("e => e.isConnected"))
        except (PlaywrightError, PlaywrightTimeoutError):
            return False

    def _labelOf(self, element):
        try:
            return element.get_attribute("aria-label") or "(unnamed entry)"
        except PlaywrightError:
            return "(unnamed entry)"

    def _visible_only(self, matches):
        """Keep the matches that are actually on screen.

        Returns [] if none are, so callers can fall back to the raw list rather
        than losing the element entirely.
        """
        visible = []
        for element in matches:
            try:
                if element._handle.is_visible():
                    visible.append(element)
            except PlaywrightError:
                continue
        return visible

    def _elementGone(self, element):
        """True once a clicked control has left the page.

        A Save button that vanishes means the form closed, which is the signal
        the caller of checkNewPage is really after. A detached handle raises
        rather than returning False, so that counts as gone too.
        """
        if element is None:
            return False
        try:
            return not element._handle.is_visible()
        except (PlaywrightError, PlaywrightTimeoutError):
            return True

    def _wait_until(self, cond, timeout_seconds):
        deadline = t.time() + max(timeout_seconds, 0)
        while t.time() < deadline:
            try:
                if cond():
                    return True
            except PlaywrightError:
                pass
            t.sleep(self.DELTA_WAIT)
        return cond() if timeout_seconds > 0 else False

    def findAndClick(self, what, type, elementXpath, indInList=0, travelUp=0, timeLimit=10, txtCond='', checkClosed=False,
                     checkNewPage=False, checkNewTab=False, waitBeforeClicking=0, findFrom=None, waitBeforeFinding=0,
                     expectingPopUp=False, elementType="*", nohang=False, newPageFollowsTimeLimit=False):
        if isinstance(elementXpath, str):
            elementXpath = [elementXpath]
        root = "." if findFrom is not None else ""

        elementType = elementType.replace("//", "")

        _elementXpath = ""
        if type == self.CONTAINS:
            _elementXpath = f"{root}//{elementType}[contains({what}, '{elementXpath[0]}')]"
            for i in range(1, len(elementXpath)):
                _elementXpath += f" | {root}//{elementType}[contains({what}, '{elementXpath[i]}')]"
        elif type == self.WHOLE:
            _elementXpath = elementXpath[0].replace("//", f"{root}//")
        elif type == self.MATCH:
            _elementXpath = f"{root}//{elementType}[{what}='{elementXpath[0]}']"
            for i in range(1, len(elementXpath)):
                _elementXpath += f" | {root}//{elementType}[{what}='{elementXpath[i]}']"

        return self.smartClick(_elementXpath, indInList, travelUp, timeLimit, txtCond, checkClosed,
                     checkNewPage, checkNewTab, waitBeforeClicking, findFrom, waitBeforeFinding,
                     expectingPopUp=expectingPopUp, nohang=nohang, newPageFollowsTimeLimit=newPageFollowsTimeLimit)

    def _perform_click(self, target, waitBeforeClicking=0, ctrl=False, listen_for_new_tab=False):
        handle = target._handle
        t.sleep(max(waitBeforeClicking, 0))
        try:
            handle.scroll_into_view_if_needed(timeout=3000)
        except PlaywrightError:
            pass
        modifiers = ["Control"] if ctrl else None
        try:
            if listen_for_new_tab:
                try:
                    with self._context.expect_page(timeout=4000) as new_page_info:
                        handle.click(modifiers=modifiers, timeout=5000)
                except PlaywrightTimeoutError as exc:
                    # Could be the click itself timing out (blocked/intercepted) or just
                    # no new tab showing up within our wait window after a fine click --
                    # only the former is a real problem the caller needs to react to.
                    if "intercepts pointer events" in str(exc):
                        return ElementClickInterceptedException(str(exc))
                    return None
                new_page = new_page_info.value
                new_page.wait_for_load_state("domcontentloaded")
                return new_page
            handle.click(modifiers=modifiers, timeout=5000)
            return None
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            if "intercepts pointer events" in str(exc):
                return ElementClickInterceptedException(str(exc))
            raise

    def smartClick(self, elementXpath='', indInList=0, travelUp=0, timeLimit=10, txtCond='', checkClosed=False,
                     checkNewPage=False, checkNewTab=False, waitBeforeClicking=0, findFrom=None, waitBeforeFinding=0,
                   element=None, expectingPopUp=False, ctrl=False, nohang=False, newPageFollowsTimeLimit=False):
        ct_enter("smartClick", elementXpath if isinstance(elementXpath, str) else "<by element>")
        t.sleep(waitBeforeFinding)
        if ctrl:
            checkNewTab = True

        # An element we were handed gets clicked directly. It used to be turned
        # into an absolute positional xpath and looked up again:
        #     /html/body[1]/.../div[3]/div[2]/div[2]/.../div[3]/button[1]
        # Every div[N] in that path is a position, so any change above the
        # element invalidates it. Deleting a work experience inserts a
        # "<name> removed / Undo" banner into the section, and after three
        # deletions the regenerated path matched NOTHING: the click never
        # landed, the delete form never opened, and that entry survived the
        # clear-out. Clicking the handle we already hold cannot drift.
        if element is not None:
            if not self._isAttached(element):
                # The handle points into a discarded render tree. Callers treat
                # None as "could not click", and the right move is to re-query.
                self.reportAction(
                    "Could not click: that element is no longer on the page.", False)
                ct_exit("smartClick", "element went stale")
                return None
            elementXpath = f"<element: {self._labelOf(element)[:60]}>"
            findFrom = None

        url_at_start = self._page.url
        start_time = t.time()
        deadline = start_time + timeLimit
        attempt = 0

        while True:
            attempt += 1
            try:
                matches = ([element] if element is not None
                           else self._resolve_matches(elementXpath, findFrom))

                if indInList == self.ALL:
                    self.reportAction(f"returning {len(matches)} matches for {elementXpath}!")
                    ct_exit("smartClick", f"{len(matches)} matches (ALL)")
                    return matches

                # Indeed's pages carry hidden duplicates of the things we click --
                # six "Continue" buttons where only one is real, decoy nav
                # buttons, and so on. Clicking a hidden one makes Playwright wait
                # the full click timeout before failing, which was costing ~78%
                # of every run. Prefer the ones actually on screen.
                visible = self._visible_only(matches)
                if visible:
                    matches = visible
                elif matches and txtCond == '':
                    # Everything that matched is hidden, and we are here to
                    # click. Clicking a hidden element just burns the whole
                    # click timeout and fails, so treat this as "not ready yet"
                    # and keep polling -- on these pages the button appears once
                    # the form covering it closes.
                    if nohang or t.time() >= deadline:
                        self.reportAction(
                            f"{len(matches)} element(s) matched {elementXpath} but none are "
                            f"visible, so there was nothing to click.", False)
                        ct_exit("smartClick", "matched only hidden elements")
                        return None
                    ct_wait("smartClick", f"all {len(matches)} matches still hidden",
                            f"attempt={attempt}")
                    t.sleep(self.DELTA_WAIT)
                    continue

                try:
                    target = matches[indInList]
                except IndexError:
                    if nohang or t.time() >= deadline:
                        if not nohang:
                            self.reportAction(f"*\n*\n*\nTime OUT.  Spent {timeLimit} secs waiting for {elementXpath}\n*\n*\n*")
                        ct_exit("smartClick", "not found")
                        return None
                    self.handleCaptcha()
                    ct_wait("smartClick", f"element to appear: {elementXpath}", f"attempt={attempt}")
                    t.sleep(self.DELTA_WAIT)
                    continue

                if target.get_attribute("disabled") is not None:
                    ct_exit("smartClick", "disabled")
                    return None

                for _ in range(travelUp, 0, -1):
                    target = self.get_parent(target)

                if txtCond != '' and txtCond != target.text:
                    self.reportAction(f"found element {elementXpath} but did not click because text did not match: {txtCond}")
                    ct_exit("smartClick", "text condition mismatch")
                    return target

                numMatchesOriginally = len(matches)
                click_result = self._perform_click(
                    target, waitBeforeClicking=waitBeforeClicking, ctrl=ctrl,
                    listen_for_new_tab=(ctrl or checkNewTab),
                )
                if isinstance(click_result, ElementClickInterceptedException):
                    if t.time() >= deadline:
                        self.reportAction(f"Ran into ElementClickInterceptedException trying to click {elementXpath}")
                        ct_exit("smartClick", "click intercepted, giving up")
                        return click_result
                    self.reportAction(f"Click intercepted on {elementXpath}, retrying...")
                    t.sleep(self.DELTA_WAIT)
                    continue

                if checkNewTab and click_result is not None:
                    self._page = click_result
                    # Ctrl+click opens the tab in the BACKGROUND. Playwright is
                    # happy to drive it there, but then the window still shows
                    # the old page, which is indistinguishable from "the tab
                    # never switched". Raise it so what you see is what the bot
                    # is working on.
                    try:
                        self._page.bring_to_front()
                    except PlaywrightError as exc:
                        ct_error("smartClick (bring_to_front)", exc)
                    ct_print("smartClick", "SWITCHED TO NEW TAB",
                             f"tabs={len(self._context.pages)} url={self._page.url[:80]}")

                if checkNewPage:
                    # "The click led somewhere" is EITHER a new URL or the
                    # clicked control going away. Waiting only for a new URL
                    # burned the whole window on every in-place save -- the
                    # resume forms save without navigating, so each of these
                    # cost a flat ten seconds:
                    #   Save this work experience ... 10038ms, 10074ms, 10044ms
                    # Both conditions can only make this return sooner.
                    self._wait_until(
                        lambda: self._page.url != url_at_start or self._elementGone(target),
                        max(deadline - t.time(), .5))

                if checkClosed:
                    self._wait_until(
                        lambda: len(self._resolve_matches(elementXpath, findFrom)) < numMatchesOriginally,
                        max(deadline - t.time(), .5),
                    )

                if not expectingPopUp:
                    self.closeDialogBox()

                self.reportAction(f"clicked {elementXpath} successfully!")
                ct_exit("smartClick", "clicked")
                return target

            except (PlaywrightError, PlaywrightTimeoutError) as exc:
                if any(marker in str(exc) for marker in _DEAD_PAGE_MARKERS):
                    ct_error("smartClick", exc)
                    return StartFromTop(str(exc))
                if t.time() >= deadline:
                    ct_error("smartClick", exc)
                    if nohang:
                        return None
                    if newPageFollowsTimeLimit:
                        return -1
                    self.reportAction(f"*\n*\n*\nTime OUT.  Spent {timeLimit} secs waiting on {elementXpath}. ({exc})\n*\n*\n*")
                    return None
                ct_wait("smartClick", f"recovering from {type(exc).__name__}", str(exc)[:160])
                self.handleCaptcha()
                t.sleep(self.DELTA_WAIT)

    def findClosestRelatives(self, refWhat, refType, refXpath, targetWhat, targetType, targetXpath, limit=10, srchLvlLmt=float('inf')):
        reference = self.findAndClick(refWhat, refType, refXpath, txtCond='@#%   Not Supposed To Match  ^&*()', timeLimit=limit)
        if reference is None:
            return []
        relatives = []
        prvWait = self.DELTA_WAIT
        self.DELTA_WAIT = .01
        level = 0
        while True:
            relatives = self.findAndClick(targetWhat, targetType, targetXpath, indInList=self.ALL, timeLimit=limit,
                                          txtCond='@#%   Not Supposed To Match  ^&*()', findFrom=reference)
            if len(relatives) > 0:
                break
            try:
                reference = self.get_parent(reference)
            except PlaywrightError:
                break
            level += 1
            if level > srchLvlLmt:
                break
        self.DELTA_WAIT = prvWait
        return relatives

    def click_all(self, list_of_elements, delayBeforeEach=0, delayBeforeFirst=0, timeLimitForEach=10):
        t.sleep(delayBeforeFirst)
        for element in list_of_elements:
            self.smartClick(element=element, waitBeforeClicking=delayBeforeEach, timeLimit=timeLimitForEach)

    def closeDialogBox(self):
        """Dismiss a modal if one is genuinely in the way.

        This runs after every single click, so it has to be cheap. It used to go
        through findAndClick with a 0.4s poll (and a full trace) on every call,
        then try to click close buttons without checking whether they were
        visible -- each miss costing a 5 second click timeout.
        """
        try:
            dialogs = self._page.query_selector_all(
                'xpath=//*[@role="dialog" and @aria-modal="true"]')
            dialog = next((d for d in dialogs if d.is_visible()), None)
            if dialog is None:
                return

            for button in dialog.query_selector_all("button"):
                label = (button.get_attribute("aria-label") or "").lower()
                if "close" not in label or not button.is_visible():
                    continue
                button.click(timeout=2000)
                self.reportAction("Closed Dialog")
                return
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            ct_error("closeDialogBox", exc)

    def handleCaptcha(self):
        cap = self.findAndClick(self.TXT, self.MATCH, "Solve with 2Captcha", timeLimit=.1, nohang=True)
        if cap is None:
            return True
        try:
            while cap.text != 'Captcha solved!':
                if "error" in cap.text.lower() or "api_http" in cap.text.lower() or "seconds" in cap.text.lower():
                    ret = self.findAndClick(self.WHOLE, self.WHOLE, "//iframe[@title='reCAPTCHA']")
                    if ret is not None:
                        t.sleep(2)
                        return True
                    else:
                        self.driver.back()
                        return StartFromTop()
                t.sleep(.25)
        except PlaywrightError as exc:
            ct_error("handleCaptcha", exc)
            return True
        return True

    # ------------------------------------------------------------- DOM traversal --

    def get_parent(self, element, level=1):
        for i in range(level):
            element = element.find_element('xpath', '..')
        return element

    def get_child(self, element, level=1, indInLevel=1):
        '''Indexes start at 1 for this function'''
        finalPath = "."
        for _ in range(level):
            finalPath += f"/*[{indInLevel}]"
        return element.find_elements('xpath', finalPath)[0]

    def get_child_complex(self, element, easyPath):
        indices = filter(None, easyPath.split('/'))
        segments = [f"*[{index}]" for index in indices]
        finalPath = './' + '/'.join(segments)
        try:
            return element.find_elements('xpath', finalPath)[0]
        except (PlaywrightError, IndexError):
            return None

    def num_children(self, element):
        # get_child_complex() returns None when the path does not exist, and
        # determine_question_type() feeds its result straight in here. Without
        # this guard that was `None.find_elements(...)` -- an AttributeError
        # that a bare `except` upstream turned into a silently skipped question.
        if element is None:
            return 0
        try:
            return len(element.find_elements('xpath', './*'))
        except PlaywrightError:
            return None

    def indexAmongSiblings(self, element):
        index = len(element.find_elements('xpath', './preceding-sibling::*'))
        return index + 1

    def getNextSibling(self, element):
        indOfSibling = self.indexAmongSiblings(element) + 1
        parent = self.get_parent(element)
        return self.get_child(parent, indInLevel=indOfSibling)

    def generate_full_xpath(self, element):
        """Absolute xpath for an element, built by walking up to <html>.

        Raises StaleElementError when the walk runs out of ancestors before
        reaching <html>, which means the element is no longer in the document.
        That used to be an unguarded [0] on an empty list: the IndexError
        escaped all the way to RunUser, which closes Chrome and restarts the
        whole run -- for a handle that had simply gone stale.
        """
        try:
            tag = element.tag_name
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            raise StaleElementError(
                "The element is detached from the page; it cannot be located.") from exc

        if tag == "html":
            return "/html"

        siblings = element.find_elements('xpath', "./preceding-sibling::" + tag)
        index = len(siblings) + 1

        parents = element.find_elements('xpath', "./..")
        if not parents:
            # Walked off the top of a detached subtree without meeting <html>.
            raise StaleElementError(
                f"A <{tag}> element is detached from the page -- the section holding it was "
                f"re-rendered while it was being used.")
        return f"{self.generate_full_xpath(parents[0])}/{tag}[{index}]"

    def xpath_or(self, *args):
        xpath = ""
        for arg in args:
            xpath += arg
            if arg != args[-1]:
                xpath += " | "
        return xpath

    # ------------------------------------------------------------------- filling --

    def findFillMoveOn(self, what, type, elementXpath, fillContent, indInList=0):
        element = self.findAndClick(what, type, elementXpath, indInList)
        if element is None:
            # fillMoveOn(None, ...) throws, and the crash reaches RunUser, which
            # closes the browser and restarts. A field that is not there is a
            # thing to report, not to die on.
            self.reportAction(f"Could not find the field {elementXpath} to fill.", False)
            return None
        self.fillMoveOn(element, fillContent)
        return element

    def findFillEnter(self, what, type, elementXpath, fillContent, indInList=0):
        element = self.findAndClick(what, type, elementXpath, indInList)
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(fillContent)
        element.send_keys(Keys.ENTER)
        return element

    def fillMoveOn(self, element, fillContent, step=20):
        """Replace a field's contents.

        The old version typed 20 characters at a time, each chunk costing a
        scroll + focus + type round trip -- a Selenium-era workaround. Playwright
        can set the whole value in one call, which is dramatically faster for
        long text like a job description or summary.
        """
        try:
            handle = element._handle
            try:
                handle.scroll_into_view_if_needed(timeout=3000)
            except PlaywrightError:
                pass

            try:
                handle.fill(str(fillContent))
            except (PlaywrightError, PlaywrightTimeoutError):
                # fill() refuses on some rich-text widgets; fall back to typing
                # the whole string at once rather than in chunks.
                handle.click(timeout=5000)
                self._page.keyboard.press("Control+a")
                self._page.keyboard.type(str(fillContent))

            self._page.keyboard.press("Tab")
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            ct_error("fillMoveOn", exc)

    def fillDropDown(self, drpElement, content):
        try:
            curVal = drpElement.get_attribute("value")
            curText = self.findAndClick(self.WHOLE, self.WHOLE, f'.//option[@value="{curVal}"]', txtCond="asdhfl98394",
                                       findFrom=drpElement).text
            if content == curText:
                return
        except (PlaywrightError, AttributeError):
            pass
        self.smartClick(element=drpElement)
        drpElement.send_keys(content)
        drpElement.send_keys(Keys.ENTER)

    # --------------------------------------------------------------------- misc --

    def nextNonBlankLine(self, file_handler):
        line = ''
        while not line or line.strip()[:2] == "//":
            line = file_handler.readline()
            if len(line) == 0:
                break
            line = line.strip()
        return line

    def select_tab_by_url_pattern(self, pattern):
        """Switches to the first tab whose URL matches pattern and closes all others."""
        deadline = t.time() + 15
        matching_page = None
        while matching_page is None and t.time() < deadline:
            for page in self._context.pages:
                if re.search(pattern, page.url):
                    matching_page = page
                    break
            if matching_page is None:
                ct_wait("select_tab_by_url_pattern", f"a tab matching {pattern}")
                t.sleep(.5)

        if matching_page is None:
            self.reportAction("No tab found with a URL matching the pattern.", False)
            raise RecoverableBrowserError(f"No open tab matched pattern {pattern!r}; restarting the browser session.")

        for page in list(self._context.pages):
            if page is not matching_page:
                try:
                    page.close()
                except PlaywrightError:
                    pass
        self._page = matching_page
        matching_page.bring_to_front()

    def escape_regex_special_chars(self, s: str) -> str:
        special_chars = ['\\', '.', '^', '$', '*', '+', '?', '{', '}', '[', ']', '|', '(', ')']
        s = s.replace("((", "({[(")[::-1].replace("))", ")}])")[::-1]
        special_substrings = re.findall(r'\(\{\[\(.*?\)\]\}\)', s)
        for i, substring in enumerate(special_substrings):
            s = s.replace(substring, f'PLACE&&&HOLDER{i}')
        special_substrings = [substring.replace('({[(', '').replace(')]})', '') for substring in special_substrings]
        for char in special_chars:
            s = s.replace(char, f'\\{char}')
        for i, substring in enumerate(special_substrings):
            s = s.replace(f'PLACE&&&HOLDER{i}', substring)
        return s

    def reportAction(self, actionMsg, reportStack=True, useFile=True):
        # Always print live (birdcatcher-style) -- this used to only go to a
        # log file, which is why main.py's failures were invisible.
        ct_print("reportAction", actionMsg.replace("\n", " ").strip()[:200])
        if useFile and getattr(self, "outputFile", None) is not None and not self.outputFile.closed:
            self.outputFile.write(f"\n{actionMsg}\n")
        if reportStack:
            stack = inspect.stack()
            listFuncCalls = [frame.function for frame in stack]
            listFuncCalls.pop(0)
            funcStack = ' | '.join(listFuncCalls)
            if useFile and getattr(self, "outputFile", None) is not None and not self.outputFile.closed:
                self.outputFile.write(f"\tFunction Stack: {funcStack}\n")

    def getCurrentEnv(self, quiet=False):
        """Read the current page as "<url>|<title>".

        `quiet` suppresses the trace. Callers that poll this once a second --
        the pause-and-alert loop, mainly -- would otherwise bury every other
        line in the log under thousands of identical entries, which is exactly
        what made one stall unreadable.
        """
        if not quiet:
            ct_enter("getCurrentEnv")
        deadline = t.time() + 15
        title = ""
        while t.time() < deadline:
            try:
                url = self._page.url
                title = self._page.title()
            except PlaywrightError as exc:
                if any(marker in str(exc) for marker in _DEAD_PAGE_MARKERS):
                    raise
                url, title = "", ""
            if title:
                break
            self.handleCaptcha()
            if not quiet:
                ct_wait("getCurrentEnv", "page title to load")
            t.sleep(1)
        currentEnv = f"{url}|{title}"
        if not quiet:
            ct_exit("getCurrentEnv", currentEnv[:120])
        return currentEnv


class IndeedHelper(PlaywrightWrap):
    area_specifier_text = {"United States": 'City, State',
                      "Canada":"City, Province / Territory"}
    def __init__(self, info, masterMilestoneList):
        self.MML = masterMilestoneList
        nowTime = datetime.datetime.now().strftime("%Y_%m_%d %H.%M.%S")
        self.MY_PATH = ''  # "Users\\name\\c
        self.home_url = ""
        self.home_url_pattern = ""
        self.chrome_profile = "user-data-dir="
        self.applicationsLeft = -1
        self.profiles = []
        self.profile_generator = None
        self.cur_profile = {}
        self.user_id = -1
        self.dataPath = "data\\"
        self.configPath = "config\\"
        self.promptsPath = 'prompts\\'

        self.details = {}
        self.JobDescriptionText = ''
        self.companyName = ''
        self.jobTitle = ''
        self.lifeSummary = ''
        self.writingSample = ''
        # Where to go back to when the resume editor loses its own link to the
        # application. Filled from the editor URL's `continue=` parameter.
        self.applicationReturnUrl = ''
        self.headline = ''
        self.coverLetter = ''
        self.resumeSummary = ''
        self.skills = []
        self.tries = []
        self.jobs = []
        self.edus = []
        self.prev_questions = []

        self.Bad = -1
        self.FreeResponse = 0
        self.MultChoice = 1
        self.DropDown = 2
        self.FreeResponseLong = 3
        self.SelectApplicable = 4
        self.DateFill = 5
        self.SearchSelect = 6
        self.SelectApplicableCombobox = 7
        self.firstName = ''
        self.lastName = ""
        self.headline = ''
        self.phone_num = ''
        self.email = ''
        self.areaSpec = ''
        self.zip = ''
        self.country = 'United States'

        self.eduRecords = info["edus"]
        self.jobRecords = info["jobs"]
        self.searchRecords = info["searches"]
        self.load_startup_info(info["mainInfo"])
        self.outputFile = open(f"{self.MY_PATH}output {nowTime}.txt", "w")

        self.load_life_summary()
        super().__init__(self.cur_profile["home"], self.home_url_pattern, self.chrome_profile)


        #self.load_edu()
        self.start_up()
        self.jobOpeningGenerator = self.process_job_openings()

    def today(self):
        # Get today's date
        today_date = datetime.date.today()

        # Format the date as "MM/DD/YYYY"
        formatted_date = today_date.strftime("%b %d, %Y")
        return formatted_date

    def today_mmddyyy(self):
        # Get today's date
        today_date = datetime.date.today()

        # Format the date as "MM/DD/YYYY"
        formatted_date = today_date.strftime("%m/%d/%Y")
        return formatted_date


    ##############################   START TRANSITION FUNCTIONS   ##################################

    def waitOneSecond(self):
        t.sleep(1)

    def closeDialog(self):
        self.findAndClick( self.ARIA_LABEL, self.CONTAINS, "close", checkClosed=True)
    def newApp(self):
        #get next opening
        next(self.jobOpeningGenerator)
    # The Indeed Apply button is matched by its semantic class first and its
    # label second. Indeed has used "Apply now" and "Apply on Indeed" for the
    # same control, and the hashed half of the class (css-1ebo7dz) rotates on
    # every redeploy, so only the jobsearch- prefix is worth pinning to.
    APPLY_BUTTON_XPATH = (
        "//*[contains(@class, 'jobsearch-IndeedApplyButton')]"
        " | //button[normalize-space(.)='Apply with Indeed']"
        " | //button[normalize-space(.)='Apply now']"
        " | //button[normalize-space(.)='Apply on Indeed']"
    )

    # A disabled Apply button (id="indeedApplyButton" ... disabled ...) means
    # Indeed itself is saying this job cannot be applied to right now --
    # already filled, requires an external site, etc. -- not a rendering
    # delay or a captcha. Matched directly on //button[@disabled], not
    # APPLY_BUTTON_XPATH's own class selector: that selector's first
    # alternative matches jobsearch-IndeedApplyButton-contentWrapper, a CHILD
    # <div> of the button with no disabled attribute of its own, so checking
    # THAT element's disabled state would always read as enabled regardless
    # of the real button.
    APPLY_BUTTON_DISABLED_XPATH = (
        "//button[@disabled and ("
        "contains(@class, 'jobsearch-IndeedApplyButton')"
        " or @id='indeedApplyButton'"
        " or normalize-space(.)='Apply with Indeed'"
        " or normalize-space(.)='Apply now'"
        " or normalize-space(.)='Apply on Indeed'"
        " or @aria-label='Apply with Indeed'"
        ")]"
    )

    def startApplication(self):
        # Skip the job if it already carries an "Applied" badge. This is a
        # probe, not a wait: the badge is rendered with the rest of the job
        # header or not at all. On the default 10s limit it burned a full ten
        # seconds on every job that had NOT been applied to -- which is nearly
        # all of them -- for an answer it already had after the first second.
        if self.findAndClick(self.TXT, self.MATCH, 'Applied', txtCond="asdfdasf",
                             timeLimit=2) is not None:
            return self.backToStart()

        # A second, independent path to the same Apply button process_job_
        # openings already guards against (Logs/Log33.txt): reached directly
        # via a /viewjob URL (state hitApply) rather than through a search-
        # results card click. APPLY_BUTTON_XPATH's class-based alternative
        # matches jobsearch-IndeedApplyButton-contentWrapper, a CHILD <div>
        # of the real <button disabled>, so smartClick's own disabled check
        # never saw the disabled button at all -- it "clicked" the harmless
        # child div instead, which does nothing, and with the URL never
        # changing, config/StateTransitions.txt's "default -- startApplication()
        # --> hitApply" rule just called this again, forever.
        if self._visible_only(self.driver.find_elements('xpath', self.APPLY_BUTTON_DISABLED_XPATH)):
            self.reportAction(
                "The Apply button is disabled on this job, so it cannot be applied "
                "to from Indeed. Skipped.", False)
            return self.backToStart()

        return self.findAndClick(self.WHOLE, self.WHOLE, self.APPLY_BUTTON_XPATH,
                                 checkNewTab=True, timeLimit=3)


    def updateContactInfo(self):
        return self.handleAddInfoPage()
    def startResume(self):
        return self.chooseToBuildIndeedResume()

    # Cloudflare's managed challenge, served in place of a job page
    # (HTMLz/captcha_view_job.html, on an ordinary /viewjob URL). It carries no
    # Apply button, which process_job_openings used to read as "this job cannot
    # be applied to from Indeed" -- so the card was skipped and a perfectly good
    # application was never sent. These are the markers on the OUTER page; the
    # widget itself is a cross-origin iframe.
    CAPTCHA_MARKER_XPATH = (
        "//iframe[contains(@src, 'challenges.cloudflare.com')]"
        " | //*[starts-with(@id, 'cf-chl-widget')]"
        " | //input[@name='cf-turnstile-response']"
        " | //*[@id='challenge-error-text']"
    )
    # Titles Cloudflare serves while the challenge is up. "additional
    # verification" is this page's <h1>; the rest are the usual wording.
    CAPTCHA_TITLE_MARKERS = (
        "just a moment",
        "checking your browser",
        "verifying you are human",
        "attention required",
        "additional verification",
    )
    # A managed challenge clears itself once Cloudflare's background checks
    # finish. Measured at three to four minutes, so this is that with room.
    CAPTCHA_CLEAR_LIMIT = 6 * 60

    def _captchaShowing(self):
        """True when a Cloudflare challenge is up instead of the real page."""
        try:
            if self._visible_only(
                    self.driver.find_elements('xpath', self.CAPTCHA_MARKER_XPATH)):
                return True
        except (PlaywrightError, PlaywrightTimeoutError):
            pass
        try:
            title = (self._page.title() or "").lower()
        except (PlaywrightError, PlaywrightTimeoutError):
            return False
        return any(marker in title for marker in self.CAPTCHA_TITLE_MARKERS)

    def _tickTurnstileBox(self):
        """Best effort click on the "Verify you are human" checkbox.

        The checkbox is plain DOM, but it lives inside an iframe that sits
        inside a CLOSED shadow root (see the capture). Closed means no selector
        run against the page can reach it -- not the page's own scripts, and
        not frame_locator either, which resolves the iframe through the DOM.

        page.frames does not go through the DOM at all: it is the browser's own
        frame tree, so the challenge frame is reachable there even though the
        element hosting it is not. Whether Cloudflare ACCEPTS a synthetic click
        is its own question, which is why nothing depends on this working -- it
        is tried once, cheaply, and the wait below is what actually clears it.
        """
        try:
            for frame in self._page.frames:
                if "challenges.cloudflare.com" not in (frame.url or ""):
                    continue
                box = frame.query_selector("input[type=checkbox]")
                if box is None:
                    continue
                box.click(timeout=3000)
                ct_print("clearCaptcha", "ticked the Turnstile checkbox")
                return True
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            ct_error("_tickTurnstileBox", exc)
        return False

    def clearCaptcha(self, limit=None):
        """Sit out a Cloudflare challenge rather than abandoning the job.

        Returns True when the page is usable (including when there was no
        challenge at all, which is the normal case and costs nothing).

        Three ways past it are tried, cheapest first: the 2Captcha extension's
        own button if it has offered one, the Turnstile checkbox, and then
        simply waiting -- which is the one that reliably works, because a
        managed challenge is designed to clear on its own once the background
        checks pass.
        """
        if not self._captchaShowing():
            return True

        limit = self.CAPTCHA_CLEAR_LIMIT if limit is None else limit
        self.reportAction(
            f"Cloudflare is challenging this page instead of showing the job. Waiting up "
            f"to {limit // 60} minutes for it to clear rather than skipping the job.", False)

        self.handleCaptcha()
        self._tickTurnstileBox()

        ct_wait("clearCaptcha", "the Cloudflare challenge to clear", f"limit={limit}s")
        cleared = self._wait_until(lambda: not self._captchaShowing(), limit)
        if cleared:
            # The real page is served by a redirect once the challenge passes,
            # and its controls are not up the instant the challenge markers go.
            self.waitOutLoading()
            ct_print("clearCaptcha", "challenge cleared", self.driver.current_url[:80])
            self.reportAction("The Cloudflare challenge cleared; carrying on with this job.",
                              False)
        else:
            self.reportAction(
                f"The Cloudflare challenge was still up after {limit // 60} minutes, so this "
                f"job was skipped.", False)
        return cleared

    # The apply flow renders a spinner and NOTHING else while a step loads --
    # HTMLz/review_loading.html and HTMLz/before_review_resume.html are both
    # nothing but this indicator. The review page in particular arrives this way
    # and turns into the real page a few seconds later.
    LOADING_INDICATOR_XPATH = '//*[@data-testid="loading-indicator"]'
    PAGE_LOAD_LIMIT = 45

    def _loadingShowing(self):
        try:
            return bool(self._visible_only(
                self.driver.find_elements('xpath', self.LOADING_INDICATOR_XPATH)))
        except PlaywrightError:
            return False

    def waitOutLoading(self, limit=None):
        """Hold until the page stops showing its loading spinner.

        Without this, a handler that runs against the spinner finds none of the
        controls it needs and concludes the page is broken -- a false alarm on a
        page that was merely a second from being ready. Returns immediately when
        nothing is loading, so it costs nothing in the normal case.
        """
        if not self._loadingShowing():
            return True

        limit = self.PAGE_LOAD_LIMIT if limit is None else limit
        ct_wait("waitOutLoading", "the page to finish loading", f"limit={limit}s")
        if self._wait_until(lambda: not self._loadingShowing(), limit):
            # The controls are added just after the spinner goes, not with it.
            t.sleep(.5)
            return True
        self.reportAction(
            f"The page was still loading after {limit}s.", False)
        return False

    SUBMIT_BUTTON_XPATH = (
        '//*[@data-testid="submit-application-button"]'
        " | //button[normalize-space(.)='Submit your application']"
        " | //button[span[contains(text(),'Submit')]]"
    )

    def _reviewPageReady(self):
        return bool(self._visible_only(self.driver.find_elements(
            'xpath', f"{self.REVIEW_RESUME_EDIT_XPATH} | {self.ADD_DOCS_XPATH}"
                     f" | {self.SUBMIT_BUTTON_XPATH}")))

    def waitForReviewPage(self, limit=None):
        """Wait until the review page has actually arrived.

        The spinner clearing is NOT the signal. The flow lands on
        .../applybyapplyablejobid with the review page's TITLE already set --
        which is what the config matches on -- sits there a moment, and only
        then navigates to /form/review-module. A run that went hunting for
        controls in that gap found none and called for a human 1.3 seconds
        before the page turned up:

            STUCK | hitEditFromReviewPage() ... /applybyapplyablejobid?...
            ATTENTION CLEARED (1295ms later) ... /form/review-module|Review...

        Waiting for one of the page's own controls covers both the spinner and
        the navigation that follows it.
        """
        self.waitOutLoading(limit)
        if self._reviewPageReady():
            return True

        limit = self.PAGE_LOAD_LIMIT if limit is None else limit
        ct_wait("waitForReviewPage", "the review page's own controls", f"limit={limit}s")
        return self._wait_until(self._reviewPageReady, limit)

    # The review page's resume section. Direct selectors are tried before the
    # find-the-heading-then-look-nearby search, which is slow and depends on the
    # heading being the literal text node "Resume".
    REVIEW_RESUME_EDIT_XPATH = (
        '//*[@data-testid="ResumeSection-edit-button"]'
        ' | //*[@data-testid="resume-section-edit-button"]'
        " | //*[@aria-label='Edit resume']"
        " | //*[starts-with(@aria-label, 'Edit') and contains(@aria-label, 'resume')]"
        " | //*[starts-with(@aria-label, 'Edit') and contains(@aria-label, 'Resume')]"
    )

    def hitEditFromReviewPage(self):
        """Open the resume editor from the application review page.

        This used to be a single line ending in `[0]`, so the moment Indeed
        stopped rendering a text node of exactly "Resume" it raised IndexError.
        That escaped to RunUser, which closes Chrome and restarts -- which is
        why the browser was seen closing mid-run.

        Now: try the labelled controls first, fall back to the relative search
        with a whitespace-tolerant, case-insensitive heading match, and if
        nothing at all is found, ask for a human rather than crashing.
        """
        # This page arrives as a spinner, and then navigates, before any of its
        # controls exist.
        self.waitForReviewPage()

        editButton = self.findAndClick(self.WHOLE, self.WHOLE, self.REVIEW_RESUME_EDIT_XPATH,
                                       txtCond="@#$ never matches %^&", timeLimit=4)

        if editButton is None:
            # Fall back to "find the resume heading, then the nearest Edit".
            # translate() is the XPath 1.0 way to lower-case; normalize-space
            # makes it survive the surrounding whitespace that an exact
            # text()='Resume' comparison chokes on.
            #
            # The length guard is what keeps this honest. Without it the match
            # is any element mentioning "resume" -- including a sentence of body
            # text -- and the search then climbs to whatever Edit button happens
            # to be nearest, which on the review page is Contact information's.
            # A heading is short; prose is not.
            heading = ("//*[contains(translate(normalize-space(text()),"
                       " 'RESUME', 'resume'), 'resume')"
                       " and string-length(normalize-space(text())) < 20]")
            edit = ("//*[normalize-space(.)='Edit']"
                    " | //*[starts-with(normalize-space(@aria-label), 'Edit')]")
            relatives = self.findClosestRelatives(self.WHOLE, self.WHOLE, heading,
                                                  self.WHOLE, self.WHOLE, edit,
                                                  limit=4, srchLvlLmt=4)
            visible = self._visible_only(relatives)
            editButton = (visible or relatives or [None])[0]

        if editButton is None:
            # Not every application offers one. HTMLz/review_application.html is
            # a real review page whose only controls are "Preview what the
            # employer sees" and "Submit your application" -- there is nothing
            # to edit and nothing wrong. Pausing for a human there would stop
            # the run on a perfectly healthy page, so only an unrecognisable
            # page raises; a loaded one just moves on to documents and submit.
            if self._visible_only(self.driver.find_elements(
                    'xpath', self.SUBMIT_BUTTON_XPATH)):
                self.reportAction(
                    "This application's review page has no resume edit step, so it goes "
                    "straight on to supporting documents and submission.", False)
                return None

            raise NeedsHumanError(
                "The review page never finished loading -- it has no Edit control and no "
                "Submit button on it. Save this page's HTML so the selectors can be updated, "
                "then press Start applying to carry on.")

        return self.smartClick(element=editButton)
    def addResume(self):
        """Continue past the resume selection page.

        Was: find every element whose text is "Continue", click them ALL, then
        return p[0] -- which raises IndexError on an empty list, and which
        clicks the five hidden decoy buttons this page ships alongside the real
        one. clickContinue already prefers data-testid="continue-button" and
        falls back to the text, which is what the questions page needs since its
        Continue carries a hashed test id.
        """
        return self.clickContinue(["Continue", "Continue applying", "Review your application"])
    def backToDidContactInfo(self):
        pass
    # Resume editor sections. Indeed rebuilt this page too: the old
    # id="edit-contact-info" is gone, and the section buttons now carry no text
    # at all -- they are icon buttons identified by data-testid or aria-label.
    # Old selectors are kept as trailing alternatives.
    CONTACT_EDIT_XPATH = (
        '//*[@data-testid="contact-info-edit-button"]'
        " | //*[@aria-label='Edit contact information']"
        ' | //*[contains(@id, "edit-contact-info")]'
    )
    SUMMARY_EDIT_XPATH = (
        "//*[@aria-label='Edit summary']"
        " | //*[@aria-label='Add summary']"
        # Scoped fallback, in case the label is reworded again.
        ' | //*[@data-testid="summary-section"]//button[starts-with(@aria-label, "Edit")'
        ' or starts-with(@aria-label, "Add")]'
    )
    # When the summary is BLANK there is no Edit button at all -- the section is
    # a single empty-state button reading "Draft a summary with AI". Looking
    # only for Edit/Add meant every resume without a summary skipped the
    # summary, which is exactly the state the stuck run was in.
    SUMMARY_EMPTY_STATE_XPATH = '//*[@data-testid="summary-empty-state"]'

    def startContactInfo(self):
        return self.findAndClick(self.WHOLE, self.WHOLE, self.CONTACT_EDIT_XPATH, checkNewPage=True)

    SUMMARY_TEXT_XPATH = ("//*[@aria-label='Summary'][@contenteditable='true']"
                          " | //*[@aria-label='Summary']"
                          " | //div[@role='textbox']")

    def startSummary(self):
        """Write the summary.

        The summary is edited IN PLACE on the resume page now -- there is no
        /resume/summary page to navigate to any more. Opening the editor left
        the URL unchanged, so the state machine found no rule for the new state,
        fell through to its default, and looped back to the top of the resume
        forever. Doing the whole edit here (open, fill, save) keeps it in one
        state transition.
        """
        # When the editor is already open there IS no Edit button -- the section
        # shows Save/Cancel/Clear instead (HTMLz/Summary_Section.html). Waiting
        # 8s for an Edit button that cannot be there and then giving up left the
        # summary unwritten with only a line in the log to show for it.
        alreadyOpen = bool(self._visible_only(
            self.driver.find_elements('xpath', self.SUMMARY_SAVE_XPATH)))

        if not alreadyOpen:
            # Tried as two lookups rather than one union: a union returns
            # matches in document order, so the empty-state button could win
            # even when a proper Edit button is present.
            opened = self.findAndClick(self.WHOLE, self.WHOLE, self.SUMMARY_EDIT_XPATH,
                                       timeLimit=5)
            if opened is None:
                opened = self.findAndClick(self.WHOLE, self.WHOLE,
                                           self.SUMMARY_EMPTY_STATE_XPATH, timeLimit=5)
            if opened is None:
                self.reportAction(
                    "The summary section offers no way in -- no Edit button, no empty-state "
                    "button, and the editor is not already open -- so the summary was not "
                    "written.", False)
                return None

        box = self.findAndClick(self.WHOLE, self.WHOLE, self.SUMMARY_TEXT_XPATH,
                                txtCond="@#$ never matches %^&", timeLimit=8)
        if box is None:
            self.reportAction("Opened the summary editor but found no text box in it.", False)
            return None
        self.fillMoveOn(box, self.resumeSummary)

        saved = self.findAndClick(self.WHOLE, self.WHOLE, self.SUMMARY_SAVE_XPATH, timeLimit=8)
        if saved is None:
            self.reportAction("Filled the summary but could not find its Save button.", False)
        return saved
    def startWorkExp(self):
        return self.do_work_exp()
    def startEdu(self):
        return self.do_edu()
    def startSkills(self):
        return self.do_skills()
    FINISH_RESUME_XPATH = (
        '//*[@data-testid="indeed-resume-detail-continue-to-application"]'
        " | //button[normalize-space(.)='Continue applying']"
    )
    # The editor's back arrow. NOTE: where this goes depends on how the editor
    # was reached. From /resume?...&continue=<app url> it returns to the
    # application. From bare /resume it goes to the Indeed PROFILE HOME
    # (HTMLz/profile_resume_indeed.html), which is outside the application
    # entirely and matches no configured page, so the run stops dead. It is
    # therefore a last resort, not the first choice.
    RESUME_GO_BACK_XPATH = "//*[@aria-label='Go back']"
    # Present only in the standalone profile editor -- the tell that we have
    # dropped out of the application.
    DELETE_RESUME_XPATH = '//*[@data-testid="delete-resume-button"]'

    def finishResume(self):
        """Leave the resume editor and get back to the application.

        "Continue applying" exists only while the editor knows there is an
        application to return to. It is reached as

            /resume?co=US&hl=en_US&continue=<the application url>

        and saving a work experience navigates within the editor, after which
        Indeed drops that query string. From then on the page is the STANDALONE
        profile editor: byte-for-byte the same resume, but its footer offers
        "Delete resume" instead of "Continue applying", and there is no way
        onward from it. (HTMLz/Edit_Resume_Stuck.html vs Edit_resume_unstuck.html
        differ in exactly that one button.)

        A run that landed there timed out looking for Continue applying, fell
        through to the resume page's default rule, and started the whole resume
        again -- five times over, deleting and re-adding the same four jobs each
        pass, which is where the twenty "X removed" banners came from.

        "Go back" returns to the resume selection page, which is inside the
        application again, and the flow picks up from there.
        """
        finished = self.findAndClick(self.WHOLE, self.WHOLE, self.FINISH_RESUME_XPATH,
                                     waitBeforeClicking=.7, checkNewPage=True, timeLimit=6)
        if finished is not None:
            return finished

        # Preferred route back: the address the editor was opened with. The
        # `continue=` parameter IS the application URL, so once it has been seen
        # there is no need to guess.
        if self.applicationReturnUrl:
            self.reportAction(
                f"The resume editor is not offering 'Continue applying', so going straight "
                f"back to the application it was opened from.", False)
            try:
                self._page.goto(self.applicationReturnUrl)
                self.waitOutLoading()
                return self.applicationReturnUrl
            except PlaywrightError as exc:
                ct_error("finishResume (return to application)", exc)

        # Last resort. The back arrow only leads to the application when the
        # editor still holds its `continue=` context; from bare /resume it lands
        # on the Indeed profile home instead, which is a dead end. One run
        # ended exactly there and had to be rescued by hand.
        self.reportAction(
            "No 'Continue applying' button and no remembered application address, so trying "
            "the editor's back arrow.", False)

        urlBefore = self._page.url
        back = self.findAndClick(self.WHOLE, self.WHOLE, self.RESUME_GO_BACK_XPATH,
                                 checkNewPage=True, timeLimit=6)
        left = back is not None and self._wait_until(
            lambda: self._page.url != urlBefore
            or bool(self._visible_only(self.driver.find_elements(
                'xpath', self.FINISH_RESUME_XPATH))), 8)

        if not left or self.onProfileHome():
            raise NeedsHumanError(
                "The resume editor has no 'Continue applying' button, and going back led to "
                "the Indeed profile page rather than into the application. The application "
                "cannot be reached from here. Open it again and press Start applying."
                if self.onProfileHome() else
                "The resume editor has no 'Continue applying' button and going back did not "
                "work either, so there is no way on from this page. Click the back arrow "
                "yourself to return to the resume selection page, then press Start applying.")
        return back
    def startAtTopOfReviewPage(self):
        pass
    def doContactInfo(self):
        return self.edit_contact_info()
    def goBackToStartCI(self):
        pass
    def doSummary(self):
        return self.do_summary()
    def goBackToStartSum(self):
        pass
    def doWorkExp(self):
        return self.do_work_exp()
    def goBackToStartWork(self):
        pass
    def doEdu(self):
        return self.do_edu()
        #return self.fillEducationInfo()
    def goBackToStartEdu(self):
        pass
    def doSkills(self):
        return self.do_skills()
    def goBackToStartSkills(self):
        pass
    def doQuestions(self):
        return self.analyzeAndAnsQuestions()
    # The apply flow renders several hidden placeholder Continue buttons
    # (data-testid="hp-continue-button-0..5") alongside the working one. Matching
    # on the text "Continue" finds all of them and takes the first in DOCUMENT
    # order -- a hidden one -- which then burns a 5s click timeout and fails.
    # The real button is the one with data-testid="continue-button".
    CONTINUE_BUTTON_XPATH = '//*[@data-testid="continue-button"]'

    def clickContinue(self, labels, checkNewPage=True, waitBeforeClicking=.7):
        """Advance the application, preferring the real Continue button.

        Tried as two separate lookups rather than one xpath union, because a
        union returns matches in document order -- listing the good selector
        first would not make it win.
        """
        result = self.findAndClick(self.WHOLE, self.WHOLE, self.CONTINUE_BUTTON_XPATH,
                                   waitBeforeClicking=waitBeforeClicking,
                                   checkNewPage=checkNewPage, timeLimit=4, nohang=True)
        if result is not None:
            return result

        # The BUTTON itself, before falling back to matching bare text. The
        # questions page renders <button data-testid="<hash>"><span>Continue</span></button>,
        # so the test id is useless and //*[text()='Continue'] matches the inner
        # SPAN. Clicking a span works only because the event bubbles; clicking
        # the button is what was actually meant.
        for label in labels:
            byButton = self.findAndClick(
                self.WHOLE, self.WHOLE,
                f"//button[normalize-space(.)='{label}']"
                f" | //*[@role='button'][normalize-space(.)='{label}']",
                waitBeforeClicking=waitBeforeClicking, checkNewPage=checkNewPage,
                timeLimit=3, nohang=True)
            if byButton is not None:
                return byButton

        return self.findAndClick(self.TXT, self.MATCH, labels,
                                 waitBeforeClicking=waitBeforeClicking,
                                 checkNewPage=checkNewPage)

    def keepGoing(self):
        return self.clickContinue(
            ["Continue", "Review your application", "Continue applying", "Continue to application"])

    def continueFromPage(self):
        return self.clickContinue(
            ["Continue", "Review your application", "Submit your application"],
            checkNewPage=False, waitBeforeClicking=0)
    # The review page's supporting-documents section. Its control is a BUTTON
    # labelled "Add" -- the old code hunted for the nearest <a> to the words
    # "Supporting documents", found none (there is no anchor there), and kept
    # climbing parents until it hit whatever link came first. On these pages
    # that is "Privacy Policy" or "Terms of Service" in the footer, so a missing
    # section meant navigating away from the application entirely.
    ADD_DOCS_XPATH = (
        "//*[@aria-label='Add supporting documents']"
        " | //*[@data-testid='SupportingDocumentsSection-add-button']"
        " | //*[starts-with(@aria-label, 'Add') and contains(@aria-label, 'supporting')]"
        " | //*[starts-with(@aria-label, 'Add') and contains(@aria-label, 'Supporting')]"
    )

    # How many times, combined across clickAddDocs() and do_cover_letter(),
    # the bot will try to get through the "add a cover letter" step before
    # giving up and submitting without one. Some review pages never actually
    # offer a working way to add one, and do_cover_letter()'s own Continue-
    # button check raises NeedsHumanError when the page will not let it
    # proceed -- which, on a page that can never satisfy it, retried forever
    # once attentionWaived muted the alert after the first pause. self.jobs
    # is a fresh application, freshly generated cover letter and all, so the
    # count is reset there rather than here.
    ADD_DOCS_ATTEMPT_LIMIT = 5

    def _addDocsAttemptsExhausted(self, where):
        self._addDocsAttempts = getattr(self, "_addDocsAttempts", 0) + 1
        if self._addDocsAttempts > self.ADD_DOCS_ATTEMPT_LIMIT:
            self.reportAction(
                f"Giving up on adding a cover letter after {self.ADD_DOCS_ATTEMPT_LIMIT} "
                f"attempts ({where}); submitting the application without one.", False)
            return True
        return False

    def _findInFrames(self, xpath):
        """xpath's matches inside any iframe on the page, main frame excluded
        (the ordinary DOM search already covers that one).

        Playwright's page-level queries never reach into an iframe's own
        document -- srcdoc or not, same origin or not, it is always a
        separate frame context. _tickTurnstileBox() already works around
        exactly this for the Cloudflare checkbox; "Add supporting documents"
        turns out to have the same problem on some applications, rendering
        inside <iframe data-testid="application-preview" srcdoc="..."> (the
        review page's own read-only application preview) instead of the page
        itself -- which is why the ordinary search for it found nothing there
        no matter how long it waited (Logs/Log34.txt,
        HTMLz/review_application_stuck2.html).
        """
        matches = []
        for frame in self._page.frames:
            if frame == self._page.main_frame:
                continue
            try:
                handles = frame.query_selector_all(f"xpath={xpath}")
            except PlaywrightError:
                continue
            matches.extend(_ElementCompat(h, self) for h in handles)
        return matches

    def clickAddDocs(self):
        if self._addDocsAttemptsExhausted("clickAddDocs"):
            return None

        # Same page as submitApp, and it arrives the same way: spinner, then a
        # navigation, and only then the controls.
        self.waitForReviewPage()
        addButton = self.findAndClick(self.WHOLE, self.WHOLE, self.ADD_DOCS_XPATH,
                                      txtCond="@#$ never matches %^&", timeLimit=6)
        if addButton is None:
            # Not every application renders this control on the page itself --
            # see _findInFrames' docstring. Same selector, just also tried
            # inside whatever iframes are actually on this page.
            inFrame = self._visible_only(self._findInFrames(self.ADD_DOCS_XPATH))
            addButton = inFrame[0] if inFrame else None
        if addButton is None:
            self.reportAction("This application has no 'Add supporting documents' control, "
                              "so the cover letter step was skipped.", False)
            return None
        return self.smartClick(element=addButton, checkNewPage=True)

    def prepDBCommit(self):
        companyInfo = f"{self.companyName}~+~{self.jobTitle}~+~{self.JobDescriptionText}"

        # full name
        fullName = f"{self.firstName} {self.lastName}"

        #prev job info
        resume = f"{fullName}~+~{self.headline}~+~{self.jobs}~+~{self.edus}~+~{self.skills}~+~{self.resumeSummary}"

        # save the application in database
        #self.saveAppInDB(companyInfo, resume, self.coverLetter)
        self.saveAppInDB(self.companyName, self.jobTitle, self.JobDescriptionText, fullName,
                         self.headline,  str(self.jobs), str(self.edus), str(self.skills),
                         self.resumeSummary, str(self.prev_questions), self.coverLetter)

        self.MML.append(datetime.datetime.now() )

    def saveUserInDB(self):
        emailCol = "IndeedEmail"
        passCol = "IndeedPass"
        checker_query = """SELECT * FROM users WHERE FirstName = ? AND LastName = ? AND PhoneNumber = ? AND 
                          email = ? AND address = ? AND cityState = ? AND country = ? AND zip = ?"""
        insert_query = f"""INSERT INTO users (FirstName, LastName, PhoneNumber, 
                                 email, address, cityState, country, zip, {emailCol}, {passCol})
                                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        values = [self.firstName, self.lastName, self.phone_num, self.email,
                  self.addr, self.areaSpec, self.country, self.zip]
        conn = sqlite3.connect('IndHelperDB.db')
        cursor = conn.cursor()

        # Create the table if it doesn't exist
        #cursor.execute('''CREATE TABLE IF NOT EXISTS users
        #                         (id INTEGER PRIMARY KEY, FirstName TEXT, LastName TEXT, PhoneNumber TEXT,
        #                         email TEXT, address TEXT, cityState TEXT, country TEXT, zip TEXT)''')

        # Check if the record already exists
        cursor.execute(checker_query, values)

        # Fetch one record, if it exists
        existing_record = cursor.fetchone()

        # If the record does not exist, insert it
        if not existing_record:
            platformEmail = input(f"Enter {self.firstName}'s platform email")
            platformPass = input(f"Enter {self.firstName}'s platoform password")
            values.extend([platformEmail, platformPass])
            cursor.execute(insert_query,tuple(values))

            # Save (commit) the changes
            conn.commit()
            self.user_id = cursor.lastrowid
        else:
            self.user_id = existing_record[0]
            platformEmail = existing_record[-2]
            platformPass = existing_record[-1]
            for fname, field in [(emailCol, platformEmail), (passCol, platformPass)]:
                if not field:
                    values_ = tuple( [input(f"What is {self.firstName}'s {fname}")] + values)
                    update_query = f"""UPDATE users SET {fname} = ? WHERE FirstName = ? AND LastName = ? AND PhoneNumber = ? AND 
                                  email = ? AND address = ? AND cityState = ? AND country = ? AND zip = ?"""
                    cursor.execute(update_query, values_)
            print(f"User '{self.firstName}' already exists.")

        # Close the connection
        conn.commit()
        conn.close()




    #def saveAppInDB(self, companyInfo, resumeInfo, coverLetter):
    def saveAppInDB(self, companyName, jobTitle, JobDescriptionText, fullName, headline, jobHist,
                    eduHist, skills, resumeSummary, prevQsAs, coverLetter):
        #https://chat.openai.com/c/17e56ec1-3cb5-4b4b-8b64-5632efe21023

        current_date = datetime.datetime.now().isoformat(' ', 'seconds')

        # Connect to the resume_records database
        conn = sqlite3.connect('IndHelperDB.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Create the records table with a foreign key for the user ID
        cursor.execute('''CREATE TABLE IF NOT EXISTS applications
                         (id INTEGER PRIMARY KEY, user_id INTEGER, DateTime TEXT, Platform TEXT,
                          companyName TEXT, jobTitle TEXT, JobDescriptionText TEXT, 
                          fullName TEXT, headline TEXT, jobHist TEXT, eduHist TEXT, 
                          skills TEXT, resumeSummary TEXT, QsAndAs TEXT, cover_letter TEXT,
                          FOREIGN KEY(user_id) REFERENCES users(id))''')

        # Insert a new application record with the user ID
        cursor.execute("""INSERT INTO applications (user_id, DateTime, Platform, companyName, jobTitle, JobDescriptionText, 
                          fullName, headline, jobHist, eduHist, skills, resumeSummary, QsAndAs, cover_letter)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                       (self.user_id, current_date, "Indeed", companyName, jobTitle, JobDescriptionText, fullName,
                        headline, jobHist, eduHist, skills, resumeSummary, prevQsAs, coverLetter))

        # update the fact that we've sent another application
        cursor.execute("""SELECT * FROM users WHERE id = ? """, (self.user_id,))
        userRec = cursor.fetchone()
        self.applicationsLeft = userRec["AppsLeft"]
        self.applicationsLeft -= 1
        cursor.execute("""UPDATE users SET AppsLeft = ? WHERE id = ? """, (self.applicationsLeft, self.user_id))


        # Save (commit) the changes
        conn.commit()

        # Close the connection
        conn.close()

    def closeAndReopenTab(self):
        #  use pygetwindow to find the proper window
        newTitle = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        self.driver.execute_script(f"document.title = '{newTitle}';")
        windows = gw.getWindowsWithTitle("Chrome")
        win_2_use = None
        for window in windows:
            if newTitle in window.title:
                win_2_use = window
                break

        #-------------------
        self.driver.close()
        win_2_use.activate()
        pyautogui.hotkey('ctrl', 'shift', 't')
        t.sleep(5)
        self.driver.switch_to.window(self.driver.window_handles[-1])


    # A captcha embedded in the submit step, as opposed to a whole "Just a
    # moment..." interstitial page. The old code CLICKED this, which does not
    # solve anything.
    SUBMIT_CAPTCHA_XPATH = ('//*[@id="captcha-wrapper"]'
                            ' | //*[@id="cf-turnstile"]'
                            ' | //iframe[contains(@src, "recaptcha")]')

    # Where each captcha provider writes its solved token. Neither widget
    # disappears or hides itself once solved -- a checked reCAPTCHA box still
    # renders the same iframe, just showing a checkmark instead of an empty
    # box (HTMLz/review_application_stuck.html) -- so SUBMIT_CAPTCHA_XPATH's
    # mere PRESENCE can never tell solved from unsolved. The response field is
    # empty until solved and holds a long token afterward, in both providers.
    SUBMIT_CAPTCHA_RESPONSE_XPATH = ('//textarea[@id="g-recaptcha-response"]'
                                     ' | //*[@name="cf-turnstile-response"]')

    def _submitCaptchaSolved(self):
        for box in self.driver.find_elements('xpath', self.SUBMIT_CAPTCHA_RESPONSE_XPATH):
            try:
                if (box._handle.input_value() or "").strip():
                    return True
            except (PlaywrightError, PlaywrightTimeoutError):
                continue
        return False

    def _bringWindowToFront(self):
        """Raise this bot's own Chrome window above every other window on
        screen, including other bots' -- several run in parallel, one per
        user profile, and a beep alone does not say WHICH window needs you.

        Same find-by-title trick closeAndReopenTab already uses: borrow the
        page title as a temporary, unique marker to pick this window out of
        every "Chrome"-titled one, then put the real title back so nothing
        else that reads it (getCurrentEnv, most of all) gets confused.
        """
        try:
            original_title = self._page.title()
            marker = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            self.driver.execute_script(f"document.title = {json.dumps(marker)};")
            for window in gw.getWindowsWithTitle("Chrome"):
                if marker in window.title:
                    window.activate()
                    break
            self.driver.execute_script(f"document.title = {json.dumps(original_title)};")
        except Exception as exc:
            ct_error("_bringWindowToFront", exc)

    def _alertForManualCaptcha(self):
        """Called once, right where an unsolved submit-step captcha is
        found: bring this window to the front and beep sharply, on top of
        (not instead of) the normal pause-and-alert cadence that follows
        once NeedsHumanError reaches the state machine -- a captcha sitting
        under a person's nose is exactly the situation that most needs
        immediate, unambiguous notice, not a beep competing with N other
        bots' windows for attention (Logs/Log32.txt).
        """
        self._bringWindowToFront()
        for _ in range(5):
            _beep()
            t.sleep(.3)

    def submitApp(self):
        # ================= TEMPORARY DEBUG STOP (2026-09-05) =================
        # Cover-letter verification: stop here, EVERY time, right before the
        # actual Submit click -- so the review page can be inspected (cover
        # letter, supporting documents, everything clickAddDocs()/addDocs()
        # did) before the application goes out irreversibly. Left in
        # deliberately across multiple applications until cover letters are
        # confirmed working reliably. Remove this raise (and this comment
        # block) once that confidence is established.
        raise NeedsHumanError(
            "TEMPORARY STOP before submitting: check that the cover letter (and any "
            "supporting documents) were actually added correctly on this application "
            "before pressing Start applying. This stop is deliberate and stays in "
            "until cover letters are confirmed working reliably across multiple "
            "applications.")
        # =======================================================================

        # The review page arrives as a spinner and then navigates; the Submit
        # button is not on it until both are done. See HTMLz/review_loading.html
        # (the spinner) and HTMLz/review_application.html (the real page).
        self.waitForReviewPage()

        # click the checkbox so they contact the person directly thru number too (maybe turn this off if you need to verify the leads)
        clickRes = self.findAndClick(self.WHOLE, self.WHOLE, "//input[@type='checkbox']", travelUp=1, timeLimit=1)
        if isinstance(clickRes, StartFromTop):
            return clickRes
        path_4_button_containing_span = "//button[span[contains(text(),'Submit')]]"
        sub = self.findAndClick(self.TXT, self.MATCH, "Submit your application", txtCond="asdfaf",
                                timeLimit=5)
        if sub is not None:
            # Guarded: this used to pass None straight into execute_script when
            # the lookup timed out, and the resulting crash reached RunUser,
            # which closes the browser and restarts.
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", sub)

        # A captcha here has to be solved by a person. Clicking its wrapper --
        # what this did before -- accomplishes nothing and then submits anyway.
        # Stop and beep instead, the same as a bot check.
        #
        # Checked for being UNSOLVED, not merely present: neither reCAPTCHA
        # nor Turnstile removes or hides its widget once solved, so a plain
        # presence check kept raising this on every single retry even after
        # a person solved it by hand -- attentionWaived then muted the
        # re-alert, and the run just sat there quietly re-failing to submit
        # every 5 seconds, forever, looking exactly like the captcha had
        # never been solved at all (Logs/Log32.txt).
        if (self._visible_only(self.driver.find_elements('xpath', self.SUBMIT_CAPTCHA_XPATH))
                and not self._submitCaptchaSolved()):
            self._alertForManualCaptcha()
            raise NeedsHumanError(
                "There is a captcha on the submit step. Solve it in the browser window, "
                "then press Start applying and the application will be submitted.")

        clickRes = self.findAndClick(self.WHOLE, self.WHOLE, path_4_button_containing_span, waitBeforeClicking=.7,
                                     checkNewPage=True, newPageFollowsTimeLimit=True)
        if isinstance(clickRes, StartFromTop):
            return clickRes
        '''if True:
        t.sleep(5)
        print("do it now")
        pyautogui.hotkey('ctrl', 'shift', 't')'''
        if clickRes == -1:
            self.closeAndReopenTab()


        #self.prepDBCommit()

        return clickRes
    def addDocs(self):
        return self.do_cover_letter()

    def quickWaitAndRefresh(self):
        t.sleep(10)
        self.driver.refresh()
        t.sleep(60)

    def doDbThenbackToStart(self):
        self.prepDBCommit()
        self.backToStart()

    def goHome(self):
        """Navigate straight back to this profile's search URL.

        Used by the Run tab's "Go to home" button, and after start-up so the
        browser lands somewhere known before pausing.
        """
        ct_print("goHome", self.home_url[:90])
        self.reportAction(f"Going to home page: {self.home_url}", False)
        self.driver.get(self.home_url)

    def backToApplication(self):
        """Recover from the Indeed profile page, which is outside the application.

        Reached by the resume editor's back arrow when the editor no longer
        holds its `continue=` context. If the application address was captured
        earlier, go straight there; otherwise the application is unreachable and
        the honest move is to abandon it and start a new one rather than sit on
        a page with nothing to click.
        """
        if self.applicationReturnUrl:
            self.reportAction(
                "Ended up on the Indeed profile page, which is outside the application. "
                "Going back to the application.", False)
            try:
                self._page.goto(self.applicationReturnUrl)
                self.waitOutLoading()
                return self.applicationReturnUrl
            except PlaywrightError as exc:
                ct_error("backToApplication", exc)

        self.reportAction(
            "Ended up on the Indeed profile page with no way back into the application, "
            "so this one is being abandoned and the next job started.", False)
        return self.backToStart()

    def backToStart(self):
        pattern = self.escape_regex_special_chars(self.home_url_pattern)
        self.select_tab_by_url_pattern(pattern)
    def backToInit(self):
        pass
    ##############################    END TRANSITION FUNCTIONS   ##################################

    def jaccard_similarity(self, str1, str2):
        set1 = set(str1)
        set2 = set(str2)
        intersection = set1.intersection(set2)
        union = set1.union(set2)
        return len(intersection) / len(union)

    # Indeed's hashed emotion classes (css-5lfssm, css-1ac2h1w, ...) change on
    # every redeploy, so the card list is found structurally instead: the <li>
    # wrappers inside #mosaic-jobResults that directly contain a .cardOutline.
    # Both of those names are semantic and have survived Indeed's redesigns.
    JOB_CARD_SELECTOR = "#mosaic-jobResults li:has(> div.cardOutline)"

    # A skipped job is recorded as its id line, then this reason line right
    # after it -- kept on ONE line each so skipped.txt stays a flat,
    # append-only, grep-able file instead of needing a real format change.
    SKIP_REASON_PREFIX = "\treason: "

    def _lookupSkippedReason(self, jobId, skippedCont):
        """Why a job already in skipped.txt was skipped, read back out of the
        file. Entries written before this was tracked have no reason line
        after them -- that is not an error, just history from before
        Logs/log29.txt showed the skip needed to explain itself.
        """
        target = jobId.strip()
        lines = skippedCont.splitlines()
        for i, line in enumerate(lines):
            if line == target:
                if i + 1 < len(lines) and lines[i + 1].startswith(self.SKIP_REASON_PREFIX):
                    return lines[i + 1][len(self.SKIP_REASON_PREFIX):].strip()
                return "no reason recorded (skipped before this was tracked)"
        return "reason unavailable"

    def _recordSkippedJob(self, jobId, reason):
        f = open(self.MY_PATH + "skipped.txt", 'a')
        f.write(jobId)
        # Collapsed to one line: the model's reply can carry its own line
        # breaks, and a reason spanning multiple lines would be
        # indistinguishable from the next job's id line to the reader above.
        f.write(f"{self.SKIP_REASON_PREFIX}{' '.join(reason.split())}\n")
        f.close()

    def process_job_openings(self):
        #  loop to go thru the different pages
        while True:
            #find the list of job openings
            openings = self.driver.find_elements(By.CSS_SELECTOR, self.JOB_CARD_SELECTOR)
            if len(openings) == 0:
                # Silence here used to look exactly like "the bot is doing
                # nothing", so say it out loud -- it almost always means Indeed
                # changed the results markup again.
                ct_print("process_job_openings", "NO JOB CARDS FOUND",
                         f"selector={self.JOB_CARD_SELECTOR} url={self.driver.current_url[:80]}")
                self.reportAction(
                    f"Found 0 job cards with {self.JOB_CARD_SELECTOR}. Either the page has not "
                    f"loaded, or Indeed changed the results markup.", False)
            else:
                ct_print("process_job_openings", f"{len(openings)} job cards on this page")
            for opening in openings:
                self.MML.append(datetime.datetime.now())
                #  check if it's a non-interactable opening
                try:
                    if len(opening.text) == 0 or "Easily apply" not in opening.text or "card" not in self.get_child(
                            opening).get_attribute("class"):
                        continue
                except Exception as e:
                    print("An error occurred:", e)
                    traceback.print_exc()
                    still = 456

                link = self.findAndClick(self.WHOLE, self.WHOLE, self.LINK, txtCond="asdf", findFrom=opening,
                                         timeLimit=1)

                urlBeforeClick = self.driver.current_url
                tabsBeforeClick = len(self._context.pages)

                try:
                    self.smartClick(element=link, ctrl=True)
                except:
                    try:
                        self.smartClick(element=opening, ctrl=True)
                    except:
                        asdf = 1

                # Say plainly which page the bot is now working on. Inferring this
                # from which selectors happened to match is unreliable, because
                # the search page's right-hand pane carries a lot of the same
                # markup as the job page.
                ct_print("process_job_openings", "after opening the card",
                         f"tabs {tabsBeforeClick}->{len(self._context.pages)} | "
                         f"now on {self.driver.current_url[:80]} | "
                         f"moved={self.driver.current_url != urlBeforeClick}")

                #  get job infos


                #rs = self.findClosestRelatives(self.CONTAINS, self.TXT, "s estimated salaries", self.CONTAINS, self.CLASS, 'CloseButton', limit=1)
                #if len(rs) == 1:
                #    self.click_all(rs)

                buttonElement = self.findAndClick(self.WHOLE, self.WHOLE, self.APPLY_BUTTON_XPATH,
                                                  timeLimit=8, txtCond="$%^& Dont click yet &*(")

                if buttonElement is None and self._visible_only(
                        self.driver.find_elements('xpath', self.APPLY_BUTTON_DISABLED_XPATH)):
                    # The button exists and was just given a full search's
                    # worth of time to enable itself -- still disabled at
                    # this point means Indeed itself says this job cannot be
                    # applied to, not a captcha or a slow-rendering page.
                    # Waiting out a challenge that will never appear only
                    # burns another ~16s before landing on the same skip.
                    self.reportAction(
                        "The Apply button is disabled on this job, so it cannot be applied "
                        "to from Indeed. Skipped.", False)
                    self.backToStart()
                    continue

                if buttonElement is None:
                    # A /viewjob URL sometimes answers with a Cloudflare
                    # challenge instead of the job (HTMLz/captcha_view_job.html),
                    # which has no Apply button at all. Checked HERE, after the
                    # search above already failed, not before it: a fresh tab is
                    # still navigating in the instant right after the switch, so
                    # checking immediately found neither the real page nor a
                    # challenge and skipped three good jobs in a row before any
                    # challenge had rendered long enough to be caught
                    # (Logs/log26.txt). By the time the Apply-button search has
                    # already spent time failing, the page -- real or
                    # challenged -- has had time to settle, so this is also the
                    # right moment to give a merely-slow real page a second try.
                    #
                    # clearCaptcha() alone gives a real Cloudflare challenge as
                    # long as it needs, but returns instantly when there was
                    # never a challenge to begin with -- and the FIRST search
                    # repeatedly caught the page mid client-side navigation
                    # ("Execution context was destroyed, most likely because of
                    # a navigation", 40+ times in one run) with nothing
                    # Cloudflare-shaped to show for it. waitOutLoading() is the
                    # dedicated wait for exactly that: a real page that is
                    # merely still rendering. It is a no-op when nothing is
                    # loading, so this costs nothing on a genuinely unapplyable
                    # job (Logs/Log31.txt: "I've seen the bot make it to the
                    # page that has the apply now button, and it just ignores
                    # it" -- the button existed, the combined ~10s budget with
                    # zero real second chance just was not enough to reach it).
                    if self.clearCaptcha():
                        self.waitOutLoading()
                        buttonElement = self.findAndClick(
                            self.WHOLE, self.WHOLE, self.APPLY_BUTTON_XPATH,
                            timeLimit=8, txtCond="$%^& Dont click yet &*(")

                if buttonElement is None:
                    # means this is not a job that you can apply from Indeed site
                    self.backToStart()
                    continue

                #clear out prev Qs and As
                self.prev_questions.clear()

                # extract job info
                self.getPositionInfo()

                jobId = f"{self.companyName} {self.jobTitle}\n"

                # Cheap, non-AI filter first: an employer on the user's own
                # avoid list is skipped without ever starting the model calls
                # that jobContainsForbiddenCharacteristics() below would make.
                employerReason = self.avoidedEmployerReason(self.companyName)
                if employerReason:
                    self.reportAction(
                        f"Skipping [{jobId.strip()}] -- {employerReason}", False)
                    self._recordSkippedJob(jobId, employerReason)
                    self.backToStart()
                    continue

                f = open(self.MY_PATH + "skipped.txt", 'r')
                skippedCont = f.read()
                f.close()
                if jobId in skippedCont:
                    # This used to be entirely silent -- backToStart() and
                    # continue, nothing printed anywhere -- which is exactly
                    # what made re-skipping an already-flagged job look like
                    # the bot randomly abandoning the tab right after a
                    # captcha cleared (Logs/log29.txt: two jobs in a row hit
                    # this immediately after getPositionInfo() and vanished,
                    # with no trace explaining why).
                    reason = self._lookupSkippedReason(jobId, skippedCont)
                    self.reportAction(
                        f"Skipping [{jobId.strip()}] -- already marked to avoid: {reason}", False)
                    self.backToStart()
                    continue

                # check if this is one of the positions we want to avoid
                forbiddenReason = self.jobContainsForbiddenCharacteristics()
                if forbiddenReason:
                    self.reportAction(f"Not proceeding with [{jobId}]... it contains characteristics this user wants to avoid", False)
                    self._recordSkippedJob(jobId, forbiddenReason)
                    self.backToStart()
                    continue

                # load jobs and change job description based on the details of current job
                self.load_jobs(), self.MML.append(datetime.datetime.now() )

                # load education history
                self.load_edu(), self.MML.append(datetime.datetime.now() )

                # generate CL
                self.generateCL(), self.MML.append(datetime.datetime.now() )

                #generate skills
                self.generateSkills(), self.MML.append(datetime.datetime.now() )

                # generate headline
                self.generateHeadline(), self.MML.append(datetime.datetime.now() )

                #resume summary
                self.generateSummary(), self.MML.append(datetime.datetime.now() )


                yield


            nextButton = self.findAndClick(self.ARIA_LABEL,  self.MATCH, 'Next Page')

            # if url1 and url2 are not different, we have hit the last page of the current profile
            if nextButton is None:
                self.cur_profile = next(self.profile_generator)
                self.driver.get(self.home_url)

    # Resume selection page. Indeed rebuilt this screen: the old
    # data-testid="IndeedResumeCard" and the #ia-container xpath are both gone,
    # replaced by resume-selection-* test ids. Each xpath below tries the current
    # markup first and falls back to the old, so either layout works.
    #
    # "Use your Indeed Resume" is a styled radio, so the label is the thing to
    # click -- the <input> itself is visually hidden.
    RESUME_CARD_XPATH = (
        '//*[@data-testid="resume-selection-structured-resume-radio-card-label"]'
        ' | //*[@data-testid="resume-selection-structured-resume-radio-card"]'
        ' | //*[@data-testid="IndeedResumeCard"]'
    )
    # "Edit resume details" now lives inside this collapsed menu.
    RESUME_OPTIONS_XPATH = (
        '//*[@data-testid="resume-selection-structured-resume-radio-card-resume-options"]'
    )
    RESUME_EDIT_XPATH = (
        '//*[@data-testid="resume-selection-structured-resume-radio-card-resume-options-editResumeDetails"]'
        " | //button[contains(normalize-space(.), 'Edit resume')]"
        " | //a[contains(normalize-space(.), 'Edit resume')]"
    )

    def chooseToBuildIndeedResume(self):
        # 1. Pick "Use your Indeed Resume" rather than uploading a file.
        self.findAndClick(self.WHOLE, self.WHOLE, self.RESUME_CARD_XPATH, timeLimit=8)

        # 2. Open the "Resume options" menu. nohang, because the older layout put
        #    the edit link straight on the card with no menu to open.
        self.findAndClick(self.WHOLE, self.WHOLE, self.RESUME_OPTIONS_XPATH,
                          timeLimit=2, nohang=True)

        # 3. "Edit resume details" -- what actually moves us onto the resume form.
        editButton = self.findAndClick(self.WHOLE, self.WHOLE, self.RESUME_EDIT_XPATH, timeLimit=5)
        if editButton is None:
            self.reportAction(
                "Could not find 'Edit resume details' on the resume selection page. "
                "Indeed may have changed this screen again.", False)
        return editButton

    # The apply flow's own contact step (smartapply contact-info-module). This is
    # a different screen from the resume's "About you" page, with its own markup.
    APPLY_CONTACT_HEADING = ('//*[@data-testid="contact-info-heading"]'
                             " | //h2[normalize-space(.)='Add your contact information']")
    APPLY_FIRST_NAME_TESTID = "name-fields-first-name-input"
    APPLY_LAST_NAME_TESTID = "name-fields-last-name-input"
    APPLY_PHONE_XPATH = ('//*[@data-testid="phone-number-field"]//input'
                         " | //input[@aria-label='Type phone number']")

    def handleAddInfoPage(self):
        # The heading moved from <h1> to <h2 data-testid="contact-info-heading">,
        # and the <h1> is now the job title. Requiring the <h1> to equal
        # "Add your contact information" therefore never matched, so this whole
        # function quietly did nothing and returned None -- leaving the state
        # machine to transition didContactInfo -> didContactInfo forever.
        heading = self.findAndClick(self.WHOLE, self.WHOLE, self.APPLY_CONTACT_HEADING,
                                    txtCond="@#$ never matches %^&", timeLimit=8)
        if heading is None:
            self.reportAction(
                "On the contact-info step but its heading was not found, so nothing was "
                "filled. Indeed may have changed this screen.", False)
            return None

        self.fillByTestId(self.APPLY_FIRST_NAME_TESTID, self.firstName, "first name")
        self.fillByTestId(self.APPLY_LAST_NAME_TESTID, self.lastName, "last name")

        phone = self.findAndClick(self.WHOLE, self.WHOLE, self.APPLY_PHONE_XPATH,
                                  txtCond="@#$ never matches %^&", timeLimit=8)
        if phone is not None:
            self.fillMoveOn(phone, self.phone_num)

        # Email is read-only here, and Age is optional -- neither is ours to fill.
        # The Continue buttons on this page carry hashed test ids that change per
        # build, so clickContinue falls back to matching the label, with the
        # visible-element filter picking the real one out of the decoys.
        return self.clickContinue(["Continue"])

    # "About you" (contact) form. Every field carries a data-testid now, which is
    # far steadier than hunting for an input near a matching label -- the labels
    # move around and get reworded, the test ids have not.
    CONTACT_FIELDS = (
        # (testid,                              attribute on self, human name)
        ("first-name-input",                    "firstName",  "first name"),
        ("last-name-input",                     "lastName",   "last name"),
        ("headline-input",                      "headline",   "headline"),
        ("phone-input-input",                   "phone_num",  "phone"),
        ("street-address-input",                "addr",       "street address"),
        ("location-input-autocomplete-input",   "areaSpec",   "city/state"),
        ("postal-code-input",                   "zip",        "postal code"),
    )
    CONTACT_SAVE_XPATH = (
        '//*[@data-testid="contact-info-save"]'
        " | //button[normalize-space(.)='Save']"
    )

    # The remaining resume sub-forms, taken from saved captures of each screen.
    # Kept together so the next markup change is a one-line edit rather than a
    # hunt through the form-filling code.
    SUMMARY_SAVE_XPATH = ('//*[@data-testid="summary-inline-save-button"]'
                          " | //*[@aria-label='Save summary']")
    SUMMARY_CLEAR_XPATH = ('//*[@data-testid="summary-inline-clear-button"]'
                           " | //*[@aria-label='Clear summary']")

    WORK_TITLE_TESTID = "job-title-input-autocomplete-input"
    WORK_COMPANY_TESTID = "company-input-autocomplete-input"
    WORK_LOCATION_TESTID = "location-input-autocomplete-input"
    WORK_CURRENT_TOGGLE = '//*[@data-testid="is-current-toggle"]'
    WORK_FROM_MONTH = "//*[@aria-label='From month']"
    WORK_FROM_YEAR = "//*[@aria-label='From year']"
    WORK_TO_MONTH = "//*[@aria-label='To month']"
    WORK_TO_YEAR = "//*[@aria-label='To year']"

    EDU_LEVEL_TESTID = "level-of-education-input-autocomplete-input"
    EDU_FIELD_TESTID = "field-of-study-input-autocomplete-input"
    EDU_SCHOOL_TESTID = "school-input-autocomplete-input"
    EDU_LOCATION_TESTID = "education-location-input-autocomplete-input"

    SKILL_NAME_TESTID = "skill-name-input-autocomplete-input"
    SKILL_SAVE_XPATH = ("//*[@aria-label='Save this skill']"
                        " | //button[normalize-space(.)='Save']")
    # "Add skill" when the section has entries, "Add skills" when it is empty
    # (the empty state carries data-testid="skills-empty-state").
    ADD_SKILL_XPATH = ('//*[@aria-label="Add skill"]'
                       ' | //*[@aria-label="Add skills"]'
                       ' | //*[@data-testid="skills-empty-state"]')

    # Skills are NOT laid out like work experience and education. Each one is a
    # chip on the resume page, labelled "Edit <skill name>" -- the word "skill"
    # never appears in the label, so the work/edu-shaped selector this replaces
    # matched nothing at all. It happened to work once, on a resume whose skill
    # was literally named "Organizational skills".
    SKILL_ENTRY_XPATH = "//*[starts-with(@data-testid, 'edit-chip-')]"

    # Clicking any chip opens a modal listing every skill, each with its own
    # "Delete <skill name>" button. That modal is the only place skills can be
    # removed; there is no per-skill delete on the resume page itself.
    # "Delete resume" is excluded because it sits on the resume page and would
    # otherwise match, and clicking it would destroy the whole resume.
    SKILL_MODAL_DELETE_XPATH = ("//button[starts-with(@aria-label, 'Delete ')"
                                " and not(@aria-label = 'Delete resume')]")
    SKILL_MODAL_BACK_XPATH = '//*[@data-testid="modal-back-button"]'

    def fillByTestId(self, testid, value, label):
        """Fill one field of the resume forms, addressed by its test id.

        Waits for the field. These forms render a moment after the button that
        opens them is clicked, and this used to pass nohang=True -- which means
        "do not wait at all", ignoring timeLimit entirely. The fields were looked
        for before they existed, so job title, company and location were silently
        left empty and the form was saved half-filled.

        The value is read back afterwards for the same reason the dropdowns are:
        a field that quietly refuses input should say so, not pass silently.
        """
        if value is None or str(value).strip() == "":
            ct_print("fillByTestId", f"skipping {label}", "nothing configured for this user")
            return None

        xpath = f'//*[@data-testid="{testid}"]'
        element = self.findAndClick(self.WHOLE, self.WHOLE, xpath,
                                    txtCond="@#$ never matches %^&", timeLimit=8)
        if element is None:
            self.reportAction(f"Could not find the {label} field ({testid}) on this page.", False)
            return None

        self.fillMoveOn(element, str(value))

        try:
            written = element._handle.input_value()
        except (PlaywrightError, PlaywrightTimeoutError):
            return element          # not an <input>; nothing to read back
        if written.strip() != str(value).strip():
            self.reportAction(
                f"The {label} field did not take its value: expected {str(value)[:40]!r}, "
                f"it holds {written[:40]!r}.", False)
        return element

    DROPDOWN_ATTEMPTS = 3

    def _dropdownShows(self, trigger, value):
        try:
            return (trigger.text or "").strip().lower() == str(value).strip().lower()
        except PlaywrightError:
            return False

    def selectFromDropdown(self, triggerXpath, value, label=""):
        """Pick a value from one of the resume forms' custom dropdowns.

        These are not <select> elements. A button opens a listbox that is only
        added to the DOM once expanded, so the option can only be looked for
        after the click.

        The selection is read back afterwards and retried if it did not take.
        A silent miss here leaves a date field on its "Month" placeholder, which
        is how one work-experience entry ended up with no start month.
        """
        if not value:
            return None

        for attempt in range(1, self.DROPDOWN_ATTEMPTS + 1):
            trigger = self.findAndClick(self.WHOLE, self.WHOLE, triggerXpath,
                                        txtCond="@#$ never matches %^&", timeLimit=5)
            if trigger is None:
                self.reportAction(f"Could not find the {label or triggerXpath} dropdown.", False)
                return None

            if self._dropdownShows(trigger, value):
                return trigger          # already showing what we want

            self.smartClick(element=trigger, expectingPopUp=True)
            # No nohang here: the listbox is rendered in response to the click,
            # so returning immediately would look past it every time.
            option = self.findAndClick(
                self.WHOLE, self.WHOLE,
                f"//*[@role='option'][normalize-space(.)='{value}']",
                timeLimit=5, expectingPopUp=True)

            if option is None:
                try:
                    self._page.keyboard.press("Escape")   # don't leave it hanging open
                except PlaywrightError:
                    pass

            t.sleep(.3)
            check = self.findAndClick(self.WHOLE, self.WHOLE, triggerXpath,
                                      txtCond="@#$ never matches %^&", timeLimit=3, nohang=True)
            if check is not None and self._dropdownShows(check, value):
                return check

            ct_print("selectFromDropdown", f"{label or 'dropdown'} did not take {value!r}",
                     f"attempt {attempt} of {self.DROPDOWN_ATTEMPTS}"
                     f"; it shows {(check.text if check is not None else '?')!r}")

        self.reportAction(
            f"Could not set the {label or 'dropdown'} to {value!r} after "
            f"{self.DROPDOWN_ATTEMPTS} attempts. It has been left unset.", False)
        return None

    # Entries already on the resume. Each is an Edit button on the resume page
    # ("Edit Ad Set Associate work experience"); opening it reveals the form's
    # own Delete button.
    WORK_ENTRY_XPATH = ("//button[starts-with(@aria-label, 'Edit') and "
                        "contains(@aria-label, 'work experience')]")
    WORK_DELETE_XPATH = "//*[@aria-label='Delete this work experience']"
    EDU_ENTRY_XPATH = ("//button[starts-with(@aria-label, 'Edit') and "
                       "contains(@aria-label, 'education')]")
    EDU_DELETE_XPATH = "//*[@aria-label='Delete this education']"

    # An entry saved without its required fields is listed differently: its Edit
    # button carries no job title ("Edit work experience", not "Edit Software
    # Consultant work experience") and the card shows its own Delete button
    # right in the list -- labelled WITHOUT the word "this". Deleting those from
    # the list avoids opening a form that may refuse to close while invalid.
    # Kept separate from the form's selector because _formIsOpen() uses that one
    # to mean "a form is covering the list", which these would wrongly trigger.
    WORK_INLINE_DELETE_XPATH = "//*[@aria-label='Delete work experience']"
    EDU_INLINE_DELETE_XPATH = "//*[@aria-label='Delete education']"
    # The confirmation dialog's buttons have no test id and no aria-label -- only
    # the text "Delete", which the form behind it uses too. Scoping to the dialog
    # is what keeps the two apart.
    CONFIRM_DELETE_XPATH = (
        "//*[@role='dialog']//button[normalize-space(.)='Delete']"
        " | //*[@role='alertdialog']//button[normalize-space(.)='Delete']"
    )
    MAX_ENTRIES_TO_DELETE = 25

    def _formIsOpen(self, deleteXpath):
        """True while an entry form or a confirmation dialog is on screen."""
        try:
            if self._visible_only(self.driver.find_elements('xpath', deleteXpath)):
                return True
            return bool(self._visible_only(
                self.driver.find_elements('xpath', "//*[@role='dialog' or @role='alertdialog']")))
        except PlaywrightError:
            return False

    # How long an empty entry list has to stay empty before it is believed.
    ENTRY_LIST_SETTLE = 4
    # Re-reads allowed when a handle keeps going stale under a re-render.
    MAX_STALE_RETRIES = 6
    # Breathing room after a deletion, so the section finishes swapping its
    # nodes before the next handle is taken from it.
    RERENDER_SETTLE = 0.6

    def _liveEntries(self, entryXpath):
        """The entries currently listed, as clickable elements.

        Empty while a form or dialog covers the list, so callers must check
        _formIsOpen() before reading anything into an empty result.
        """
        try:
            return self._visible_only(self.driver.find_elements('xpath', entryXpath))
        except PlaywrightError:
            return []

    def _settledEntries(self, entryXpath):
        """The listed entries, not believing the first empty read.

        Confirming a deletion navigates back to the resume page, and for a
        moment afterwards the section has not re-rendered: the list reads as
        zero entries whether or not any are left. Taking that at face value is
        what stopped the clearing after a single deletion --

            deleteExistingEntries | removed existing work experience
                                  | Edit AI Consultant work experience (5 -> 0)
            Removed 1 pre-existing work experience entry before adding this user's.

        -- 471ms after the confirm click, on a resume that still had four jobs
        on it. Those four then got the new entries added on top of them.

        A non-empty list is returned straight away, so this costs nothing in the
        normal case; only "it looks empty" is worth waiting to confirm.
        """
        entries = self._liveEntries(entryXpath)
        if entries:
            return entries

        deadline = t.time() + self.ENTRY_LIST_SETTLE
        while t.time() < deadline:
            t.sleep(self.DELTA_WAIT)
            entries = self._liveEntries(entryXpath)
            if entries:
                return entries
        return []

    def _confirmDelete(self):
        """Click through "Are you sure you want to delete this...?".

        The dialog's buttons carry no test id and no aria-label, only the text
        "Delete" -- which the form underneath uses too. Scoping to the dialog is
        what keeps the two apart. This waits for the dialog rather than probing
        for it: it is raised a moment after the Delete click, so a no-wait
        lookup reliably missed it.
        """
        return self.findAndClick(self.WHOLE, self.WHOLE, self.CONFIRM_DELETE_XPATH,
                                 timeLimit=5, expectingPopUp=True)

    # Ways out of an entry form that will not close on its own.
    FORM_DISMISS_XPATH = (
        "//*[@aria-label='Close']"
        " | //*[@aria-label='Back']"
        " | //button[normalize-space(.)='Cancel']"
    )

    def _leaveEntryForm(self, deleteXpath, returnUrl=None):
        """Get back to the entry list after a deletion that did not go through.

        Without this a failed attempt strands the run inside the form: the list
        is hidden, so the next pass sees zero entries and concludes the section
        is already clear.

        Deliberately NOT go_back(). Opening an entry does not always navigate,
        so going back can leave the resume page altogether -- off to the review
        page or the job posting -- and derail the rest of the application.
        Returning to a URL we recorded ourselves can only land where we started.
        """
        for attempt in range(3):
            if not self._formIsOpen(deleteXpath):
                return True
            try:
                self._page.keyboard.press("Escape")
            except PlaywrightError:
                pass
            if self._wait_until(lambda: not self._formIsOpen(deleteXpath), 3):
                return True

            if attempt == 0:
                self.findAndClick(self.WHOLE, self.WHOLE, self.FORM_DISMISS_XPATH,
                                  timeLimit=3, nohang=True)
            elif returnUrl and self._page.url != returnUrl:
                try:
                    self._page.goto(returnUrl)
                except PlaywrightError:
                    pass
        return not self._formIsOpen(deleteXpath)

    def _deleteOneEntry(self, entry, deleteXpath, inlineDeleteXpath):
        """Remove a single listed entry. True if the page accepted the deletion."""
        # Incomplete entries carry their own Delete button in the list. Use it
        # rather than opening a form that may refuse to close while invalid.
        # Which card it belongs to does not matter here -- the whole section is
        # being cleared, so any of them is a valid thing to remove.
        # Where the list lives, so a form that will not close can be escaped by
        # coming back here rather than by guessing with go_back().
        listUrl = self._page.url

        if inlineDeleteXpath:
            inline = self._visible_only(self.driver.find_elements('xpath', inlineDeleteXpath))
            if inline:
                self.smartClick(element=inline[0], expectingPopUp=True)
                self._confirmDelete()
                if self._wait_until(lambda: not self._formIsOpen(deleteXpath), 8):
                    t.sleep(self.RERENDER_SETTLE)   # as below: let the swap finish
                    return True
                self._leaveEntryForm(deleteXpath, listUrl)
                return False

        self.smartClick(element=entry, checkNewPage=True)

        # expectingPopUp: deleting raises a confirmation dialog, and without
        # this smartClick would run closeDialogBox against it first.
        deleteButton = self.findAndClick(self.WHOLE, self.WHOLE, deleteXpath,
                                         timeLimit=8, expectingPopUp=True)
        if deleteButton is None:
            self._leaveEntryForm(deleteXpath, listUrl)
            return False

        self._confirmDelete()
        # Wait for the form and dialog to close before judging the result. While
        # either is open the entry list is hidden, so counting entries straight
        # away would read "none left" and mistake a failure for a success.
        if self._wait_until(lambda: not self._formIsOpen(deleteXpath), 8):
            # The form closing is not the end of it: the section re-renders
            # afterwards, and a handle taken during that swap is born detached.
            t.sleep(self.RERENDER_SETTLE)
            return True
        self._leaveEntryForm(deleteXpath, listUrl)
        return False

    def _entryTexts(self, entryXpath):
        """What each listed entry currently reads, normalised for comparison.

        The entry button wraps the whole card, so its text carries the title,
        employer, dates and description together.
        """
        texts = []
        for element in self._settledEntries(entryXpath):
            try:
                texts.append(" ".join((element._handle.inner_text() or "").split()).lower())
            except (PlaywrightError, PlaywrightTimeoutError):
                texts.append("")
        return texts

    def sectionAlreadyCorrect(self, entryXpath, expected, label):
        """True when the section already holds exactly what we would write.

        Rewriting a section costs a delete and a re-add for every entry, and
        when something upstream loops it does that over and over -- one run
        rebuilt the same four jobs five times and left twenty "X removed"
        banners behind.

        Deliberately strict: the counts must match and EVERY part of every
        entry must be present, matched one-for-one. So a description tailored
        differently for this posting still counts as "not correct" and gets
        rewritten -- this only skips work that is genuinely already done.
        """
        if not expected:
            return False

        remaining = self._entryTexts(entryXpath)
        if len(remaining) != len(expected):
            return False

        for parts in expected:
            wanted = [str(p).strip().lower() for p in parts if str(p).strip()]
            if not wanted:
                return False
            hit = next((t for t in remaining if all(w in t for w in wanted)), None)
            if hit is None:
                return False
            remaining.remove(hit)   # one-for-one, so duplicates cannot both match one entry

        ct_print("sectionAlreadyCorrect", f"{label} already matches",
                 f"{len(expected)} entr{'y' if len(expected) == 1 else 'ies'}")
        self.reportAction(
            f"The {label} section already holds exactly this user's entries, so it was left "
            f"alone rather than deleted and retyped.", False)
        return True

    @staticmethod
    def _jobSignature(job):
        # Same positional unpacking handleJob uses, so the two cannot drift.
        title, comp, _kind, cityState, _current, fromDate, _toDate, _country, desc = \
            tuple(job.values())
        # handleJob strips the leading "- " before typing, so compare likewise.
        firstLine = next((l.strip() for l in str(desc or "").splitlines() if l.strip()), "")
        return [title, comp, cityState, fromDate, firstLine.replace("- ", "")[:60]]

    @staticmethod
    def _eduSignature(edu):
        eduLvl, fieldOS, schoolName, cityState, _current, fromDate, _toDate, _country = \
            tuple(edu.values())
        return [eduLvl, fieldOS, schoolName, cityState, fromDate]

    def deleteExistingEntries(self, entryXpath, deleteXpath, label, inlineDeleteXpath=None,
                              stopIfNotCleared=True):
        """Clear a resume section completely before writing this user's entries.

        Anything left behind is submitted alongside ours, so this has to empty
        the section or say plainly that it could not. A previous version gave up
        on the first hiccup and the adding ran anyway, which is how one resume
        ended up with three "Software Consultant" entries and two of everything
        else.

        Two things it must not do:

        * judge progress by the deleted entry's NAME disappearing. Duplicates
          are exactly what this is here to clean up, and with two entries
          sharing one aria-label the name is still listed after the first is
          gone -- read as a failed delete, so it stopped with the duplicate
          still there. It counts instead.
        * stop at the first entry it cannot remove. It now skips past a stubborn
          one and comes back to the rest, giving up only when a whole pass
          removes nothing.
        """
        removed = 0
        skipped = 0            # entries already tried and failed; not retried forever
        stale = 0              # handles that went stale under a re-render
        while removed < self.MAX_ENTRIES_TO_DELETE:
            entries = self._settledEntries(entryXpath)
            if len(entries) <= skipped:
                break

            target = entries[skipped]
            name = self._labelOf(target)
            before = len(entries)

            # Deleting re-renders the whole section, and the list can read back
            # non-empty a moment before React swaps the nodes out. A handle
            # taken then is detached by the time it is used -- which is not a
            # failed deletion, it is a handle that needs taking again.
            if not self._isAttached(target):
                stale += 1
                if stale <= self.MAX_STALE_RETRIES:
                    ct_wait("deleteExistingEntries", "the list to finish re-rendering",
                            f"stale={stale}")
                    t.sleep(self.DELTA_WAIT)
                    continue
                self.reportAction(
                    f"The {label} list keeps changing under the bot faster than it can act "
                    f"on it, so it stopped rather than thrashing.", False)
                break

            if self._deleteOneEntry(target, deleteXpath, inlineDeleteXpath):
                after = len(self._settledEntries(entryXpath))
                if after < before:
                    removed += 1
                    ct_print("deleteExistingEntries", f"removed existing {label}",
                             f"{name[:60]} ({before} -> {after})")
                    continue

            skipped += 1
            self.reportAction(
                f"Could not remove {name!r} from {label}; moving on to the next entry.", False)

        if removed:
            self.reportAction(f"Removed {removed} pre-existing {label} entr"
                              f"{'y' if removed == 1 else 'ies'} before adding this user's.", False)

        leftover = [self._labelOf(e) for e in self._settledEntries(entryXpath)]
        if leftover and not stopIfNotCleared:
            # For a section where a leftover is an extra keyword rather than
            # employment history the applicant never had, say so and carry on.
            self.reportAction(
                f"{len(leftover)} existing {label} entr"
                f"{'y' if len(leftover) == 1 else 'ies'} could not be removed and will stay "
                f"on the resume: {', '.join(name[:50] for name in leftover[:6])}.", False)
        elif leftover:
            # Adding on top of leftovers is what produced the duplicated resume.
            # Stop and ask for a person instead of making it worse.
            raise NeedsHumanError(
                f"Could not clear the existing {label} section -- {len(leftover)} entr"
                f"{'y' if len(leftover) == 1 else 'ies'} would not delete: "
                f"{', '.join(name[:50] for name in leftover[:6])}. "
                f"Nothing new has been added, so the resume is not duplicated. Delete "
                f"{'it' if len(leftover) == 1 else 'them'} by hand, then press Start applying.")
        return removed

    def setToggle(self, xpath, shouldBeOn, label=""):
        """Set a role=checkbox control, which reports state via aria-checked
        rather than the usual checked property.

        Returns the toggle's ACTUAL resulting state (a bool), not just
        whatever was asked for, and not the element the old version
        returned. The click can be silently intercepted and give up
        (ElementClickInterceptedException, previously never even looked at
        here) without changing anything -- a caller that then assumes
        shouldBeOn took effect anyway skips work it should not.
        setDateRange's isCurrent flag did exactly that: "I currently work
        here" failed to tick, the "To" date got skipped believing the job
        was current, Indeed still required it and refused to save, and the
        leftover open, unsaved form hid "Add work experience" from every
        later job for the rest of the run (Logs/Log30.txt).
        """
        toggle = self.findAndClick(self.WHOLE, self.WHOLE, xpath,
                                   txtCond="@#$ never matches %^&", timeLimit=8)
        if toggle is None:
            self.reportAction(f"Could not find the {label or xpath} toggle.", False)
            return None
        isOn = (toggle.get_attribute("aria-checked") or "").strip().lower() == "true"
        if isOn == bool(shouldBeOn):
            return isOn

        self.smartClick(element=toggle)

        # Re-queried rather than trusting the same handle: a controlled
        # checkbox like this can re-render on click, and the click can also
        # simply have failed -- either way, only the page itself can say
        # what actually ended up set.
        recheck = self.findAndClick(self.WHOLE, self.WHOLE, xpath,
                                    txtCond="@#$ never matches %^&", timeLimit=2)
        if recheck is not None:
            isOn = (recheck.get_attribute("aria-checked") or "").strip().lower() == "true"
        if isOn != bool(shouldBeOn):
            self.reportAction(
                f"Could not set the {label or xpath} toggle to "
                f"{'on' if shouldBeOn else 'off'}; it is still "
                f"{'on' if isOn else 'off'}.", False)
        return isOn

    @staticmethod
    def _dateParts(value):
        """Split a stored date into (month, year).

        Normally "February 2008". Some rows hold a bare year -- user 9's
        Software Consultant is From "2019", To "2025" -- and the old split
        returned (None, None) for those, so BOTH dropdowns were skipped and
        nothing was reported. That is what put "Missing dates." on the resume:
        the log shows that entry going straight from the current-job toggle to
        the description with no date lookups at all.

        A bare year now fills the year at least, and the caller says out loud
        that the month is missing.
        """
        bits = str(value or "").strip().split()
        if len(bits) >= 2:
            return bits[0], bits[1]
        if len(bits) == 1 and bits[0].isdigit() and len(bits[0]) == 4:
            return None, bits[0]
        return None, None

    def setDateRange(self, fromDate, toDate, isCurrent, prefix=""):
        """Fill a "From"/"To" month+year pair. The To pair is absent when the
        entry is marked as current, so it is only touched when relevant.
        """
        def fill(which, raw, monthXpath, yearXpath):
            month, year = self._dateParts(raw)
            if not month or not year:
                # Indeed requires both, and saves the entry flagged "Missing
                # dates." without them. Say so rather than leaving it to be
                # discovered on the finished resume.
                self.reportAction(
                    f"{prefix}{which} date is {str(raw).strip()!r}, which has no "
                    f"{'month' if year else 'usable month and year'}. Indeed needs both, so "
                    f"this entry will be flagged 'Missing dates'. Fix it in the Work History "
                    f"tab of the GUI.", False)
            self.selectFromDropdown(monthXpath, month, f"{prefix}{which} month")
            self.selectFromDropdown(yearXpath, year, f"{prefix}{which} year")

        fill("from", fromDate, "//*[@aria-label='From month']", "//*[@aria-label='From year']")
        if not isCurrent:
            fill("to", toDate, "//*[@aria-label='To month']", "//*[@aria-label='To year']")

    def edit_contact_info(self):
        for testid, attribute, label in self.CONTACT_FIELDS:
            self.fillByTestId(testid, getattr(self, attribute, None), label)

        result = self.findAndClick(self.WHOLE, self.WHOLE, self.CONTACT_SAVE_XPATH,
                                   checkNewPage=True, timeLimit=5)
        if result is None:
            result = self.findAndClick(self.ARIA_LABEL, self.MATCH, 'Back', checkNewPage=True, timeLimit=5)
        return result

    def do_summary(self):
        txtBoxPath = "//div[@role='textbox']"
        self.findFillMoveOn(self.WHOLE, self.WHOLE, txtBoxPath, self.resumeSummary) # need GPT
        return self.findAndClick(self.TXT, self.MATCH, 'Save', travelUp=1, waitBeforeClicking=.5, checkNewPage=True)

    def do_education(self):
        # delete all prior
        deletes = self.findClosestRelatives(self.TXT, self.MATCH,  'Education', self.ID, self.CONTAINS, 'delete', srchLvlLmt=2)
        self.click_all(deletes)

        addEduBut = self.findClosestRelatives( self.TXT, self.MATCH, 'Education', self.WHOLE, self.WHOLE, self.BUTTON)[0]
        self.smartClick(element=addEduBut, waitBeforeClicking=.7)

        return self.fillEducationInfo()

    EDU_SAVE_XPATH = ("//*[@aria-label='Save this education']"
                      " | //button[normalize-space(.)='Save']")
    EDU_CURRENT_TOGGLE = '//*[@data-testid="is-current-toggle"]'

    def _formStillOpen(self, markerTestId):
        """True while a field unique to an open add/edit form is still on
        screen. Used right after clicking a form's Save button: smartClick's
        own checkNewPage wait already looks for exactly this, but discards
        the answer and returns as if the click succeeded regardless. Trusting
        that silently means a save Indeed actually blocked on a validation
        error (empty required field, most often) looks identical to a real
        success -- the form is left open, unsaved, and the NEXT entry's own
        "Add" button stays hidden behind it for the rest of the run
        (Logs/Log30.txt).
        """
        return bool(self._visible_only(self.driver.find_elements(
            By.CSS_SELECTOR, f'[data-testid="{markerTestId}"]')))

    def handleEdu(self, edu : dict):
        eduLvl, fieldOS, schoolName, cityState, current, fromDate, toDate, country = tuple(edu.values())
        current = "y" in current.lower()

        self.fillByTestId(self.EDU_LEVEL_TESTID, eduLvl, "education level")
        self.fillByTestId(self.EDU_FIELD_TESTID, fieldOS, "field of study")
        self.fillByTestId(self.EDU_SCHOOL_TESTID, schoolName, "school")
        self.fillByTestId(self.EDU_LOCATION_TESTID, cityState, "school location")

        # The toggle's ACTUAL resulting state, not the value asked for --
        # see setToggle's docstring for why trusting the request blindly is
        # exactly what let this get stuck.
        actualCurrent = self.setToggle(self.EDU_CURRENT_TOGGLE, current, "currently enrolled")
        if actualCurrent is None:
            actualCurrent = current
        self.setDateRange(fromDate, toDate, actualCurrent, prefix="education ")

        saveResult = self.findAndClick(self.WHOLE, self.WHOLE, self.EDU_SAVE_XPATH,
                                       waitBeforeClicking=1, checkNewPage=True)
        if isinstance(saveResult, ElementClickInterceptedException):
            return saveResult
        if self._formStillOpen(self.EDU_SCHOOL_TESTID):
            raise NeedsHumanError(
                "Clicked 'Save this education' but the form is still open -- Indeed is "
                "likely blocking the save on a validation error (often a missing date). "
                "Fix it in the browser, then press Start applying.")
        return saveResult

    @staticmethod
    def _cleanSkill(skill):
        """Trim the leading "and" GPT leaves on the last item of a list.

        The old version compared skill[:3] to "and" and then cut FOUR
        characters, so "Android" became "oid". Requiring the trailing space
        makes it a word rather than a prefix.
        """
        text = str(skill or "").strip()
        for prefix in ("and ", "And ", "AND "):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        return text

    # Indeed's "tailored resume" step (HTMLz/review_taylorded_resume.html).
    # Note these use data-tn-element, NOT data-testid, so the ordinary Continue
    # selector misses them entirely.
    TAILORED_CONTINUE_XPATH = "//*[@data-tn-element='continue-btn']"
    TAILORED_DIALOG_XPATH = ("//*[@data-tn-component="
                             "'tailored-resume-ai-confirmation-dialog']")
    TAILORED_CONFIRM_BOX_XPATH = "//*[@data-tn-element='confirm-changes']"

    def confirmTailoredResume(self):
        """Get past the AI-tailored resume review.

        Click Continue, and Indeed raises a dialog insisting the AI's edits have
        been checked. Its own Continue starts DISABLED and only enables once the
        confirmation box is ticked, so the box has to be ticked first.

        Both the page's button and the dialog's button carry
        data-tn-element="continue-btn", so the second click is scoped to inside
        the dialog. Clicking whichever came first in document order would just
        press the page button again.
        """
        self.waitOutLoading()

        # expectingPopUp=True: this click's entire job is to OPEN the
        # confirmation dialog. Without it, smartClick's post-click
        # closeDialogBox() ran unconditionally, saw the dialog it had just
        # opened (role="dialog" aria-modal="true", with a button
        # aria-label="Close dialog" -- HTMLz/post_continue_pop_up2.html),
        # and clicked that close button immediately -- the dialog opening
        # and closing itself was this same click, not two separate events.
        # That is what made the popup look like it "closes immediately":
        # the 8s wait below for the checkbox then always timed out, this
        # returned as if there were simply no dialog, and the state machine
        # called confirmTailoredResume() again next pass -- forever
        # (Logs/Log28.txt).
        opened = self.findAndClick(self.WHOLE, self.WHOLE, self.TAILORED_CONTINUE_XPATH,
                                   waitBeforeClicking=.4, timeLimit=8, expectingPopUp=True)
        if opened is None:
            self.reportAction(
                "Could not find the Continue button on the tailored resume page.", False)
            return None

        # No dialog is not a failure: Indeed only asks when it actually changed
        # something with AI. Checked via the CHECKBOX, not the dialog wrapper --
        # Logs/Log25.txt shows confirmTailoredResume being called correctly and
        # looping for many minutes, giving up with "no confirmation dialog"
        # every single time on an 8-second cadence, even though the dialog
        # demonstrably opened each time (the popup-closes-immediately symptom
        # was this loop re-clicking the page's own Continue button on every
        # retry). The wrapper carries data-tn-component, but the real DOM has
        # it nested inside a separate `role="dialog"` element (seen in an
        # earlier capture, question_unanswered1.html) that this was never
        # checking -- whatever about that outer element made the wrapper
        # register as not-visible does not apply to the checkbox itself, a
        # plain <input> with no wrapper of its own, and the checkbox is the
        # thing that actually needs to be interacted with anyway.
        if not self._wait_until(
                lambda: bool(self._visible_only(self.driver.find_elements(
                    'xpath', self.TAILORED_CONFIRM_BOX_XPATH))), 8):
            ct_print("confirmTailoredResume", "no confirmation dialog", "carrying on")
            return opened

        box = self.findAndClick(self.WHOLE, self.WHOLE, self.TAILORED_CONFIRM_BOX_XPATH,
                                txtCond="@#$ never matches %^&", timeLimit=5)
        if box is not None and not box.is_selected():
            # Same closeDialogBox() trap as the click above: this click stays
            # inside the still-open dialog, so it must not let the post-click
            # cleanup close it out from under the checkbox -- which is what
            # produced the "Element is not attached to the DOM" errors on
            # box.is_selected() right after this used to run without it.
            self.smartClick(element=box, expectingPopUp=True)
            self._wait_until(box.is_selected, 3)
        if box is None or not box.is_selected():
            raise NeedsHumanError(
                "The tailored resume dialog wants its 'I have reviewed all changes' box "
                "ticked before it will continue, and the box would not tick. Tick it and "
                "press Continue yourself, then press Start applying.")

        # Scoped to the dialog: the page's own Continue is still on screen.
        confirmed = self.findAndClick(
            self.WHOLE, self.WHOLE,
            f"{self.TAILORED_DIALOG_XPATH}//*[@data-tn-element='continue-btn']",
            waitBeforeClicking=.3, checkNewPage=True, timeLimit=8)
        if confirmed is None:
            self.reportAction(
                "Ticked the confirmation box but could not click the dialog's Continue.", False)
        return confirmed

    def rememberApplicationUrl(self):
        """Note the address to return to, from the editor's own URL.

        The resume editor is opened as

            /resume?co=US&hl=en_US&continue=<url-encoded application address>

        and Indeed drops that query string as soon as anything inside the editor
        navigates. Capturing it the first time it is seen means the way back is
        known for the rest of the resume, instead of being guessed at with a
        back arrow that leads somewhere else entirely.
        """
        try:
            url = self._page.url
        except (PlaywrightError, PlaywrightTimeoutError):
            return
        if "continue=" not in url:
            return
        try:
            target = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("continue", [])
        except ValueError:
            return
        if target and target[0].startswith("http") and target[0] != self.applicationReturnUrl:
            self.applicationReturnUrl = target[0]
            ct_print("rememberApplicationUrl", "noted the way back",
                     self.applicationReturnUrl[:90])

    PROFILE_HOME_MARKERS = ("profile - resume - indeed", "profile - indeed")

    def onProfileHome(self):
        """True on the Indeed profile page, which is outside the application."""
        try:
            url = self._page.url
            title = (self._page.title() or "").lower()
        except (PlaywrightError, PlaywrightTimeoutError):
            return False
        path = urllib.parse.urlparse(url).path.rstrip("/")
        return path in ("", "/") and "profile.indeed.com" in url \
            or any(marker in title for marker in self.PROFILE_HOME_MARKERS) \
            and "/resume" not in path

    def getCurrentEnv(self, quiet=False):
        # Every loop of the state machine passes through here, which makes it
        # the one place guaranteed to see the editor's URL while it still
        # carries the application address.
        env = super().getCurrentEnv(quiet=quiet)
        self.rememberApplicationUrl()
        return env

    def clearSkills(self):
        """Remove every skill already on the resume.

        Skills do not delete the way work experience and education do. There is
        no delete control on the resume page at all. The route is:

            click any skill chip          -> opens a modal listing every skill
            click "Delete <name>" on each -> the row becomes "<name> removed / Undo"
            click the modal's back arrow  -> back to the resume, skills empty

        Deleting a row replaces it in place, so its Delete button disappears and
        the list has to be re-read each pass rather than iterated once. The Undo
        buttons that appear alongside are deliberately not matched.
        """
        chips = self._visible_only(self.driver.find_elements('xpath', self.SKILL_ENTRY_XPATH))
        if not chips:
            return 0

        # Any chip opens the same modal.
        self.smartClick(element=chips[0], checkNewPage=True)
        if not self._wait_until(
                lambda: bool(self._visible_only(self.driver.find_elements(
                    'xpath', self.SKILL_MODAL_DELETE_XPATH))), 8):
            self.reportAction(
                "Opened a skill but the list of skills to delete never appeared, so the "
                "existing skills were left in place.", False)
            self.findAndClick(self.WHOLE, self.WHOLE, self.SKILL_MODAL_BACK_XPATH,
                              timeLimit=4, nohang=True)
            return 0

        removed = 0
        while removed < self.MAX_ENTRIES_TO_DELETE:
            buttons = self._visible_only(
                self.driver.find_elements('xpath', self.SKILL_MODAL_DELETE_XPATH))
            if not buttons:
                break
            before = len(buttons)
            name = (self._labelOf(buttons[0]) or "").replace("Delete ", "")

            self.smartClick(element=buttons[0])
            shrank = self._wait_until(
                lambda: len(self._visible_only(self.driver.find_elements(
                    'xpath', self.SKILL_MODAL_DELETE_XPATH))) < before, 5)
            if not shrank:
                self.reportAction(
                    f"Clicked delete on the skill {name!r} and the list did not change, so "
                    f"the rest were left alone.", False)
                break
            removed += 1
            ct_print("clearSkills", "removed skill", f"{name[:50]} ({before} -> {before - 1})")

        back = self.findAndClick(self.WHOLE, self.WHOLE, self.SKILL_MODAL_BACK_XPATH,
                                 checkNewPage=True, timeLimit=6)
        if back is None:
            self.reportAction(
                "Removed the existing skills but could not find the modal's back arrow.", False)

        if removed:
            self.reportAction(f"Removed {removed} existing skill"
                              f"{'' if removed == 1 else 's'} before adding this user's.", False)
        return removed

    def do_skills(self):
        """Replace the skills on the resume with this user's.

        The version this replaces looked for id="skillName" and for a delete
        control with "delete" in its id. Neither exists any more -- both match
        zero elements on HTMLz/Add_Skill_stuck.html -- so every skill failed:

            Could not find the field skillName to fill.   (x4)

        It also picked its Add button with findClosestRelatives(...)[0], the
        same "nearest thing to some text" guess that clicked a footer link on
        the documents page.
        """
        wanted = [self._cleanSkill(s) for s in self.skills]
        wanted = [s for s in wanted if s]
        if self.sectionAlreadyCorrect(self.SKILL_ENTRY_XPATH, [[s] for s in wanted], "skills"):
            return None

        self.clearSkills()

        for skill in wanted:
            addSkillBut = self.findAndClick(self.WHOLE, self.WHOLE, self.ADD_SKILL_XPATH,
                                            waitBeforeClicking=.5, checkNewPage=True,
                                            timeLimit=8)
            if addSkillBut is None:
                self.reportAction("Could not find the 'Add skill' button.", False)
                return None

            if self.fillByTestId(self.SKILL_NAME_TESTID, skill, "skill name") is None:
                # The form is open with nothing in it; back out rather than
                # saving a blank skill or stacking another form on top.
                self.findAndClick(self.WHOLE, self.WHOLE, self.SKILL_MODAL_BACK_XPATH,
                                  timeLimit=4, nohang=True)
                continue

            self.findAndClick(self.WHOLE, self.WHOLE, self.SKILL_SAVE_XPATH,
                              waitBeforeClicking=.5, checkNewPage=True, timeLimit=8)

    ADD_WORK_XPATH = "//*[@aria-label='Add work experience']"
    ADD_EDU_XPATH = "//*[@aria-label='Add education']"

    def do_work_exp(self):
        if self.sectionAlreadyCorrect(self.WORK_ENTRY_XPATH,
                                      [self._jobSignature(j) for j in self.jobs],
                                      "work experience"):
            return None

        # Clear whatever is already on the profile first. The old lookup hunted
        # for elements with "delete" in their id near the heading; there are no
        # such elements any more, so nothing was ever removed and stale jobs the
        # applicant never listed were submitted alongside ours.
        self.deleteExistingEntries(self.WORK_ENTRY_XPATH, self.WORK_DELETE_XPATH,
                                   "work experience",
                                   inlineDeleteXpath=self.WORK_INLINE_DELETE_XPATH)

        for job in self.jobs:
            addWorkBut = self.findAndClick(self.WHOLE, self.WHOLE, self.ADD_WORK_XPATH,
                                           waitBeforeClicking=.5, checkNewPage=True, timeLimit=8)
            if addWorkBut is None:
                self.reportAction("Could not find the 'Add work experience' button.", False)
                return None
            possExp = self.handleJob(job)
            if isinstance(possExp, ElementClickInterceptedException):
                return possExp

    def do_edu(self):
        if self.sectionAlreadyCorrect(self.EDU_ENTRY_XPATH,
                                      [self._eduSignature(e) for e in self.edus],
                                      "education"):
            return None

        self.deleteExistingEntries(self.EDU_ENTRY_XPATH, self.EDU_DELETE_XPATH, "education",
                                   inlineDeleteXpath=self.EDU_INLINE_DELETE_XPATH)

        for edu in self.edus:
            addEduBut = self.findAndClick(self.WHOLE, self.WHOLE, self.ADD_EDU_XPATH,
                                          waitBeforeClicking=.5, checkNewPage=True, timeLimit=8)
            if addEduBut is None:
                self.reportAction("Could not find the 'Add education' button.", False)
                return None
            possExp = self.handleEdu(edu)
            if isinstance(possExp, ElementClickInterceptedException):
                return possExp


    # How many times a whole generation (not just one chat message) gets
    # redone when myGPT2 reports need_redo -- doCheckNots/doChecks already
    # retry the CHAT a few times per call; this bounds retrying the whole
    # call on top of that, which used to be `while doAgain:` with no limit
    # at all. A model that reliably violates one formatting rule (gpt-5-nano
    # skipping a required preamble far more than gpt-5-mini did) hung every
    # one of these for hours (Logs/Log20.txt).
    GENERATION_REDO_LIMIT = 3

    def process_job_file(self, filename):
        jobFile = open(filename, "r")
        infoDict = {}
        for subject in ['title', 'comp', 'compType', 'cityState', 'current', 'fromDate', 'toDate']:
            _, infoDict[subject] = self.nextNonBlankLine(jobFile), self.nextNonBlankLine(jobFile).strip()


        #read the rest of the lines, that'll be the description
        _, rawDesc = self.nextNonBlankLine(jobFile), jobFile.read().strip()
        '''mygpt = myGPT("job_desc_prompts.txt", infoDict['title'], infoDict['comp'],
                      rawDesc, self.JobDescriptionText, infoDict['title'])
        infoDict['desc'] = mygpt.sendAll()'''

        mygpt = myGPT2("job_desc_prompts2.txt", self.jobTitle, self.JobDescriptionText, infoDict['title'],
                      infoDict['compType'],  rawDesc, infoDict['title'], infoDict['compType'],
                      self.styleGuide())

        doAgain = True
        attempts = 0
        while doAgain and attempts < self.GENERATION_REDO_LIMIT:
            attempts += 1
            # [-1], not [1]: a reply without the expected preamble was an
            # IndexError that took the whole run down with it.
            jobDesc = self.stripDashes(
                mygpt.sendAll().split("Here are the 3 points:")[-1].strip())
            doAgain = mygpt.need_redo
        infoDict['desc'] = jobDesc

        return infoDict

    def process_job_record(self, record):
        infoDict = {}
        for subject in [('title', "JobTitle"), ('comp',"CompanyName"), ('compType',"CompanyType"), ('cityState',"areaSpec"),
                        ('current',"currentPosition"), ('fromDate',"From"), ('toDate',"To"), ("country","country")]:
            infoDict[subject[0]] = record[subject[1]]


        #read the rest of the lines, that'll be the description
        rawDesc = record["Description"]
        '''mygpt = myGPT("job_desc_prompts.txt", infoDict['title'], infoDict['comp'],
                      rawDesc, self.JobDescriptionText, infoDict['title'])
        infoDict['desc'] = mygpt.sendAll()'''

        mygpt = myGPT2("job_desc_prompts2.txt", self.jobTitle, self.JobDescriptionText, infoDict['title'],
                      infoDict['compType'],  rawDesc, infoDict['title'], infoDict['compType'],
                      self.styleGuide())

        doAgain = True
        attempts = 0
        while doAgain and attempts < self.GENERATION_REDO_LIMIT:
            attempts += 1
            # [-1], not [1]: a reply without the expected preamble was an
            # IndexError that took the whole run down with it.
            jobDesc = self.stripDashes(
                mygpt.sendAll().split("Here are the 3 points:")[-1].strip())
            doAgain = mygpt.need_redo
        infoDict['desc'] = jobDesc

        return infoDict

    def process_edu_file(self, filename):
        eduFile = open(filename, "r")
        infoDict = {}
        for subject in ['educationLevel', 'fieldOfStudy', 'school', 'cityState', 'current', 'frmDate', 'toDate']:
            _, infoDict[subject] = self.nextNonBlankLine(eduFile), self.nextNonBlankLine(eduFile).strip()

        return infoDict

    def process_edu_record(self, record):
        infoDict = {}
        for subject in [('educationLevel',"level"), ('fieldOfStudy',"fieldOfStudy"), ('school',"SchoolName"), ('cityState',"areaSpec"),
                        ('current',"currentlyEnrolled"), ('frmDate',"From"), ('toDate',"To"), ("country", "country")]:
            infoDict[subject[0]] = record[subject[1]]

        return infoDict

    def load_jobs(self):
        self.jobs.clear()

        for jobRec in self.jobRecords:
            if self.cur_profile["jobN"] is None or jobRec["jobNum"] in self.cur_profile["jobN"]:
                self.jobs.append(self.process_job_record(jobRec))

        '''files_in_subdir = os.listdir(self.MY_PATH + self.dataPath)

        if self.cur_profile["jobN"] is None:  # then doing all job files
            jobFiles = [self.MY_PATH + self.dataPath  + f for f in files_in_subdir if re.match(r'Job\d+\.txt$', f)]
        else:
            jobFiles = [self.MY_PATH + self.dataPath + f"Job{n}.txt" for n in self.cur_profile["jobN"] ]

        for jobFile in jobFiles:
            self.jobs.append(self.process_job_file(jobFile))'''

    def load_edu(self):
        self.edus.clear()
        for eduRec in self.eduRecords:
            if self.cur_profile["eduN"] is None or eduRec["eduNum"] in self.cur_profile["eduN"]:
                self.edus.append(self.process_edu_record(eduRec))
        '''files_in_subdir = os.listdir(self.MY_PATH + self.dataPath)

        if self.cur_profile["eduN"] is None:
            eduFiles = [self.MY_PATH + self.dataPath  + f for f in files_in_subdir if re.match(r'Edu\d+\.txt$', f)]
        else:
            eduFiles = [self.MY_PATH + self.dataPath + f"Edu{n}.txt" for n in self.cur_profile["eduN"]]

        for eduFile in eduFiles:
            self.edus.append(self.process_edu_file(eduFile))'''

    def deleteAllPrevJobs(self):
        t.sleep(1)
        delButs = self.driver.find_elements("xpath", "//*[contains(@id, 'delete')]")
        for delB in delButs:
            self.smartClick(element=delB)

            if delB == delButs[-1]:
                # only want to do this after deleting the last job.  If we didn't have to delete anyting, then don't need
                # to click on this "Add another" button
                self.addAnother()

    def fillPrevJobsInfo(self):
        # Adding a job
        for job in self.jobs:
            self.handleJob(job)

            self.finalizeResumeSection()

            # check if there are still more job files to process
            if job != self.jobs[-1]:
                self.addAnother()

    WORK_SAVE_XPATH = ("//*[@aria-label='Save this work experience']"
                       " | //button[normalize-space(.)='Save']")
    DESCRIPTION_XPATH = "//*[@aria-label='Description'] | //div[@role='textbox']"
    BULLET_LIST_XPATH = ("//*[@aria-label='Bulleted list']"
                         " | //button[@data-testid='insertUnorderedList']")

    def handleJob(self, job : dict ):
        title, comp, _, cityState, current, fromDate, toDate, country, desc = tuple(job.values())
        current = "y" in current.lower()

        self.fillByTestId(self.WORK_TITLE_TESTID, title, "job title")
        self.fillByTestId(self.WORK_COMPANY_TESTID, comp, "company")
        self.fillByTestId(self.WORK_LOCATION_TESTID, cityState, "job location")

        # Set this before the dates: ticking it removes the "To" pair entirely.
        # The toggle's ACTUAL resulting state, not the value asked for --
        # see setToggle's docstring for why trusting the request blindly is
        # exactly what let this get stuck.
        actualCurrent = self.setToggle(self.WORK_CURRENT_TOGGLE, current, "I currently work here")
        if actualCurrent is None:
            actualCurrent = current
        self.setDateRange(fromDate, toDate, actualCurrent, prefix="work ")

        # Description is a contenteditable rich-text box, not an <input>.
        desc = (desc or "").replace("- ", "")
        descEle = self.findFillMoveOn(self.WHOLE, self.WHOLE, self.DESCRIPTION_XPATH, desc)
        if descEle is not None and desc.strip():
            descEle.send_keys(Keys.CONTROL, "a")
            self.findAndClick(self.WHOLE, self.WHOLE, self.BULLET_LIST_XPATH,
                              timeLimit=3, nohang=True)

        saveResult = self.findAndClick(self.WHOLE, self.WHOLE, self.WORK_SAVE_XPATH,
                                       waitBeforeClicking=1, checkNewPage=True)
        if isinstance(saveResult, ElementClickInterceptedException):
            return saveResult
        if self._formStillOpen(self.WORK_TITLE_TESTID):
            raise NeedsHumanError(
                "Clicked 'Save this work experience' but the form is still open -- Indeed "
                "is likely blocking the save on a validation error (often a missing date). "
                "Fix it in the browser, then press Start applying.")
        return saveResult


    @staticmethod
    def _questionKey(questn):
        """A stable identity for a question, so the same one is not re-answered.

        Element wrappers CANNOT be used for this. Every find_elements() call
        builds fresh _ElementCompat objects, and the class defines no __eq__,
        so two wrappers around the same DOM node compare unequal:

            set(first_scan) - set(second_scan)  ->  all 6 questions

        The old code did exactly that subtraction to spot newly appeared
        questions, so after every answer it appended the entire page again. Six
        questions turned into 36 GPT calls and a loop that never finished.
        Question text is what actually distinguishes one question from another.
        """
        try:
            return " ".join((questn.text or "").split())[:200].lower()
        except (PlaywrightError, PlaywrightTimeoutError):
            return ""

    def checkIfMoreQuestionsAppeared(self, tup_ptr):
        """Add any question that appeared in response to an answer just given.

        Some screeners reveal follow-up questions conditionally, which is why
        this exists at all. It must only pick up ones genuinely not seen before.
        """
        allPageQuestions, seenKeys, questn = tup_ptr
        nextQuestInd = allPageQuestions.index(questn) + 1
        QsLeft = allPageQuestions[nextQuestInd:]
        del allPageQuestions[nextQuestInd:]

        latest = self.findAndClick(self.CLASS, self.CONTAINS, 'Questions-item',
                                   indInList=self.ALL, txtCond="#$%^&*(KJH")
        genuinelyNew = []
        for candidate in latest:
            key = self._questionKey(candidate)
            if key and key not in seenKeys:
                seenKeys.add(key)
                genuinelyNew.append(candidate)

        if genuinelyNew:
            ct_print("checkIfMoreQuestionsAppeared",
                     f"{len(genuinelyNew)} follow-up question(s) appeared",
                     f"{len(latest)} on the page now")
        allPageQuestions.extend(genuinelyNew)
        allPageQuestions.extend(QsLeft)

    # A screener page that keeps producing questions is malfunctioning, not
    # thorough. The most ever seen on one page is ten.
    MAX_QUESTIONS_PER_PAGE = 40

    def analyzeAndAnsQuestions(self):
        allPageQuestions = self.findAndClick(self.CLASS, self.CONTAINS, 'Questions-item',
                                             indInList=self.ALL, txtCond="#$%^&*(KJH")

        seenKeys = {self._questionKey(q) for q in allPageQuestions}
        if len(allPageQuestions) > 0:
            url1 = self.driver.current_url
            # hit continue. Since no answers are chosen, this
            # wont be allowed and all the question error txt will appear
            self.findAndClick(self.TXT, self.MATCH,  'Continue', travelUp=1, waitBeforeClicking=.2)

            # if the url changed (meaning that our old responses were used)then just finish/return
            t.sleep(2)
            url2 = self.driver.current_url
            if url1 != url2:
                return  # nothing to do...questions already answered

            answered = 0
            failed = []
            processed = 0
            for questn in allPageQuestions:
                # allPageQuestions is appended to inside this loop, which is how
                # follow-up questions get picked up -- and also how a bad
                # "is this new?" test turned six questions into an endless
                # supply. The cap is a backstop: no screener has 40 questions.
                processed += 1
                if processed > self.MAX_QUESTIONS_PER_PAGE:
                    self.reportAction(
                        f"Stopped after {self.MAX_QUESTIONS_PER_PAGE} questions on one page. "
                        f"The page is producing questions faster than they can be answered, "
                        f"so the rest were left alone.", False)
                    break
                try:
                    ret = self.process_question(questn)
                    if isinstance(ret, BadPost):
                        return ret
                    answered += 1
                    #after answering quesiton, see if any more pop up
                    self.checkIfMoreQuestionsAppeared( (allPageQuestions, seenKeys, questn) )
                    self.MML.append(datetime.datetime.now())

                except NeedsHumanError:
                    # A question that is genuinely stuck -- required, no
                    # profile answer, no safe default to fall back on --
                    # needs a person, not another silent retry. Catching it
                    # below as a plain Exception (Logs/Log24.txt) meant it
                    # never reached transition()'s handler at all: the page
                    # just printed "1 answered, 0 failed" and retried the
                    # same unanswerable question every second, forever.
                    raise
                except Exception as exc:
                    # Kept non-fatal so one odd question does not lose the
                    # application -- but it now SAYS so. This used to be a bare
                    # `except` that printed a raw traceback and set h = 3, so
                    # every question failing looked exactly like every question
                    # succeeding: GPT was consulted five times and not one
                    # answer was ever ticked.
                    failed.append(f"{type(exc).__name__}: {exc}")
                    traceback.print_exc()

            if failed:
                self.reportAction(
                    f"{len(failed)} of {len(allPageQuestions)} screener question(s) could not "
                    f"be answered: {'; '.join(failed[:4])}", False)
            ct_print("analyzeAndAnsQuestions", "questions handled",
                     f"{answered} answered, {len(failed)} failed")

        return self.keepGoing()

    def checkIfQuestionAlreadyAnswered(self, questn, type, answer_choices):
        if type == self.FreeResponse or type == self.FreeResponseLong:
            prevTxt = answer_choices['inputBox'].get_attribute("value")
            return len(prevTxt) > 0
        elif type == self.MultChoice:
            # check if already answered
            checked = self.findAndClick(self.WHOLE, self.WHOLE, '//*[@checked]', txtCond="asdf", findFrom=questn,
                                        timeLimit=1)
            return checked is not None
        elif type == self.DropDown:
            # EVERY dropdown in the question, not just the first. Checking only
            # the first calls "Country" answered as soon as the country is set,
            # leaving the state select blank and the page refusing to continue.
            selects = self._selectsIn(questn)
            return bool(selects) and all(self._selectedTextOf(s) for s in selects)
        elif type == self.SelectApplicable or type == self.DateFill:
            return False
        elif type == self.SearchSelect or type == self.SelectApplicableCombobox:
            trigger = answer_choices.get('trigger')
            if trigger is None:
                return False
            return "select an option" not in (trigger.text or "").lower()
        else:
            return

    def ensureQualityOfDateRespAns(self, gptObj, questn, helpTxt, ans):
        qxpath = self.generate_full_xpath(questn)
        updatedQ = self.findAndClick(self.WHOLE, self.WHOLE, qxpath, txtCond="dasfsd", timeLimit=1)
        _, answer_choices, errorTxt, _ = self.extractQuestionInfo(updatedQ)

        while errorTxt is not None:
            ans = gptObj.sendFromFile("date_wrong_prompts.txt", helpTxt)
            self.fillMoveOn(answer_choices['inputBox'], ans)
            qxpath = self.generate_full_xpath(questn)
            updatedQ = self.findAndClick(self.WHOLE, self.WHOLE, qxpath, txtCond="dasfsd", timeLimit=1)
            _, answer_choices, errorTxt, _ = self.extractQuestionInfo(updatedQ)
        return ans

    def ensureQualityOfFreeRespAns(self, gptObj, questn, helpTxt, ans):
        qxpath = self.generate_full_xpath(questn)
        updatedQ = self.findAndClick(self.WHOLE, self.WHOLE, qxpath, txtCond="dasfsd", timeLimit=1)
        _, answer_choices, errorTxt, _ = self.extractQuestionInfo(updatedQ)

        while errorTxt is not None:
            helpTxt = errorTxt.text
            ans = gptObj.sendFromFile("free_resp_choice_wrong_prompts.txt", helpTxt)
            self.fillMoveOn(answer_choices['inputBox'], ans)
            qxpath = self.generate_full_xpath(questn)
            updatedQ = self.findAndClick(self.WHOLE, self.WHOLE, qxpath, txtCond="dasfsd", timeLimit=1)
            _, answer_choices, errorTxt, _ = self.extractQuestionInfo(updatedQ)

        return ans


    # Word-overlap floor for accepting a choice when the answer does not quote
    # one outright.
    CHOICE_MATCH_FLOOR = 0.30

    @staticmethod
    def _normaliseChoice(text):
        """Lower-case, punctuation-free, single-spaced -- for comparing answers
        with the choices on offer. Digits and '+' survive, so "5+ years" and
        "0-1" still compare sensibly."""
        cleaned = re.sub(r"[^a-z0-9+ ]+", " ", str(text or "").lower())
        return " ".join(cleaned.split())

    def getTopChoiceScore(self, ans, answer_choices):
        """Work out which offered choice an answer actually means.

        The threshold this replaces was

            thresh = self.jaccard_similarity(ans + "~`*", ans)

        -- the answer compared against itself plus three junk characters, which
        is N/(N+3) for an answer of N distinct characters. That RISES with
        answer length, so the longer the reply the harder it was to accept:

            "Yes"                                          0.75 vs 0.57  accepted
            "Yes, I am authorized to work in the US."       0.14 vs 0.88  rejected

        Any reply phrased as a sentence was rejected and re-asked until the
        retry budget ran out. That is 23 GPT calls for five questions, and most
        of the seventeen minutes one questions page took.

        Character-set similarity was the wrong measure too: it compares which
        letters appear, not which words. This looks for the choice quoted in
        the answer first, and falls back to word overlap.
        """
        normAns = self._normaliseChoice(ans)
        ansWords = set(normAns.split())

        # A choice quoted in the answer is a direct hit. When more than one is
        # quoted ("No, but yes if sponsored") the earliest wins, which is the
        # one being answered with.
        hits = []
        for choice in answer_choices:
            normChoice = self._normaliseChoice(choice)
            if not normChoice:
                continue
            found = re.search(rf"(?:^|\s){re.escape(normChoice)}(?:$|\s)", normAns)
            if found:
                hits.append((found.start(), choice))
        if hits:
            hits.sort()
            return hits[0][1], 1.0, self.CHOICE_MATCH_FLOOR

        best, bestScore = None, -1.0
        for choice in answer_choices:
            words = set(self._normaliseChoice(choice).split())
            if not words:
                continue
            union = words | ansWords
            overlap = len(words & ansWords) / len(union) if union else 0.0
            if overlap > bestScore:
                best, bestScore = choice, overlap

        if best is None:
            best, bestScore = next(iter(answer_choices), ""), 0.0
        return best, bestScore, self.CHOICE_MATCH_FLOOR
    # How many times GPT gets asked again for an answer that matches one of the
    # offered choices, and how many times a choice is clicked before giving up.
    ANSWER_RETRIES = 4
    SELECT_ATTEMPTS = 4

    def _tickChoice(self, choiceElement, label):
        """Click an answer choice until its input actually reads as selected.

        Bounded, and it checks the input rather than assuming the click landed.
        The unbounded version could not run at all -- is_selected() did not
        exist on the element wrapper -- but had it existed, a click that never
        registered would have spun here forever.
        """
        for attempt in range(1, self.SELECT_ATTEMPTS + 1):
            inputElement = self.findAndClick(self.WHOLE, self.WHOLE, self.INPUT,
                                             txtCond="adsfadsfads",
                                             findFrom=choiceElement, timeLimit=3)
            if inputElement is not None and inputElement.is_selected():
                return True
            self.smartClick(element=choiceElement)
            t.sleep(self.DELTA_WAIT)

        self.reportAction(
            f"Clicked the answer {label!r} {self.SELECT_ATTEMPTS} times and it never "
            f"registered as selected.", False)
        return False

    def ensureQualityOfMultChoiceAns(self, gptObj, answer_choices, answer):
        topChoice, topScore, thresh = self.getTopChoiceScore(answer, answer_choices)
        for _ in range(self.ANSWER_RETRIES):
            if topScore >= thresh:
                break
            # Bounded: this used to loop until GPT happened to produce an answer
            # matching one of the choices, with no way out if it never did.
            retry = gptObj.sendFromFile("mult_choice_wrong_prompts.txt")
            answer = retry.split("The answer is:")[-1]
            topChoice, topScore, thresh = self.getTopChoiceScore(answer, answer_choices)

        if topScore < thresh:
            self.reportAction(
                f"Could not match an answer to the offered choices for this question "
                f"(best guess {topChoice!r}); ticking it anyway.", False)

        self._tickChoice(answer_choices[topChoice], topChoice)
        return topChoice

    def ensureQualityOfSelectApplicableAns(self, gptObj, answer_choices, ans):
        answers = ans
        topChoiceScoreThresh = [self.getTopChoiceScore(answer, answer_choices) for answer in answers]
        for _ in range(self.ANSWER_RETRIES):
            if not any(topScore < thresh for _c, topScore, thresh in topChoiceScoreThresh):
                break
            # The real filename on disk has "_question_" in it, the same as
            # the main prompt this question uses. The shortened name this
            # replaces does not exist, so every retry here raised
            # FileNotFoundError (Logs/Log21.txt), caught by the caller and
            # reported as "could not be answered" instead of actually retrying.
            answer = gptObj.sendFromFile("select_applicable_question_wrong_prompts.txt")
            answers = [thing.strip() for thing in answer.split("\n") if len(thing.strip()) > 0 ]
            topChoiceScoreThresh = [self.getTopChoiceScore(answer, answer_choices) for answer in answers]

        final_answers = []
        for topChoice, topScore, thresh in topChoiceScoreThresh:
            self._tickChoice(answer_choices[topChoice], topChoice)
            final_answers.append(topChoice)
        return str(final_answers)


    # ensureQualityOfDropDownAns is gone. answerLinkedInputs replaces it, and
    # nothing else called it. It held two unbounded `while` loops -- one asking
    # the model again until an answer happened to match, one sending keystrokes
    # until a <select> reported a value -- either of which parks the run.

    def relevantSubStr(self, substr, fullStr):
        maxLen = int(len(substr)*1.5)
        # Escape any special characters in substr
        escaped_substr = re.escape(substr.lower())
        # Construct the regular expression pattern
        pattern = rf'^(?!.{{{maxLen},}})(.*[^a-zA-Z])?{escaped_substr}([^a-zA-Z].*)?$'
        # Check if the string matches the pattern
        return bool(re.match(pattern, fullStr))

    # A question can hold more than one control, and they can arrive in stages:
    # "Country" is a single question whose second dropdown (the state) does not
    # exist in the HTML at all until "United States" is chosen in the first.
    MAX_LINKED_INPUTS = 6

    def _selectsIn(self, questn):
        """The <select> controls inside one question, in document order."""
        try:
            return self._visible_only(questn.find_elements('xpath', ".//select"))
        except (PlaywrightError, PlaywrightTimeoutError):
            return []

    def _optionsOf(self, selectElement):
        """The choosable options of one select, as {text: value}.

        Per select, deliberately. Reading every option in the QUESTION lumps the
        countries and the states into one list, so the model is asked to pick a
        US state from a list that also contains Zimbabwe.
        """
        options = {}
        try:
            for option in selectElement.find_elements('xpath', ".//option"):
                text = (option.text or "").strip()
                value = (option.get_attribute("value") or "").strip()
                if text and value:          # value="" is the blank placeholder
                    options[text] = value
        except (PlaywrightError, PlaywrightTimeoutError):
            pass
        return options

    def _selectedTextOf(self, selectElement):
        try:
            return (selectElement._handle.evaluate(
                "e => e.selectedOptions.length ? e.selectedOptions[0].text : ''") or "").strip()
        except (PlaywrightError, PlaywrightTimeoutError):
            return ""

    def setSelectTo(self, selectElement, text):
        """Choose an option by its visible text, and check that it took.

        select_option() rather than typing into the control: fillDropDown sends
        the text as keystrokes, which a native <select> resolves by first letter
        and lands on whatever else starts with the same one.
        """
        try:
            selectElement._handle.select_option(label=text)
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            ct_error("setSelectTo", exc)
            return False
        return self._wait_until(
            lambda: self._selectedTextOf(selectElement).lower() == text.lower(), 3)

    def _profileAnswerFor(self, options):
        """An option matching something already known about the applicant.

        Country and state are on file, so asking a model which country the
        applicant lives in is a round trip for information already to hand.
        """
        known = [self.country, self.areaSpec, self.addr, self.zip]
        # areaSpec is "Powder Springs, GA", so its pieces matter as much as
        # the whole: "GA" is what identifies the state option.
        pieces = []
        for value in known:
            text = str(value or "").strip()
            if not text:
                continue
            pieces.append(text)
            pieces.extend(part.strip() for part in text.split(",") if part.strip())

        # Matched on the option's VALUE as well as its text. The country is
        # stored as "United States", which is an option's text, but the state
        # comes from areaSpec "Powder Springs, Ga" -- and "Ga" is the VALUE of
        # the option whose text is "Georgia".
        byText = {self._normaliseChoice(t): t for t in options}
        byValue = {self._normaliseChoice(v): t for t, v in options.items()}
        for piece in pieces:
            key = self._normaliseChoice(piece)
            if not key:
                continue
            if key in byText:
                return byText[key]
            if key in byValue:
                return byValue[key]
        return None

    def answerLinkedInputs(self, questn, questn_txt, helpTxt):
        """Fill every dropdown in a question, including ones that appear later.

        Indeed treats "Country" as ONE question containing a country select and,
        once a country is chosen, a state select. The old code read the options
        of every select at once, set only the first, and left the second empty,
        so the page kept saying "Choose an option to continue."

        Each select is answered from what is already known about the applicant
        where possible, and only otherwise by asking the model.
        """
        answered = []
        for _round in range(self.MAX_LINKED_INPUTS):
            pending = [s for s in self._selectsIn(questn) if not self._selectedTextOf(s)]
            if not pending:
                break

            target = pending[0]
            options = self._optionsOf(target)
            if not options:
                break

            choice = self._profileAnswerFor(options)
            source = "the profile"
            if choice is None:
                mygpt = myGPT2("drop_down_question_prompts.txt", self.JobDescriptionText,
                               str(self.prev_questions), questn_txt, str(self.details),
                               self.lifeSummary, "\n".join(options.keys()), helpTxt,
                               version=1, model=configured_fast_model())
                reply = mygpt.sendAll()
                choice, score, floor = self.getTopChoiceScore(reply, options)
                source = f"the model (match {score:.2f})"
                if score < floor:
                    self.reportAction(
                        f"No option clearly matches the answer for {questn_txt[:60]!r}; "
                        f"going with {choice!r}.", False)

            if self.setSelectTo(target, choice):
                answered.append(choice)
                ct_print("answerLinkedInputs", f"chose {choice[:40]!r}", source)
            else:
                self.reportAction(
                    f"Could not set a dropdown on {questn_txt[:60]!r} to {choice!r}.", False)
                break

            # Choosing can reveal the next control, which needs a moment to
            # render before it can be seen.
            t.sleep(self.DELTA_WAIT)
            self._wait_until(
                lambda n=len(self._selectsIn(questn)): len(self._selectsIn(questn)) != n, 2)

        return ", ".join(answered)

    # The same combobox widget is also how Indeed's demographic/EEO page
    # (HTMLz/question_unanswered1.html: "Ethnicity/Race", and by the same
    # pattern gender, veteran, and disability status) asks its questions.
    # There is no profile field for any of those, and there must never be
    # one filled in by a guess -- these are voluntary by federal law
    # specifically so that declining costs the applicant nothing, which
    # makes "decline" the one always-safe default when nothing on file
    # answers the question.
    DECLINE_MARKERS = ("decline", "prefer not", "do not wish", "don't wish", "not to answer")

    def answerSearchSelect(self, questn, answer_choices, required=False,
                            questn_txt="", helpTxt=""):
        """Answer Indeed's searchable "select-list" combobox.

        The applicant's own country is already on file, the same fact
        answerLinkedInputs uses for the resume's country dropdown, so a
        country/dial-code picker (HTMLz/questions6.html) is answered from the
        profile rather than the model. A demographic question has no such
        fact to match against, so it falls through to DECLINE_MARKERS
        instead -- see that constant for why that, and not the model, is the
        right fallback here.

        `required` is whether Indeed is already showing a validation error
        for this question (a REQUIRED field is unanswerable no other way).
        Silently returning None there is not a safe "skip" the way it is for
        an optional one: the page can never advance, checkIfQuestionAlready
        Answered keeps reporting it unanswered, and the run retried this
        exact question once a second forever (Logs/Log24.txt). A person has
        to look at it instead -- but only once the model has also had ONE
        shot at it (below): most of these are ordinary questions that simply
        have no matching profile fact and no decline option, not demographic
        ones, and the model can pick a reasonable answer from what is on
        offer the same way it already does for a plain dropdown
        (answerLinkedInputs) rather than stopping the whole run for a person
        every time ("No option matched the applicant's profile ... and it
        offered no 'decline to answer' option either" was blocking real
        applications that a model could have answered correctly).
        """
        trigger = answer_choices.get('trigger')
        options = answer_choices.get('options') or {}
        if trigger is None or not options:
            message = ("Could not read the options for a searchable-select question, so it "
                       "was left unanswered.")
            if required:
                raise NeedsHumanError(
                    f"{message} It is required, so the application cannot continue without "
                    f"it. Answer it in the browser, then press Start applying.")
            self.reportAction(message, False)
            return None

        choice = self._profileAnswerFor(options)
        source = "the profile"
        if choice is None:
            choice = next((text for text in options
                           if any(marker in text.lower() for marker in self.DECLINE_MARKERS)), None)
            source = "declining (likely a demographic question with no profile fact to answer it)"
        if choice is None:
            # Last resort, ONE attempt: neither the profile nor a decline
            # option answered this, so ask the model to pick the best of
            # what is actually on offer -- the same call answerLinkedInputs
            # already makes for a plain dropdown in the same situation, not
            # a new/riskier one. No retry loop: one round trip, take
            # whatever real option it lands closest to, or fall through to
            # the "no option matched" NeedsHumanError below exactly as
            # before if the reply doesn't land on any of them at all.
            mygpt = myGPT2("drop_down_question_prompts.txt", self.JobDescriptionText,
                           str(self.prev_questions), questn_txt, str(self.details),
                           self.lifeSummary, "\n".join(options.keys()), helpTxt,
                           version=1, model=configured_fast_model())
            reply = mygpt.sendAll()
            modelChoice, score, floor = self.getTopChoiceScore(reply, options)
            if modelChoice is not None and score >= floor:
                choice = modelChoice
                source = f"the model, as a last resort (match {score:.2f})"
        if choice is None:
            message = ("No option matched the applicant's profile for a searchable-select "
                       "question, and it offered no 'decline to answer' option either, so it "
                       "was left unanswered.")
            if required:
                raise NeedsHumanError(
                    f"{message} It is required, so the application cannot continue without "
                    f"it. Choose an option in the browser yourself, then press Start applying.")
            self.reportAction(message, False)
            return None
        ct_print("answerSearchSelect", f"chose {choice[:60]!r}", source)

        self.smartClick(element=trigger)
        picked = self.findAndClick(self.TXT, self.MATCH, choice, findFrom=questn, timeLimit=4)
        if picked is None:
            self.reportAction(
                f"Opened a searchable-select question but could not find the option "
                f"{choice!r} to click.", False)
            return None

        if not self._wait_until(
                lambda: "select an option" not in (trigger.text or "").lower(), 3):
            self.reportAction(
                f"Chose {choice!r} on a searchable-select question but the control still "
                f"shows no selection.", False)
        return choice

    def _tickAriaCheckbox(self, choiceElement, label):
        """Click an ARIA role="menuitemcheckbox" choice until aria-checked
        actually reads true.

        The same job _tickChoice does for a real <input>-backed checkbox,
        but these choices (HTMLz/questions_stuck.html) are custom ARIA
        controls with no <input> inside them at all -- is_selected() /
        is_checked() do not apply to a plain <li>, so aria-checked is the
        only way to tell whether a click actually registered.
        """
        for _ in range(self.SELECT_ATTEMPTS):
            if (choiceElement.get_attribute("aria-checked") or "").lower() == "true":
                return True
            self.smartClick(element=choiceElement, expectingPopUp=True)
            t.sleep(self.DELTA_WAIT)

        self.reportAction(
            f"Clicked the answer {label!r} {self.SELECT_ATTEMPTS} times and it never "
            f"registered as checked.", False)
        return False

    def answerSelectApplicableCombobox(self, questn, answer_choices, required=False,
                                        questn_txt="", helpTxt=""):
        """Answer the "select all that apply" version of Indeed's combobox
        widget (HTMLz/questions_stuck.html): a role="combobox" trigger opens
        a role="dialog" popup of role="menuitemcheckbox" items, several of
        which can be checked at once -- unlike answerSearchSelect's widget,
        where picking one option closes the popup immediately.

        The ANSWER side of "which of these apply" does not change just
        because Indeed drew this as a dropdown instead of a flat list of
        checkboxes, so this reuses the exact same model call and retry-on-
        bad-match convention as the plain-checkbox version of this question
        (SelectApplicable / ensureQualityOfSelectApplicableAns) -- only how
        a chosen answer gets CLICKED differs (_tickAriaCheckbox).
        """
        trigger = answer_choices.get('trigger')
        options = answer_choices.get('options') or {}
        if trigger is None or not options:
            message = ("Could not read the options for a 'select all that apply' "
                       "dropdown question, so it was left unanswered.")
            if required:
                raise NeedsHumanError(
                    f"{message} It is required, so the application cannot continue "
                    f"without it. Answer it in the browser, then press Start applying.")
            self.reportAction(message, False)
            return None

        mygpt = myGPT2("select_applicable_question_prompts.txt", self.JobDescriptionText,
                       str(self.prev_questions), questn_txt, "\n".join(options.keys()),
                       helpTxt, version=1, model=configured_fast_model())
        ans = mygpt.sendAll()
        answers = [thing.strip() for thing in ans.split("\n") if thing.strip()]
        topChoiceScoreThresh = [self.getTopChoiceScore(answer, options) for answer in answers]
        for _ in range(self.ANSWER_RETRIES):
            if not any(topScore < thresh for _c, topScore, thresh in topChoiceScoreThresh):
                break
            # Same reasoning, and the same real filename, as
            # ensureQualityOfSelectApplicableAns's identical retry.
            answer = mygpt.sendFromFile("select_applicable_question_wrong_prompts.txt")
            answers = [thing.strip() for thing in answer.split("\n") if thing.strip()]
            topChoiceScoreThresh = [self.getTopChoiceScore(answer, options) for answer in answers]

        chosen = [topChoice for topChoice, _score, _thresh in topChoiceScoreThresh]
        if not chosen:
            message = ("The model did not offer any option for a 'select all that "
                       "apply' dropdown question, so it was left unanswered.")
            if required:
                raise NeedsHumanError(
                    f"{message} It is required, so the application cannot continue "
                    f"without it. Choose options in the browser yourself, then press "
                    f"Start applying.")
            self.reportAction(message, False)
            return None

        self.smartClick(element=trigger, expectingPopUp=True)
        ticked = [choice for choice in chosen
                 if options.get(choice) is not None
                 and self._tickAriaCheckbox(options[choice], choice)]

        # Closes the popup: unlike answerSearchSelect's single-select
        # version, this one stays open after each click so more than one
        # option can be checked, and never closes on its own.
        try:
            self._page.keyboard.press("Escape")
        except PlaywrightError:
            pass

        if not ticked:
            message = ("Could not tick any option for a 'select all that apply' "
                       "dropdown question.")
            if required:
                raise NeedsHumanError(
                    f"{message} It is required, so the application cannot continue "
                    f"without it. Choose options in the browser yourself, then press "
                    f"Start applying.")
            self.reportAction(message, False)
            return None
        return ", ".join(ticked)

    def checkIfAPreMadeAnswerFits(self, questn_txt, type, answer_choices):
        detailKeysOrdrd = list(self.details.keys())
        detailKeysOrdrd.sort(key=lambda x:len(x), reverse=True)
        ourAns = None
        for detKey in detailKeysOrdrd:
            if self.relevantSubStr(detKey, questn_txt.lower()):
                ourAns = self.details[detKey]
                break
        if ourAns is not None:
            if type == self.DropDown:
                # Left to answerLinkedInputs, which consults the same profile
                # details, handles every dropdown in the question rather than
                # the first, and verifies the choice actually took. send_keys
                # on a <select> resolves by first letter and lands anywhere.
                return False
            elif type == self.FreeResponse:
                self.fillMoveOn(answer_choices['inputBox'], ourAns)
            else:
                return False
            return True
        else:
            return False
    def _questionTypeName(self, type):
        return {
            self.FreeResponse: "free response",
            self.MultChoice: "multiple choice",
            self.DropDown: "dropdown",
            self.FreeResponseLong: "free response (long)",
            self.SelectApplicable: "select all that apply",
            self.DateFill: "date",
            self.SearchSelect: "searchable select",
            self.SelectApplicableCombobox: "select all that apply (dropdown)",
        }.get(type, f"unknown ({type!r})")

    def process_question(self, questn):  #//div[contains(@class, 'Questions-item')]
        #Do we even have to do this question?
        txt = questn.text
        # Real capture (HTMLz/questions6.html) reads "(Optional)", capital O
        # -- a case-sensitive check let it through into full processing.
        if '(optional)' in txt.lower():
            return

        questn_txt, answer_choices, errorTxt, type = self.extractQuestionInfo(questn)

        if isinstance(type, BadPost):
            return type

        ct_section("QUESTION", questn_txt.strip() or "(no question text found)",
                   f"type={self._questionTypeName(type)}"
                   + (", flagged required by Indeed" if errorTxt is not None else ""),
                   indent=1)

        if self.checkIfQuestionAlreadyAnswered(questn, type, answer_choices):
            return

        if self.checkIfAPreMadeAnswerFits(questn_txt, type, answer_choices):
            return

        helpTxt = "Answer as concisely and in as natural a way as possible"
        if errorTxt is not None:
            helpTxt = errorTxt.text

        self.txt = questn_txt


        #  get ans back from chat GPT
        ans = None
        final_answer = None
        if type == self.FreeResponse or type == self.FreeResponseLong:
            # get chat GPT help with free response question
            # Order matters: placeholders are filled in the order they appear in
            # the prompt file. The work history and the style guide are new, and
            # they sit between the life summary and the question, and between
            # the question and "reply only with the answer", respectively.
            mygpt = myGPT2("free_response_question_prompts.txt", self.JobDescriptionText,
                          str(self.prev_questions), str(self.details), self.lifeSummary,
                          self.realExperienceBlock(), questn_txt, self.styleGuide(), helpTxt,
                          self.zip, self.phone_num, self.email, version=1)
            ans = self.stripDashes(mygpt.sendAll())
            self.fillMoveOn(answer_choices['inputBox'], ans)

            final_answer = self.ensureQualityOfFreeRespAns(mygpt, questn, helpTxt, ans)

        elif type == self.DateFill:
            # get chat GPT help with free response question
            mygpt = myGPT2("date_fill_question_prompts.txt", self.JobDescriptionText, str(self.prev_questions),
                        questn_txt, self.today_mmddyyy(), helpTxt, version=1)
            ans = mygpt.sendAll()
            month, day, year = tuple(ans.split("-"))

            # Two different real widgets get classified as DateFill. The one
            # actually captured (HTMLz/questions9.html, "Today's Date") is a
            # plain text input reading "MM/DD/YYYY" with a calendar-icon
            # button beside it -- typing into it is all it needs. The
            # classification only requires SOME button near an input though,
            # so this also fires for a genuine calendar-popup picker (month
            # dropdown, year dropdown, click a day) -- what the code below
            # was written for, and which does not exist on questions9.html.
            # Before this, EVERY DateFill question hit the popup flow first
            # and burned 10+ seconds on each of three elements that were
            # never on the page at all, every retry, forever (Logs/Log22.txt).
            inputBox = answer_choices.get('inputBox')
            filled = False
            if inputBox is not None:
                monthNum = None
                for fmt in ("%B", "%b"):
                    try:
                        monthNum = datetime.datetime.strptime(month.strip(), fmt).month
                        break
                    except ValueError:
                        continue
                if monthNum is not None:
                    self.fillMoveOn(inputBox, f"{monthNum:02d}/{int(day.strip()):02d}/{year.strip()}")
                    filled = self._wait_until(
                        lambda: bool((inputBox.get_attribute("value") or "").strip()), 2)

            if not filled:
                self.findAndClick(self.ARIA_LABEL, self.CONTAINS, "Choose a date", findFrom=questn)

                #  select month
                monSelect = self.findAndClick(self.ARIA_LABEL, self.CONTAINS, "Month select", findFrom=questn,
                                              txtCond="adfas")
                self.fillDropDown(monSelect, month)

                # seelct year
                yrSelect = self.findAndClick(self.ARIA_LABEL, self.CONTAINS, "Year select", findFrom=questn,
                                              txtCond="adfas")
                self.fillDropDown(yrSelect, year)

                self.findAndClick(self.TXT, self.MATCH, day, findFrom=questn)

            #final_answer = self.ensureQualityOfDateRespAns(mygpt, questn, helpTxt, ans)


        elif type == self.MultChoice:
            #get chat GPT help
            mygpt = myGPT2("mult_choice_question_prompts.txt", self.JobDescriptionText,  str(self.prev_questions),
                          questn_txt, "\n".join(list(answer_choices.keys())), helpTxt, version=1, model=configured_fast_model())
            # [-1], not [1]: when GPT answers without the "The answer is:"
            # preamble, [1] is an IndexError that kills the whole question.
            # [-1] gives the reply itself, which then gets scored against the
            # offered choices like any other.
            ans = mygpt.sendAll().split("The answer is:")[-1]

            final_answer = self.ensureQualityOfMultChoiceAns(mygpt, answer_choices, ans)

        elif type == self.SelectApplicable:
            #get chat GPT help
            mygpt = myGPT2("select_applicable_question_prompts.txt", self.JobDescriptionText,  str(self.prev_questions),
                          questn_txt, "\n".join(list(answer_choices.keys())), helpTxt, version=1, model=configured_fast_model())
            ans = mygpt.sendAll()
            ans_list = [thing.strip() for thing in ans.split("\n") if len(thing.strip()) > 0 ]

            final_answer = self.ensureQualityOfSelectApplicableAns(mygpt, answer_choices, ans_list)


        elif type == self.DropDown:
            # Every dropdown in the question, not just the first, and including
            # any that only appear once an earlier one is answered.
            final_answer = self.answerLinkedInputs(questn, questn_txt, helpTxt)

        elif type == self.SearchSelect:
            final_answer = self.answerSearchSelect(questn, answer_choices, required=errorTxt is not None,
                                                    questn_txt=questn_txt, helpTxt=helpTxt)

        elif type == self.SelectApplicableCombobox:
            final_answer = self.answerSelectApplicableCombobox(
                questn, answer_choices, required=errorTxt is not None,
                questn_txt=questn_txt, helpTxt=helpTxt)

        self.prev_questions.append({"Question":questn_txt, "Answer":final_answer})


    # A combobox option reads "United States (+1)"; this is the country name
    # alone, for matching against the profile the same way answerLinkedInputs
    # matches a state's option VALUE.
    DIAL_CODE_SUFFIX = re.compile(r"\s*\(\+\s*\d+\)\s*$")

    def extractQuestionInfo(self, questn):
        ans_dict = {
            # format =  "Yes": <obj>
            # format =  "No": <obj>
        }
        intermediate_ans_list = []
        questionText = ""
        # determine type  //*[@aria-label="Day and time option"]
        type = self.determine_question_type(questn)

        if isinstance(type, BadPost):
            return None, None, None, type

        # Error text is a PROBE, not a wait: a validation message is either on
        # the question right now or it is not, and it cannot arrive later on its
        # own. At 2s each these two lookups cost 4 seconds per question, every
        # question, every rescan -- which is most of why a page of ten questions
        # took longer than the 15 minute stall alarm.
        errorTxt = self.findAndClick(self.ID,  self.CONTAINS, 'errorText', txtCond="$%^&*()",
                                     findFrom=questn, timeLimit=.4)
        if errorTxt is None:
            errorTxt = self.findAndClick(self.WHOLE, self.WHOLE, "//span[@role='alert']",
                                         txtCond="$%^&*()", findFrom=questn, timeLimit=.4)
        if errorTxt is None:
            # Indeed's newer Mosaic questions -- single-select-question,
            # date-question (HTMLz/question_unanswered1.html, questions9.html) --
            # use a HYPHENATED "*-error-text-*" id and no role="alert" ANYWHERE,
            # so both lookups above always missed them. errorTxt stayed None for
            # every one of these regardless of whether Indeed was genuinely
            # blocking on the question, which silently disabled the
            # "required and unanswerable -> ask a person" check in
            # answerSearchSelect: required=errorTxt is not None was never once
            # True, so a required combobox with no safe answer just retried
            # forever instead of stopping (Logs/log27.txt).
            errorTxt = self.findAndClick(self.ID, self.CONTAINS, 'error-text', txtCond="$%^&*()",
                                         findFrom=questn, timeLimit=.4)
        if errorTxt is not None and self.num_children(errorTxt) == 0:
            errorTxt = None

        #get answer choices & question text
        try:
            if type == self.FreeResponse or type == self.FreeResponseLong or type == self.DateFill:
                ans_dict['inputBox'] = self.findAndClick(self.WHOLE, self.WHOLE, self.xpath_or(self.INPUT, self.TXTAREA) , findFrom=questn)
                if ans_dict['inputBox'] is None:
                    # The probe in determine_question_type only checks that AN
                    # input exists somewhere in the question, not that it is
                    # visible -- a combobox's hidden search-filter input passes
                    # that probe. Falling through to the dict lookup below with
                    # type still FreeResponse/DateFill/FreeResponseLong crashed
                    # with KeyError: -1 once type became Bad (Logs/log19.txt);
                    # grab the label the same way the real `type == self.Bad`
                    # branch does and stop here instead.
                    type = self.Bad
                    label = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn,
                                              txtCond="#$%^&", timeLimit=.4)
                    questionText = label.text if label is not None else ""
                else:
                    txtRoot = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn, txtCond="#$%^&")
                    questionText = {self.FreeResponse: txtRoot.text,
                                    self.DateFill: txtRoot.text,
                                    self.FreeResponseLong: txtRoot.text.split("\n")[-1].replace("\"", "")}[type]

            elif type == self.SearchSelect:
                # Indeed's searchable "select-list" combobox (HTMLz/questions6.html):
                # a role="combobox" trigger and a role="listbox" popup of
                # role="option" items, all mounted in the DOM together whether
                # the popup is open or not.
                # txtCond is a probe, not a real condition -- it never matches,
                # so this reads the trigger without a default '' txtCond
                # clicking it open (findAndClick clicks whatever it finds
                # unless txtCond fails to match).
                trigger = self.findAndClick(self.WHOLE, self.WHOLE, "//*[@role='combobox']",
                                            findFrom=questn, txtCond="*()")
                optionElements = self.findAndClick(self.WHOLE, self.WHOLE, f"{self.LIST_ELEMENT}[@role='option']",
                                                   findFrom=questn, indInList=self.ALL)
                options = {}
                for element in optionElements:
                    text = (element.text or "").strip()
                    if text:
                        options[text] = self.DIAL_CODE_SUFFIX.sub("", text).strip()
                ans_dict = {'trigger': trigger, 'options': options}
                questionText = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn, txtCond="#$%^&").text

            elif type == self.SelectApplicableCombobox:
                # The "select all that apply" version of the same combobox
                # widget (HTMLz/questions_stuck.html): choices are
                # role="menuitemcheckbox" <li>s inside a role="dialog" popup,
                # not role="option" -- ARIA custom controls, several can be
                # checked at once, and this whole thing sits inside a
                # fieldset/legend the way a plain checkbox group does.
                trigger = self.findAndClick(self.WHOLE, self.WHOLE, "//*[@role='combobox']",
                                            findFrom=questn, txtCond="*()")
                optionElements = self.findAndClick(
                    self.WHOLE, self.WHOLE, f"{self.LIST_ELEMENT}[@role='menuitemcheckbox']",
                    findFrom=questn, indInList=self.ALL)
                options = {(element.text or "").strip(): element
                          for element in optionElements if (element.text or "").strip()}
                ans_dict = {'trigger': trigger, 'options': options}
                questionText = self.findAndClick(self.WHOLE, self.WHOLE, '//legend', findFrom=questn,
                                                 txtCond="#$%^&").text

            elif type == self.MultChoice:
                intermediate_ans_list = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn, indInList=self.ALL)
                ans_dict = { element.text : element for element in intermediate_ans_list}
                questionText = self.findAndClick(self.WHOLE, self.WHOLE, '//legend', findFrom=questn, txtCond="#$%^&").text
            elif type == self.DropDown:
                intermediate_ans_list = self.findAndClick(self.WHOLE, self.WHOLE, self.OPTION, findFrom=questn, indInList=self.ALL)
                ans_dict = {}
                ans_dict['answers'] = { element.text : element for element in intermediate_ans_list if len(element.text) > 0 }
                ans_dict['dropDown'] = self.findAndClick(self.WHOLE, self.WHOLE, '//select', findFrom=questn)
                questionText = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn, txtCond="#$%^&").text
            elif type == self.SelectApplicable:
                # Every <label> in the fieldset wraps one checkbox choice --
                # same shape as MultChoice's radios just above, and the same
                # reason MultChoice does not pop anything off this list
                # either. The pop(0) this replaces assumed a decoy label
                # ahead of the real choices; no real capture in HTMLz/ has
                # one (questions6.html, questions8.html), so for the common
                # case of a single checkbox (an "I agree" attestation,
                # Logs/Log21.txt) it deleted the only real choice, leaving
                # GPT asked to pick from an empty list every time.
                intermediate_ans_list = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn, indInList=self.ALL)
                ans_dict = {element.text: element for element in intermediate_ans_list}
                # The question text: MultChoice already reads this from
                # //legend rather than a <label>, and it is right to -- the
                # per-checkbox <label>s are answer choices, not the question,
                # and the actual question here lives in the <legend> too.
                questionText = self.findAndClick(self.WHOLE, self.WHOLE, '//legend', findFrom=questn, txtCond="#$%^&").text
            elif type == self.Bad:
                # A question already judged unanswerable. Its text is only used
                # for the log, so this must not be the default TEN SECOND
                # lookup it used to be -- with every question on a page coming
                # back Bad that was ten seconds each, for a string nothing reads.
                label = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn,
                                          txtCond="#$%^&", timeLimit=.4)
                questionText = label.text if label is not None else ""
        except Exception as exc:
            # This used to end with `while still: t.sleep(1)` -- an unbreakable
            # loop that parked the whole run forever on any error in here. And
            # the handler above it did `t = 3`, rebinding the name `t` for the
            # entire function, so `t.sleep` was an int by the time it was
            # reached. Report and move on; the caller treats a Bad question as
            # one to skip.
            ct_error("extractQuestionInfo", exc)
            traceback.print_exc()
            type = self.Bad

        if "(optional)" in questionText.lower():
            type = self.Bad

        return questionText, ans_dict, errorTxt, type

    def redirectAndSkip(self, message):
        self.driver.get("https://www.google.com")
        try:
            alert = self.driver.switch_to.alert
            alert.accept()
        except:
            pass
        return BadPost(message)

    # Anything a person could actually answer with. A "Questions-item" holding
    # none of these is not a question -- on these pages the first one is
    # usually the employer's introductory paragraph.
    QUESTION_CONTROL_XPATH = ".//input | .//textarea | .//select"

    def questionHasControls(self, questn):
        """True when this item contains something to answer.

        Replaces a positional guess: num_children(get_child_complex(questn,
        "1/2")) == 0, i.e. "the second child of the first child has no children
        of its own". That asserts a particular DOM nesting rather than anything
        about the question, and when Indeed renested the page every one of six
        questions was classed as unanswerable and skipped -- a whole screener
        page left blank without a single line in the log saying why.
        """
        try:
            return bool(questn.find_elements('xpath', self.QUESTION_CONTROL_XPATH))
        except (PlaywrightError, PlaywrightTimeoutError):
            return False

    def determine_question_type(self, questn):
        try:
            qChild = self.get_child(questn, 1, 1)
        except:
            return self.Bad

        num = self.num_children(qChild)
        listOfBad = self.findAndClick( '@aria-label', self.MATCH, 'Day and time option', findFrom=questn, indInList=self.ALL)
        if len(listOfBad) > 0 or not self.questionHasControls(questn):
            # then it's a question we don't want
            if "upload" in questn.text.lower():
                return self.redirectAndSkip("bad question... not dealing with it")
            else:
                return self.Bad
        elif self.findAndClick(self.WHOLE, self.WHOLE, "//fieldset", findFrom=questn, timeLimit=.1, txtCond="*()") is not None:
            # Newer "select all that apply" questions wrap a role="combobox"
            # trigger + role="dialog" popup in the SAME fieldset/legend shape
            # a plain radio/checkbox group uses (HTMLz/questions_stuck.html).
            # Checked before assuming radio/checkbox: this fieldset's only
            # <input> is then the popup's search-filter box, which carries no
            # type attribute at all, and looking that up in the dict below
            # crashed with KeyError: None (Logs/Log35.txt) before this shape
            # was ever considered.
            if self.findAndClick(self.WHOLE, self.WHOLE, "//*[@role='combobox']", findFrom=questn,
                                 timeLimit=.1, txtCond="*()") is not None:
                return self.SelectApplicableCombobox
            #  also contains input, find out what kind of input (radio or checkbox)
            inputEle = self.findAndClick(self.WHOLE, self.WHOLE, self.INPUT, txtCond="asdf", findFrom=questn, timeLimit=.1)
            typeOfInput = inputEle.get_attribute("type")
            # .get(), not a bare [] lookup: a fieldset holding neither a
            # combobox nor a real radio/checkbox input is a shape this has
            # never seen, and crashing the whole run on it is worse than
            # treating it as unanswerable the same way other unrecognised
            # shapes already are.
            return {"radio": self.MultChoice, "checkbox": self.SelectApplicable}.get(typeOfInput, self.Bad)
        elif self.findAndClick(self.WHOLE, self.WHOLE, "//div[@role='group']", findFrom=questn, timeLimit=.1, txtCond="*()") is not None:
            return self.redirectAndSkip("This was the group... analzye and see..")
        elif self.findAndClick(self.ID, self.CONTAINS, "FileUpload", findFrom=questn, timeLimit=.1, txtCond="*()") is not None:
            #redirect to google because that's the environment that tells us we need to skip this post
            return self.redirectAndSkip("They wanted us to upload a file... fuck that.. not dealing with it")
        elif self.findAndClick(self.WHOLE, self.WHOLE, "//*[@role='combobox']", findFrom=questn, timeLimit=.1, txtCond="*()") is not None:
            # Indeed's searchable "select-list" widget (HTMLz/questions6.html,
            # the Mobile Number country/dial-code picker): a role="combobox"
            # trigger with a role="listbox" popup of role="option" items. This
            # check has to come before the plain //input check below -- the
            # popup's search-filter input lives inside this same question and
            # would otherwise get misread as a free-text box, which is not
            # findable when the popup is closed and crashed extractQuestionInfo.
            return self.SearchSelect
        elif self.findAndClick(self.WHOLE, self.WHOLE, self.TXTAREA, findFrom=questn, timeLimit=.1, txtCond="^&*") is not None:
            return self.FreeResponseLong

        elif self.findAndClick(self.WHOLE, self.WHOLE, self.INPUT, findFrom=questn, timeLimit=.1, txtCond="*()") is not None:
            if self.findAndClick(self.WHOLE, self.WHOLE, self.BUTTON, findFrom=questn, timeLimit=.1, txtCond="*()") is not None:
                return self.DateFill
            else:
                return self.FreeResponse

        elif self.findAndClick(self.WHOLE, self.WHOLE, self.SELECT, findFrom=questn, timeLimit=.1, txtCond="%^&") is not None:
            return self.DropDown
        else:
            return self.Bad



    # The cover letter page (HTMLz/Add_Documents.html). Indeed rebuilt it: the
    # old data-testid="CoverLetterRadioCard" matches nothing at all now, and the
    # footer button says "Continue", not "Update"/"Review your application".
    #
    # The important part is that "No cover letter" is the option that comes
    # PRESELECTED, so choosing the cover letter is not optional -- skip it and
    # the application goes out without one no matter what was typed.
    COVER_LETTER_CHOICES = (
        "//*[@data-testid='cover-letter-radio-card-input']",
        "//*[@data-testid='cover-letter-radio-card-label']",
        "//*[@data-testid='cover-letter-radio-card']",
        "//div[@data-testid='CoverLetterRadioCard']",
    )
    COVER_LETTER_INPUT_XPATH = "//*[@data-testid='cover-letter-radio-card-input']"
    COVER_LETTER_TEXT_XPATH = (
        "//*[@data-testid='cover-letter-radio-card-text-area']"
        " | //textarea[@aria-label='Write a cover letter']"
        " | //textarea"
    )
    DOCS_CONTINUE_XPATH = (
        '//*[@data-testid="continue-button"]'
        " | //button[normalize-space(.)='Continue']"
        " | //button[normalize-space(.)='Update']"
        " | //button[normalize-space(.)='Review your application']"
    )

    def _coverLetterChosen(self):
        """True when the 'write a cover letter' radio is actually selected."""
        for element in self._visible_only(
                self.driver.find_elements('xpath', self.COVER_LETTER_INPUT_XPATH)):
            try:
                return element._handle.is_checked()
            except (PlaywrightError, PlaywrightTimeoutError):
                continue
        return False

    def chooseCoverLetterOption(self):
        """Select the cover letter radio, checking that it took.

        Radios in this UI are sometimes the input, sometimes only reachable
        through the label, so each candidate is tried and then read back.
        """
        for xpath in self.COVER_LETTER_CHOICES:
            target = self.findAndClick(self.WHOLE, self.WHOLE, xpath,
                                       txtCond="@#$ never matches %^&", timeLimit=4)
            if target is None:
                continue
            self.smartClick(element=target)
            if self._wait_until(self._coverLetterChosen, 3):
                return True
        return False

    def do_cover_letter(self):
        if self._addDocsAttemptsExhausted("do_cover_letter"):
            return None

        self.waitOutLoading()

        if not self.chooseCoverLetterOption():
            self.reportAction(
                "Could not select the 'write a cover letter' option; 'No cover letter' is "
                "the one that comes preselected, so the letter would not be attached.", False)

        field = self.findAndClick(self.WHOLE, self.WHOLE, self.COVER_LETTER_TEXT_XPATH,
                                  txtCond="@#$ never matches %^&", timeLimit=6)
        if field is None:
            self.reportAction("Could not find the cover letter box on this page.", False)
        else:
            self.fillMoveOn(field, self.coverLetter)
            try:
                written = field._handle.input_value()
            except (PlaywrightError, PlaywrightTimeoutError):
                written = None
            if written is not None and written.strip() != str(self.coverLetter).strip():
                self.reportAction(
                    f"The cover letter box did not take the whole letter: wrote "
                    f"{len(str(self.coverLetter))} characters, it holds {len(written)}.", False)

        # Continue starts out DISABLED and only enables once a choice is made,
        # so clicking it straight away just burns the click timeout.
        button = self.findAndClick(self.WHOLE, self.WHOLE, self.DOCS_CONTINUE_XPATH,
                                   txtCond="@#$ never matches %^&", timeLimit=6)
        if button is None:
            self.reportAction("Could not find the Continue button on the documents page.", False)
            return None
        if not self._wait_until(lambda: button._handle.is_enabled(), 8):
            raise NeedsHumanError(
                "The cover letter page will not let the application continue -- its Continue "
                "button is still disabled, which means the page wants something it has not "
                "been given. Sort it out in the browser, then press Start applying.")
        return self.smartClick(element=button, checkNewPage=True)


    def addAnother(self):
        self.findAndClick(self.TXT, self.CONTAINS,  'Add another', travelUp=1)


    def finalizeResumeSection(self):
        self.findAndClick(self.TXT, self.MATCH, 'Save', travelUp=1, waitBeforeClicking=.7, checkNewPage=True)

    def nextResumeSection(self):
        self.findAndClick( self.TXT, self.MATCH, 'Save and continue', travelUp=1)

    def getProfileGen(self):
        infinite_iterator = itertools.cycle(self.profiles)
        for profile in infinite_iterator:
            self.home_url = profile["home"]
            yield profile

    def load_startup_info(self, info):
        # Job searches come from the job_searches table (ordered by `position`,
        # which is what decides run order) rather than the old space-delimited
        # users.homePage blob. That column still exists as an audit trail but is
        # no longer read.
        try:
            self.MY_PATH          =  "Users\\" + f"{info['FirstName']} {info['LastName']} {info['id']}" + "\\"

            for rec in self.searchRecords:
                jobNums = (rec["job_nums"] or "").strip()
                eduNums = (rec["edu_nums"] or "").strip()
                # An empty list means "use every Job/Edu record for this user",
                # which the rest of the code expresses as None.
                self.profiles.append({"home": rec["url"],
                                      "eduN": [int(n) for n in eduNums.split(",")] if eduNums else None,
                                      "jobN": [int(n) for n in jobNums.split(",")] if jobNums else None})

            if not self.profiles:
                raise ValueError(
                    f"User {info['id']} ({info['FirstName']} {info['LastName']}) has no rows in "
                    f"job_searches, so there is no job search to start from. Add one in the "
                    f"database admin GUI (db_admin.py) before running this user."
                )

            self.profile_generator = self.getProfileGen()
            self.cur_profile = next(self.profile_generator)

            self.home_url_pattern =  info["homePagePattern"]
            self.chrome_profile  +=  info["ProfilePath"]
            self.chrome_profile_ = info["ProfilePath"]
            self.user_id = int(info["id"])
            self.applicationsLeft = info["AppsLeft"]
            self.firstName = info["FirstName"]
            self.lastName = info["LastName"]
            self.phone_num = info["PhoneNumber"]
            self.email = info["IndeedEmail"]
            self.addr = info["address"]
            self.areaSpec = info["areaSpec"]
            self.country = info["country"]
            self.zip = info["zip"]
            self.lifeSummary = info["LifeSummary"]
            # Optional: a passage the applicant actually wrote, used to hold
            # generated text to their own voice. Absent on databases that have
            # not had the migration run, so read it defensively.
            self.writingSample = (info["WritingSample"]
                                  if "WritingSample" in info.keys() else "") or ""
            self.avoid = info["avoid"]
            # Optional: absent on databases that have not had the
            # add_avoid_employers migration run, so read it defensively.
            self.avoidEmployers = (info["avoidEmployers"]
                                   if "avoidEmployers" in info.keys() else "") or ""

        except Exception as exc:
            # This used to be a bare `except: return`, which silently produced a
            # half-configured helper -- a NULL homePage turned into "no profiles"
            # with no error anywhere. Fail loudly instead.
            ct_error("load_startup_info", exc)
            raise


    def load_life_summary(self):
        # purpose of '_' is to skip the explanation of the next line/section
        try:
            self.setDetails()
            #self.saveUserInDB()
        except Exception as e:
            print("An error occurred:", e)
            traceback.print_exc()

    def setDetails(self):
        c, s = tuple(self.areaSpec.split(","))
        self.details = {"name": f"{self.firstName} {self.lastName}",
                        "first name": self.firstName,
                        "last name": self.lastName,
                        "number":self.phone_num, "phone":self.phone_num,
                        "phone number":self.phone_num.replace("(", "").replace(")", "").replace(" ", "").replace("-", ""),
                        "email": self.email,
                        "address":self.addr,
                        "city":c, "state":s.strip(), "country":self.country,
                        "zip":self.zip, "postal code":self.zip}



    def jobContainsForbiddenCharacteristics(self):
        """None if the job is fine to proceed with. Otherwise the model's own
        explanation of which avoid-criterion it matched and why -- the caller
        persists this in skipped.txt (_recordSkippedJob) precisely so a LATER
        run recognizing this same job can say why it is skipping it, instead
        of silently abandoning the tab with nothing in the trace to explain
        it (Logs/log29.txt: read exactly like a captcha-handling bug).
        """
        mygpt = myGPT2("avoid_job_characteristics_prompts2.txt", self.JobDescriptionText)
        mygpt.sendAll()
        # get the avoidance qualities
        #avoidFile = open(self.MY_PATH + self.dataPath + "AvoidTheseJobCharacteristics.txt", 'r')
        #avoidLines = avoidFile.readlines()
        for avoidLine in self.avoid.split("\n"):
            if len(avoidLine.strip()) == 0:
                continue
            #prompt = f'''Does this job match this characteristic:\n{avoidLine}\n\nif not, then just say "no",
            # if so, then say "yes" and also include the portion of the job description that
            # matches the above characteristic.'''

            prompt = f'''{avoidLine} If the answer is no, then reply "NO" and say nothing else.  If the answer is yes,
            then reply "YES" and then also tell me the portion of the job description that made you say "YES"'''
            ans = mygpt.send(prompt)
            if "yes" in ans.lower():
                self.reportAction("CHAT GPT SAID: " + ans.lower(), False)
                return ans.strip()

        return None

    def avoidedEmployerReason(self, companyName):
        """None if companyName is not on the user's avoid-employers list,
        otherwise a reason string suitable for _recordSkippedJob. Pure string
        comparison against self.avoidEmployers -- no AI call, so this can run
        before jobContainsForbiddenCharacteristics() and skip the job without
        ever spending a model call on it.
        """
        target = companyName.strip().lower()
        if not target:
            return None
        for line in self.avoidEmployers.split("\n"):
            if line.strip().lower() == target:
                return f'employer "{companyName}" is on the avoid-employers list'
        return None

    def getPositionInfo(self):
        x = "//*[@data-testid='inlineHeader-companyName']"
        compNameEle = self.findAndClick(self.WHOLE, self.WHOLE, x, txtCond="dsfdsd324", timeLimit=1)
        self.companyName = compNameEle.text


        # The title now lives in h1.jobsearch-JobInfoHeader-title. The old
        # "<span>... - job post</span>" wrapper is gone from Indeed's markup, and
        # looking for it burned a 2 second timeout on every single job before
        # falling through to the h1 anyway.
        titleElement = self.findAndClick(self.WHOLE, self.WHOLE,
                                         "//h1[contains(@class,'jobsearch-JobInfoHeader-title')] | //h1",
                                         txtCond="adfddfsa", timeLimit=2)
        self.jobTitle = titleElement.text.split("\n")[0]

        jobDescElement = self.findAndClick(self.ID, self.MATCH, 'jobDescriptionText', txtCond='adsfdasf134')
        self.JobDescriptionText = jobDescElement.text

    def generateHeadline(self):
        mygpt = myGPT2("headline_prompts2.txt", self.JobDescriptionText)

        doAgain = True
        attempts = 0
        while doAgain and attempts < self.GENERATION_REDO_LIMIT:
            attempts += 1
            # [-1], not [1]: doCheckNots now gives up and returns a reply
            # that may be missing "The headline is:" rather than retrying
            # forever, and [1] on that reply was an IndexError.
            self.headline = mygpt.sendAll().split("The headline is:")[-1].strip().strip(".")
            doAgain = mygpt.need_redo

    @staticmethod
    def stripDashes(text):
        """Remove em and en dashes from generated prose.

        The prompt asks for this, but asking is not enough -- models put em
        dashes back in regardless, and it is the single most recognisable tell
        that a passage was machine-written. So it is enforced on the way out as
        well as requested on the way in.

        A dash between words becomes a comma; a dash used as a range separator
        between digits ("2019-2025") becomes a hyphen, since a comma there would
        be wrong.
        """
        if not text:
            return text
        out = str(text)
        # Ranges first, so "2019 – 2025" does not turn into "2019, 2025".
        out = re.sub(r"(?<=\d)\s*[–—]\s*(?=\d)", "-", out)
        # Everything else reads as a comma.
        out = re.sub(r"\s*[–—]\s*", ", ", out)
        # Tidy what that can leave behind.
        out = re.sub(r",\s*,", ",", out)
        out = re.sub(r"\s+,", ",", out)
        out = re.sub(r",(\s*[.!?;:])", r"\1", out)
        return out

    # Phrases that mark text as machine-written. Listed explicitly because
    # "sound natural" on its own does nothing -- models produce these anyway.
    AI_TELLS = (
        "I am excited to", "I am thrilled", "passionate about", "proven track record",
        "leverage", "seamlessly", "dynamic environment", "fast-paced environment",
        "wealth of experience", "I am confident that my skills", "delve", "testament to",
        "spearheaded", "in today's", "ever-evolving", "landscape", "robust",
        "meticulous", "synergy", "utilize", "furthermore", "moreover",
    )

    def realExperienceBlock(self):
        """The applicant's actual jobs, written out for the question prompts.

        Free-text screener answers were being invented wholesale. One described
        a 14-week NetSuite/Salesforce/Databricks programme with a named team and
        a budget -- none of which appears anywhere in this applicant's history.
        The prompt had the life summary but never the WORK history, and never
        asked for the answer to be built out of either, so the model filled the
        gap with a plausible fiction. On a job application that is a lie with
        the applicant's name on it.
        """
        lines = []
        for job in self.jobs:
            title, comp, kind, where, current, frm, to, _country, desc = tuple(job.values())
            ends = "Present" if "y" in str(current).lower() else str(to or "")
            when = f"{frm} to {ends}".strip(" to ")
            head = " | ".join(str(p).strip() for p in (title, comp, kind, where, when)
                              if str(p or "").strip())
            if head:
                lines.append(head)
            for line in str(desc or "").splitlines():
                if line.strip():
                    lines.append("    " + line.strip().lstrip("-* ").strip())
        return "\n".join(lines) if lines else "(no work history on file)"

    def styleGuide(self):
        """The writing rules every generated passage gets, in one place.

        Everything the bot produced went out in the model's default register,
        which reads as machine-written at a glance. Two things fix that: telling
        it plainly what not to do, and giving it a sample of how the applicant
        actually writes so it has something real to imitate.
        """
        rules = [
            "HOW TO WRITE THIS -- follow every rule:",
            "1. Never use an em dash or an en dash. Not one, anywhere. Use a comma, "
            "a full stop, or a colon instead. This matters more than any other rule here.",
            "2. Do not use any of these words or phrases: "
            + ", ".join(f'"{tell}"' for tell in self.AI_TELLS) + ".",
            "3. Be specific. Name the actual project, tool, number or result. A sentence "
            "that would fit any applicant for any job is a wasted sentence, so cut it.",
            "4. Vary your sentence length, and do not start two sentences in a row the "
            "same way. Short sentences are good.",
            "5. Do not end a paragraph with a sentence that restates the paragraph.",
            "6. Write like a person talking about work they actually did, not like a "
            "brochure about themselves.",
        ]

        sample = (self.writingSample or "").strip()
        if sample:
            rules.append(
                "7. Below is a passage the applicant wrote themselves. Match its voice: "
                "sentence length and rhythm, how formal or plain it is, the kind of words "
                "they reach for, whether they use contractions. Do not copy its content or "
                "quote it, and do not mention it. Imitate how it sounds.\n"
                "--- BEGIN WRITING SAMPLE ---\n" + sample + "\n--- END WRITING SAMPLE ---")
        else:
            rules.append(
                "7. No writing sample was provided, so keep the tone plain and direct "
                "and avoid anything that sounds like marketing copy.")
        return "\n".join(rules)

    def generateCL(self):
        # A fresh application gets a fresh budget for trying to add this
        # cover letter -- otherwise a prior job that exhausted its 5 attempts
        # would leave this one unable to try at all.
        self._addDocsAttempts = 0

        '''mygpt = myGPT("cover_letter_prompts.txt", self.jobTitle, self.companyName,
                      self.JobDescriptionText, self.firstName, self.lastName,
                      self.lifeSummary, self.firstName, self.lastName, self.phone_num,
                      self.email, self.cityState, self.today() )
        self.coverLetter = mygpt.sendAll()'''

        # 13th argument is the style guide, which the prompt file consumes as
        # its last placeholder. Placeholders are filled strictly in file order
        # (myGPT2.setAllPlaceVals pops them off the front), so the count here
        # and the count in the file have to stay in step.
        mygpt = myGPT2("cover_letter_prompts2.txt", self.jobTitle, self.companyName,
                       self.JobDescriptionText, self.firstName, self.lastName,
                       self.lifeSummary, self.firstName, self.lastName, self.phone_num,
                       self.email, self.areaSpec, self.today(), self.styleGuide())

        doAgain = True
        attempts = 0
        while doAgain and attempts < self.GENERATION_REDO_LIMIT:
            attempts += 1
            self.coverLetter = self.stripDashes(mygpt.sendAll())
            doAgain = mygpt.need_redo


    def generateSummary(self):
        '''mygpt = myGPT("summary_prompts.txt", self.coverLetter, self.firstName)
        self.resumeSummary = mygpt.sendAll()'''

        # The cover letter stays the source of SCOPE: it has already been
        # filtered down to the projects this particular job cares about, and
        # handing the summary the raw life details would let it reintroduce the
        # ones the letter correctly dropped. The life details go in only as a
        # reference for concrete detail where the letter was vague; the prompt
        # forbids adding any topic the letter left out.
        # (firstName was passed before and never consumed; the only placeholder
        # that used it is commented out in the prompt file.)
        mygpt = myGPT2("summary_prompts2.txt", self.coverLetter, self.lifeSummary,
                       self.styleGuide())

        doAgain = True
        attempts = 0
        while doAgain and attempts < self.GENERATION_REDO_LIMIT:
            attempts += 1
            self.resumeSummary = self.stripDashes(mygpt.sendAll())
            doAgain = mygpt.need_redo

    def generateSkills(self):
        '''mygpt = myGPT("skills_prompts.txt", self.JobDescriptionText, self.lifeSummary)
        skillsStrList = mygpt.sendAll()
        self.skills2 = skillsStrList.split(",")'''

        # initial skill list generation
        mygpt = myGPT2("skills_prompts2.txt", self.jobTitle, self.JobDescriptionText, self.lifeSummary)

        doAgain = True
        attempts = 0
        while doAgain and attempts < self.GENERATION_REDO_LIMIT:
            attempts += 1
            skillsStrList2 = mygpt.sendAll()
            doAgain = mygpt.need_redo

        firstTry = skillsStrList2
        skillsStrList2 = skillsStrList2.split("END_LIST")[0].strip().strip(";;")
        skillsStrList2 = skillsStrList2.replace("Here is the combined list:", "").strip().strip(".")
        intermediate_skills = skillsStrList2.split(";;")


        # skill list cleaning
        mygpt = myGPT2("skills_prompts_cleaning.txt", self.jobTitle, str(intermediate_skills), version=1)
        skillsStrList2 = mygpt.sendAll()
        secTry = skillsStrList2
        skillsStrList2 = skillsStrList2.split("END_LIST")[0].strip().strip(";;")
        skillsStrList2 = skillsStrList2.replace("Here is the revised list:", "").strip().strip(".").strip("\"").strip()
        self.skills = skillsStrList2.split(";;")
        self.tries.append({"1":firstTry, "2":secTry})

    def run(self):
        self.start_up()

        input("Press enter when you have signed in.")

        #for each page, process the job openings
        self.process_job_openings()


class StateMachine:
    def __init__(self, helper : PlaywrightWrap, control=None ):
        self.helper = helper
        self.control = control if control is not None else RunControl(getattr(helper, "user_id", "unknown"))
        # Set when the bot pauses itself (currently only for a bot check), as
        # opposed to being paused from the Run tab.
        self.selfPaused = False
        self.validate_files("States.txt", "ExpectedEnvironments.txt", "StateTransitions.txt")
        self.states = self.load_states("States.txt")
        self.expected_environments = self.load_environments("ExpectedEnvironments.txt")
        self.transitions = self.load_transitions("StateTransitions.txt")
        self.current_state = self.states[0]
        self.prev_state = None


    def validate_files(self, states_file, expected_environments_file, state_transitions_file):
        # Helper function to read and clean lines from a file
        def read_clean_lines(filename, dirty=False):
            with open(filename, 'r') as f:
                lines = f.readlines()
            if dirty:
                return [line for line in lines if line.strip() and not line.strip().startswith("//")]
            return [line.strip() for line in lines if line.strip() and not line.strip().startswith("//")]

        # Read and clean lines from each file
        states = set(read_clean_lines(self.helper.configPath + states_file))
        expected_environments = set(read_clean_lines(self.helper.configPath + expected_environments_file))
        state_transitions_lines = read_clean_lines(self.helper.configPath + state_transitions_file, dirty=True)

        # Extract states and environments from state_transitions_lines
        state_transitions_states = set()
        state_transitions_environments = set()
        transFuncsMentioned = set()
        helpersAttributes = set(dir(self.helper))
        for line in state_transitions_lines:
            if "--" in line:
                line = line.replace("-->", "--")
                state1, func, state2 = line.split("--")
                transFuncsMentioned.add(func.strip().replace("()", ""))
                if 'default' not in state1:
                    state_transitions_states.add(state1.strip())
                state_transitions_states.add(state2.strip())
            elif line == line.lstrip():  # Lines without leading blanks are environments
                state_transitions_environments.add(line.strip())
            else:  # Indented lines without '--' are states
                state_transitions_states.add(line.strip())

        # Perform the checks
        missing_states_in_transitions = states - state_transitions_states
        extra_states_in_transitions = state_transitions_states - states - set(["default"])
        missing_environments_in_transitions = expected_environments - state_transitions_environments
        extra_environments_in_transitions = state_transitions_environments - expected_environments

        funcsNotDefined = transFuncsMentioned - helpersAttributes

        sep = '\n\t'
        problems = []
        if missing_states_in_transitions:
            problems.append(f"States missing in {state_transitions_file}:{sep}{sep.join(missing_states_in_transitions)}")
        if extra_states_in_transitions:
            problems.append(
                f"Extra states in {state_transitions_file} not found in {states_file}:{sep}{sep.join(extra_states_in_transitions)}")
        if missing_environments_in_transitions:
            problems.append(f"Environments missing in {state_transitions_file}:{sep}{sep.join(missing_environments_in_transitions)}")
        if extra_environments_in_transitions:
            problems.append(
                f"Extra environments in {state_transitions_file} not found in {expected_environments_file}:{sep}{sep.join(extra_environments_in_transitions)}")
        if funcsNotDefined:
            problems.append(
                f"Transition Functions mentioned in {state_transitions_file} but not defined in Helper:{sep}{sep.join(funcsNotDefined)}")

        if problems:
            # This used to be sys.exit(). RunUser runs on a worker thread, and
            # SystemExit derives from BaseException, so `except Exception` never
            # saw it: the thread died silently, the unflushed print()s above went
            # with it, and the process sat there looking idle. A normal exception
            # gets caught, logged, and surfaced in the Run tab instead.
            summary = "\n".join(problems)
            for line in summary.splitlines():
                print(line, flush=True)
            raise ConfigMismatch(
                f"{self.helper.configPath} files disagree with each other:\n{summary}"
            )

    def load_states(self, filename):
        with open(self.helper.configPath + filename, "r") as f:
            return [line.strip() for line in f.readlines()  if line[:2] != "//" and len(line.strip()) > 0]

    def load_environments(self, filename):
        with open(self.helper.configPath + filename, "r") as f:
            return [self.helper.escape_regex_special_chars(line.strip()) for line in f.readlines() if line[:2] != "//" and len(line.strip()) > 0 ]

    def load_transitions(self, filename):
        transitions = {}
        with open(self.helper.configPath + filename, "r") as f:
            lines = f.readlines()
            env = None
            pending_states = []  # List to store states that are waiting for transition info
            for line in lines:
                line = line.strip()
                prepped_line = self.helper.escape_regex_special_chars(line)
                if line[:2] == "//" or len(line) == 0:
                    # Skip empty lines and commented out lines
                    continue
                if prepped_line in self.expected_environments:
                    env = prepped_line
                    pending_states = []  # Reset pending states for a new environment
                elif "--" not in line:
                    # This line contains only a state without transition info
                    pending_states.append(line)
                else:
                    state, func, next_state = line.split("--")
                    state = state.strip()
                    func = func.strip("() ")
                    next_state = next_state.strip("-> ")
                    if env not in transitions:
                        transitions[env] = {}
                    # Apply the transition to the current state
                    transitions[env][state] = (func, next_state)
                    # Apply the transition to all pending states
                    for pending_state in pending_states:
                        transitions[env][pending_state] = (func, next_state)
                    # Clear the list of pending states
                    pending_states = []
        return transitions

    def envIsValid(self, environment):
        for pattern in sorted(self.expected_environments, key=len, reverse=True):
            if re.match(pattern.lower(), environment.lower()):
                return pattern
        #equivalent:
        #return next( (pattern for pattern in sorted(self.expected_environments, key=len, reverse=True)
        #            if re.match(pattern.lower(), environment.lower()) ) , None )
        return None

    def envNextTrans(self, environment):
        #here next is taking in 2 args: 1) a generator and 2) a defualt value for gen if empty
        return next( (pattern for pattern in sorted(self.transitions.keys(), key=len, reverse=True)
                    if re.match(pattern.lower(), environment.lower()) ) , None )


    def transition(self, environment):
        t.sleep(1)
        envPattern = self.envIsValid(environment)
        if not envPattern:
            self.handleUnknownEnvironment(environment)
            return

        next_state = None
        #checking that the transition file as made properly
        if self.envNextTrans(environment) is not None:
            funcName = None
            if self.current_state in self.transitions[envPattern]:
                funcName, next_state = self.transitions[envPattern][self.current_state]
            elif "default" in self.transitions[envPattern]:
                funcName, next_state = self.transitions[envPattern]["default"]
            else:
                # No rule for this state on this page, and no default. next_state
                # is still None here, so the old code went straight into
                # None.strip() -- an AttributeError that reached RunUser and
                # restarted the browser. This is a config gap, not a crash.
                self.handleStuck(
                    f"no rule for state '{self.current_state}' on this page", environment,
                    f"config/StateTransitions.txt has no transition for state "
                    f"'{self.current_state}' on this page, and no default. Add one, or move "
                    f"the page along by hand and press Start applying.")
                return

            if "default" == next_state.strip():
                next_state = self.current_state

            self.helper.reportAction(f"Calling function: {funcName}() in environment: {environment}", False)
            url, _, title = environment.partition("|")
            ct_section("PAGE", f"{funcName}()  (from state {self.current_state})", url, f'"{title}"')
            try:
                funcResult = self.executeFunc(funcName)
            except NeedsHumanError as exc:
                self.handleStuck(f"{funcName}() could not continue", environment, str(exc))
                return
            # need to check that we accomplished what we wanted to accomplish with this function
            if isinstance(funcResult, StartFromTop):
                self.helper.reportAction(f"Transitioning  STATE from {self.current_state} BACK TO {self.prev_state}", False)
                self.current_state = self.prev_state
            elif not isinstance(funcResult, ElementClickInterceptedException):
                self.helper.reportAction(f"Transitioning  STATE from {self.current_state} to {next_state}", False)
                self.prev_state = self.current_state
                self.current_state = next_state
            else:
                self.helper.reportAction(f"Not Transitioning  STATE from {self.current_state} to {next_state} because function failed somewhere.  Remaining in state to try again")

        else:
            # The page matched ExpectedEnvironments but StateTransitions has no
            # rule for it. This used to call waitForever() -- an unbreakable
            # `while True: sleep(1)` that parked the run silently. Pause and
            # beep instead, the same as any other page we cannot get past.
            self.handleStuck(
                "no transition rule for this page", environment,
                "This page is listed in config/ExpectedEnvironments.txt but has no matching "
                "block in config/StateTransitions.txt, so there is nothing to do here. Add "
                "one, or move the page along by hand and press Start applying.")

    def executeFunc(self, funcName):
        # Get the method reference based on the string name
        method_to_call = getattr(self.helper, funcName)

        # Call the method
        return method_to_call()

    # How long an unrecognised page gets to turn into a recognised one before
    # the run gives up on it. Pages often report a transitional title while
    # still loading, so a short grace period avoids false alarms. The
    # AI-tailored-resume redirect (smartapply.indeed.com -> profile.indeed.com)
    # is the slow case that set this: its URL settles in ~2s but the SPA can
    # take well over 20s to render a real <title>, which used to blow through
    # the old grace period every time.
    UNKNOWN_ENV_GRACE = 40

    def handleUnknownEnvironment(self, environment):
        """Deal with a page no configured pattern matches.

        This used to call waitForever() -- an unbounded `while True: sleep(1)`.
        The run sat there indefinitely looking alive while doing nothing, which
        is what cost a 13 minute stall.

        Now it waits briefly in case the page is merely still loading, and then
        pauses and beeps for a human, the same as a bot check. Pausing beats
        restarting here: an unrecognised page needs someone to look at it (and
        usually to save the HTML), and restarting would throw away the
        part-finished application.

        If it turns out to just be slow rather than actually wrong, nobody was
        needed at all, so `pauseAndAlert` is told to resume on its own once it
        recognises the page (see `resumeWhenResolved` below) instead of sitting
        there having already solved itself, waiting for a human with no reason
        to come.
        """
        ct_print("StateMachine", "UNKNOWN PAGE", environment[:110])

        # Pages often report a transitional title while still loading, so give
        # it a moment before raising the alarm.
        deadline = t.time() + self.UNKNOWN_ENV_GRACE
        while t.time() < deadline:
            t.sleep(2)
            current = self.helper.getCurrentEnv(quiet=True)
            if self.envIsValid(current):
                ct_print("StateMachine", "page settled into a known one", current[:90])
                return
            if self.isInterstitial(current):
                self.waitOutInterstitial()
                return

        # Don't nag repeatedly about a page already waved through by hand.
        if self.attentionWaived(environment):
            t.sleep(5)
            return

        resolved = self.pauseAndAlert(
            reason="UNKNOWN PAGE",
            isResolved=lambda env: self.envIsValid(env) is not None or self.isInterstitial(env),
            message=(f"This page does not match any configured pattern, so the bot does not "
                     f"know what to do with it. Paused.\n  {environment}\n"
                     f"Save the page's HTML if you want it handled, then add an entry to "
                     f"config/ExpectedEnvironments.txt and config/StateTransitions.txt."),
            clearedMessage="The page settled into a recognised one on its own; continuing "
                           "without waiting for Start applying.",
            resumeWhenResolved=True,
        )
        if not resolved:
            # Resumed by hand while still on the unknown page.
            self.waiveAttention(environment)

    # How long "I already told you to carry on" stays in force. It has to
    # expire: several pages in the flow share one url|title (every job's review
    # page is the same environment string), so a permanent waiver would silence
    # the alarm for every later job too.
    ATTENTION_WAIVER_TTL = 5 * 60

    def waiveAttention(self, environment):
        self._attentionWaivedFor = (environment, t.time())

    def attentionWaived(self, environment):
        waived = getattr(self, "_attentionWaivedFor", None)
        if not waived or waived[0] != environment:
            return False
        if t.time() - waived[1] > self.ATTENTION_WAIVER_TTL:
            self._attentionWaivedFor = None
            return False
        return True

    @staticmethod
    def pageIdentity(environment):
        """Which page this is, ignoring the query string.

        An environment is "<url>|<title>", and Indeed rewrites query strings
        underneath us without navigating anywhere: the resume editor silently
        drops its `continue=` parameter. Comparing whole environment strings
        therefore reports a page change when nothing has changed at all.
        """
        url, _, title = str(environment or "").partition("|")
        return f"{url.split('?', 1)[0].rstrip('/')}|{title.strip()}"

    def handleStuck(self, reason, environment, message):
        """Pause and beep when the bot cannot get past a page it does recognise.

        The counterpart to handleUnknownEnvironment: there the page is a
        mystery, here the page is known but a control the bot needs is missing
        (or the config has no rule for the state it is in). Both need a person,
        and neither is helped by restarting -- restarting closes the browser and
        loses the part-finished application, then hits the same wall again.

        Cleared when the page changes, which covers the human clicking the
        control themselves.
        """
        ct_print("StateMachine", "STUCK", f"{reason} -- {environment[:90]}")

        # Already waved through: stay quiet and keep re-reading the page, so the
        # moment the human clicks the control themselves the run picks up.
        if self.attentionWaived(environment):
            t.sleep(5)
            return

        # "The page changed" has to mean a DIFFERENT PAGE, not a different URL.
        # Comparing the raw environment string counted the query string, and the
        # resume editor drops its `continue=` parameter on its own. One run
        # paused, decided 1.3 seconds later that the page had moved on because
        # /resume?co=US&hl=en_US&continue=... had become /resume, and cleared an
        # alarm about a work-experience entry that was still sitting there.
        here = self.pageIdentity(environment)
        resolved = self.pauseAndAlert(
            reason=f"STUCK: {reason}",
            isResolved=lambda env: self.pageIdentity(env) != here,
            # Nobody had to be fetched for this one: the page moved on by
            # itself, so carry on rather than waiting to be released by hand.
            resumeWhenResolved=True,
            message=f"{message}\n  {environment}",
            clearedMessage="The page moved on. Press Start applying to continue.",
        )
        if not resolved:
            # Waved through by hand while still on the same page. Don't nag
            # about it again, and let the next loop re-read the page.
            self.waiveAttention(environment)

    # waitForever() is gone. Every place that parked the run in an unbreakable
    # `while True: sleep(1)` now pauses through pauseAndAlert, which beeps, says
    # why, and can be released from the Run tab.


    def handleCommand(self, command):
        """Run a one-shot command sent from the GUI."""
        if command == "home":
            self.helper.goHome()
            # Starting over from the search page means the previous state no
            # longer describes where we are.
            self.current_state = self.states[0]
            self.prev_state = None
            ct_print("StateMachine", "went home", f"state reset to {self.current_state}")
        else:
            ct_print("StateMachine", "ignoring unknown command", str(command))

    def waitWhilePaused(self):
        """Block until the GUI switches this run to 'running'.

        Commands still run while paused, so "Go to home" works without having
        to start applying first.

        `selfPaused` is set when the bot pauses itself (a bot check). Clicking
        Start applying is what acknowledges it -- that keeps working standalone,
        where there is no GUI to write the control file.
        """
        if not hasattr(self, "selfPaused"):
            self.selfPaused = False

        announced = False
        while self.control.mode() == "paused" or self.selfPaused:
            command = self.control.pending_command()
            if command:
                self.handleCommand(command)
                continue
            if self.selfPaused and self.control.mode() == "running":
                self.selfPaused = False
                break
            if not announced:
                ct_print("StateMachine", "PAUSED", "waiting for a command from the Run tab")
                announced = True
            t.sleep(1)
        if announced:
            ct_print("StateMachine", "RESUMED")

    # Titles Indeed shows while a bot check is in front of the real page.
    INTERSTITIAL_MARKERS = (
        "just a moment",
        "checking your browser",
        "verifying you are human",
        "attention required",
    )
    # Alert cadence while a bot check is on screen: every 5s for the first 30s,
    # then every 30s. Frequent enough to catch you at the desk, sparse enough to
    # live with if you have stepped away.
    BEEP_FAST_INTERVAL = 5
    BEEP_FAST_WINDOW = 30
    BEEP_SLOW_INTERVAL = 30
    BEEP_GIVE_UP_AFTER = 30 * 60      # stop the noise eventually; stay paused

    def isInterstitial(self, environment):
        title = environment.split("|", 1)[-1].strip().lower()
        return any(marker in title for marker in self.INTERSTITIAL_MARKERS)

    def beep(self):
        """One audible alert. Never allowed to break the run."""
        _beep()

    def pauseAndAlert(self, reason, isResolved, message, clearedMessage,
                      resumeWhenResolved=False):
        """Stop the run and call for a human, until the situation resolves.

        Used for anything the bot cannot get past on its own -- a bot check, or
        a page no configured pattern matches. Both need someone to look at the
        browser, so both stop rather than guessing or restarting (restarting
        would throw away the part-finished application).

        Beeps every 5s for the first 30s, then every 30s, going quiet after
        BEEP_GIVE_UP_AFTER while staying paused.

        `isResolved(env)` decides when the situation has cleared.
        """
        # The runner watches for this marker and pauses the run, which keeps the
        # GUI the only writer of the control file. selfPaused covers the
        # standalone case, where nothing is watching stdout.
        self.selfPaused = True
        ct_print("StateMachine", "NEEDS ATTENTION", f"{reason} -- pausing and alerting")
        self.helper.reportAction(message, False)

        started = t.time()
        nextBeep = 0.0
        # The mode is 'running' right now -- that is why the bot was working when
        # this came up. So only a NEW instruction counts as "carry on anyway".
        seqAtStart = self.control.seq()
        while True:
            now = t.time()
            elapsed = now - started

            if now >= nextBeep:
                if elapsed <= self.BEEP_GIVE_UP_AFTER:
                    self.beep()
                    interval = (self.BEEP_FAST_INTERVAL if elapsed < self.BEEP_FAST_WINDOW
                                else self.BEEP_SLOW_INTERVAL)
                    nextBeep = now + interval
                elif nextBeep:
                    ct_print("StateMachine", f"{reason} still unresolved",
                             f"quiet after {self.BEEP_GIVE_UP_AFTER // 60} min; still paused")
                    nextBeep = 0.0   # stop announcing, stay paused

            # Poll in short slices so Start applying stays responsive rather
            # than waiting out a beep interval.
            t.sleep(1)
            env = self.helper.getCurrentEnv(quiet=True)
            if isResolved(env):
                ct_print("StateMachine", "ATTENTION CLEARED", f"{reason}: {env[:80]}")
                self.helper.reportAction(clearedMessage, False)
                # A bot check stays paused on purpose: a person was at the
                # keyboard solving it, and pressing Start applying is how they
                # say they are done looking. A situation that resolved WITHOUT
                # anyone being needed is different -- staying paused there means
                # announcing "ATTENTION CLEARED" and then sitting still, waiting
                # for a human who has no reason to come.
                if resumeWhenResolved:
                    self.selfPaused = False
                return True
            if self.control.seq() != seqAtStart and self.control.mode() == "running":
                # Start applying pressed while it is still unresolved: a
                # deliberate call, so stop nagging and let the run proceed.
                ct_print("StateMachine", "ATTENTION overridden", f"{reason}: resumed by hand")
                self.selfPaused = False
                return False

    def waitOutInterstitial(self):
        """Pause and alert when Indeed puts up a bot check.

        This runs before pattern matching on purpose. envIsValid picks the
        LONGEST matching pattern, and the generic ".../jobs?q...|..." entry is
        longer than the "|Just a moment..." one, so the config's own rule never
        fired: the bot saw zero job cards and jumped to the next page, silently
        skipping everything on the current one.
        """
        return self.pauseAndAlert(
            reason="BOT CHECK",
            isResolved=lambda env: not self.isInterstitial(env),
            message=("Indeed is showing a bot check. Paused. Solve it in the browser "
                     "window, then press Start applying."),
            clearedMessage="Bot check cleared. Press Start applying to continue.",
        )

    def run(self):
        while True:
            self.waitWhilePaused()

            command = self.control.pending_command()
            if command:
                self.handleCommand(command)
                continue

            env = self.helper.getCurrentEnv()
            if env == "exit":
                break
            if self.isInterstitial(env):
                self.waitOutInterstitial()
                continue
            self.transition(env)

def loadUsersFromDB(userIds=None):
    """Load runnable users.

    With no argument this returns every user flagged Active with applications
    left -- the standalone behaviour. When the GUI launches a run it passes the
    explicit ids it selected instead, so the child process runs exactly who it
    was told to and cannot be affected by a later edit to the Active column.
    """
    conn = sqlite3.connect('IndHelperDB.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if userIds:
        placeholders = ",".join("?" for _ in userIds)
        cursor.execute(f"SELECT * FROM users WHERE id IN ({placeholders})", tuple(userIds))
    else:
        cursor.execute("""SELECT * FROM users WHERE AppsLeft > ? AND Active = ?""", (0, "T"))
    allRecords = cursor.fetchall()

    user_data = []

    for record in allRecords:
        userID = record["id"]

        # Task 1: Get all the records from the Job table that have the same userID
        job_query = """SELECT * FROM Job WHERE userID = ?"""
        cursor.execute(job_query, (userID,))
        job_records = cursor.fetchall()

        # Task 2: Get all the records from the Edu table that have the same userID
        edu_query = """SELECT * FROM Edu WHERE userID = ?"""
        cursor.execute(edu_query, (userID,))
        edu_records = cursor.fetchall()

        # Task 3: Get this user's job searches, in run order. `position` decides
        # which search the bot starts on, so the ORDER BY is load-bearing.
        search_query = """SELECT * FROM job_searches WHERE user_id = ? ORDER BY position"""
        cursor.execute(search_query, (userID,))
        search_records = cursor.fetchall()

        # Task 4: Construct the data structure
        user_data.append({"mainInfo":record, "edus":edu_records, "jobs":job_records,
                          "searches":search_records})

    conn.close()
    return user_data


# =====================================================================================
#  Resilient top-level run loop.
#
#  main.py's version of this wrapped everything in "except: pass" with no sleep, so a
#  startup failure (e.g. two copies fighting over the same Chrome profile) span an
#  invisible, silent, CPU-pegging infinite retry loop -- nothing printed, nothing
#  logged, no backoff. This version classifies every failure, always prints it live
#  (ct_error), and backs off between restarts instead of hot-looping.
# =====================================================================================

RESTART_BACKOFF_SECONDS = 15


def RunUser(user_to_run, masterRecords):
    user_label = f"{user_to_run['mainInfo']['FirstName']} {user_to_run['mainInfo']['LastName']} (id={user_to_run['mainInfo']['id']})"
    consecutive_failures = 0
    while True:
        sm = None
        try:
            ct_enter("RunUser", user_label)
            sm = StateMachine(IndeedHelper(user_to_run, masterRecords["milestoneList"]))
            masterRecords["sm_ref"] = sm
            # start_up() has opened the browser on the home page and stopped
            # there; sm.run() begins paused and waits for the Run tab.
            ct_print("RunUser", "READY", f"{user_label} is on the home page and paused")
            sm.run()
            ct_exit("RunUser", f"{user_label} reached 'exit' environment, stopping cleanly")
            return
        except Exception as exc:
            consecutive_failures += 1
            ct_error("RunUser", exc)
            traceback.print_exc()
            if sm is not None:
                try:
                    sm.helper.reportAction(f"An error occurred: {exc}", False)
                except Exception as report_exc:
                    ct_error("RunUser (reportAction)", report_exc)
            if sm is not None:
                try:
                    sm.helper.close()
                except Exception as close_exc:
                    ct_error("RunUser (close)", close_exc)
            backoff = min(RESTART_BACKOFF_SECONDS * consecutive_failures, 300)
            ct_print("RunUser", f"restarting {user_label} in {backoff}s", f"consecutive_failures={consecutive_failures}")
            t.sleep(backoff)
        except BaseException as exc:
            # SystemExit and friends do not derive from Exception, so without
            # this a `sys.exit()` anywhere below would end this thread in total
            # silence while the process kept running. Log it, then let it end.
            ct_error(f"RunUser FATAL ({type(exc).__name__})", exc)
            traceback.print_exc()
            sys.stdout.flush()
            raise


def ReportStall(id):
    engine = pyttsx3.init()
    engine.setProperty('rate', 150)
    engine.setProperty('volume', 1)
    engine.say(f"Yoooooo bro id {id} is stalled")
    engine.runAndWait()


if __name__ == "__main__":
    # --user-id N may be repeated; the GUI spawns one process per selected user
    # so that a crash or a hung browser can only take down that one user.
    requestedIds = []
    for index, arg in enumerate(sys.argv):
        if arg == "--user-id" and index + 1 < len(sys.argv):
            requestedIds.append(int(sys.argv[index + 1]))

    usersToStart = list(loadUsersFromDB(requestedIds or None))

    if not usersToStart:
        ct_print("__main__", "no users to run",
                 f"requested={requestedIds}" if requestedIds
                 else "nothing is marked Active with applications left")
        raise SystemExit(1)

    threads = []
    usr_records = {}

    for user in usersToStart:
        usr_records[user["mainInfo"]["id"]] = {"milestoneList": [datetime.datetime.now()], "sm_ref": None}
        thread = Thread(target=RunUser, args=(user, usr_records[user["mainInfo"]["id"]]), daemon=True)
        thread.start()
        threads.append(thread)
        ct_print("__main__", f"started worker thread for user id={user['mainInfo']['id']}")

    while True:
        t.sleep(60)
        try:
            for id, rec in usr_records.items():
                lastMilestone = rec["milestoneList"][-1]
                now = datetime.datetime.now()
                if (now - lastMilestone).seconds > 60 * 15:
                    # Deliberately does NOT touch the browser. Playwright's sync
                    # objects belong to the greenlet on the worker thread, so
                    # calling helper.close() from here raised "Cannot switch to a
                    # different thread" and recovered nothing. Report it and let
                    # the worker's own error handling restart the run; the Run
                    # tab surfaces this so it can be stopped by hand.
                    ct_print("__main__", f"user id={id} has made no progress in 15 minutes",
                             "the run may be stuck; stop and restart it from the Run tab "
                             "if it does not recover on its own")
                    rec["milestoneList"].append(datetime.datetime.now())
        except Exception:
            ct_error("__main__ (monitor loop)", sys.exc_info()[1])
            traceback.print_exc()
