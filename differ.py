"""Idempotent diff: Things desired state vs mapped Todoist items."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from config import LIST_LABELS, OBSOLETE_LABELS
from things_reader import DesiredTask
from todoist_client import command, due_object, snapshot_item


@dataclass
class PendingCreate:
    things_uuid: str
    temp_id: str
    cmd_uuid: str
    title: str


@dataclass
class PendingComplete:
    things_uuid: str
    todoist_id: str
    cmd_uuid: str
    title: str


@dataclass
class PendingLabelDelete:
    name: str
    cmd_uuid: str


@dataclass
class SyncPlan:
    create_labels: list[str] = field(default_factory=list)
    label_commands: list[dict] = field(default_factory=list)
    delete_label_commands: list[dict] = field(default_factory=list)
    pending_label_deletes: list[PendingLabelDelete] = field(default_factory=list)
    item_commands: list[dict] = field(default_factory=list)
    pending_creates: list[PendingCreate] = field(default_factory=list)
    complete_todoist: list[PendingComplete] = field(default_factory=list)
    complete_things: list[tuple[str, str, str]] = field(default_factory=list)
    drop_mapping: list[str] = field(default_factory=list)
    unchanged: int = 0
    summaries: list[str] = field(default_factory=list)

    @property
    def writes(self) -> int:
        return (
            len(self.label_commands)
            + len(self.delete_label_commands)
            + len(self.item_commands)
            + len(self.complete_things)
        )


def _due_date(item: dict) -> str | None:
    return snapshot_item(item)["due_date"]


def _labels_equal(desired: tuple[str, ...], actual: list[str] | None) -> bool:
    return set(desired) == set(actual or [])


def _item_complete(item: dict | None) -> bool:
    if item is None:
        return True
    snap = snapshot_item(item)
    return bool(snap["checked"] or snap["is_deleted"] or snap["completed_at"])


def _queue_label_deletes(
    plan: SyncPlan,
    needed_labels: set[str],
    existing_labels: dict[str, str],
    managed_labels: set[str],
    active_containers: set[str],
    retired_containers: set[str],
) -> None:
    protected = set(LIST_LABELS) | needed_labels | set(active_containers)
    protected -= set(OBSOLETE_LABELS)
    candidates = set(managed_labels)
    candidates |= set(retired_containers) & set(existing_labels)
    candidates |= set(OBSOLETE_LABELS) & set(existing_labels)
    candidates -= protected
    for name in sorted(candidates):
        label_id = existing_labels.get(name)
        if not label_id:
            plan.pending_label_deletes.append(PendingLabelDelete(name=name, cmd_uuid=""))
            plan.summaries.append(f"forget-label {name}")
            continue
        cmd = command("label_delete", {"id": label_id, "cascade": "all"})
        plan.delete_label_commands.append(cmd)
        plan.pending_label_deletes.append(
            PendingLabelDelete(name=name, cmd_uuid=cmd["uuid"])
        )
        plan.summaries.append(f"delete-label {name}")


def build_plan(
    desired: list[DesiredTask],
    mapping: dict[str, str],
    items: dict[str, dict],
    existing_labels: dict[str, str],
    managed_labels: set[str] | None = None,
    active_containers: set[str] | frozenset[str] | None = None,
    retired_containers: set[str] | frozenset[str] | None = None,
) -> SyncPlan:
    plan = SyncPlan()
    desired_uuids = {task.things_uuid for task in desired}

    needed_labels: set[str] = set()
    for task in desired:
        needed_labels.update(task.labels)
    missing_labels = sorted(name for name in needed_labels if name not in existing_labels)
    plan.create_labels = missing_labels
    for name in missing_labels:
        plan.label_commands.append(command("label_add", {"name": name}))
        plan.summaries.append(f"create-label {name}")

    for task in desired:
        todoist_id = mapping.get(task.things_uuid)
        item = items.get(todoist_id) if todoist_id else None

        if todoist_id and _item_complete(item):
            title = (item or {}).get("content") or task.title
            plan.complete_things.append((task.things_uuid, todoist_id, title))
            plan.summaries.append(f"complete-things {task.title!r} ({task.things_uuid})")
            continue

        if not todoist_id:
            _queue_create(plan, task)
            continue

        changes: dict = {}
        if (item.get("content") or "") != task.title:
            changes["content"] = task.title
        if (item.get("description") or "") != task.description:
            changes["description"] = task.description
        if not _labels_equal(task.labels, item.get("labels")):
            changes["labels"] = list(task.labels)
        if _due_date(item) != task.due_date:
            changes["due"] = due_object(task.due_date)

        if not changes:
            plan.unchanged += 1
            continue

        plan.item_commands.append(command("item_update", {"id": todoist_id, **changes}))
        bits = ", ".join(sorted(changes))
        plan.summaries.append(f"update {task.title!r} [{bits}]")

    for things_uuid, todoist_id in mapping.items():
        if things_uuid in desired_uuids:
            continue
        item = items.get(todoist_id)
        title = (item or {}).get("content") or things_uuid
        if _item_complete(item):
            plan.drop_mapping.append(things_uuid)
            plan.summaries.append(f"drop-mapping {title!r} ({things_uuid})")
            continue
        cmd = command("item_complete", {"id": todoist_id})
        plan.item_commands.append(cmd)
        plan.complete_todoist.append(
            PendingComplete(
                things_uuid=things_uuid,
                todoist_id=todoist_id,
                cmd_uuid=cmd["uuid"],
                title=title,
            )
        )
        plan.summaries.append(f"complete-todoist {title!r} ({things_uuid})")

    _queue_label_deletes(
        plan,
        needed_labels,
        existing_labels,
        set(managed_labels or ()),
        set(active_containers or ()),
        set(retired_containers or ()),
    )
    return plan


def _queue_create(plan: SyncPlan, task: DesiredTask) -> None:
    temp_id = str(uuid.uuid4())
    args: dict = {
        "content": task.title,
        "description": task.description,
        "labels": list(task.labels),
    }
    if task.due_date:
        args["due"] = due_object(task.due_date)
    cmd = command("item_add", args, temp_id=temp_id)
    plan.item_commands.append(cmd)
    plan.pending_creates.append(
        PendingCreate(
            things_uuid=task.things_uuid,
            temp_id=temp_id,
            cmd_uuid=cmd["uuid"],
            title=task.title,
        )
    )
    plan.summaries.append(
        f"create {task.title!r} labels={list(task.labels)} due={task.due_date}"
    )
