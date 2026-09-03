#!/usr/bin/env python3
"""Things 3 → Todoist Inbox + labels. Dry-run by default; pass --apply to write."""

from __future__ import annotations

import argparse
import logging
import sys

from config import INBOX_ACTIVE_LIMIT, LIST_LABELS, things_auth_token, todoist_token
from differ import SyncPlan, build_plan
from logging_setup import log_path, setup_logging
from state import State
from things_reader import read_things
from things_url import complete_todo
from todoist_client import TodoistClient, TodoistError

log = logging.getLogger("things_todoist")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync incomplete Things to-dos into the Todoist Inbox as labeled tasks."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write to Todoist and Things. Without this flag the run is a dry-run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log intended changes without writing (default).",
    )
    return parser.parse_args(argv)


def _command_ok(status: dict, cmd_uuid: str) -> bool:
    result = status.get(cmd_uuid, "ok")
    return result == "ok"


def apply_plan(plan: SyncPlan, client: TodoistClient, state: State, dry_run: bool) -> None:
    if dry_run:
        for line in plan.summaries:
            log.info("dry-run %s", line)
        log.info(
            "dry-run summary: %d label creates, %d label deletes, %d item commands, "
            "%d Things completions, %d mapping drops, %d unchanged",
            len(plan.label_commands),
            len(plan.delete_label_commands),
            len(plan.item_commands),
            len(plan.complete_things),
            len(plan.drop_mapping),
            plan.unchanged,
        )
        return

    status: dict = {}
    temp: dict = {}

    if plan.label_commands:
        result = client.push(plan.label_commands)
        status = result.get("sync_status") or {}
        _log_status(status, "label")

    if plan.item_commands:
        result = client.push(plan.item_commands)
        status = result.get("sync_status") or {}
        temp = result.get("temp_id_mapping") or {}
        _log_status(status, "item")

        for pending in plan.pending_creates:
            if not _command_ok(status, pending.cmd_uuid):
                log.error(
                    "create failed for %r: %s",
                    pending.title,
                    status.get(pending.cmd_uuid),
                )
                continue
            real_id = temp.get(pending.temp_id)
            if not real_id:
                log.error("no Todoist id returned for create %r", pending.title)
                continue
            state.mapping[pending.things_uuid] = str(real_id)
            log.info("created %r → %s", pending.title, real_id)

        for pending in plan.complete_todoist:
            if not _command_ok(status, pending.cmd_uuid):
                log.error(
                    "Todoist complete failed for %r: %s",
                    pending.title,
                    status.get(pending.cmd_uuid),
                )
                continue
            state.mapping.pop(pending.things_uuid, None)
            log.info("completed in Todoist %r (%s)", pending.title, pending.things_uuid)

    for things_uuid in plan.drop_mapping:
        state.mapping.pop(things_uuid, None)

    if plan.delete_label_commands:
        result = client.push(plan.delete_label_commands)
        status = result.get("sync_status") or {}
        _log_status(status, "label-delete")

    for pending in plan.pending_label_deletes:
        if pending.cmd_uuid and not _command_ok(status, pending.cmd_uuid):
            log.error(
                "label delete failed for %r: %s",
                pending.name,
                status.get(pending.cmd_uuid),
            )
            continue
        state.managed_labels.discard(pending.name)
        state.labels.pop(pending.name, None)
        log.info("deleted label %r", pending.name)

    auth = things_auth_token() if plan.complete_things else None
    if plan.complete_things and not auth:
        log.error(
            "Need THINGS_AUTH_TOKEN (env or Keychain) or Things URL auth enabled "
            "to complete %d to-do(s) in Things.",
            len(plan.complete_things),
        )
    elif auth:
        for things_uuid, _todoist_id, title in plan.complete_things:
            try:
                complete_todo(things_uuid, auth)
                state.mapping.pop(things_uuid, None)
                log.info("completed in Things %r (%s)", title, things_uuid)
            except Exception as exc:
                log.error("failed to complete Things to-do %s: %s", things_uuid, exc)

    state.save()
    log.info(
        "applied: %d labels, %d label deletes, %d item commands, "
        "%d Things completions, %d unchanged",
        len(plan.label_commands),
        len(plan.delete_label_commands),
        len(plan.item_commands),
        len(plan.complete_things),
        plan.unchanged,
    )


def _log_status(status: dict, kind: str) -> None:
    for cmd_uuid, result in status.items():
        if result == "ok":
            continue
        log.error("%s command %s: %s", kind, cmd_uuid, result)


def run(apply: bool) -> int:
    setup_logging()
    dry_run = not apply
    log.info("start (%s) log=%s", "apply" if apply else "dry-run", log_path())

    snapshot = read_things()
    desired = snapshot.todos
    over_cap = len(desired) >= INBOX_ACTIVE_LIMIT
    if over_cap:
        log.error(
            "Open Things to-dos: %d. Todoist Inbox allows %d active tasks. %s",
            len(desired),
            INBOX_ACTIVE_LIMIT,
            "Aborting apply." if apply else "Dry-run continues; apply would abort.",
        )
        if apply:
            return 1

    try:
        token = todoist_token()
    except SystemExit as exc:
        if dry_run:
            log.warning("%s", exc)
            for task in desired:
                log.info(
                    "dry-run would sync %r labels=%s due=%s",
                    task.title,
                    list(task.labels),
                    task.due_date,
                )
            return 0
        raise

    state = State.load()
    client = TodoistClient(token, state)
    try:
        client.pull()
    except TodoistError as exc:
        log.error("%s", exc)
        return 1
    state.save()

    for name in snapshot.active_containers:
        state.managed_labels.add(name)
    for task in desired:
        for name in task.labels:
            if name not in LIST_LABELS:
                state.managed_labels.add(name)
    state.save()

    plan = build_plan(
        desired,
        state.mapping,
        state.items,
        state.labels,
        managed_labels=state.managed_labels,
        active_containers=snapshot.active_containers,
        retired_containers=snapshot.retired_containers,
    )
    if not plan.summaries:
        log.info("noop: %d tasks already in sync", plan.unchanged)
        state.save()
        return 0

    apply_plan(plan, client, state, dry_run=dry_run)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    apply = bool(args.apply) and not args.dry_run
    try:
        return run(apply)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
