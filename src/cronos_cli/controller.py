from __future__ import annotations

from datetime import datetime
from typing import Optional

from cronos_cli.models import Task, TimeEntry
from cronos_cli.storage import StorageManager


class CronosController:
    """Owns all business logic: task state, timer state, and persistence."""

    def __init__(self, storage: StorageManager) -> None:
        self.storage = storage
        self.tasks: list[Task] = []
        self.active_entries: dict[str, TimeEntry] = {}  # task_id -> live entry

    # ── Tasks ─────────────────────────────────────────────────────────────────

    def load_tasks(self) -> list[Task]:
        self.tasks = self.storage.load_tasks()
        return self.tasks

    def create_task(self, name: str, description: str) -> Task:
        task = Task(name=name, description=description)
        self.tasks.append(task)
        self.storage.save_tasks(self.tasks)
        return task

    def update_task(self, task: Task, name: str, description: str) -> None:
        task.name = name
        task.description = description
        if task.id in self.active_entries:
            self.active_entries[task.id].task_name = name
        self.storage.save_tasks(self.tasks)

    def delete_task(self, task_id: str) -> None:
        self.active_entries.pop(task_id, None)
        self.tasks = [t for t in self.tasks if t.id != task_id]
        self.storage.save_tasks(self.tasks)

    # ── Timers ────────────────────────────────────────────────────────────────

    def toggle_timer(self, task_id: str) -> None:
        """Start a new timer, or pause/resume the existing one."""
        now = datetime.now()
        if task_id in self.active_entries:
            entry = self.active_entries[task_id]
            if entry.is_running():
                start = datetime.fromisoformat(entry.start_time)
                entry.total_seconds += (now - start).total_seconds()
                entry.paused_at = now.isoformat(timespec="seconds")
            elif entry.is_paused():
                entry.start_time = now.isoformat(timespec="seconds")
                entry.paused_at = None
        else:
            task = next((t for t in self.tasks if t.id == task_id), None)
            if task is None:
                return
            self.active_entries[task_id] = TimeEntry(
                task_id=task_id,
                task_name=task.name,
                start_time=now.isoformat(timespec="seconds"),
            )

    def stop_timer(self, task_id: str) -> Optional[TimeEntry]:
        """Stop, finalize, persist the active entry, and update daily_stats."""
        entry = self.active_entries.pop(task_id, None)
        if entry is None:
            return None
        now = datetime.now()
        if entry.is_running():
            start = datetime.fromisoformat(entry.start_time)
            entry.total_seconds += (now - start).total_seconds()
        entry.end_time = now.isoformat(timespec="seconds")
        entry.paused_at = None

        entries, _ = self.storage.load_daily_data()
        entries.append(entry)
        stats = self._compute_daily_stats(entries)
        self.storage.save_daily_data(entries, stats)
        return entry

    def save_all_timers(self) -> None:
        """Stop and save all active timers (e.g. on app quit)."""
        for task_id in list(self.active_entries.keys()):
            self.stop_timer(task_id)

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_today_seconds(self, task_id: str) -> float:
        """Total seconds for a task today: persisted entries + live active entry."""
        saved = self.storage.get_today_totals().get(task_id, 0.0)
        if task_id in self.active_entries:
            saved += self.active_entries[task_id].elapsed_seconds()
        return saved

    def get_total_today_seconds(self) -> float:
        """Grand total seconds across all tasks today (saved + all live entries)."""
        total = sum(self.storage.get_today_totals().values())
        for entry in self.active_entries.values():
            total += entry.elapsed_seconds()
        return total

    def get_status_icon(self, task_id: str) -> str:
        entry = self.active_entries.get(task_id)
        if entry is None:
            return " "
        if entry.is_running():
            return "▶"
        return "⏸"

    # ── Internal ──────────────────────────────────────────────────────────────

    def _compute_daily_stats(self, entries: list[TimeEntry]) -> dict:
        """Compute stats snapshot from a list of entries (completed only)."""
        total = sum(
            e.total_seconds for e in entries if e.end_time is not None
        )
        return {"total_seconds": total}
