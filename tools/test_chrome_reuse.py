"""A Chrome that is already open on the bot's profile must be reused, not fought.

From a real run on a Mac: closing Chrome's window (or pressing Stop in the GUI,
which ends the bot but not the Chrome it launched) leaves Chrome running on the
profile. The next start_up launched a second Chrome on it, which handed its URL
to the first one ("Opening in existing browser session.") and exited, so the
DevTools port the bot was waiting on never opened. The log was 40 identical WAIT
lines per attempt and one more home-page tab each time (Logs/Log57.txt).

PlaywrightWrap._running_debug_port reads the port start_up noted in the profile
folder (Chrome's own DevToolsActivePort is only written for port 0, so it is no
use here) and only believes it if a DevTools endpoint answers there.
"""

from __future__ import annotations

import http.server
import socket
import sys
import tempfile
import threading
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


def serve(status: int, body: bytes = DEVTOOLS_BODY):
    handler = type("Handler", (_Handler,), {"status": status, "body": body})
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write_port(profile: Path, text: str) -> None:
    (profile / main3.PlaywrightWrap.DEBUG_PORT_FILE).write_text(text, encoding="utf-8")


def main() -> int:
    find = main3.PlaywrightWrap._running_debug_port
    with tempfile.TemporaryDirectory() as tmp:
        profile = Path(tmp)

        check("no port note in the profile -> nothing to reuse", find(str(profile)) is None)

        write_port(profile, "not a port")
        check("unreadable note -> nothing to reuse", find(str(profile)) is None)

        live = serve(200)
        try:
            port = live.server_address[1]
            write_port(profile, str(port))
            check("live Chrome on the recorded port -> reused", find(str(profile)) == port,
                  f"got {find(str(profile))!r}, expected {port}")
        finally:
            live.shutdown()

        write_port(profile, str(closed_port()))
        check("stale note from a Chrome that is gone -> not reused", find(str(profile)) is None)

        failing = serve(500)
        try:
            write_port(profile, str(failing.server_address[1]))
            check("something answers with an error -> not reused", find(str(profile)) is None)
        finally:
            failing.shutdown()

        other = serve(200, body=b"<html>some other local service</html>")
        try:
            write_port(profile, str(other.server_address[1]))
            check("something answers 200 but is not DevTools -> not reused", find(str(profile)) is None)
        finally:
            other.shutdown()

    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
