"""Tests for Task and TimeEntry models."""
from __future__ import annotations

import time
from datetime import datetime

import pytest

from cronos_cli.models import Task, TimeEntry


class TestTask:
    def test_defaults(self):
        task = Task(name="My Task")
        assert task.name == "My Task"
        assert task.description == ""
        assert task.id  # non-empty UUID
        assert task.created_at  # non-empty ISO string

    def test_round_trip(self):
        task = Task(name="Test", description="Desc")
        assert Task.from_dict(task.to_dict()) == task

    def test_to_dict_keys(self):
        keys = Task(name="x").to_dict().keys()
        assert set(keys) == {"id", "name", "description", "created_at"}


class TestTimeEntry:
    def _running_entry(self) -> TimeEntry:
        return TimeEntry(
            task_id="tid",
            task_name="T",
            start_time=datetime.now().isoformat(timespec="seconds"),
        )

    def test_is_running(self):
        entry = self._running_entry()
        assert entry.is_running()
        assert not entry.is_paused()

    def test_is_paused(self):
        entry = self._running_entry()
        entry.paused_at = datetime.now().isoformat(timespec="seconds")
        assert entry.is_paused()
        assert not entry.is_running()

    def test_elapsed_running_grows(self):
        entry = self._running_entry()
        e1 = entry.elapsed_seconds()
        time.sleep(0.05)
        e2 = entry.elapsed_seconds()
        assert e2 >= e1

    def test_elapsed_paused_is_fixed(self):
        entry = self._running_entry()
        time.sleep(0.05)
        now = datetime.now()
        start = datetime.fromisoformat(entry.start_time)
        entry.total_seconds += (now - start).total_seconds()
        entry.paused_at = now.isoformat(timespec="seconds")
        e1 = entry.elapsed_seconds()
        time.sleep(0.05)
        e2 = entry.elapsed_seconds()
        assert e1 == e2

    def test_elapsed_completed(self):
        entry = self._running_entry()
        entry.total_seconds = 42.0
        entry.end_time = datetime.now().isoformat(timespec="seconds")
        assert entry.elapsed_seconds() == 42.0

    def test_round_trip(self):
        entry = self._running_entry()
        assert TimeEntry.from_dict(entry.to_dict()) == entry
