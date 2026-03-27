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

    def create_subtask(
        self, parent_id: str, name: str, description: str
    ) -> Optional[Task]:
        """Create a subtask under a top-level task."""
        parent = next((t for t in self.tasks if t.id == parent_id), None)
        if parent is None:
            return None
        subtask = Task(name=name, description=description)
        parent.subtasks.append(subtask)
        self.storage.save_tasks(self.tasks)
        return subtask

    def toggle_complete(self, task_id: str) -> None:
        """Toggle the completed status of a task or subtask."""
        task = self._find_task(task_id)
        if task is None:
            return
        task.status = "" if task.status == "completed" else "completed"
        self.storage.save_tasks(self.tasks)

    def update_task(self, task: Task, name: str, description: str) -> None:
        task.name = name
        task.description = description
        if task.id in self.active_entries:
            self.active_entries[task.id].task_name = name
        self.storage.save_tasks(self.tasks)

    def delete_task(self, task_id: str) -> None:
        self.active_entries.pop(task_id, None)
        parent = self._find_parent(task_id)
        if parent is not None:
            # Deleting a subtask: remove from parent's subtask list
            parent.subtasks = [s for s in parent.subtasks if s.id != task_id]
        else:
            # Deleting a top-level task: also discard any active subtask timers
            task = next((t for t in self.tasks if t.id == task_id), None)
            if task:
                for sub in task.subtasks:
                    self.active_entries.pop(sub.id, None)
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
                self._pause_hierarchy_except(task_id, now)
                entry.start_time = now.isoformat(timespec="seconds")
                entry.paused_at = None
        else:
            task = self._find_task(task_id)
            if task is None:
                return
            self._pause_hierarchy_except(task_id, now)
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

    def get_own_seconds(self, task_id: str) -> float:
        """Seconds for this specific task/subtask only (no subtask aggregation)."""
        saved = self.storage.get_today_totals().get(task_id, 0.0)
        if task_id in self.active_entries:
            saved += self.active_entries[task_id].elapsed_seconds()
        return saved

    def get_today_seconds(self, task_id: str) -> float:
        """Total seconds today: for top-level tasks aggregates all subtask time."""
        if self.is_subtask(task_id):
            return self.get_own_seconds(task_id)
        total = self.get_own_seconds(task_id)
        task = next((t for t in self.tasks if t.id == task_id), None)
        if task:
            for sub in task.subtasks:
                total += self.get_own_seconds(sub.id)
        return total

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

    def get_effective_status_icon(self, task_id: str) -> str:
        """Icon for a top-level task row: own state, or delegated from subtasks."""
        own = self.get_status_icon(task_id)
        if own == "▶":
            return "▶"
        task = next((t for t in self.tasks if t.id == task_id), None)
        if task:
            for sub in task.subtasks:
                if self.get_status_icon(sub.id) == "▶":
                    return "▶"
            if own == "⏸":
                return "⏸"
            for sub in task.subtasks:
                if self.get_status_icon(sub.id) == "⏸":
                    return "⏸"
        return own

    # ── Lookup helpers ────────────────────────────────────────────────────────

    def _find_task(self, task_id: str) -> Optional[Task]:
        """Find any task or subtask by ID."""
        for t in self.tasks:
            if t.id == task_id:
                return t
            for s in t.subtasks:
                if s.id == task_id:
                    return s
        return None

    def _find_parent(self, task_id: str) -> Optional[Task]:
        """Return the parent task of a subtask, or None if top-level."""
        for t in self.tasks:
            for s in t.subtasks:
                if s.id == task_id:
                    return t
        return None

    def is_subtask(self, task_id: str) -> bool:
        return self._find_parent(task_id) is not None

    def _pause_hierarchy_except(self, task_id: str, now: datetime) -> None:
        """Pause all running timers in the same parent-children hierarchy except task_id."""
        parent = self._find_parent(task_id)
        root = parent if parent is not None else next(
            (t for t in self.tasks if t.id == task_id), None
        )
        if root is None:
            return
        # Pause root timer if it's running and not the target
        if root.id != task_id:
            entry = self.active_entries.get(root.id)
            if entry and entry.is_running():
                start = datetime.fromisoformat(entry.start_time)
                entry.total_seconds += (now - start).total_seconds()
                entry.paused_at = now.isoformat(timespec="seconds")
        # Pause all subtask timers except the target
        for sub in root.subtasks:
            if sub.id == task_id:
                continue
            entry = self.active_entries.get(sub.id)
            if entry and entry.is_running():
                start = datetime.fromisoformat(entry.start_time)
                entry.total_seconds += (now - start).total_seconds()
                entry.paused_at = now.isoformat(timespec="seconds")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _compute_daily_stats(self, entries: list[TimeEntry]) -> dict:
        """Compute stats snapshot from a list of entries (completed only)."""
        total = sum(
            e.total_seconds for e in entries if e.end_time is not None
        )
        return {"total_seconds": total}
