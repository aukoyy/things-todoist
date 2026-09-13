#!/bin/bash
# Load tokens from the environment or Keychain, then run an applying sync.
# Secrets never live in the launchd plist.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin:${PATH:-}"

# sync.py also reads ROOT/.env; Keychain is a fallback when .env is absent.
load_secret() {
  local account="$1"
  local varname="$2"
  if [[ -n "${!varname:-}" ]]; then
    return 0
  fi
  local value
  value="$(security find-generic-password -s things-todoist -a "$account" -w 2>/dev/null || true)"
  if [[ -n "$value" ]]; then
    export "${varname}=${value}"
  fi
}

load_secret todoist-api-token TODOIST_API_TOKEN
load_secret things-auth-token THINGS_AUTH_TOKEN

PYTHON="${ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "things-todoist: missing ${PYTHON}. Run: uv sync" >&2
  exit 1
fi

exec "$PYTHON" "${ROOT}/sync.py" --apply
