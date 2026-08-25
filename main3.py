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

log = None


# =====================================================================================
#  console_trace  --  ported from birdcatcher_py/console_trace.py
#  Always prints (flush=True), so progress/errors are visible live in the
#  terminal instead of silently going only to a log file, which is what made
#  main.py's failures invisible.
# =====================================================================================

_last_print_time = 0.0


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
    print(f"[CT] {elapsed:7.1f}ms | {where} | {what}{suffix}", flush=True)


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

        if element is not None:
            elementXpath = self.generate_full_xpath(element)
            findFrom = None

        url_at_start = self._page.url
        start_time = t.time()
        deadline = start_time + timeLimit
        attempt = 0

        while True:
            attempt += 1
            try:
                matches = self._resolve_matches(elementXpath, findFrom)

                if indInList == self.ALL:
                    self.reportAction(f"returning {len(matches)} matches for {elementXpath}!")
                    ct_exit("smartClick", f"{len(matches)} matches (ALL)")
                    return matches

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

                if checkNewPage:
                    self._wait_until(lambda: self._page.url != url_at_start, max(deadline - t.time(), .5))

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
        dialogBox = self.findAndClick(self.WHOLE, self.WHOLE, '//*[@role="dialog" and @aria-modal="true"]',
                                      txtCond="#$%^&*", timeLimit=.4)
        try:
            if dialogBox is not None:
                possCloseButs = dialogBox.find_elements(By.TAG_NAME, 'button')
                for button in possCloseButs:
                    infoLabel = (button.get_attribute("aria-label") or "").lower()
                    if 'close' in infoLabel:
                        self.smartClick(element=button)
                        self.reportAction("Closed Dialog")
                        return
        except PlaywrightError as exc:
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
        try:
            if element.tag_name == "html":
                return "/html"
        except PlaywrightError as exc:
            ct_error("generate_full_xpath", exc)

        siblings = element.find_elements('xpath', "./preceding-sibling::" + element.tag_name)
        index = len(siblings) + 1
        parent_xpath = self.generate_full_xpath(element.find_elements('xpath', "./..")[0])
        return f"{parent_xpath}/{element.tag_name}[{index}]"

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
        self.fillMoveOn(element, fillContent)
        return element

    def findFillEnter(self, what, type, elementXpath, fillContent, indInList=0):
        element = self.findAndClick(what, type, elementXpath, indInList)
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(fillContent)
        element.send_keys(Keys.ENTER)
        return element

    def fillMoveOn(self, element, fillContent, step=20):
        try:
            element.send_keys(Keys.CONTROL, "a")
            i = 0
            while i < len(fillContent):
                end = i + step
                while (end - 1) < len(fillContent) and fillContent[end - 1] == ' ':
                    end += 1
                element.send_keys(fillContent[i:end])
                element.send_keys(Keys.END)
                i = end
            element.send_keys(Keys.TAB)
        except PlaywrightError as exc:
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

    def getCurrentEnv(self):
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
            ct_wait("getCurrentEnv", "page title to load")
            t.sleep(1)
        currentEnv = f"{url}|{title}"
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
    def startApplication(self):
        # click on the Apply Now button if it is there
        if self.findAndClick(self.TXT, self.MATCH, 'Applied', txtCond="asdfdasf") is not None:
            return self.backToStart()

        return  self.findAndClick(self.TXT, self.MATCH, 'Apply now', checkNewTab=True, timeLimit=3)


    def updateContactInfo(self):
        return self.handleAddInfoPage()
    def startResume(self):
        return self.chooseToBuildIndeedResume()

    def hitEditFromReviewPage(self):
        editButton = self.findClosestRelatives(self.TXT, self.MATCH, "Resume", self.TXT, self.MATCH, "Edit")[0]
        return self.smartClick(element=editButton)
    def addResume(self):
        p = self.findAndClick(self.TXT, self.MATCH, 'Continue', indInList=self.ALL)
        for element in p:
            try:
                element.click()
            except:
                pass
        return p[0]
        #return self.findAndClick(self.TXT, self.MATCH, 'Continue', travelUp=1, waitBeforeFinding=2)
    def backToDidContactInfo(self):
        pass
    def startContactInfo(self):
        return self.findAndClick(self.ID, self.CONTAINS, 'edit-contact-info', checkNewPage=True)
    def startSummary(self):
        # remove if already there
        delButs = self.findClosestRelatives( self.TXT, self.MATCH, 'Summary', self.ID, self.CONTAINS, 'delete',
                                            srchLvlLmt=2)
        if len(delButs) > 0:
            self.click_all(delButs)

        sumBut = self.findClosestRelatives(self.TXT, self.MATCH, 'Summary', self.WHOLE, self.WHOLE, self.BUTTON)[0]
        return self.smartClick(element=sumBut, waitBeforeClicking=.7, checkNewPage=True)
    def startWorkExp(self):
        return self.do_work_exp()
    def startEdu(self):
        return self.do_edu()
    def startSkills(self):
        return self.do_skiils()
    def finishResume(self):
        return self.findAndClick(self.TXT, self.MATCH,  'Continue applying', travelUp=1, waitBeforeClicking=.7, checkNewPage=True)
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
        return self.do_skiils()
    def goBackToStartSkills(self):
        pass
    def doQuestions(self):
        return self.analyzeAndAnsQuestions()
    def keepGoing(self):
        path_4_button_containing_span = "//button[span[contains(text(),'Continue')]]"
        #return self.findAndClick(self.WHOLE, self.WHOLE, path_4_button_containing_span, waitBeforeClicking=.7, checkNewPage=True)
        return self.findAndClick(self.TXT, self.MATCH, ["Continue", "Review your application", "Continue applying", "Continue to application"], waitBeforeClicking=.7,
                                 checkNewPage=True)

    def continueFromPage(self):
        return self.findAndClick(self.TXT, self.MATCH, ["Continue", "Review your application", "Submit your application"])
    def clickAddDocs(self):
        #  Find Supporting documents section and click on the add button
        try:
            addButton = self.findClosestRelatives(self.TXT, self.CONTAINS, 'Supporting documents',
                                                  self.WHOLE, self.WHOLE, "//a")[0]
        except:
            self.reportAction("Skipping the 'Add Docs' part because there doesn't seem to be a section for adding CL")
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


    def submitApp(self):

        # click the checkbox so they contact the person directly thru number too (maybe turn this off if you need to verify the leads)
        clickRes = self.findAndClick(self.WHOLE, self.WHOLE, "//input[@type='checkbox']", travelUp=1, timeLimit=1)
        if isinstance(clickRes, StartFromTop):
            return clickRes
        path_4_button_containing_span = "//button[span[contains(text(),'Submit')]]"
        sub = self.findAndClick(self.TXT, self.MATCH, "Submit your application", txtCond="asdfaf")
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", sub)
        '''captchaWrap = self.findAndClick(self.ID, self.MATCH, "captcha-wrapper", txtCond="asdfads", timeLimit = 1)
        if captchaWrap is not None:
            pyautogui.moveTo(729, 582)
            t.sleep(1)
            pyautogui.click()
            t.sleep(3)'''
        #self.findAndClick(self.WHOLE, self.WHOLE, '//*[@id="cf-turnstile"]')
        self.findAndClick(self.WHOLE, self.WHOLE, '//*[@id="captcha-wrapper"]')

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

    def process_job_openings(self):
        #  loop to go thru the different pages
        while True:
            #find the list of job openings
            openings = self.driver.find_elements(By.CSS_SELECTOR, '.css-5lfssm.eu4oa1w0')
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

                try:
                    self.smartClick(element=link, ctrl=True)
                except:
                    try:
                        self.smartClick(element=opening, ctrl=True)
                    except:
                        asdf = 1

                #  get job infos


                #rs = self.findClosestRelatives(self.CONTAINS, self.TXT, "s estimated salaries", self.CONTAINS, self.CLASS, 'CloseButton', limit=1)
                #if len(rs) == 1:
                #    self.click_all(rs)

                buttonElement = self.findAndClick(self.TXT, self.MATCH, 'Apply now',
                                                  timeLimit=5, txtCond="$%^& Dont click yet &*(")

                if buttonElement is None:
                    # means this is not a job that you can apply from Indeed site
                    self.backToStart()
                    continue

                #clear out prev Qs and As
                self.prev_questions.clear()

                # extract job info
                self.getPositionInfo()

                jobId = f"{self.companyName} {self.jobTitle}\n"
                f = open(self.MY_PATH + "skipped.txt", 'r')
                skippedCont = f.read()
                f.close()
                if jobId in skippedCont:
                    self.backToStart()
                    continue

                # check if this is one of the positions we want to avoid
                if self.jobContainsForbiddenCharacteristics():
                    self.reportAction(f"Not proceeding with [{jobId}]... it contains characteristics this user wants to avoid", False)
                    f = open(self.MY_PATH + "skipped.txt", 'a')
                    f.write(jobId)
                    f.close()
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

    def chooseToBuildIndeedResume(self):
        resButtonPath = '//*[@id="ia-container"]/div/div[1]/div/main/div[2]/div[2]/div/div/div[1]/div/div/div[2]/div[1]/div/div[2]/span[1]'
        editButtonPath = '//*[@id="edit-Ee5RAspBhdSgNHMSFzJyZg"]'
        indResPth  = '//*[@data-testid="IndeedResumeCard"]'

        self.findAndClick(self.WHOLE, self.WHOLE, indResPth)
        #self.findAndClick(self.TXT, self.CONTAINS, 'Indeed Resume', waitBeforeClicking=1)
        editButton = self.findAndClick( self.TXT, self.CONTAINS,'Edit resume', timeLimit=1)
        return editButton

    def handleAddInfoPage(self):
        #  if We find it, We're not gonna click it.  just Wanted to knoW if it Was there
        title = self.findAndClick(self.WHOLE, self.WHOLE, self.H1, timeLimit=2, txtCond='@#%^&*()')
        if title is not None and title.text == 'Add your contact information':
            fn = self.findClosestRelatives(self.TXT, self.MATCH, 'First name', self.WHOLE, self.WHOLE, '//input')[0]
            self.fillMoveOn(fn, self.firstName)
            ln = self.findClosestRelatives(self.TXT, self.MATCH, 'Last name', self.WHOLE, self.WHOLE, '//input')[0]
            self.fillMoveOn(ln, self.lastName)
            phone = self.findClosestRelatives(self.TXT, self.MATCH, 'Phone number', self.WHOLE, self.WHOLE, '//input')[0]
            self.fillMoveOn(phone, self.phone_num)
            try:
                cS = self.findClosestRelatives(self.TXT, self.MATCH, IndeedHelper.area_specifier_text[self.country], self.WHOLE, self.WHOLE, '//input')[0]
                self.fillMoveOn(cS, self.areaSpec)
            except:
                pass
            return self.findAndClick(self.TXT, self.MATCH, "Continue", checkNewPage=True )

    def edit_contact_info(self):
        #self.findAndClick(self.CONTAINS, self.ID, 'edit-contact-info')
        fn_input = self.findClosestRelatives(self.TXT, self.MATCH, 'First name', self.WHOLE, self.WHOLE, self.INPUT)[0]
        self.smartClick(element=fn_input)
        self.smartClick(element=fn_input)
        self.fillMoveOn(fn_input, self.firstName)

        ln_input = self.findClosestRelatives(self.TXT, self.MATCH, 'Last name', self.WHOLE, self.WHOLE, self.INPUT)[0]
        self.smartClick(element=ln_input)
        self.fillMoveOn(ln_input, self.lastName)

        head_input = self.findClosestRelatives(self.TXT, self.MATCH,  'Headline', self.WHOLE, self.WHOLE, self.INPUT)[0]
        self.smartClick(element=head_input)
        self.fillMoveOn(head_input, self.headline)  # need GPT

        phone_num_input = self.findClosestRelatives(self.TXT, self.MATCH, 'Phone', self.WHOLE, self.WHOLE, self.INPUT)[0]
        self.smartClick(element=phone_num_input)
        self.fillMoveOn(phone_num_input, self.phone_num)  # need GPT

        showPhone = self.findClosestRelatives(self.ID, self.CONTAINS, 'showPhoneNumber', self.WHOLE, self.WHOLE, self.INPUT)[0]
        if showPhone.is_selected():
            self.smartClick(element=showPhone)

        chg_country_but = self.findClosestRelatives(self.TXT, self.MATCH, 'Country', self.WHOLE, self.WHOLE, self.BUTTON)[0]
        self.smartClick(element=chg_country_but)
        chg_country_drp = self.findClosestRelatives(self.TXT, self.MATCH, 'Country', self.WHOLE, self.WHOLE, self.SELECT)[0]
        self.fillDropDown(chg_country_drp, self.country)


        citystate_input = self.findClosestRelatives(self.TXT, self.CONTAINS, IndeedHelper.area_specifier_text[self.country], self.WHOLE, self.WHOLE, self.INPUT)[0]
        self.smartClick(element=citystate_input)
        self.fillMoveOn(citystate_input, self.areaSpec)  # need GPT

        zip_input = self.findClosestRelatives(self.TXT, self.CONTAINS,  'Postal code', self.WHOLE, self.WHOLE, '//input')[0]
        self.smartClick(element=zip_input)
        self.fillMoveOn(zip_input, self.zip )  # need GPT

        result = self.findAndClick( self.TXT, self.MATCH, 'Save', travelUp=1, checkNewPage=True, timeLimit=.5)

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

    def handleEdu(self, edu : dict):
        eduLvl, fieldOS, schoolName, cityState, current, fromDate, toDate, country = tuple(edu.values())
        current = "y" in current.lower()

        # education level
        self.findFillMoveOn(self.ID, self.CONTAINS, 'educationLevel', eduLvl)

        # field of study
        self.findFillMoveOn(self.ID, self.CONTAINS, 'fieldOfStudy', fieldOS)

        # school name
        self.findFillMoveOn(self.ID, self.CONTAINS, 'school', schoolName)

        #country location
        chg_country_but = self.findClosestRelatives(self.TXT, self.MATCH, 'Country', self.WHOLE, self.WHOLE, self.BUTTON)[0]
        self.smartClick(element=chg_country_but)
        chg_country_drp = self.findClosestRelatives(self.TXT, self.MATCH, 'Country', self.WHOLE, self.WHOLE, self.SELECT)[0]
        self.fillDropDown(chg_country_drp, country)

        # school location
        self.findFillMoveOn(self.ID, self.CONTAINS, 'cityState', cityState)

        # current position
        if current:
            self.findAndClick(self.ID, self.CONTAINS, 'isCurrent')

        #  drop downs
        drp_dwns = self.driver.find_elements('xpath', "//*[contains(@id, 'SelectFormField')]")
        if current:
            frmMon, frmYr = tuple(drp_dwns[-2:])
        else:
            frmMon, frmYr = tuple(drp_dwns[-4:-2])
        frmMonCont, frmYrCont = tuple(fromDate.split(" "))
        self.fillDropDown(frmMon, frmMonCont)
        self.fillDropDown(frmYr, frmYrCont)

        if not current:
            toMon, toYr = tuple(drp_dwns[-2:])
            toMonCont, toYrCont = tuple(toDate.split(" "))
            self.fillDropDown(toMon, toMonCont)
            self.fillDropDown(toYr, toYrCont)

        return self.findAndClick(self.TXT, self.MATCH, 'Save', travelUp=1, waitBeforeClicking=1, checkNewPage=True)

    def do_skiils(self):
        # delete all prior
        deletes = self.findClosestRelatives(self.TXT, self.MATCH, 'Skills', self.ID, self.CONTAINS,  'delete', srchLvlLmt=2)
        self.click_all(deletes, delayBeforeEach=.1, timeLimitForEach=1)

        for skill in self.skills:
            if "and" == skill[:3]:
                skill = skill[4:]
            if " and" == skill[:4]:
                skill = skill[5:]
            try:
                addSkillBut = self.findClosestRelatives(self.TXT, self.MATCH,  'Skills', self.WHOLE, self.WHOLE, self.BUTTON)[0]
            except:
                traceback.print_exc()
                h = 3
            self.smartClick(element=addSkillBut, waitBeforeClicking=.7, checkNewPage=True)
            self.findFillMoveOn(self.ID, self.CONTAINS, 'skillName', skill)
            possExp = self.finalizeResumeSection()
            if isinstance(possExp, ElementClickInterceptedException):
                return possExp

    def fillSkills(self):
        # generate a list of skills using chat GPT here
        for skill in self.skills:
            self.findFillEnter( self.ID, self.CONTAINS,'new-skill-form', skill)

    def do_work_exp(self):
        #delete all prior
        deletes = self.findClosestRelatives(self.TXT, self.CONTAINS, 'Work experience', self.ID, self.CONTAINS, 'delete', srchLvlLmt=2)
        self.click_all(deletes)

        for job in self.jobs:
            try:
                addWorkBut = self.findClosestRelatives(self.TXT, self.MATCH ,  'Work experience', self.WHOLE, self.WHOLE, self.BUTTON)[0]
            except:
                traceback.print_exc()
                h = 3
            self.smartClick(element=addWorkBut, waitBeforeClicking=.7, checkNewPage=True)
            possExp = self.handleJob(job)
            if isinstance(possExp, ElementClickInterceptedException):
                return possExp
    def do_edu(self):
        # delete all prior
        deletes = self.findClosestRelatives( self.TXT, self.MATCH, 'Education', self.ID, self.CONTAINS,
                                            'delete', srchLvlLmt=2)
        self.click_all(deletes)

        for edu in self.edus:
            addEduBut = self.findClosestRelatives( self.TXT, self.MATCH, 'Education', self.WHOLE, self.WHOLE, self.BUTTON)[0]
            self.smartClick(element=addEduBut, waitBeforeClicking=.7, checkNewPage=True)
            possExp = self.handleEdu(edu)
            if isinstance(possExp, ElementClickInterceptedException):
                return possExp


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
                      infoDict['compType'],  rawDesc, infoDict['title'], infoDict['compType'])

        doAgain = True
        while doAgain:
            jobDesc = mygpt.sendAll().split("Here are the 3 points:")[1].strip()
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
                      infoDict['compType'],  rawDesc, infoDict['title'], infoDict['compType'])

        doAgain = True
        while doAgain:
            jobDesc = mygpt.sendAll().split("Here are the 3 points:")[1].strip()
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

    def handleJob(self, job : dict ):
        title, comp, _, cityState, current, fromDate, toDate, country, desc = tuple(job.values())
        current = "y" in current.lower()

        # Job Title
        self.findFillMoveOn(self.ID, self.CONTAINS, 'jobTitle', title)

        # company name
        self.findFillMoveOn(self.ID, self.CONTAINS, 'company', comp)

        # country location
        chg_country_but = self.findClosestRelatives(self.TXT, self.MATCH, 'Country', self.WHOLE, self.WHOLE, self.BUTTON)[0]
        self.smartClick(element=chg_country_but)
        chg_country_drp = self.findClosestRelatives(self.TXT, self.MATCH, 'Country', self.WHOLE, self.WHOLE, self.SELECT)[0]
        self.fillDropDown(chg_country_drp, country)

        # city state
        self.findFillMoveOn(self.ID, self.CONTAINS, 'cityState', cityState)

        # current position
        if current:
            self.findAndClick( self.ID, self.CONTAINS,'isCurrent')

        #  drop downs
        drp_dwns = self.driver.find_elements('xpath', "//*[contains(@id, 'SelectFormField')]")
        if current:
            frmMon, frmYr = tuple(drp_dwns[-2:])
        else:
            frmMon, frmYr = tuple(drp_dwns[-4:-2])
        frmMonCont, frmYrCont = tuple(fromDate.split(" "))
        self.fillDropDown(frmMon, frmMonCont)
        self.fillDropDown(frmYr, frmYrCont)

        if not current:
            toMon, toYr = tuple(drp_dwns[-2:])
            toMonCont, toYrCont = tuple(toDate.split(" "))
            self.fillDropDown(toMon, toMonCont)
            self.fillDropDown(toYr, toYrCont)

        # description
        txtBoxPath = "//div[@role='textbox']"
        desc = desc.replace("- ", "")
        descEle = self.findFillMoveOn(self.WHOLE, self.WHOLE, txtBoxPath, desc)  # need GPT

        while any([descPoint[2:] not in descEle.text for descPoint in desc.split("\n")]):
            self.findFillMoveOn(self.WHOLE, self.WHOLE, txtBoxPath, desc)

        #make bullets
        descEle.send_keys(Keys.CONTROL, "a")
        xp = "//button[@data-testid='insertUnorderedList']"
        self.findAndClick(self.WHOLE, self.WHOLE, xp)

        return self.findAndClick(self.TXT, self.MATCH, 'Save', travelUp=1, waitBeforeClicking=1, checkNewPage=True)


    def checkIfMoreQuestionsAppeared(self, tup_ptr):
        allPageQuestions, origQuestSet, questn = tup_ptr
        nextQuestInd = allPageQuestions.index(questn) + 1
        QsLeft = allPageQuestions[nextQuestInd:]
        del allPageQuestions[nextQuestInd:]
        latestAllQs = set(self.findAndClick(self.CLASS, self.CONTAINS, 'Questions-item',
                                            indInList=self.ALL, txtCond="#$%^&*(KJH"))
        newQs = latestAllQs - origQuestSet
        origQuestSet.clear()
        origQuestSet.update(latestAllQs)
        allPageQuestions.extend(newQs)
        allPageQuestions.extend(QsLeft)

    def analyzeAndAnsQuestions(self):
        allPageQuestions = self.findAndClick(self.CLASS, self.CONTAINS, 'Questions-item',
                                             indInList=self.ALL, txtCond="#$%^&*(KJH")

        origQuestSet = set(allPageQuestions)
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

            for questn in allPageQuestions:
                try:
                    ret = self.process_question(questn)
                    if isinstance(ret, BadPost):
                        return ret
                    #after answering quesiton, see if any more pop up
                    self.checkIfMoreQuestionsAppeared( (allPageQuestions, origQuestSet, questn) )
                    self.MML.append(datetime.datetime.now())

                except:
                    traceback.print_exc()
                    h = 3

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
            return answer_choices['dropDown'].get_attribute("value") != ""
        elif type == self.SelectApplicable or type == self.DateFill:
            return False
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


    def getTopChoiceScore(self, ans, answer_choices):
        choices_n_scores = [(ans_choice, self.jaccard_similarity(ans_choice, ans)) for ans_choice in
                            answer_choices.keys()]
        choices_n_scores.sort(key=lambda x: x[1], reverse=True)
        thresh = self.jaccard_similarity(ans + "~`*", ans)
        topChoice, topScore = choices_n_scores[0]
        return topChoice, topScore, thresh
    def ensureQualityOfMultChoiceAns(self, gptObj, answer_choices, answer):
        topChoice, topScore, thresh = self.getTopChoiceScore(answer, answer_choices)
        while topScore < thresh:
            answer = gptObj.sendFromFile("mult_choice_wrong_prompts.txt").split("The answer is:")[1]
            topChoice, topScore, thresh = self.getTopChoiceScore(answer, answer_choices)
        inputElement = self.findAndClick(self.WHOLE, self.WHOLE, self.INPUT, txtCond="adsfadsfads",
                                         findFrom=answer_choices[topChoice])
        while not inputElement.is_selected():
            self.smartClick(element=answer_choices[topChoice])
        return topChoice

    def ensureQualityOfSelectApplicableAns(self, gptObj, answer_choices, ans):
        answers = ans
        topChoiceScoreThresh = [self.getTopChoiceScore(answer, answer_choices) for answer in answers]
        while any(topScore < thresh for topChoice, topScore, thresh in topChoiceScoreThresh):
            answer = gptObj.sendFromFile("select_applicable_wrong_prompts.txt")
            answers = [thing.strip() for thing in answer.split("\n") if len(thing.strip()) > 0 ]
            topChoiceScoreThresh = [self.getTopChoiceScore(answer, answer_choices) for answer in answers]

        final_answers = []
        for topChoice, topScore, thresh in topChoiceScoreThresh:
            inputElement = self.findAndClick(self.WHOLE, self.WHOLE, self.INPUT, txtCond="adsfadsfads",
                                             findFrom=answer_choices[topChoice])
            while not inputElement.is_selected():
                self.smartClick(element=answer_choices[topChoice])
            final_answers.append(topChoice)
        return str(final_answers)


    def ensureQualityOfDropDownAns(self, gptObj, answer_choices, answer):
        topChoice, topScore, thresh = self.getTopChoiceScore(answer, answer_choices['answers'])
        while topScore < thresh:
            answer = gptObj.sendFromFile("mult_choice_wrong_prompts.txt")
            topChoice, topScore, thresh = self.getTopChoiceScore(answer, answer_choices['answers'])
        #print(f"b4  *{answer_choices['dropDown'].get_attribute('value')}*")
        while answer_choices['dropDown'].get_attribute("value") == "":
            #print(f"b4 send eys  *{answer_choices['dropDown'].get_attribute('value')}*")
            answer_choices['dropDown'].send_keys(topChoice)
            answer_choices['dropDown'].send_keys(Keys.TAB)
            #print(f"after send eys  *{answer_choices['dropDown'].get_attribute('value')}*")
        return topChoice

    def relevantSubStr(self, substr, fullStr):
        maxLen = int(len(substr)*1.5)
        # Escape any special characters in substr
        escaped_substr = re.escape(substr.lower())
        # Construct the regular expression pattern
        pattern = rf'^(?!.{{{maxLen},}})(.*[^a-zA-Z])?{escaped_substr}([^a-zA-Z].*)?$'
        # Check if the string matches the pattern
        return bool(re.match(pattern, fullStr))

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
                answer_choices['dropDown'].send_keys(ourAns)
            elif type == self.FreeResponse:
                self.fillMoveOn(answer_choices['inputBox'], ourAns)
            else:
                return False
            return True
        else:
            return False
    def process_question(self, questn):  #//div[contains(@class, 'Questions-item')]
        #Do we even have to do this question?
        txt = questn.text
        if '(optional)' in txt:
            return

        questn_txt, answer_choices, errorTxt, type = self.extractQuestionInfo(questn)

        if isinstance(type, BadPost):
            return type

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
            mygpt = myGPT2("free_response_question_prompts.txt", self.JobDescriptionText, str(self.prev_questions),
                          str(self.details), self.lifeSummary, questn_txt, helpTxt, self.zip, self.phone_num, self.email, version=1)
            ans = mygpt.sendAll()
            self.fillMoveOn(answer_choices['inputBox'], ans)

            final_answer = self.ensureQualityOfFreeRespAns(mygpt, questn, helpTxt, ans)

        elif type == self.DateFill:
            # get chat GPT help with free response question
            mygpt = myGPT2("date_fill_question_prompts.txt", self.JobDescriptionText, str(self.prev_questions),
                        questn_txt, self.today_mmddyyy(), helpTxt, version=1)
            ans = mygpt.sendAll()
            month, day, year = tuple(ans.split("-"))
            #self.fillMoveOn(answer_choices['inputBox'], ans)
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
                          questn_txt, "\n".join(list(answer_choices.keys())), helpTxt, version=1)
            ans = mygpt.sendAll().split("The answer is:")[1]

            final_answer = self.ensureQualityOfMultChoiceAns(mygpt, answer_choices, ans)

        elif type == self.SelectApplicable:
            #get chat GPT help
            mygpt = myGPT2("select_applicable_question_prompts.txt", self.JobDescriptionText,  str(self.prev_questions),
                          questn_txt, "\n".join(list(answer_choices.keys())), helpTxt, version=1)
            ans = mygpt.sendAll()
            ans_list = [thing.strip() for thing in ans.split("\n") if len(thing.strip()) > 0 ]

            final_answer = self.ensureQualityOfSelectApplicableAns(mygpt, answer_choices, ans_list)


        elif type == self.DropDown:
            # get chat GPT help
            mygpt = myGPT2("drop_down_question_prompts.txt", self.JobDescriptionText,  str(self.prev_questions),
                          questn_txt, str(self.details), self.lifeSummary,  "\n".join(list(answer_choices['answers'].keys())),
                           helpTxt, version=1)
            ans = mygpt.sendAll()

            #  break here because need to verify that dropdwn is actually the corrct element to send answer to
            final_answer = self.ensureQualityOfDropDownAns(mygpt, answer_choices, ans)

        self.prev_questions.append({"Question":questn_txt, "Answer":final_answer})


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

        #get error text
        errorTxt = self.findAndClick(self.ID,  self.CONTAINS, 'errorText', txtCond="$%^&*()", findFrom=questn, timeLimit=2)
        if errorTxt is None:
            errorTxt = self.findAndClick(self.WHOLE, self.WHOLE, "//span[@role='alert']", txtCond="$%^&*()", findFrom=questn, timeLimit=2)
        elif self.num_children(errorTxt) == 0:
            errorTxt = None

        #get answer choices & question text
        try:
            if type == self.FreeResponse or type == self.FreeResponseLong or type == self.DateFill:
                ans_dict['inputBox'] = self.findAndClick(self.WHOLE, self.WHOLE, self.xpath_or(self.INPUT, self.TXTAREA) , findFrom=questn)
                if ans_dict['inputBox'] is None:
                    type = self.Bad
                txtRoot = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn, txtCond="#$%^&")
                questionText = {self.FreeResponse: txtRoot.text,
                                self.DateFill: txtRoot.text,
                                self.FreeResponseLong: txtRoot.text.split("\n")[-1].replace("\"", "")}[type]

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
                intermediate_ans_list = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn, indInList=self.ALL)
                intermediate_ans_list.pop(0)
                ans_dict = {element.text: element for element in intermediate_ans_list}
                questionText = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn, txtCond="zdsffd").text
            elif type == self.Bad:
                try:
                    questionText = self.findAndClick(self.WHOLE, self.WHOLE, self.LABEL, findFrom=questn, txtCond="#$%^&").text
                except:
                    t = 3
        except Exception as e:
            print("An error occurred:", e)
            traceback.print_exc()
            still = True
            while still:
                t.sleep(1)

        if "(optional)" in questionText:
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

    def determine_question_type(self, questn):
        try:
            qChild = self.get_child(questn, 1, 1)
        except:
            return self.Bad

        num = self.num_children(qChild)
        listOfBad = self.findAndClick( '@aria-label', self.MATCH, 'Day and time option', findFrom=questn, indInList=self.ALL)
        if len(listOfBad) > 0 or self.num_children(self.get_child_complex(questn, "1/2")) == 0:
            # then it's a question we don't want
            if "upload" in questn.text.lower():
                return self.redirectAndSkip("bad question... not dealing with it")
            else:
                return self.Bad
        elif self.findAndClick(self.WHOLE, self.WHOLE, "//fieldset", findFrom=questn, timeLimit=.1, txtCond="*()") is not None:
            #  also contains input, find out what kind of input (radio or checkbox)
            inputEle = self.findAndClick(self.WHOLE, self.WHOLE, self.INPUT, txtCond="asdf", findFrom=questn, timeLimit=.1)
            typeOfInput = inputEle.get_attribute("type")
            return {"radio": self.MultChoice, "checkbox": self.SelectApplicable}[typeOfInput]
        elif self.findAndClick(self.WHOLE, self.WHOLE, "//div[@role='group']", findFrom=questn, timeLimit=.1, txtCond="*()") is not None:
            return self.redirectAndSkip("This was the group... analzye and see..")
        elif self.findAndClick(self.ID, self.CONTAINS, "FileUpload", findFrom=questn, timeLimit=.1, txtCond="*()") is not None:
            #redirect to google because that's the environment that tells us we need to skip this post
            return self.redirectAndSkip("They wanted us to upload a file... fuck that.. not dealing with it")
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



    def do_cover_letter(self):

        #selection = self.findAndClick(self.ID, self.CONTAINS,  'write-cover-letter-selection-card')
        cl = self.findAndClick(self.WHOLE, self.WHOLE, "//div[@data-testid='CoverLetterRadioCard']", txtCond="asdfas")
        if cl is not None:
            cl.click()

        self.findFillMoveOn(self.WHOLE, self.WHOLE, self.TXTAREA, self.coverLetter)

        return self.findAndClick(self.TXT, self.MATCH, ['Update', 'Review your application'], travelUp=1, checkNewPage=True)


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
            self.avoid = info["avoid"]

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
            ans = mygpt.send(prompt).lower()
            if "yes" in ans:
                self.reportAction("CHAT GPT SAID: " + ans, False)
                return True

        return False

    def getPositionInfo(self):
        x = "//*[@data-testid='inlineHeader-companyName']"
        compNameEle = self.findAndClick(self.WHOLE, self.WHOLE, x, txtCond="dsfdsd324", timeLimit=1)
        self.companyName = compNameEle.text


        spanElement = self.findAndClick(self.WHOLE, self.WHOLE, "//span[contains(text(), '- job post')]", txtCond="33343vscads", timeLimit=2)
        if spanElement is not None:
            titleElement = self.get_parent(spanElement )
        else:
            titleElement = self.findAndClick(self.WHOLE, self.WHOLE, self.H1, txtCond="adfddfsa", timeLimit=1)
        self.jobTitle = titleElement.text.split("\n")[0]

        jobDescElement = self.findAndClick(self.ID, self.MATCH, 'jobDescriptionText', txtCond='adsfdasf134')
        self.JobDescriptionText = jobDescElement.text

    def generateHeadline(self):
        mygpt = myGPT2("headline_prompts2.txt", self.JobDescriptionText)

        doAgain = True
        while doAgain:
            self.headline = mygpt.sendAll().split("The headline is:")[1].strip().strip(".")
            doAgain = mygpt.need_redo

    def generateCL(self):
        '''mygpt = myGPT("cover_letter_prompts.txt", self.jobTitle, self.companyName,
                      self.JobDescriptionText, self.firstName, self.lastName,
                      self.lifeSummary, self.firstName, self.lastName, self.phone_num,
                      self.email, self.cityState, self.today() )
        self.coverLetter = mygpt.sendAll()'''

        mygpt = myGPT2("cover_letter_prompts2.txt", self.jobTitle, self.companyName,
                       self.JobDescriptionText, self.firstName, self.lastName,
                       self.lifeSummary, self.firstName, self.lastName, self.phone_num,
                       self.email, self.areaSpec, self.today())

        doAgain = True
        while doAgain:
            self.coverLetter = mygpt.sendAll()
            doAgain = mygpt.need_redo


    def generateSummary(self):
        '''mygpt = myGPT("summary_prompts.txt", self.coverLetter, self.firstName)
        self.resumeSummary = mygpt.sendAll()'''

        mygpt = myGPT2("summary_prompts2.txt", self.coverLetter, self.firstName)

        doAgain = True
        while doAgain:
            self.resumeSummary = mygpt.sendAll()
            doAgain = mygpt.need_redo

    def generateSkills(self):
        '''mygpt = myGPT("skills_prompts.txt", self.JobDescriptionText, self.lifeSummary)
        skillsStrList = mygpt.sendAll()
        self.skills2 = skillsStrList.split(",")'''

        # initial skill list generation
        mygpt = myGPT2("skills_prompts2.txt", self.jobTitle, self.JobDescriptionText, self.lifeSummary)

        doAgain = True
        while doAgain:
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
        if missing_states_in_transitions:
            print(f"States missing in {state_transitions_file}:{sep}{sep.join(missing_states_in_transitions)}")
        if extra_states_in_transitions:
            print(
                f"Extra states in {state_transitions_file} not found in {states_file}:{sep}{sep.join(extra_states_in_transitions)}")
        if missing_environments_in_transitions:
            print(f"Environments missing in {state_transitions_file}:{sep}{sep.join(missing_environments_in_transitions)}")
        if extra_environments_in_transitions:
            print(
                f"Extra environments in {state_transitions_file} not found in {expected_environments_file}:{sep}{sep.join(extra_environments_in_transitions)}")
        if funcsNotDefined:
            print(
                f"Transition Functions mentioned in {state_transitions_file} but not defined in Helper:{sep}{sep.join(funcsNotDefined)}")

        if (extra_environments_in_transitions or missing_environments_in_transitions
                or extra_states_in_transitions or missing_states_in_transitions or
                funcsNotDefined):
            sys.exit()

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
            print(f"Unexpected environment: {environment}")
            self.waitForever()
            return

        next_state = None
        #checking that the transition file as made properly
        if self.envNextTrans(environment) is not None:
            if self.current_state in self.transitions[envPattern]:
                funcName, next_state = self.transitions[envPattern][self.current_state]
            elif "default" in self.transitions[envPattern]:
                funcName, next_state = self.transitions[envPattern]["default"]
            else:
                print(f"No transition for state {self.current_state} and env {environment}")

            if "default" == next_state.strip():
                next_state = self.current_state

            self.helper.reportAction(f"Calling function: {funcName}() in environment: {environment}", False)
            funcResult  = self.executeFunc(funcName)
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
            print(f"No transition defined for environment: {environment}")
            self.waitForever()

    def executeFunc(self, funcName):
        # Get the method reference based on the string name
        method_to_call = getattr(self.helper, funcName)

        # Call the method
        return method_to_call()

    def waitForever(self):
        still = True
        while still:
            t.sleep(1)


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
        """
        announced = False
        while self.control.mode() == "paused":
            command = self.control.pending_command()
            if command:
                self.handleCommand(command)
                continue
            if not announced:
                ct_print("StateMachine", "PAUSED", "waiting for a command from the Run tab")
                announced = True
            t.sleep(1)
        if announced:
            ct_print("StateMachine", "RESUMED")

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
                    ct_print("__main__", f"user id={id} looks stalled (no milestone in 15 min), restarting its browser")
                    sm_ref = rec["sm_ref"]
                    if sm_ref is not None:
                        try:
                            sm_ref.helper.close()
                        except Exception as exc:
                            ct_error("__main__ (stall recovery)", exc)
                    rec["milestoneList"].append(datetime.datetime.now())
        except Exception:
            ct_error("__main__ (monitor loop)", sys.exc_info()[1])
            traceback.print_exc()
