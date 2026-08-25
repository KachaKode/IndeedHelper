"""Launcher for the IndeedHelper database admin GUI.

Starts Flask on a background thread bound to 127.0.0.1 and wraps it in a native
desktop window via pywebview. If the webview backend cannot start, falls back to
opening the default browser rather than failing silently.

    venv\\Scripts\\python.exe db_admin.py
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dbgui.data import IndeedDB  # noqa: E402
from dbgui.migrations import add_target_position, schema_exists  # noqa: E402
from dbgui.runner import RunnerManager  # noqa: E402
from dbgui.server import create_app  # noqa: E402

DB_PATH = ROOT / "IndHelperDB.db"
WINDOW_TITLE = "IndeedHelper Database"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_server(url: str, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1.0) as response:
                if response.status == 200:
                    return True
        except (URLError, OSError):
            time.sleep(0.15)
    return False


def main() -> int:
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}", file=sys.stderr)
        return 1

    db = IndeedDB(DB_PATH, project_root=ROOT)

    with db._connect() as conn:
        if not schema_exists(conn):
            print(
                "The job_searches table does not exist yet.\n"
                "Run the migration first:\n"
                "    venv\\Scripts\\python.exe tools/verify_migration.py --apply",
                file=sys.stderr,
            )
            return 1

    # Additive and idempotent, so it is safe to self-heal on startup rather than
    # making the user run a migration by hand for a display-only column.
    added = add_target_position(db)
    if added["added"]:
        print(f"Added job_searches.target_position "
              f"(labelled {added['backfilled']} existing searches from their search terms).")

    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    runner = RunnerManager(db, ROOT)
    app = create_app(db, runner)

    server = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False,
                               use_reloader=False, threaded=True),
        daemon=True,
    )
    server.start()

    if not wait_for_server(url):
        print(f"Flask did not come up on {url}", file=sys.stderr)
        return 1

    print(f"Database admin running at {url}")

    def shutdown() -> None:
        # Bot runs are child processes; without this they would keep their Chrome
        # windows open after the control window is gone.
        stopped = runner.stop_all()
        if stopped:
            print(f"Stopped {len(stopped)} running automation process(es).")

    try:
        import webview
        webview.create_window(WINDOW_TITLE, url, width=1400, height=900, min_size=(1000, 640))
        webview.start()
        shutdown()
        return 0
    except Exception as exc:  # noqa: BLE001 - any backend failure should degrade, not crash
        print(f"Could not open a native window ({exc}). Falling back to your browser.",
              file=sys.stderr)
        import webbrowser
        webbrowser.open(url)
        print("Press Ctrl+C to stop the server.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            shutdown()
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
