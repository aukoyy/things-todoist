"""Load and save Things UUID ↔ Todoist item id plus the Sync API token."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from config import STATE_PATH, ensure_dirs


@dataclass
class State:
    sync_token: str = "*"
    mapping: dict[str, str] = field(default_factory=dict)
    items: dict[str, dict] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    managed_labels: set[str] = field(default_factory=set)

    def dump(self) -> dict:
        return {
            "sync_token": self.sync_token,
            "mapping": self.mapping,
            "items": self.items,
            "labels": self.labels,
            "managed_labels": sorted(self.managed_labels),
        }

    @classmethod
    def load(cls, path: Path = STATE_PATH) -> State:
        ensure_dirs()
        if not path.exists():
            return cls()
        with path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
        return cls(
            sync_token=raw.get("sync_token") or "*",
            mapping=dict(raw.get("mapping") or {}),
            items=dict(raw.get("items") or {}),
            labels=dict(raw.get("labels") or {}),
            managed_labels=set(raw.get("managed_labels") or []),
        )

    def save(self, path: Path = STATE_PATH) -> None:
        ensure_dirs()
        payload = json.dumps(self.dump(), indent=2, sort_keys=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".mapping.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.write("\n")
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
