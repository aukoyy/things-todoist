# Things → Todoist sync

## Before you use this

Most of this repo was written by an AI coding agent. I have not audited it as a product. If you clone it, you are responsible for reading the code, the tokens you give it, and anything it writes to Todoist or Things. No warranty.

## What it does

One-way sync from [Things 3](https://culturedcode.com/things/) (macOS) into the [Todoist](https://todoist.com) Inbox, so [Sunsama](https://sunsama.com) can pull those tasks in. Completing a task in Todoist or Sunsama completes it in Things.

Things wins on title, notes, dates, and labels. Todoist wins only on completion. The Things database is never written; completions go through `things:///`. That URL scheme brings Things 3 to the front, so if you complete a task in Sunsama (or Todoist), Things might open on the next sync.

Every incomplete to-do becomes an Inbox task. Organization is labels, not projects:

| Things                      | Todoist label       |
| --------------------------- | ------------------- |
| Inbox / Someday             | `Inbox` / `Someday` |
| A project                   | that project's name |
| An area (no project)        | that area's name    |
| Anytime, no project or area | `Anytime`           |

Things When → Todoist due date. Deadlines, headings, and checklists go in the description. `--apply` aborts at 300 open Things to-dos (Todoist Inbox cap).

macOS only. Needs [uv](https://docs.astral.sh/uv/) (`brew install uv`) and Full Disk Access for `.venv/bin/python` (and `/bin/bash` if you use launchd).

## Setup

```bash
git clone https://github.com/aukoyy/things-todoist.git
cd things-todoist
uv sync
```

1. Put your [Todoist API token](https://app.todoist.com/app/settings/integrations/developer) in a gitignored `.env`:

   ```
   TODOIST_API_TOKEN=your-token-here
   ```

   Or Keychain: `security add-generic-password -s things-todoist -a todoist-api-token -w`

2. In Things → Settings → General, enable **Things URLs**. The auth token is usually read from the Things DB; if reverse completion fails, set `THINGS_AUTH_TOKEN` the same way.

3. System Settings → Privacy & Security → Full Disk Access: add `.venv/bin/python` (absolute path) and `/bin/bash`.

4. Dry-run, then apply:

   ```bash
   uv run python sync.py
   uv run python sync.py --apply
   ```

Logs: `~/Library/Logs/things-todoist/sync.log`. Mapping: `~/Library/Application Support/things-todoist/mapping.json`.

Optional: connect Sunsama's Todoist integration. From the repo root, this installs the LaunchAgent that syncs every 5 minutes while the Mac is awake:

```bash
scripts/install-launchd.sh
```

Unload: `launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/com.aukoyy.things-todoist.plist`

Inspired by [stancl/things3-trello-sync](https://github.com/stancl/things3-trello-sync).
