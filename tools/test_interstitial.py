"""The bot check page must be waited out, not treated as a results page.

Indeed sometimes serves a Cloudflare-style "Just a moment..." page. The config
has a rule for it, but envIsValid picks the LONGEST matching pattern and the
generic jobs-page pattern is longer, so the rule never fired: the bot saw zero
job cards and jumped to the next page, skipping everything on the current one.

These tests pin the guard that runs before pattern matching.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402

JOBS_URL = ("https://www.indeed.com/jobs?q=Technical+Project+Manager&l=Remote"
            "&from=searchOnHP%2Cwhereautocomplete&vjk=e90515b1389029d0")

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


class FakeHelper:
    """Serves a scripted sequence of environments."""

    def __init__(self, envs):
        self.envs = list(envs)
        self.calls = 0

    def getCurrentEnv(self, quiet=False):
        # `quiet` mirrors the real signature: polling loops suppress the trace so
        # they do not bury the rest of the log.
        self.calls += 1
        return self.envs[min(self.calls - 1, len(self.envs) - 1)]

    def reportAction(self, *a, **k):
        pass


class FakeControl:
    """Mirrors main3.RunControl, including the seq counter that distinguishes a
    fresh instruction from the mode simply already being 'running'."""

    def __init__(self, mode="running", seq=1):
        self._mode = mode
        self._seq = seq

    def mode(self):
        return self._mode

    def seq(self):
        return self._seq

    def instruct(self, mode):
        """What pressing a button in the Run tab does."""
        self._mode = mode
        self._seq += 1

    def pending_command(self):
        return None


def sm_with(helper, control=None):
    sm = main3.StateMachine.__new__(main3.StateMachine)
    sm.helper = helper
    sm.control = control or FakeControl()
    sm.selfPaused = False      # set by __init__ in real use; __new__ skips it
    return sm


def main() -> int:
    sm = sm_with(FakeHelper([""]))

    # --- detection -----------------------------------------------------------
    check("detects 'Just a moment...'", sm.isInterstitial(f"{JOBS_URL}|Just a moment..."))
    check("detects 'Checking your browser'",
          sm.isInterstitial("https://www.indeed.com/jobs?q=x|Checking your browser before accessing"))
    check("detects 'Attention Required'",
          sm.isInterstitial("https://www.indeed.com/jobs?q=x|Attention Required! | Cloudflare"))
    check("a real results page is NOT an interstitial",
          not sm.isInterstitial(f"{JOBS_URL}|Technical Project Manager Jobs, Employment | Indeed.com"))
    check("a job page is NOT an interstitial",
          not sm.isInterstitial("https://www.indeed.com/viewjob?jk=abc|Technical Project Manager - Dark Alpha"))

    # --- the precedence problem this guard exists to sidestep -----------------
    env = f"{JOBS_URL}|Just a moment..."
    helper = main3.PlaywrightWrap.__new__(main3.PlaywrightWrap)
    patterns = [ln.strip() for ln in (ROOT / "config" / "ExpectedEnvironments.txt")
                .read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("//")]
    matched = [p for p in sorted(patterns, key=len, reverse=True)
               if re.match(main3.PlaywrightWrap.escape_regex_special_chars(helper, p).lower(),
                           env.lower())]
    check("more than one config pattern matches the check page", len(matched) > 1,
          f"matched={matched}")
    check("the winning pattern is NOT the 'Just a moment' rule",
          matched and "Just a moment" not in matched[0],
          "if this changes, envIsValid alone would be enough and the guard is redundant")
    print(f"         longest-wins picks: {matched[0][:60]!r}")

    # --- pausing + alerting --------------------------------------------------
    CHECK = f"{JOBS_URL}|Just a moment..."
    CLEAR = f"{JOBS_URL}|Technical Project Manager Jobs | Indeed.com"

    def instrument(machine):
        """Replace the real beep with a recorder, and time with a fast clock."""
        machine.beeps = []
        machine.beep = lambda: machine.beeps.append(machine._clock)
        machine._clock = 0.0
        return machine

    def fake_clock(machine, step=1.0):
        """Advance a virtual clock instead of sleeping through 30 real minutes."""
        def _time():
            return machine._clock
        def _sleep(secs):
            machine._clock += max(secs, step)
        return _time, _sleep

    import time as real_time

    # 1. clears after a while -> stops beeping and returns
    helper = FakeHelper([CHECK] * 8 + [CLEAR])
    machine = instrument(sm_with(helper))
    orig_time, orig_sleep = main3.t.time, main3.t.sleep
    main3.t.time, main3.t.sleep = fake_clock(machine)
    try:
        machine.waitOutInterstitial()
    finally:
        main3.t.time, main3.t.sleep = orig_time, orig_sleep

    check("pauses itself on a bot check", machine.selfPaused,
          "the run must stop; a bot check needs a person")
    check("returns once the check clears", helper.calls >= 8,
          f"polled {helper.calls} times")
    check("beeped immediately", machine.beeps and machine.beeps[0] <= 1,
          f"first beep at {machine.beeps[:1]}")

    # 2. cadence: every 5s for the first 30s, then every 30s
    helper = FakeHelper([CHECK])           # never clears
    machine = instrument(sm_with(helper))
    machine.BEEP_GIVE_UP_AFTER = 120
    orig_time, orig_sleep = main3.t.time, main3.t.sleep
    main3.t.time, main3.t.sleep = fake_clock(machine)
    try:
        # stop once the virtual clock passes 120s
        original = machine.isInterstitial
        machine.isInterstitial = lambda env: machine._clock < 121 and original(env)
        machine.waitOutInterstitial()
    finally:
        main3.t.time, main3.t.sleep = orig_time, orig_sleep

    beeps = machine.beeps
    first30 = [b for b in beeps if b < 30]
    after30 = [b for b in beeps if b >= 30]
    print(f"         beep times: {[round(b) for b in beeps]}")
    check("6 beeps in the first 30s (every 5s)", len(first30) == 6, f"got {first30}")
    check("first-30s gaps are 5s",
          all(round(b - a) == 5 for a, b in zip(first30, first30[1:])), f"{first30}")
    check("then every 30s",
          all(round(b - a) == 30 for a, b in zip(after30, after30[1:])), f"{after30}")

    # 3. the mode being ALREADY 'running' must not count as an override --
    #    it always is, which is why the check appeared mid-run.
    helper = FakeHelper([CHECK])
    control = FakeControl(mode="running")
    machine = instrument(sm_with(helper, control))
    machine.BEEP_GIVE_UP_AFTER = 60
    orig_time, orig_sleep = main3.t.time, main3.t.sleep
    main3.t.time, main3.t.sleep = fake_clock(machine)
    try:
        original = machine.isInterstitial
        machine.isInterstitial = lambda env: machine._clock < 45 and original(env)
        machine.waitOutInterstitial()
    finally:
        main3.t.time, main3.t.sleep = orig_time, orig_sleep
    check("an already-running mode does not silently override the check",
          len(machine.beeps) > 3,
          f"only {len(machine.beeps)} beep(s): it bailed out instead of alerting")

    # 4. pressing Start applying (a NEW instruction) does override it
    helper = FakeHelper([CHECK])
    control = FakeControl(mode="running")
    machine = instrument(sm_with(helper, control))
    orig_time, orig_sleep = main3.t.time, main3.t.sleep
    main3.t.time, main3.t.sleep = fake_clock(machine)
    try:
        original_seq = machine.control.seq
        # Simulate the button press once the virtual clock passes 10s.
        machine.control.seq = lambda: (control._seq + 1) if machine._clock > 10 else original_seq()
        machine.waitOutInterstitial()
    finally:
        main3.t.time, main3.t.sleep = orig_time, orig_sleep
    check("Start applying overrides a stuck bot check", not machine.selfPaused,
          "resuming by hand should let the run proceed")

    # 5. the alert eventually goes quiet but stays paused
    helper = FakeHelper([CHECK])
    machine = instrument(sm_with(helper))
    machine.BEEP_GIVE_UP_AFTER = 60
    orig_time, orig_sleep = main3.t.time, main3.t.sleep
    main3.t.time, main3.t.sleep = fake_clock(machine)
    try:
        original = machine.isInterstitial
        machine.isInterstitial = lambda env: machine._clock < 200 and original(env)
        machine.waitOutInterstitial()
    finally:
        main3.t.time, main3.t.sleep = orig_time, orig_sleep
    check("stops beeping after the give-up window",
          max(machine.beeps) <= 60 + 30, f"last beep at {max(machine.beeps)}")
    check("but stays paused", machine.selfPaused)

    # --- unknown pages must not hang the run -------------------------------
    # This used to call waitForever() -- an unbounded sleep loop. The run sat on
    # an unrecognised page for 13 minutes looking alive while doing nothing.
    UNKNOWN = "https://profile.indeed.com/resume?x=1|Some Brand New Page"
    KNOWN = f"{JOBS_URL}|Technical Project Manager Jobs | Indeed.com"

    def envIsValid(env):
        return "pattern" if "Indeed.com" in env else None

    # An unknown page must pause and beep for a human, exactly like a bot check,
    # while it is genuinely unresolved.
    helper = FakeHelper([UNKNOWN])
    machine = instrument(sm_with(helper))
    machine.UNKNOWN_ENV_GRACE = 0
    machine.BEEP_GIVE_UP_AFTER = 60
    machine.envIsValid = envIsValid
    orig_time, orig_sleep = main3.t.time, main3.t.sleep
    main3.t.time, main3.t.sleep = fake_clock(machine)
    try:
        original = machine.isInterstitial
        # let it run for a while of virtual time, then "fix" the page
        machine.envIsValid = lambda env: "pattern" if machine._clock > 40 else None
        machine.handleUnknownEnvironment(UNKNOWN)
    finally:
        main3.t.time, main3.t.sleep = orig_time, orig_sleep

    check("an unknown page beeps for attention", len(machine.beeps) >= 6,
          f"only {len(machine.beeps)} beep(s): {machine.beeps}")
    first30 = [b for b in machine.beeps if b < 30]
    check("unknown-page beeps use the same 5s/30s cadence", len(first30) == 6,
          f"got {first30}")
    print(f"         beep times: {[round(b) for b in machine.beeps]}")

    # But once the page turns out to have just been SLOW rather than actually
    # wrong -- it settled into a known one on its own -- nobody was needed, so
    # the run must not sit there waiting for "Start applying" from a human who
    # has no reason to come. This is the AI-tailored-resume redirect case: its
    # title can take well over the grace period to settle.
    check("a page that settles on its own resumes without Start applying",
          not machine.selfPaused,
          "it beeped for a while, then resolved itself; staying paused here "
          "means waiting for a person who was never needed")

    # A page that is merely still loading should be tolerated, not alarmed about.
    settling = FakeHelper([KNOWN])
    machine = instrument(sm_with(settling))
    machine.UNKNOWN_ENV_GRACE = 6
    machine.envIsValid = envIsValid
    orig_time, orig_sleep = main3.t.time, main3.t.sleep
    main3.t.time, main3.t.sleep = fake_clock(machine)
    try:
        machine.handleUnknownEnvironment(UNKNOWN)
    finally:
        main3.t.time, main3.t.sleep = orig_time, orig_sleep
    check("a page that settles into a known one raises no alarm",
          not machine.beeps and not machine.selfPaused,
          f"beeps={machine.beeps} selfPaused={machine.selfPaused}")

    # Waving it through by hand must not re-nag about the same page.
    helper = FakeHelper([UNKNOWN])
    control = FakeControl(mode="running")
    machine = instrument(sm_with(helper, control))
    machine.UNKNOWN_ENV_GRACE = 0
    machine.envIsValid = lambda env: None
    orig_time, orig_sleep = main3.t.time, main3.t.sleep
    main3.t.time, main3.t.sleep = fake_clock(machine)
    try:
        base = control.seq()
        machine.control.seq = lambda: (base + 1) if machine._clock > 8 else base
        machine.handleUnknownEnvironment(UNKNOWN)
        waived = machine.attentionWaived(UNKNOWN)
        before = len(machine.beeps)
        machine.handleUnknownEnvironment(UNKNOWN)   # same page again
        after = len(machine.beeps)

        # The waiver has to expire. Several pages in the flow share one
        # url|title -- every job's review page is the same environment string --
        # so a permanent waiver would silence the alarm for every later job.
        machine._clock += machine.ATTENTION_WAIVER_TTL + 1
        expired = not machine.attentionWaived(UNKNOWN)
    finally:
        main3.t.time, main3.t.sleep = orig_time, orig_sleep
    check("waving a page through is remembered", waived)
    check("it does not nag again for the same page", after == before,
          f"beeped {after - before} more time(s) for a page already waved through")
    check("but the waiver expires, so a later run still gets alerted", expired,
          "a single wave-through silences this page forever")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL INTERSTITIAL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
