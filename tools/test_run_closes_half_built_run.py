"""A run that fails while it is still being built must release its Playwright.

From a real run on a Mac (Logs, 2026-11-07): IndeedHelper started fine and
opened Chrome, then StateMachine() raised FileNotFoundError on a Windows-style
config path. RunUser's cleanup only closed `sm.helper`, and sm was still None,
so the helper -- and the Playwright it had started on this thread -- was never
released. Every retry then died on "It looks like you are using Playwright Sync
API inside the asyncio loop", hiding the real error behind a misleading one.

Pinned here:
  1. A failure inside StateMachine() still closes the helper that was built.
  2. A failure inside IndeedHelper() leaves nothing to close and does not raise
     a second error from the cleanup.
  3. start_up() stops its own Playwright when connecting to Chrome fails, since
     the helper is never finished and nothing else can.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

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


USER = {"mainInfo": {"FirstName": "Test", "LastName": "User", "id": 1}}


class FakeHelper:
    def __init__(self, *args, **kwargs):
        self.closed = 0
        self.currentJobKey = None
        FakeHelper.built.append(self)

    built: list["FakeHelper"] = []

    def close(self):
        self.closed += 1

    def reportAction(self, *a, **k):
        pass


class FinishingMachine:
    """The second attempt: constructs fine and ends the run cleanly."""

    def __init__(self, helper):
        self.helper = helper

    def run(self):
        pass


def run_user(helper_factory, machine_factory):
    """Run RunUser until it returns, with restarts instant and silent."""
    FakeHelper.built = []
    with mock.patch.object(main3, "IndeedHelper", helper_factory), \
         mock.patch.object(main3, "StateMachine", machine_factory), \
         mock.patch.object(main3, "RESTART_BACKOFF_SECONDS", 0), \
         mock.patch.object(main3.t, "sleep", lambda s: None), \
         mock.patch.object(main3.traceback, "print_exc", lambda: None):
        main3.RunUser(USER, {"milestoneList": [], "sm_ref": None})


def test_state_machine_failure_closes_helper() -> None:
    attempts = []

    def machine(helper):
        attempts.append(helper)
        if len(attempts) == 1:
            raise FileNotFoundError("config/States.txt")
        return FinishingMachine(helper)

    run_user(FakeHelper, machine)
    first = FakeHelper.built[0]
    check("StateMachine() failed -> the helper that was built is closed", first.closed == 1,
          f"closed {first.closed} times")
    check("the retry builds a fresh helper", len(FakeHelper.built) == 2)
    check("the retry's helper is not closed by a clean finish", FakeHelper.built[1].closed == 0)


def test_helper_failure_has_nothing_to_close() -> None:
    attempts = []

    def helper(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("chrome never started")
        return FakeHelper()

    run_user(helper, FinishingMachine)
    check("IndeedHelper() failed -> cleanup copes and the retry still happens",
          len(attempts) == 2, f"attempts={len(attempts)}")


def test_start_up_stops_playwright_on_connect_failure() -> None:
    wrap = main3.PlaywrightWrap.__new__(main3.PlaywrightWrap)
    wrap.chrome_profile = "user-data-dir=" + str(ROOT / "runtime" / "test_profile_unused")
    wrap.home_url = "about:blank"
    wrap._chrome_process = None

    playwright = mock.MagicMock()
    playwright.chromium.connect_over_cdp.side_effect = RuntimeError("connection refused")

    with mock.patch.object(main3.PlaywrightWrap, "_find_chrome_executable", return_value="chrome"), \
         mock.patch.object(main3.PlaywrightWrap, "_running_debug_port", return_value=9222), \
         mock.patch.object(main3.os, "makedirs"), \
         mock.patch.object(main3, "sync_playwright") as sync_playwright:
        sync_playwright.return_value.start.return_value = playwright
        raised = None
        try:
            wrap.start_up()
        except RuntimeError as exc:
            raised = exc

    check("the original error still propagates", raised is not None and "connection refused" in str(raised))
    check("Playwright is stopped so the retry can start its own", playwright.stop.called)
    check("the helper does not keep a dead Playwright", wrap._playwright is None)


def main() -> int:
    test_state_machine_failure_closes_helper()
    test_helper_failure_has_nothing_to_close()
    test_start_up_stops_playwright_on_connect_failure()

    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
