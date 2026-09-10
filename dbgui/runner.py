"""Supervises bot runs launched from the GUI.

One OS process per selected user (`main3.py --user-id N`) rather than threads
inside the GUI process. That buys three things worth the extra plumbing:

  * a hung browser or a crashed run can only take down that one user, never the
    admin window,
  * Playwright's sync API gets its own process, which is how it wants to live,
  * `main3.py` stays runnable on its own exactly as before.

Log output is kept in a bounded deque per user. This is deliberate: the GUI it
replaces accumulated an unbounded rich-text log and got slow, so here old lines
fall off the end instead.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any

from .data import IndeedDB, user_folder_name, user_folder_path

MAX_LOG_LINES = 200
VALID_MODES = ("running", "paused")


class PreflightError(Exception):
    """A run was blocked before any browser was launched."""


class UserRun:
    def __init__(self, user_id: int, label: str, process: subprocess.Popen,
                 log_path: Path | None = None) -> None:
        self.user_id = user_id
        self.label = label
        self.process = process
        # The deque below only keeps a tail for display. Everything the run ever
        # printed goes to this file, so Copy can hand back the whole thing --
        # losing the start of a run is exactly what makes a stall hard to read.
        self.log_path = log_path
        self._log_file = None
        if log_path is not None:
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                self._log_file = log_path.open("w", encoding="utf-8", errors="replace")
            except OSError:
                self._log_file = None
        self.started_at = datetime.datetime.now()
        self.state = "starting"
        self.last_error: str | None = None
        self.attention_reason: str | None = None
        self.last_activity: str | None = None
        self.lines: deque[str] = deque(maxlen=MAX_LOG_LINES)
        self.stopped_at: datetime.datetime | None = None

    def note(self, line: str) -> None:
        self.lines.append(line)
        if self._log_file is not None:
            try:
                self._log_file.write(line + "\n")
                self._log_file.flush()
            except (OSError, ValueError):
                self._log_file = None      # keep running even if the file goes away
        # The bot's own trace format is "[CT] <elapsed> | <where> | <what> | <extra>".
        if "| ERROR |" in line:
            self.state = "error"
            self.last_error = line.split("| ERROR |", 1)[1].strip()
        elif "NEEDS ATTENTION" in line:
            self.state = "attention"
            # The trailing detail names which situation it is.
            detail = line.split("|")[-1].strip()
            reason = detail.split("--")[0].strip() or "Something"
            self.attention_reason = reason
            self.last_activity = (f"{reason.title()}: the run is paused and waiting for you. "
                                  f"Check the browser window, then press Start applying.")
        elif "ATTENTION CLEARED" in line:
            self.state = "paused"
            self.attention_reason = None
            self.last_activity = "Resolved. Press Start applying to continue."
        elif "| PAUSED |" in line:
            self.state = "paused"
        elif "| RESUMED" in line:
            self.state = "running"
        elif "| READY |" in line:
            self.state = "paused"
            self.last_activity = "On the home page, waiting for you."
        elif "start_up | EXIT" in line:
            self.state = "starting"
        elif "reportAction |" in line:
            self.last_activity = line.split("reportAction |", 1)[1].strip()[:160]
        elif "| ENTER |" in line and self.state == "starting":
            self.last_activity = line.split("| ENTER |", 1)[1].strip()[:160]

    def is_alive(self) -> bool:
        return self.process.poll() is None


class RunnerManager:
    def __init__(self, db: IndeedDB, project_root: Path) -> None:
        self.db = db
        self.project_root = Path(project_root)
        self.runs: dict[int, UserRun] = {}
        self._lock = threading.Lock()

    # -------------------------------------------------------- run control --
    # Mirrors main3.RunControl. The GUI is the only writer of these files.

    def _control_path(self, user_id: int) -> Path:
        return self.project_root / "runtime" / f"control_{user_id}.json"

    def read_control(self, user_id: int) -> dict[str, Any]:
        try:
            data = json.loads(self._control_path(user_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        mode = data.get("mode")
        return {
            "mode": mode if mode in VALID_MODES else "paused",
            "seq": int(data.get("seq") or 0),
            "command": data.get("command"),
        }

    def write_control(self, user_id: int, mode: str | None = None,
                      command: str | None = None) -> dict[str, Any]:
        """Set the mode and/or queue a one-shot command.

        `seq` increments on every write so the bot can tell a new command from
        the one it already acted on.
        """
        current = self.read_control(user_id)
        payload = {
            "mode": mode if mode in VALID_MODES else current["mode"],
            "command": command,
            "seq": current["seq"] + 1,
        }
        path = self._control_path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-replace so the bot never reads a half-written file.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
        return payload

    # ------------------------------------------------------------ preflight --

    def preflight(self, user_ids: list[int]) -> list[dict[str, Any]]:
        """Problems that would make a run fail, found before launching anything.

        Blocking issues stop the run; warnings are shown but allowed.
        """
        problems: list[dict[str, Any]] = []
        users = {u["id"]: u for u in self.db.list_users()}

        # Chrome refuses to open a second instance against a user-data-dir that
        # is already in use, and the failure surfaces as an unhelpful "DevTools
        # endpoint never came up", so catch it here instead.
        by_profile: dict[str, list[int]] = {}
        for user_id in user_ids:
            user = users.get(user_id)
            if not user:
                problems.append({"userId": user_id, "blocking": True,
                                 "message": f"User {user_id} no longer exists."})
                continue
            path = (user.get("ProfilePath") or "").strip()
            if path:
                by_profile.setdefault(path.lower(), []).append(user_id)

        for path, ids in by_profile.items():
            if len(ids) > 1:
                names = ", ".join(
                    f"{users[i].get('FirstName','')} {users[i].get('LastName','')} (#{i})".strip()
                    for i in ids
                )
                problems.append({
                    "userId": ids[0], "blocking": True,
                    "message": (f"{names} all use the same Chrome profile folder. "
                                f"Chrome can only run one window per profile, so these cannot "
                                f"run at the same time. Give each user their own Chrome profile "
                                f"path, or run them one at a time."),
                })

        for user_id in user_ids:
            user = users.get(user_id)
            if not user:
                continue
            label = f"{user.get('FirstName','')} {user.get('LastName','')}".strip() or f"User {user_id}"

            if user_id in self.runs and self.runs[user_id].is_alive():
                problems.append({"userId": user_id, "blocking": True,
                                 "message": f"{label} is already running."})

            if not (user.get("ProfilePath") or "").strip():
                problems.append({"userId": user_id, "blocking": True,
                                 "message": f"{label} has no Chrome profile path set."})

            if int(user.get("AppsLeft") or 0) <= 0:
                problems.append({"userId": user_id, "blocking": True,
                                 "message": f"{label} has no applications left."})

            if not self.db.list_searches(user_id):
                problems.append({"userId": user_id, "blocking": True,
                                 "message": f"{label} has no job searches configured."})

            if not user_folder_path(self.project_root, user).exists():
                problems.append({"userId": user_id, "blocking": True,
                                 "message": (f"{label} is missing its folder "
                                             f"Users/{user_folder_name(user)}, which the bot "
                                             f"writes its output into.")})
        return problems

    # ------------------------------------------------------------ lifecycle --

    def start(self, user_ids: list[int]) -> dict[str, Any]:
        problems = self.preflight(user_ids)
        blocking = [p for p in problems if p.get("blocking")]
        if blocking:
            raise PreflightError("; ".join(p["message"] for p in blocking))

        users = {u["id"]: u for u in self.db.list_users()}
        started = []
        with self._lock:
            for user_id in user_ids:
                user = users[user_id]
                label = f"{user.get('FirstName','')} {user.get('LastName','')}".strip() or f"User {user_id}"
                # Start paused: the browser opens on the home page and waits.
                self.write_control(user_id, mode="paused", command=None)
                # -u (unbuffered) matters: without it, plain print() output from
                # the bot and the GPT helpers sits in a pipe buffer indefinitely,
                # so a failure that is being logged still looks like silence.
                env = dict(os.environ, PYTHONUNBUFFERED="1")
                process = subprocess.Popen(
                    [sys.executable, "-u", str(self.project_root / "main3.py"),
                     "--user-id", str(user_id)],
                    cwd=str(self.project_root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                )
                stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                log_path = self.project_root / "runtime" / "logs" / f"run_{user_id}_{stamp}.log"
                run = UserRun(user_id, label, process, log_path=log_path)
                self.runs[user_id] = run
                threading.Thread(target=self._pump, args=(run,), daemon=True).start()
                started.append(user_id)
        return {"started": started}

    def _pump(self, run: UserRun) -> None:
        """Drain the child's output so it never blocks on a full pipe."""
        try:
            for raw in run.process.stdout:
                line = raw.rstrip("\n")
                if line:
                    run.note(line)
                    # A bot check, or a page the bot does not recognise, needs a
                    # person -- so stop the run rather than letting it push on.
                    # Done here so the GUI stays the only writer of the control file.
                    if "NEEDS ATTENTION" in line:
                        self.write_control(run.user_id, mode="paused")
        except Exception as exc:  # noqa: BLE001 - reading a dying pipe should not kill the thread
            run.note(f"[runner] stopped reading output: {exc}")
        finally:
            code = run.process.wait()
            if run._log_file is not None:
                try:
                    run._log_file.flush()
                    run._log_file.close()
                except (OSError, ValueError):
                    pass
                run._log_file = None
            run.stopped_at = datetime.datetime.now()
            if run.state != "stopped":
                run.state = "stopped" if code == 0 else "error"
            if code != 0 and not run.last_error:
                run.last_error = f"Process exited with code {code}."

    def stop(self, user_id: int) -> bool:
        with self._lock:
            run = self.runs.get(user_id)
        if run is None or not run.is_alive():
            return False
        run.state = "stopped"
        run.process.terminate()
        try:
            run.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            run.process.kill()
        return True

    def stop_all(self) -> list[int]:
        with self._lock:
            ids = list(self.runs)
        return [uid for uid in ids if self.stop(uid)]

    # --------------------------------------------------------------- status --

    def status(self) -> list[dict[str, Any]]:
        out = []
        with self._lock:
            runs = list(self.runs.values())
        for run in runs:
            alive = run.is_alive()
            if not alive and run.state in ("starting", "running"):
                run.state = "stopped"
            out.append({
                "userId": run.user_id,
                "label": run.label,
                "state": run.state,
                "attentionReason": run.attention_reason,
                "mode": self.read_control(run.user_id)["mode"],
                "alive": alive,
                "startedAt": run.started_at.isoformat(timespec="seconds"),
                "uptimeSeconds": int(
                    ((run.stopped_at or datetime.datetime.now()) - run.started_at).total_seconds()
                ),
                "lastError": run.last_error,
                "lastActivity": run.last_activity,
                "applicationsThisRun": self._applications_since(run),
                "lines": list(run.lines),
            })
        return out

    def _applications_since(self, run: UserRun) -> int:
        """Counted from the applications table rather than parsed out of the log,
        so the number reflects what was actually written."""
        stamp = run.started_at.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self.db._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM applications WHERE user_id = ? AND DateTime >= ?",
                    (run.user_id, stamp),
                ).fetchone()
            return int(row[0])
        except Exception:  # noqa: BLE001 - a status poll must never raise
            return 0

    def full_log(self, user_id: int) -> str:
        """Everything this run has printed, not just the displayed tail."""
        with self._lock:
            run = self.runs.get(user_id)
        if run is None:
            return ""
        if run.log_path is not None and run.log_path.exists():
            try:
                return run.log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        # No file (or it vanished): the tail is better than nothing.
        return "\n".join(run.lines)

    def any_running(self) -> bool:
        with self._lock:
            return any(run.is_alive() for run in self.runs.values())
