"""Todoist Sync API client: incremental pull, batched commands, 429 backoff."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from config import MAX_COMMANDS_PER_REQUEST, SYNC_URL
from state import State

log = logging.getLogger("things_todoist")

_MAX_ATTEMPTS = 6
_TIMEOUT = 30


class TodoistError(RuntimeError):
    pass


class TodoistClient:
    def __init__(self, token: str, state: State) -> None:
        self.token = token
        self.state = state

    def pull(self) -> None:
        data = self._request(
            {
                "sync_token": self.state.sync_token,
                "resource_types": json.dumps(["items", "labels"]),
            }
        )
        self._ingest(data)
        if data.get("full_sync"):
            return
        missing = [
            tid for tid in self.state.mapping.values() if tid not in self.state.items
        ]
        if not missing:
            return
        log.info(
            "mapped Todoist items missing after incremental sync; pulling full state"
        )
        self.state.sync_token = "*"
        data = self._request(
            {
                "sync_token": "*",
                "resource_types": json.dumps(["items", "labels"]),
            }
        )
        self._ingest(data)

    def push(self, commands: list[dict]) -> dict[str, Any]:
        """Send commands in chunks of 100. Returns merged temp_id_mapping and sync_status."""
        merged_temp: dict[str, str] = {}
        merged_status: dict[str, Any] = {}
        for start in range(0, len(commands), MAX_COMMANDS_PER_REQUEST):
            chunk = commands[start : start + MAX_COMMANDS_PER_REQUEST]
            data = self._request(
                {
                    "sync_token": self.state.sync_token,
                    "resource_types": json.dumps(["items", "labels"]),
                    "commands": json.dumps(chunk),
                }
            )
            self._ingest(data)
            merged_temp.update(data.get("temp_id_mapping") or {})
            merged_status.update(data.get("sync_status") or {})
        return {"temp_id_mapping": merged_temp, "sync_status": merged_status}

    def _ingest(self, data: dict) -> None:
        self.state.sync_token = data.get("sync_token") or self.state.sync_token
        if data.get("full_sync"):
            self.state.items = {}
            self.state.labels = {}
        for item in data.get("items") or []:
            item_id = str(item["id"])
            if item.get("is_deleted"):
                self.state.items.pop(item_id, None)
            else:
                self.state.items[item_id] = item
        for label in data.get("labels") or []:
            name = label.get("name")
            if not name:
                continue
            if label.get("is_deleted"):
                self.state.labels.pop(name, None)
            else:
                self.state.labels[name] = str(label["id"])

    def _request(self, fields: dict[str, str]) -> dict:
        body = urllib.parse.urlencode(fields).encode()
        delay = 1.0
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            req = urllib.request.Request(
                SYNC_URL,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "things-todoist/1.0",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                    payload = json.loads(resp.read().decode())
                return payload
            except urllib.error.HTTPError as exc:
                last_error = exc
                detail = exc.read().decode(errors="replace")
                retry_after = _retry_after_seconds(exc, detail)
                if exc.code == 401:
                    raise TodoistError(
                        "Todoist rejected the API token (401). Check TODOIST_API_TOKEN."
                    ) from exc
                if exc.code == 429 or exc.code >= 500:
                    wait = retry_after if retry_after is not None else delay
                    log.warning(
                        "Todoist HTTP %s; backing off %.1fs (attempt %d/%d)",
                        exc.code,
                        wait,
                        attempt,
                        _MAX_ATTEMPTS,
                    )
                    time.sleep(wait)
                    delay = min(delay * 2, 60)
                    continue
                raise TodoistError(
                    f"Todoist HTTP {exc.code}: {detail[:500]}"
                ) from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                log.warning(
                    "Todoist request failed (%s); backing off %.1fs (attempt %d/%d)",
                    exc,
                    delay,
                    attempt,
                    _MAX_ATTEMPTS,
                )
                time.sleep(delay)
                delay = min(delay * 2, 60)
        raise TodoistError(f"Todoist request failed after retries: {last_error}")


def command(type_: str, args: dict, temp_id: str | None = None) -> dict:
    cmd: dict[str, Any] = {
        "type": type_,
        "uuid": str(uuid.uuid4()),
        "args": args,
    }
    if temp_id is None and type_.endswith("_add"):
        temp_id = str(uuid.uuid4())
    if temp_id is not None:
        cmd["temp_id"] = temp_id
    return cmd


def due_object(date: str | None) -> dict | None:
    if not date:
        return None
    return {"date": date, "timezone": None}


def snapshot_item(item: dict) -> dict:
    due = item.get("due") or {}
    due_date = None
    if isinstance(due, dict) and due.get("date"):
        due_date = str(due["date"])[:10]
    return {
        "content": item.get("content") or "",
        "description": item.get("description") or "",
        "labels": list(item.get("labels") or []),
        "due_date": due_date,
        "checked": bool(item.get("checked")),
        "is_deleted": bool(item.get("is_deleted")),
        "completed_at": item.get("completed_at"),
    }


def _retry_after_seconds(exc: urllib.error.HTTPError, body: str) -> float | None:
    raw = exc.headers.get("Retry-After") if exc.headers else None
    if raw is not None:
        try:
            return float(raw)
        except ValueError:
            pass
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict) and parsed.get("retry_after") is not None:
            return float(parsed["retry_after"])
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return None
