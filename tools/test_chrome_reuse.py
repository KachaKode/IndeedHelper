"""A Chrome that is already open on the bot's profile must be reused, not fought.

From real runs on a Mac and on Windows: pressing Stop in the GUI (or closing
Chrome's window on a Mac) ends the bot but leaves Chrome running on the profile.
The next start_up launched a second Chrome on it, which handed its URL to the
first one ("Opening in existing browser session.") and exited, so the DevTools
port the bot was waiting on never opened. The log was one WAIT line per half
second, then a retry, and one more home-page tab each time (Logs/Log57.txt,
Logs/Log59.txt).

The Chrome left behind still has remote debugging on, and its command line says
which port. PlaywrightWrap._running_debug_port reads it from there -- not from a
file the bot wrote, because the Chrome that needs rescuing may have been started
by an older bot -- and only believes it if a DevTools endpoint answers.
"""

from __future__ import annotations

import http.server
import socket
import sys
import threading
from unittest import mock

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


DEVTOOLS_BODY = b'{"Browser": "Chrome/1", "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/abc"}'


class _Handler(http.server.BaseHTTPRequestHandler):
    status = 200
    body = DEVTOOLS_BODY

    def do_GET(self):  # noqa: N802 - http.server's name
        self.send_response(type(self).status)
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *args):
        pass


def serve(status: int = 200, body: bytes = DEVTOOLS_BODY):
    handler = type("Handler", (_Handler,), {"status": status, "body": body})
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


WIN_PROFILE = r"C:\Users\PJuJu\AppData\Local\Google\Chrome\User Data\Profile 12"
MAC_PROFILE = "/Users/someone/Documents/IndeedHelper/ChromeProfiles/user_1"


def test_command_line_matching() -> None:
    find = main3.PlaywrightWrap._debug_port_in

    # Exactly what Win32_Process reported for the Chrome left running on 2026-11-05:
    # the profile argument is quoted because its path contains a space.
    win_browser = (r'"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=6878 '
                   rf'"--user-data-dir={WIN_PROFILE}" --no-first-run --no-default-browser-check '
                   r'--start-maximized https://www.indeed.com/jobs?q=Data')
    with mock.patch.object(main3.sys, "platform", "win32"):
        check("Windows browser process, quoted profile with a space -> its port",
              find(win_browser, WIN_PROFILE) == 6878, f"got {find(win_browser, WIN_PROFILE)!r}")
        check("profile path compared case-insensitively on Windows",
              find(win_browser, WIN_PROFILE.upper()) == 6878)
        check("a different profile -> not matched",
              find(win_browser, WIN_PROFILE.replace("12", "7")) is None)
        check("'Profile 12' does not claim 'Profile 123'",
              find(win_browser, WIN_PROFILE + "3") is None)
        helper = win_browser.replace("chrome.exe\" --remote", 'chrome.exe" --type=renderer --remote')
        check("a --type= helper process is ignored", find(helper, WIN_PROFILE) is None)

    mac_browser = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --remote-debugging-port=53271 "
                   f"--user-data-dir={MAC_PROFILE} --no-first-run --no-default-browser-check --start-maximized "
                   "https://ca.indeed.com/jobs?q=x")
    with mock.patch.object(main3.sys, "platform", "darwin"):
        check("macOS browser process -> its port", find(mac_browser, MAC_PROFILE) == 53271)
        check("'user_1' does not claim 'user_10'", find(mac_browser, MAC_PROFILE + "0") is None)
        check("paths are case-sensitive off Windows", find(mac_browser, MAC_PROFILE.upper()) is None)
        check("profile argument last on the line still matches",
              find(f"chrome --remote-debugging-port=9222 --user-data-dir={MAC_PROFILE}", MAC_PROFILE) == 9222)
        check("trailing slash on the configured path is tolerated",
              find(mac_browser, MAC_PROFILE + "/") == 53271)
        check("no remote debugging flag -> nothing to connect to",
              find(f"chrome --user-data-dir={MAC_PROFILE}", MAC_PROFILE) is None)
        check("--remote-debugging-port=0 -> nothing to connect to",
              find(f"chrome --remote-debugging-port=0 --user-data-dir={MAC_PROFILE}", MAC_PROFILE) is None)
        check("Chrome on another profile entirely -> not matched",
              find("chrome --remote-debugging-port=9222", MAC_PROFILE) is None)


def test_endpoint_is_verified() -> None:
    find = main3.PlaywrightWrap._running_debug_port

    def run(lines):
        with mock.patch.object(main3.PlaywrightWrap, "_chrome_command_lines", return_value=lines), \
             mock.patch.object(main3.sys, "platform", "darwin"):
            return find(MAC_PROFILE)

    def line(port):
        return f"chrome --remote-debugging-port={port} --user-data-dir={MAC_PROFILE} --no-first-run"

    check("no Chrome running -> nothing to reuse", run([]) is None)

    live = serve()
    try:
        port = live.server_address[1]
        check("live Chrome on its own port -> reused", run(["unrelated process", line(port)]) == port)
    finally:
        live.shutdown()

    check("Chrome listed but its port no longer answers -> not reused", run([line(closed_port())]) is None)

    other = serve(body=b"<html>some other local service</html>")
    try:
        check("port answers 200 but is not DevTools -> not reused", run([line(other.server_address[1])]) is None)
    finally:
        other.shutdown()

    erroring = serve(status=500)
    try:
        check("port answers with an error -> not reused", run([line(erroring.server_address[1])]) is None)
    finally:
        erroring.shutdown()

    live = serve()
    try:
        port = live.server_address[1]
        check("a dead entry before a live one does not hide it",
              run([line(closed_port()), line(port)]) == port)
    finally:
        live.shutdown()


def main() -> int:
    test_command_line_matching()
    test_endpoint_is_verified()

    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
