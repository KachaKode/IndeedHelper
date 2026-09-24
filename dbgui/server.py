"""Flask JSON API behind the database admin UI.

Read-only enforcement is structural rather than a flag: there is simply no
POST/PUT/DELETE route for `applications` or `applicationsOld`, so the historical
record cannot be modified through this API even by a malformed request.

Bound to 127.0.0.1 only -- this serves a local desktop window, never a network.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from . import billing
from .data import (
    ACTIVE_CHOICES,
    APPLICATION_FIELDS,
    EDU_FIELDS,
    JOB_FIELDS,
    USER_EDITABLE_FIELDS,
    USER_MULTILINE_FIELDS,
    VETTED_QUESTION_TYPES,
    VETTED_STATUS_CHOICES,
    YES_NO_CHOICES,
    IndeedDB,
    rename_user_folder,
    to_display,
    user_folder_name,
    user_folder_path,
)
from .runner import PreflightError, RunnerManager

PAGE_SIZE = 50


def _json_body() -> dict[str, Any]:
    return request.get_json(silent=True) or {}


def create_app(db: IndeedDB, runner: RunnerManager | None = None) -> Flask:
    # static_url_path="" so the page can reference /css/... and /js/... directly.
    app = Flask(__name__, static_folder="static", static_url_path="")
    runner = runner or RunnerManager(db, db.project_root)

    @app.after_request
    def no_store(response):
        # The window can stay open for hours across edits to the JS/CSS; without
        # this, WebView2 can keep serving a stale copy of the UI.
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    # ------------------------------------------------------------- metadata --

    @app.get("/api/meta")
    def meta():
        return jsonify({
            "activeChoices": [{"label": lbl, "value": val} for lbl, val in ACTIVE_CHOICES],
            "yesNoChoices": [{"label": lbl, "value": val} for lbl, val in YES_NO_CHOICES],
            "jobFields": list(JOB_FIELDS),
            "eduFields": list(EDU_FIELDS),
            "userFields": list(USER_EDITABLE_FIELDS),
            "multilineFields": list(USER_MULTILINE_FIELDS),
            "applicationFields": list(APPLICATION_FIELDS),
            "vettedQuestionTypes": list(VETTED_QUESTION_TYPES),
            "vettedStatusChoices": [{"label": lbl, "value": val} for lbl, val in VETTED_STATUS_CHOICES],
            "dbPath": str(db.db_path),
            "pageSize": PAGE_SIZE,
        })

    # ---------------------------------------------------------------- users --

    @app.get("/api/users")
    def list_users():
        users = db.list_users()
        for user in users:
            folder = user_folder_path(db.project_root, user)
            user["_folderName"] = user_folder_name(user)
            user["_folderExists"] = folder.exists()
        return jsonify(users)

    @app.get("/api/users/<int:user_id>")
    def get_user(user_id: int):
        user = db.get_user(user_id)
        if user is None:
            return jsonify({"error": "No such user"}), 404
        # Hand the UI newline-delimited text; CRLF is restored on save.
        for field in USER_MULTILINE_FIELDS:
            user[field] = to_display(user.get(field))
        user["_folderName"] = user_folder_name(user)
        user["_folderExists"] = user_folder_path(db.project_root, user).exists()
        return jsonify(user)

    @app.post("/api/users")
    def create_user():
        body = _json_body()
        new_id = db.add_user(
            body.get("FirstName") or "New",
            body.get("LastName") or "User",
        )
        return jsonify({"id": new_id}), 201

    @app.put("/api/users/<int:user_id>")
    def update_user(user_id: int):
        body = _json_body()
        before = db.get_user(user_id)
        if before is None:
            return jsonify({"error": "No such user"}), 404

        old_folder = user_folder_name(before)
        db.save_user(user_id, body)
        after = db.get_user(user_id)
        new_folder = user_folder_name(after)

        result: dict[str, Any] = {"ok": True, "folderRenamePending": None}
        if old_folder != new_folder:
            source_exists = (Path(db.project_root) / "Users" / old_folder).exists()
            target_exists = (Path(db.project_root) / "Users" / new_folder).exists()
            result["folderRenamePending"] = {
                "from": old_folder,
                "to": new_folder,
                "sourceExists": source_exists,
                "targetExists": target_exists,
            }
        return jsonify(result)

    @app.post("/api/users/<int:user_id>/rename-folder")
    def do_rename_folder(user_id: int):
        body = _json_body()
        try:
            renamed = rename_user_folder(db.project_root, body.get("from", ""), body.get("to", ""))
        except FileExistsError as exc:
            return jsonify({"error": str(exc)}), 409
        except OSError as exc:
            return jsonify({"error": f"Could not rename folder: {exc}"}), 500
        return jsonify({"renamed": renamed})

    @app.get("/api/users/<int:user_id>/orphans")
    def user_orphans(user_id: int):
        return jsonify(db.user_orphan_counts(user_id))

    @app.delete("/api/users/<int:user_id>")
    def remove_user(user_id: int):
        if db.get_user(user_id) is None:
            return jsonify({"error": "No such user"}), 404
        db.delete_user(user_id)
        return jsonify({"ok": True})

    @app.get("/api/users/<int:user_id>/validate")
    def validate(user_id: int):
        return jsonify([asdict(issue) for issue in db.validate_user(user_id)])

    # --------------------------------------------------------- job searches --

    @app.get("/api/users/<int:user_id>/searches")
    def list_searches(user_id: int):
        searches = db.list_searches(user_id)
        # 0 for every row when nothing is running for this user, rather than
        # an extra round trip the frontend would have to special-case.
        session_counts = runner.applications_by_search(user_id)
        for row in searches:
            row["sessionApplications"] = session_counts.get(row["id"], 0)
        return jsonify(searches)

    @app.post("/api/users/<int:user_id>/searches")
    def create_search(user_id: int):
        body = _json_body()
        new_id = db.add_search(
            user_id,
            body.get("url", ""),
            body.get("job_nums", ""),
            body.get("edu_nums", ""),
            body.get("target_position", ""),
            body.get("max_applications", 0),
        )
        return jsonify({"id": new_id}), 201

    @app.put("/api/searches/<int:search_id>")
    def update_search(search_id: int):
        db.save_search(search_id, _json_body())
        return jsonify({"ok": True})

    @app.delete("/api/searches/<int:search_id>")
    def remove_search(search_id: int):
        db.delete_search(search_id)
        return jsonify({"ok": True})

    @app.post("/api/users/<int:user_id>/searches/reorder")
    def reorder(user_id: int):
        ids = _json_body().get("ids") or []
        db.reorder_searches(user_id, [int(i) for i in ids])
        return jsonify({"ok": True})

    # ----------------------------------------------------- vetted questions --
    # No create route: rows only ever come from the seed script or the live
    # bot's own runtime hook, never a manual "add a vetted question" action.

    @app.get("/api/users/<int:user_id>/vetted-questions")
    def list_vetted_questions(user_id: int):
        status = request.args.get("status") or None
        sort = request.args.get("sort", "default")
        return jsonify(db.list_vetted_questions(user_id, status=status, sort=sort))

    @app.put("/api/vetted-questions/<int:vetted_id>")
    def update_vetted_question(vetted_id: int):
        db.save_vetted_question(vetted_id, _json_body())
        return jsonify({"ok": True})

    @app.post("/api/vetted-questions/<int:vetted_id>/status")
    def set_vetted_question_status(vetted_id: int):
        db.set_vetted_status(vetted_id, _json_body().get("status"))
        return jsonify({"ok": True})

    @app.delete("/api/vetted-questions/<int:vetted_id>")
    def remove_vetted_question(vetted_id: int):
        db.delete_vetted_question(vetted_id)
        return jsonify({"ok": True})

    @app.delete("/api/users/<int:user_id>/vetted-questions")
    def clear_vetted_questions(user_id: int):
        status = request.args.get("status") or None
        db.delete_vetted_questions(user_id, status)
        return jsonify({"ok": True})

    # ------------------------------------------------------ work history/edu --

    @app.get("/api/users/<int:user_id>/jobs")
    def list_jobs(user_id: int):
        return jsonify(db.list_jobs(user_id))

    @app.post("/api/users/<int:user_id>/jobs")
    def create_job(user_id: int):
        return jsonify({"rowid": db.add_job(user_id)}), 201

    @app.put("/api/jobs/<int:rowid>")
    def update_job(rowid: int):
        db.save_job(rowid, _json_body())
        return jsonify({"ok": True})

    @app.delete("/api/jobs/<int:rowid>")
    def remove_job(rowid: int):
        db.delete_row("Job", rowid)
        return jsonify({"ok": True})

    @app.get("/api/users/<int:user_id>/edu")
    def list_edu(user_id: int):
        return jsonify(db.list_edu(user_id))

    @app.post("/api/users/<int:user_id>/edu")
    def create_edu(user_id: int):
        return jsonify({"rowid": db.add_edu(user_id)}), 201

    @app.put("/api/edu/<int:rowid>")
    def update_edu(rowid: int):
        db.save_edu(rowid, _json_body())
        return jsonify({"ok": True})

    @app.delete("/api/edu/<int:rowid>")
    def remove_edu(rowid: int):
        db.delete_row("Edu", rowid)
        return jsonify({"ok": True})

    # ------------------------------------------------- applications (READ ONLY) --
    # Deliberately GET-only. No write route exists for these tables.

    @app.get("/api/applications")
    def list_applications():
        raw_user = request.args.get("user_id", "").strip()
        user_id = int(raw_user) if raw_user.isdigit() else None
        search = request.args.get("search", "")
        page = max(1, int(request.args.get("page", "1") or 1))
        offset = (page - 1) * PAGE_SIZE

        total = db.count_applications(user_id, search)
        rows = db.list_applications(user_id, search, limit=PAGE_SIZE, offset=offset)
        return jsonify({
            "rows": rows,
            "total": total,
            "page": page,
            "pageSize": PAGE_SIZE,
            "pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
        })

    @app.get("/api/applications/<int:app_id>")
    def get_application(app_id: int):
        record = db.get_application(app_id)
        if record is None:
            return jsonify({"error": "No such application"}), 404
        return jsonify(record)

    @app.get("/api/applications-old")
    def list_applications_old():
        return jsonify(db.list_applications_old())

    # ------------------------------------------------------------- run control --

    @app.post("/api/run/selection")
    def set_selection():
        """Ticking users in the Run screen writes the Active column, so the GUI
        and a standalone `python main3.py` always agree on who runs."""
        wanted = {int(i) for i in (_json_body().get("userIds") or [])}
        for user in db.list_users():
            desired = "T" if user["id"] in wanted else "F"
            if str(user.get("Active") or "").upper() != desired:
                db.save_user(user["id"], {"Active": desired})
        return jsonify({"selected": sorted(wanted)})

    @app.get("/api/run/preflight")
    def run_preflight():
        raw = request.args.get("user_ids", "")
        ids = [int(part) for part in raw.split(",") if part.strip().isdigit()]
        return jsonify(runner.preflight(ids))

    @app.post("/api/run/start")
    def run_start():
        ids = [int(i) for i in (_json_body().get("userIds") or [])]
        if not ids:
            return jsonify({"error": "Select at least one user to run."}), 400
        try:
            return jsonify(runner.start(ids))
        except PreflightError as exc:
            return jsonify({"error": str(exc)}), 409

    @app.post("/api/run/stop")
    def run_stop():
        body = _json_body()
        if body.get("all"):
            return jsonify({"stopped": runner.stop_all()})
        user_id = body.get("userId")
        if user_id is None:
            return jsonify({"error": "Pass userId or all:true"}), 400
        return jsonify({"stopped": [int(user_id)] if runner.stop(int(user_id)) else []})

    @app.get("/api/run/status")
    def run_status():
        return jsonify({"runs": runner.status(), "anyRunning": runner.any_running()})

    @app.get("/api/run/log/<int:user_id>")
    def run_log(user_id: int):
        """The complete log for a run. The Run tab only displays a tail, but Copy
        needs the whole thing -- the start of a run is usually where the useful
        part is."""
        text = runner.full_log(user_id)
        return app.response_class(text, mimetype="text/plain; charset=utf-8")

    @app.post("/api/run/command")
    def run_command():
        """Drive a running bot: pause it, let it apply, or send it home.

        "home" also pauses, so the browser lands on the search page and stays
        there rather than immediately carrying on.
        """
        body = _json_body()
        user_id = body.get("userId")
        action = body.get("action")
        if user_id is None:
            return jsonify({"error": "Pass userId"}), 400

        actions = {
            "pause": {"mode": "paused", "command": None},
            "resume": {"mode": "running", "command": None},
            "home": {"mode": "paused", "command": "home"},
        }
        if action not in actions:
            return jsonify({"error": f"Unknown action {action!r}"}), 400

        result = runner.write_control(int(user_id), **actions[action])
        return jsonify({"ok": True, "control": result})

    # ----------------------------------------------------------------- admin --

    @app.get("/api/admin/probe")
    def admin_probe():
        """Lightweight: just the live call, no Costs API round trip. Used for
        the background poll that drives the app-wide low-credit banner."""
        return jsonify(billing.probe_status(db.project_root))

    @app.get("/api/admin/status")
    def admin_status():
        """Everything the Admin tab shows, refreshed on every visit.

        Spend is summed from the moment the current grant was saved, not a
        fixed rolling window, so "grant minus spend" are on the same clock.
        """
        grant = billing.get_credit_grant(db.project_root)
        since = datetime.fromisoformat(grant["at"]) if grant else None
        return jsonify({
            "probe": billing.probe_status(db.project_root),
            "costs": billing.fetch_costs(db.project_root, start_time=since),
            "grant": grant,
        })

    @app.put("/api/admin/grant")
    def admin_set_grant():
        body = _json_body()
        try:
            amount = float(body.get("amount"))
        except (TypeError, ValueError):
            return jsonify({"error": "amount must be a number"}), 400
        if amount < 0:
            return jsonify({"error": "amount cannot be negative"}), 400
        grant = billing.set_credit_grant(db.project_root, amount)
        return jsonify({"ok": True, "grant": grant})

    return app
