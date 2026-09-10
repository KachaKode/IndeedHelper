"""OpenAI credit status for the Admin tab.

Two different OpenAI accounts are in play, and they answer two different
questions:

- The REGULAR key (input/api_key.txt) is what main3.py actually spends.
  OpenAI has no endpoint that reports a remaining prepaid balance -- checked
  by hand: every /v1/dashboard/billing/* route 403s for a secret key ("must
  be made with a session key"), and there is no other candidate. The only
  way to know FOR CERTAIN whether credits are exhausted right now is to
  actually try a call and see whether it fails with RateLimitError, so
  `probe_status` spends a few tokens on the cheapest configured model to ask.

- An ADMIN key (input/admin_api_key.txt, generated separately in the org's
  settings with the api.usage.read scope) unlocks /v1/organization/costs --
  spend over time, not a balance either. There is no API for "how much was
  the last top-up" or "what is the running balance", so the Admin tab just
  asks for the top-up amount once and remembers WHEN it was told, then sums
  spend from that moment instead of a fixed rolling window. "grant minus
  spend-since-that-moment" is still an ESTIMATE, labelled as one, but it is
  one number on one clock rather than something that has to be kept in sync
  by hand.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

import requests

from myGPT2 import configured_fast_model

ADMIN_KEY_FILE = "admin_api_key.txt"
REGULAR_KEY_FILE = "api_key.txt"
GRANT_FILE = "credit_grant.json"

COSTS_URL = "https://api.openai.com/v1/organization/costs"
CHAT_URL = "https://api.openai.com/v1/chat/completions"
PROBE_TIMEOUT = 15


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _input_path(project_root: Path, filename: str) -> Path:
    return Path(project_root) / "input" / filename


def probe_status(project_root: Path) -> dict[str, Any]:
    """Try a trivial real completion and report whether it went through.

    This is the only reliable signal: it is what main3.py itself will hit on
    its next call, not an approximation of it. Talks to the REST endpoint
    directly with `requests` rather than the pinned openai==0.28.1 SDK --
    dbgui otherwise has no dependency on that package at all (runner.py runs
    main3.py as a subprocess for the same reason), and the raw HTTP response
    carries the documented `error.type` field, which is a precise signal:
    "insufficient_quota" means the balance is empty; "rate_limit_exceeded" is
    an ordinary too-many-requests limit and not the same problem at all.
    """
    key = _read_text(_input_path(project_root, REGULAR_KEY_FILE))
    if not key:
        return {"ok": False, "exhausted": None,
                "message": f"input/{REGULAR_KEY_FILE} is missing or empty."}

    try:
        resp = requests.post(
            CHAT_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": configured_fast_model(),
                  "messages": [{"role": "user", "content": "Reply with just: ok"}]},
            timeout=PROBE_TIMEOUT,
        )
    except requests.RequestException as exc:
        return {"ok": False, "exhausted": None, "message": f"Could not reach OpenAI: {exc}"}

    if resp.status_code == 200:
        return {"ok": True, "exhausted": False, "message": None}

    try:
        detail = resp.json().get("error") or {}
    except ValueError:
        detail = {}
    message = detail.get("message") or resp.text[:200] or f"HTTP {resp.status_code}"
    exhausted = resp.status_code == 429 and detail.get("type") == "insufficient_quota"
    return {"ok": False, "exhausted": exhausted, "message": message}


def _explain_costs_error(resp: requests.Response) -> str:
    try:
        payload = resp.json()
        detail = payload.get("error")
        message = detail.get("message") if isinstance(detail, dict) else detail
    except ValueError:
        message = resp.text[:200]
    message = message or f"HTTP {resp.status_code}"
    if resp.status_code == 403:
        return f"The admin key is missing the api.usage.read scope: {message}"
    if resp.status_code == 401:
        return f"The admin key was rejected: {message}"
    return f"OpenAI returned {resp.status_code}: {message}"


DEFAULT_WINDOW_DAYS = 30


def fetch_costs(project_root: Path, start_time: datetime.datetime | None = None) -> dict[str, Any]:
    """Spend per day, from the Admin Costs API.

    `start_time` is normally the moment the current grant was saved (see
    get_credit_grant), so "spend" here is spend SINCE the last top-up, not an
    arbitrary rolling window -- that is what makes "grant minus spend" a
    meaningful estimate of what is left, rather than two numbers on
    different clocks. With no grant on file yet this falls back to the last
    DEFAULT_WINDOW_DAYS days, just so the tab is not empty.

    Requires input/admin_api_key.txt. Absent that file this is not an error,
    just "not configured" -- the probe above works without it.
    """
    key = _read_text(_input_path(project_root, ADMIN_KEY_FILE))
    if not key:
        return {"configured": False}

    if start_time is None:
        start_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=DEFAULT_WINDOW_DAYS)
    days_covered = max(
        1, (datetime.datetime.now(datetime.timezone.utc) - start_time).days + 1)

    try:
        resp = requests.get(
            COSTS_URL,
            headers={"Authorization": f"Bearer {key}"},
            params={"start_time": int(start_time.timestamp()), "bucket_width": "1d",
                    "limit": days_covered + 2},
            timeout=PROBE_TIMEOUT,
        )
    except requests.RequestException as exc:
        return {"configured": True, "error": f"Could not reach OpenAI: {exc}"}

    if resp.status_code != 200:
        return {"configured": True, "error": _explain_costs_error(resp)}

    try:
        payload = resp.json()
    except ValueError:
        return {"configured": True, "error": "OpenAI's response was not valid JSON."}

    buckets = payload.get("data", payload) if isinstance(payload, dict) else payload
    series = []
    total = 0.0
    for bucket in buckets or []:
        day_total = sum(
            (result.get("amount") or {}).get("value") or 0
            for result in bucket.get("results") or []
        )
        total += day_total
        when = bucket.get("start_time")
        date = (datetime.datetime.fromtimestamp(when, tz=datetime.timezone.utc).date().isoformat()
                if when else "")
        series.append({"date": date, "amount": round(day_total, 4)})

    return {"configured": True, "totalSpend": round(total, 4), "currency": "usd", "series": series,
            "since": start_time.isoformat()}


def get_credit_grant(project_root: Path) -> dict[str, Any] | None:
    """The last top-up on file: {"amount": ..., "at": <ISO timestamp>}.

    `at` is when this was SAVED, not necessarily the real purchase moment --
    the Admin tab's copy says to enter it right after topping up, and spend
    is only ever counted from here, so a stale entry undercounts rather than
    silently drifting the other way.
    """
    text = _read_text(_input_path(project_root, GRANT_FILE))
    if not text:
        return None
    try:
        data = json.loads(text)
        return {"amount": float(data["amount"]), "at": str(data["at"])}
    except (ValueError, KeyError, TypeError):
        return None


def set_credit_grant(project_root: Path, amount: float) -> dict[str, Any]:
    record = {"amount": round(float(amount), 2),
              "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    _input_path(project_root, GRANT_FILE).write_text(json.dumps(record), encoding="utf-8")
    return record
