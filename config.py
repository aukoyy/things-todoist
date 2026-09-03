"""Paths, secrets, and constants. Secrets come from env or Keychain — never a plist."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

APP_NAME = "things-todoist"
KEYCHAIN_SERVICE = "things-todoist"
INBOX_ACTIVE_LIMIT = 300
LIST_LABELS = ("Inbox", "Today", "Anytime", "Someday")
MAX_COMMANDS_PER_REQUEST = 100
SYNC_URL = "https://api.todoist.com/api/v1/sync"

HOME = Path.home()
ROOT = Path(__file__).resolve().parent
STATE_DIR = HOME / "Library" / "Application Support" / APP_NAME
LOG_DIR = HOME / "Library" / "Logs" / APP_NAME
STATE_PATH = STATE_DIR / "mapping.json"
LOG_PATH = LOG_DIR / "sync.log"
ENV_PATH = ROOT / ".env"


def load_dotenv(path: Path = ENV_PATH) -> None:
    """Load KEY=VALUE pairs from .env without overriding existing env vars."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _keychain(account: str) -> str | None:
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            account,
            "-w",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def todoist_token() -> str:
    load_dotenv()
    token = os.environ.get("TODOIST_API_TOKEN") or _keychain("todoist-api-token")
    if not token:
        raise SystemExit(
            "Missing Todoist API token. Set TODOIST_API_TOKEN in .env or the "
            "environment, or add a Keychain item (service things-todoist, "
            "account todoist-api-token)."
        )
    return token


def things_auth_token() -> str | None:
    load_dotenv()
    token = os.environ.get("THINGS_AUTH_TOKEN") or _keychain("things-auth-token")
    if token:
        return token
    try:
        import things

        return things.token()
    except Exception:
        return None
