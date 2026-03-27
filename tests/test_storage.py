"""Tests for StorageManager."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from cronos_cli.models import Task, TimeEntry
from cronos_cli.storage import StorageManager


@pytest.fixture
def storage(tmp_path):
    return StorageManager(tmp_path)


def make_entry(task_id: str, seconds: float, ended: bool = True) -> TimeEntry:
    now = datetime.now().isoformat(timespec="seconds")
    return TimeEntry(
        task_id=task_id,
        task_name="T",
        start_time=now,
        end_time=now if ended else None,
        total_seconds=seconds,
    )


# ── Tasks ─────────────────────────────────────────────────────────────────────


class TestTasks:
    def test_load_empty(self, storage):
        assert storage.load_tasks() == []

    def test_save_and_load(self, storage):
        tasks = [Task(name="A"), Task(name="B")]
        storage.save_tasks(tasks)
        loaded = storage.load_tasks()
        assert [t.name for t in loaded] == ["A", "B"]

    def test_overwrite(self, storage):
        storage.save_tasks([Task(name="Old")])
        storage.save_tasks([Task(name="New")])
        assert storage.load_tasks()[0].name == "New"

    def test_corrupted_file_returns_empty(self, storage):
        storage.tasks_file.write_text("not json", encoding="utf-8")
        assert storage.load_tasks() == []


# ── Daily data (entries + daily_stats) ───────────────────────────────────────


class TestLoadDailyData:
    def test_returns_empty_when_no_file(self, storage):
        entries, stats = storage.load_daily_data()
        assert entries == []
        assert stats == {}

    def test_round_trip(self, storage):
        entries = [make_entry("t1", 60.0)]
        daily_stats = {"total_seconds": 60.0}
        storage.save_daily_data(entries, daily_stats)
        loaded_entries, loaded_stats = storage.load_daily_data()
        assert len(loaded_entries) == 1
        assert loaded_stats == {"total_seconds": 60.0}

    def test_backward_compat_plain_list(self, storage):
        """Files written in the old format (bare JSON array) still load."""
        import json

        entries = [make_entry("t1", 30.0)]
        storage.daily_file().write_text(
            json.dumps([e.to_dict() for e in entries]), encoding="utf-8"
        )
        loaded_entries, loaded_stats = storage.load_daily_data()
        assert len(loaded_entries) == 1
        assert loaded_stats == {}

    def test_extra_stat_keys_preserved(self, storage):
        """Unknown keys in daily_stats survive a round-trip (forward compat)."""
        storage.save_daily_data([], {"total_seconds": 0, "custom_key": "value"})
        _, stats = storage.load_daily_data()
        assert stats["custom_key"] == "value"

    def test_corrupted_file_returns_empty(self, storage):
        storage.daily_file().write_text("not json", encoding="utf-8")
        entries, stats = storage.load_daily_data()
        assert entries == []
        assert stats == {}


class TestSaveDailyData:
    def test_writes_both_entries_and_stats(self, storage):
        import json

        storage.save_daily_data([make_entry("t1", 10.0)], {"total_seconds": 10.0})
        raw = json.loads(storage.daily_file().read_text())
        assert "entries" in raw
        assert "daily_stats" in raw
        assert raw["daily_stats"]["total_seconds"] == pytest.approx(10.0)

    def test_daily_file_isolation(self, storage):
        today = date.today()
        yesterday = today - timedelta(days=1)
        storage.save_daily_data([make_entry("t1", 10.0)], {}, for_date=today)
        storage.save_daily_data([make_entry("t2", 20.0)], {}, for_date=yesterday)
        e_today, _ = storage.load_daily_data(for_date=today)
        e_yesterday, _ = storage.load_daily_data(for_date=yesterday)
        assert len(e_today) == 1
        assert len(e_yesterday) == 1


# ── Convenience wrappers ──────────────────────────────────────────────────────


class TestEntries:
    def test_load_empty(self, storage):
        assert storage.load_entries() == []

    def test_save_and_load(self, storage):
        entries = [make_entry("t1", 60.0), make_entry("t2", 30.0)]
        storage.save_entries(entries)
        loaded = storage.load_entries()
        assert len(loaded) == 2

    def test_save_entries_preserves_existing_daily_stats(self, storage):
        """Calling save_entries must not wipe out daily_stats written earlier."""
        storage.save_daily_data([], {"total_seconds": 99.0, "custom": "x"})
        storage.save_entries([make_entry("t1", 10.0)])
        _, stats = storage.load_daily_data()
        assert stats["total_seconds"] == pytest.approx(99.0)
        assert stats["custom"] == "x"


# ── Aggregations ──────────────────────────────────────────────────────────────


class TestGetTodayTotals:
    def test_empty(self, storage):
        assert storage.get_today_totals() == {}

    def test_sums_completed_entries(self, storage):
        storage.save_entries([
            make_entry("t1", 60.0),
            make_entry("t1", 30.0),
            make_entry("t2", 45.0),
        ])
        totals = storage.get_today_totals()
        assert totals["t1"] == pytest.approx(90.0)
        assert totals["t2"] == pytest.approx(45.0)

    def test_excludes_unfinished_entries(self, storage):
        storage.save_entries([make_entry("t1", 60.0, ended=False)])
        assert storage.get_today_totals() == {}
