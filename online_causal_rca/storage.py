"""Tiny JSONL event store.

The paper describes an LSM-style store.  This public implementation provides a
compact JSONL-backed store with the same persistence role and a minimal API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

from .models import Event


class JsonlEventStore:
    """Append-only event store partitioned by a user-provided file path."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.memtable: List[Event] = []
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: Event) -> None:
        self.memtable.append(event)

    def flush(self) -> None:
        if self.path is None or not self.memtable:
            return
        with self.path.open("a", encoding="utf-8") as f:
            for e in self.memtable:
                f.write(json.dumps(e.to_json(), ensure_ascii=False) + "\n")
        self.memtable.clear()

    def iter_events(self) -> Iterator[Event]:
        if self.path is not None and self.path.exists():
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        yield Event.from_json(json.loads(line))
        yield from self.memtable
