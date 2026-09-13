# Things → Todoist sync

One-way sync from [Things 3](https://culturedcode.com/things/) on macOS into [Todoist](https://todoist.com), so [Sunsama](https://sunsama.com) can pull those tasks through its native Todoist integration.

Things stays the source of truth for titles, notes, dates, and organization. Completing a task in Todoist or Sunsama completes it in Things.

This is a local Python script plus an optional `launchd` job. It is macOS-only because it reads the Things SQLite database on disk.

## How it works

Every incomplete Things to-do is mirrored as a task in the **Todoist Inbox**. Projects and headings themselves are not synced.

Organization in Todoist is **labels**, not projects or sections:

| Things location | Todoist labels |
| --- | --- |
| Inbox | `Inbox` |
| Someday | `Someday` |
| A project | that project's name |
| An area (no project) | that area's name |
| Anytime, no project or area | `Anytime` |

Inbox and Someday always apply when the to-do is in those lists. A project label wins over an area label.

Things **When** becomes the Todoist due date (that is what puts a task in Todoist Today). Deadlines, headings, and checklists are appended to the description.

If a Things area is deleted, or a project is deleted, completed, or canceled, that Todoist label is removed. `Inbox`, `Anytime`, and `Someday` are never deleted.

### Conflict rule

- **Things wins** on content: title, notes, dates, labels.
- **Todoist wins** only on completion.
- The script never writes content back to Things, and never opens the Things database read-write. Completions go through the `things:///` URL scheme.

The differ is idempotent: running it twice in a row with no changes does nothing.

### Limits

Todoist's Inbox shares a **300 active-task** cap. `--apply` aborts if you have 300 or more open Things to-dos. Dry-run still reports what it would do.

## Requirements

- A Mac with Things 3 installed and in use
- A Todoist account
- [uv](https://docs.astral.sh/uv/) (`brew install uv`)
- Python 3.10 or newer (`uv` will install it if needed)
- Full Disk Access for the Python that runs the sync (Things stores its database under `~/Library/Group Containers/`)
- Optional: Sunsama, if that is why you are syncing into Todoist

## Setup

### 1. Clone and install

```bash
git clone https://github.com/aukoyy/things-todoist.git
cd things-todoist

uv sync
```

### 2. Get a Todoist API token

1. Open [Todoist Settings → Integrations → Developer](https://app.todoist.com/app/settings/integrations/developer).
2. Copy your API token.

Put it in a `.env` file in the repo root (gitignored):

```
TODOIST_API_TOKEN=your-token-here
```

Alternatively, store it in the macOS Keychain instead of a file:

```bash
security add-generic-password -s things-todoist -a todoist-api-token -w
```

The script looks for the token in this order: already-set environment variable, `.env`, then Keychain.

### 3. Enable Things URLs (for reverse completion)

Needed so completing a task in Todoist/Sunsama can complete it in Things.

1. Open Things → **Settings → General**.
2. Turn on **Enable Things URLs**.
3. Copy the auth token if you want to set it yourself.

Usually you can skip storing this yourself: `things.py` can read the token from the Things database. If reverse completion fails, set it explicitly:

```
THINGS_AUTH_TOKEN=your-things-url-token
```

in `.env`, or:

```bash
security add-generic-password -s things-todoist -a things-auth-token -w
```

### 4. Grant Full Disk Access

The Things database is outside the sandbox. Without this, reads fail with a permissions error.

1. Open **System Settings → Privacy & Security → Full Disk Access**.
2. Add the venv interpreter:  
   `/absolute/path/to/things-todoist/.venv/bin/python`
3. If you will use the `launchd` job, also add `/bin/bash` (the wrapper that launches the sync).

Use the real absolute path to this clone. After granting access, quit and reopen Terminal (or reload the LaunchAgent) so the new permission applies.

### 5. Dry-run first

Dry-run is the default. It logs what would change and writes nothing to Todoist or Things:

```bash
uv run python sync.py
```

Read the output. Confirm titles, labels, and due dates look right. Logs are also written to:

```
~/Library/Logs/things-todoist/sync.log
```

### 6. Apply

When the dry-run looks correct:

```bash
uv run python sync.py --apply
```

A local mapping of Things UUID ↔ Todoist task ID is stored at:

```
~/Library/Application Support/things-todoist/mapping.json
```

### 7. Connect Sunsama (optional)

In Sunsama, enable the Todoist integration and import from Inbox (or filter by the labels this sync creates). Sunsama never talks to Things directly.

### 8. Run on a schedule

To sync every 5 minutes while the Mac is awake:

```bash
scripts/install-launchd.sh
```

This installs `~/Library/LaunchAgents/com.aukoyy.things-todoist.plist`. The job calls `scripts/run-sync.sh`, which runs `sync.py --apply`. Secrets stay in `.env` or Keychain — they are never written into the plist.

`launchd` uses `StartInterval` (not cron) so the job resumes after sleep.

To unload it later:

```bash
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/com.aukoyy.things-todoist.plist
rm ~/Library/LaunchAgents/com.aukoyy.things-todoist.plist
```

## Commands

```bash
uv run python sync.py           # dry-run (default)
uv run python sync.py --apply   # write to Todoist and Things
scripts/install-launchd.sh      # schedule every 5 minutes
```

`--dry-run` can be passed explicitly; it wins if both flags are set.

## Troubleshooting

**Cannot read the Things database.**  
Grant Full Disk Access to `.venv/bin/python` and, for the scheduled job, `/bin/bash`. Then restart Terminal or reload the LaunchAgent.

**Missing Todoist API token.**  
Set `TODOIST_API_TOKEN` in `.env` or the environment, or add the Keychain item (`service` `things-todoist`, `account` `todoist-api-token`).

**Reverse completion does nothing.**  
Enable Things URLs, confirm `THINGS_AUTH_TOKEN` (or that `things.py` can read it), and make sure Things is installed. Completions open a `things:///update?...` URL.

**Apply aborted at 300 tasks.**  
Todoist Inbox cannot hold more than 300 active tasks. Complete or defer Things to-dos below that cap, then run `--apply` again.

**Scheduled job is silent or stuck.**  
Check `~/Library/Logs/things-todoist/sync.log`, plus `launchd.out.log` and `launchd.err.log` in the same folder.

## License

Use and adapt as you like. Inspired by [stancl/things3-trello-sync](https://github.com/stancl/things3-trello-sync), same idea with Trello as the target.
