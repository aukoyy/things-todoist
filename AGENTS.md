# Things 3 → Todoist → Sunsama sync

One-way sync from Things 3 (macOS) into Todoist, so Sunsama can pull tasks
in via its native Todoist integration. Plus a reverse leg that completes
Things to-dos when they're completed in Todoist/Sunsama.

## Hard constraints

- macOS only. The Things SQLite DB lives under
  ~/Library/Group Containers/ — reading it requires Full Disk Access for
  whatever binary runs the sync (Terminal, the venv Python, or the
  launchd job). If reads fail with a permissions error, this is why.
  Grant it in System Settings → Privacy & Security → Full Disk Access.
- The Things DB is READ-ONLY. Never write to it, never open it read-write,
  never migrate it. All writes to Things go through the things:/// URL
  scheme, which needs the auth token from Things → Settings → General →
  Enable Things URLs.
- Secrets (Todoist API token, Things auth token) come from the environment
  or Keychain. Never commit them, never hardcode them in a plist.

## Design

- Read: things.py against the local SQLite DB. Sync every incomplete
  to-do (not projects or headings themselves).
- Write: Todoist Sync API with incremental sync tokens. All synced tasks
  land in the Todoist Inbox. Organization is labels, not projects/sections,
  with hierarchy Project > Area > Anytime: a project label if the to-do is
  in a project, else an area label, else Anytime. Inbox and Someday always
  apply when the to-do is in those lists. Things When → Todoist due date
  (that is what puts a task in Todoist Today). Deadline is appended to the
  description. If a Things area is deleted, or a project is
  deleted/completed/canceled, that Todoist label is removed
  (Inbox/Anytime/Someday are never deleted).
- Reverse: poll Todoist for completed tasks, then
  things:///update?id=<uuid>&completed=true
- State: local file mapping Things UUID ↔ Todoist task ID. The differ must
  be idempotent — running it twice in a row changes nothing.
- Schedule: launchd with StartInterval 300, not cron, so it survives sleep.
- Cap: Todoist Inbox shares the 300 active-task limit. Apply aborts if
  there are 300 or more open Things to-dos.

## Conflict rule

Things wins on all content (title, notes, dates, labels). Todoist wins only
on completion. Never write content back to Things.

## Non-negotiables for any change

- Every run supports --dry-run, and it's the default until explicitly
  disabled with --apply. This is a script that mutates two live task systems.
- Respect Todoist's rate limit; back off rather than retry tightly.
- Log what changed on every run, to a file, with timestamps. When it
  silently stops working at 6am you'll need this.

## Run / schedule

```
uv sync

# Tokens: .env (gitignored), the environment, or Keychain (service things-todoist)
# TODOIST_API_TOKEN=...
# THINGS_AUTH_TOKEN=...   # optional; falls back to the token in Things' DB
# security add-generic-password -s things-todoist -a todoist-api-token -w
# security add-generic-password -s things-todoist -a things-auth-token -w

uv run python sync.py                 # dry-run (default)
uv run python sync.py --apply         # write

scripts/install-launchd.sh            # every 5 minutes while the Mac is awake
```

Grant Full Disk Access to the venv interpreter
(`.venv/bin/python`) and/or `/bin/bash` (the launchd wrapper). Logs:
`~/Library/Logs/things-todoist/sync.log`.

## Prior art

stancl/things3-trello-sync — same idea, Trello target.
