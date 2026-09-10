"""A GPT call that never comes back must not hold the whole run.

From a two hour run that sent zero applications: 23 completions finished in
12.7 minutes of GPT time between them, and the 24th never printed "done" at
all. It sat there for the rest of the run.

The timeout looked like it handled this and did not:

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(self.sendChatWrapper)
        try:
            return future.result(timeout=self.chatTimeOut)
        except concurrent.futures.TimeoutError:
            ...

future.result() does raise on time. But leaving the `with` block calls
ThreadPoolExecutor.__exit__, which is shutdown(wait=True) -- so the very
request just declared hung is then waited on anyway. Nothing was ever
abandoned. Makes no network calls.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import concurrent.futures  # noqa: E402

import myGPT2  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


class Stub(myGPT2.myGPT):
    """Just the timeout machinery -- no prompt files, no API key, no network."""

    def __init__(self, behaviour, chatTimeOut=1.0):
        self.behaviour = behaviour
        self.chatTimeOut = chatTimeOut
        self.calls = 0
        self.model = None

    def sendChatWrapper(self):
        self.calls += 1
        return self.behaviour(self.calls)


# Long enough to be "hung" for the purposes of a 0.5s timeout, short enough
# that the interpreter's own thread-join at exit does not stall the suite.
# That join is the reason request_timeout matters: shutdown(wait=False) frees
# the RUN immediately, but the abandoned worker lives until the HTTP call
# itself gives up.
HANG_SECONDS = 12


def hangs_forever(_call):
    time.sleep(HANG_SECONDS)
    return "late"


def main() -> int:
    print("--- a request that never returns ---")
    stub = Stub(hangs_forever, chatTimeOut=0.5)
    stub.MAX_TIMEOUT_RETRIES = 2
    stub.RETRY_PAUSE = 0.2

    started = time.time()
    raised = None
    try:
        stub.executeWrapperWithTimeOut()
    except BaseException as exc:          # noqa: BLE001
        raised = exc
    elapsed = time.time() - started

    check("it gives up instead of waiting for the hung request",
          isinstance(raised, concurrent.futures.TimeoutError),
          f"raised {type(raised).__name__ if raised else 'nothing'}")
    # Two attempts at 0.5s plus one 0.2s pause is about 1.2s. The old code
    # blocked on shutdown(wait=True) and would sit here for the full 600s.
    check("and it returns promptly rather than blocking on shutdown",
          elapsed < HANG_SECONDS, f"took {elapsed:.1f}s -- it waited for the hung call")
    check("it retried the configured number of times",
          stub.calls == 2, f"made {stub.calls} attempts")
    print(f"         gave up after {elapsed:.1f}s across {stub.calls} attempts")

    print()
    print("--- a request that is merely slow still succeeds ---")

    def slow_then_fine(call):
        time.sleep(0.1)
        return f"reply {call}"

    stub = Stub(slow_then_fine, chatTimeOut=5)
    started = time.time()
    result = stub.executeWrapperWithTimeOut()
    check("a normal call comes back", result == "reply 1", f"got {result!r}")
    check("and is not delayed by the timeout machinery",
          time.time() - started < 3)

    print()
    print("--- a request that fails once and then works ---")
    state = {"n": 0}

    def hang_once(call):
        if call == 1:
            time.sleep(HANG_SECONDS)
        return "recovered"

    stub = Stub(hang_once, chatTimeOut=0.5)
    stub.MAX_TIMEOUT_RETRIES = 3
    stub.RETRY_PAUSE = 0.2
    started = time.time()
    result = stub.executeWrapperWithTimeOut()
    check("the retry succeeds", result == "recovered", f"got {result!r}")
    check("without waiting on the abandoned attempt",
          time.time() - started < HANG_SECONDS, f"took {time.time() - started:.1f}s")

    print()
    print("--- the settings that made one stuck call cost an hour ---")
    src = (ROOT / "myGPT2.py").read_text(encoding="utf-8")
    check("the executor is no longer a context manager",
          "with concurrent.futures.ThreadPoolExecutor() as executor:" not in src,
          "leaving the block waits for the hung request")
    check("it is shut down without waiting", "shutdown(wait=False)" in src)
    check("the HTTP call has its own timeout", "request_timeout=" in src,
          "a socket with no timeout cannot be interrupted at all")
    check("the retry pause is no longer a full minute",
          "t.sleep(60)" not in src)

    import inspect
    sig = inspect.signature(myGPT2.myGPT.__init__)
    default = sig.parameters["chatTimeOut"].default
    check("the per-call timeout is minutes shorter than it was",
          default <= 120, f"chatTimeOut defaults to {default}s")
    print(f"         chatTimeOut={default}s, "
          f"MAX_TIMEOUT_RETRIES={myGPT2.myGPT.MAX_TIMEOUT_RETRIES}, "
          f"RETRY_PAUSE={myGPT2.myGPT.RETRY_PAUSE}s "
          f"-> worst case "
          f"{default * myGPT2.myGPT.MAX_TIMEOUT_RETRIES + myGPT2.myGPT.RETRY_PAUSE * 2:.0f}s")

    print()
    print("--- a reply that never satisfies a required-phrase check ---")
    # Logs/Log20.txt: doCheckNots was `while True` with no bound at all,
    # unlike its sibling doChecks (which gives up after 5). gpt-5-nano skips
    # a required preamble ("The answer is:", "The headline is:") far more
    # often than gpt-5-mini did, so a page with one such question hung for
    # HOURS -- one real API call every 15-20s, forever printing "GPT made
    # mistake not having this". Makes no network calls: send() is stubbed to
    # never produce the required phrase, no matter how many times it is told.
    class NeverComplies(myGPT2.myGPT):
        def __init__(self):
            self.checkNOTs = {}
            self.checks = {}
            self.need_redo = False
            self.reply = "a reply without the required phrase"
            self.send_calls = 0

        def send(self, nu_msg=None):
            self.send_calls += 1
            # The reply never changes: this model never complies, no matter
            # how many times doCheckNots asks it to.

    stub = NeverComplies()
    stub.checkNOTs[((("The answer is:", 1),),)] = "please include it"
    started = time.time()
    stub.doCheckNots()
    elapsed = time.time() - started

    check("it gives up rather than looping forever",
          stub.send_calls <= 6, f"sent {stub.send_calls} follow-ups")
    check("and reports need_redo so the caller knows the reply is unreliable",
          stub.need_redo is True)
    check("giving up does not itself take any real time",
          elapsed < 2, f"took {elapsed:.2f}s")

    # A model that DOES eventually comply must not be punished for the
    # earlier misses -- doCheckNots exits the moment the phrase shows up.
    class ComplyOnThirdTry(myGPT2.myGPT):
        def __init__(self):
            self.checkNOTs = {}
            self.checks = {}
            self.need_redo = False
            self.reply = "still missing it"
            self.send_calls = 0

        def send(self, nu_msg=None):
            self.send_calls += 1
            if self.send_calls >= 3:
                self.reply = "The answer is: Yes"

    stub2 = ComplyOnThirdTry()
    stub2.checkNOTs[((("The answer is:", 1),),)] = "please include it"
    stub2.doCheckNots()
    check("a model that eventually complies is not marked need_redo",
          stub2.need_redo is False)
    check("and stops asking as soon as it complies",
          stub2.send_calls == 3, f"sent {stub2.send_calls} follow-ups")

    print()
    print("--- prose and mechanical work can use different models ---")
    check("a prose model is configured", bool(myGPT2.configured_model()))
    check("a fast model is configured", bool(myGPT2.configured_fast_model()))
    check("the model can be overridden per call",
          "model" in inspect.signature(myGPT2.myGPT.__init__).parameters)
    print(f"         prose={myGPT2.configured_model()}  "
          f"fast={myGPT2.configured_fast_model()}")

    main3_src = (ROOT / "main3.py").read_text(encoding="utf-8")
    for name in ("mult_choice_question_prompts.txt",
                 "select_applicable_question_prompts.txt",
                 "drop_down_question_prompts.txt"):
        idx = main3_src.find(name)
        tail = main3_src[idx:idx + 700] if idx >= 0 else ""
        check(f"{name} uses the fast model",
              "configured_fast_model()" in tail,
              "picking from a fixed list does not need the prose model")

    print()
    print("--- the outer 'redo the whole generation' loops are bounded too ---")
    # doCheckNots giving up and setting need_redo is not the whole fix:
    # generateHeadline/generateCL/generateSummary/generateSkills/
    # process_job_file/process_job_record each wrapped their call in their
    # OWN `while doAgain:` with no cap either, so a need_redo of True just
    # made THIS loop call sendAll() again forever instead.
    check("a shared bound is defined for it", "GENERATION_REDO_LIMIT" in main3_src)
    doagain_starts = main3_src.count("doAgain = True")
    doagain_bounded = main3_src.count("while doAgain and attempts < self.GENERATION_REDO_LIMIT:")
    check("every doAgain loop is bounded, none left unbounded",
          doagain_starts == 6 and doagain_bounded == 6,
          f"{doagain_starts} loop(s) start, {doagain_bounded} are bounded -- "
          f"a mismatch means one still loops with no cap")
    # generateHeadline's split used to be [1]: fine while the loop could not
    # return without the phrase present, but doCheckNots now CAN give up and
    # hand back a reply missing it, and [1] on that is an IndexError.
    check("generateHeadline no longer indexes [1] into a possibly-missing split",
          '"The headline is:")[1]' not in main3_src,
          "a reply doCheckNots gave up on would IndexError here")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL GPT TIMEOUT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
