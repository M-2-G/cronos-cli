from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

from cronos_cli.models import Task, TimeEntry

DATA_DIR = Path("data")


class StorageManager:
    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def tasks_file(self) -> Path:
        return self.data_dir / "tasks.json"

    def daily_file(self, for_date: Optional[date] = None) -> Path:
        d = for_date or date.today()
        return self.data_dir / f"{d}.json"

    # ── Tasks ─────────────────────────────────────────────────────────────────

    def load_tasks(self) -> list[Task]:
        if not self.tasks_file.exists():
            return []
        try:
            data = json.loads(self.tasks_file.read_text(encoding="utf-8"))
            return [Task.from_dict(t) for t in data]
        except (json.JSONDecodeError, KeyError):
            return []

    def save_tasks(self, tasks: list[Task]) -> None:
        self.tasks_file.write_text(
            json.dumps([t.to_dict() for t in tasks], indent=2),
            encoding="utf-8",
        )

    # ── Daily file (entries + daily_stats) ────────────────────────────────────

    def load_daily_data(
        self, for_date: Optional[date] = None
    ) -> tuple[list[TimeEntry], dict]:
        """Return (entries, daily_stats).

        Handles the legacy format where the file was a plain JSON array of
        entries — in that case daily_stats is returned as an empty dict.
        """
        f = self.daily_file(for_date)
        if not f.exists():
            return [], {}
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                # Legacy format: bare array of entries
                return [TimeEntry.from_dict(e) for e in raw], {}
            entries = [TimeEntry.from_dict(e) for e in raw.get("entries", [])]
            daily_stats = raw.get("daily_stats", {})
            return entries, daily_stats
        except (json.JSONDecodeError, KeyError):
            return [], {}

    def save_daily_data(
        self,
        entries: list[TimeEntry],
        daily_stats: dict,
        for_date: Optional[date] = None,
    ) -> None:
        """Persist entries and daily_stats together in one atomic write."""
        f = self.daily_file(for_date)
        data = {
            "entries": [e.to_dict() for e in entries],
            "daily_stats": daily_stats,
        }
        f.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ── Convenience wrappers (preserve daily_stats on entry-only saves) ────────

    def load_entries(self, for_date: Optional[date] = None) -> list[TimeEntry]:
        entries, _ = self.load_daily_data(for_date)
        return entries

    def save_entries(
        self, entries: list[TimeEntry], for_date: Optional[date] = None
    ) -> None:
        """Save entries while preserving any existing daily_stats."""
        _, existing_stats = self.load_daily_data(for_date)
        self.save_daily_data(entries, existing_stats, for_date)

    # ── Aggregations ──────────────────────────────────────────────────────────

    def get_today_totals(self) -> dict[str, float]:
        """Return {task_id: total_seconds} for all completed entries today."""
        entries = self.load_entries()
        totals: dict[str, float] = {}
        for entry in entries:
            if entry.end_time is not None:
                totals[entry.task_id] = (
                    totals.get(entry.task_id, 0.0) + entry.total_seconds
                )
        return totals
