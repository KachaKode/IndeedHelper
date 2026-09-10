"""Guards the config files and the way their failures are reported.

Two things are checked:

  1. The real config/ files agree with each other. A single-character typo
     ("looking fo r" vs "looking for") once silently stopped the bot dead.

  2. When they DO disagree, validate_files raises a catchable ConfigMismatch
     rather than calling sys.exit(). That distinction matters: RunUser runs on a
     worker thread, and SystemExit does not derive from Exception, so sys.exit()
     killed the thread without a word while the process kept running and looked
     merely idle.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main3  # noqa: E402

CONFIG_FILES = ("States.txt", "ExpectedEnvironments.txt", "StateTransitions.txt")
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        if detail:
            print(f"         {detail}")
        failures.append(label)


def state_machine_for(config_dir: Path):
    helper = main3.IndeedHelper.__new__(main3.IndeedHelper)
    helper.configPath = str(config_dir) + "\\"
    sm = main3.StateMachine.__new__(main3.StateMachine)
    sm.helper = helper
    return sm


def main() -> int:
    # 1. the real files -------------------------------------------------------
    sm = state_machine_for(ROOT / "config")
    try:
        sm.validate_files(*CONFIG_FILES)
        check("real config files agree with each other", True)
    except main3.ConfigMismatch as exc:
        check("real config files agree with each other", False, str(exc)[:300])
    except SystemExit:
        check("real config files agree with each other", False,
              "validate_files called sys.exit()")

    # 2. a deliberate mismatch is reported, not fatal --------------------------
    tmp = Path(tempfile.mkdtemp())
    try:
        cfg = tmp / "config"
        cfg.mkdir()
        for name in CONFIG_FILES:
            shutil.copy2(ROOT / "config" / name, cfg / name)

        broken = cfg / "StateTransitions.txt"
        broken.write_text(
            broken.read_text(encoding="utf-8").replace(
                "looking for specific", "looking fo r specific"),
            encoding="utf-8",
        )

        raised = None
        try:
            state_machine_for(cfg).validate_files(*CONFIG_FILES)
        except BaseException as exc:  # noqa: BLE001 - identifying the type is the point
            raised = exc

        check("a mismatch is reported", raised is not None,
              "validate_files accepted files that disagree")
        check("mismatch raises ConfigMismatch, not SystemExit",
              isinstance(raised, main3.ConfigMismatch),
              f"got {type(raised).__name__}")
        check("ConfigMismatch is catchable by RunUser's `except Exception`",
              isinstance(raised, Exception),
              "a BaseException here would kill the worker thread silently")
        check("the message names the offending text",
              raised is not None and "qualifications" in str(raised),
              f"message was {str(raised)[:160]!r}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL CONFIG VALIDATION TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
