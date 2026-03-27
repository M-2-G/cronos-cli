"""Tests for CronosController — the core business logic."""
from __future__ import annotations

import time

import pytest

from cronos_cli.controller import CronosController
from cronos_cli.models import TaskStatus
from cronos_cli.storage import StorageManager


@pytest.fixture
def storage(tmp_path):
    return StorageManager(tmp_path)


@pytest.fixture
def ctrl(storage):
    return CronosController(storage)


# ── Task CRUD ─────────────────────────────────────────────────────────────────


class TestCreateTask:
    def test_returns_task(self, ctrl):
        task = ctrl.create_task("Work", "desc")
        assert task.name == "Work"
        assert task.description == "desc"

    def test_added_to_tasks_list(self, ctrl):
        task = ctrl.create_task("Work", "")
        assert task in ctrl.tasks

    def test_persisted(self, ctrl, storage):
        ctrl.create_task("Work", "")
        assert storage.load_tasks()[0].name == "Work"

    def test_multiple_tasks(self, ctrl):
        ctrl.create_task("A", "")
        ctrl.create_task("B", "")
        assert len(ctrl.tasks) == 2


class TestLoadTasks:
    def test_loads_from_storage(self, ctrl, storage):
        from cronos_cli.models import Task
        storage.save_tasks([Task(name="Saved")])
        ctrl.load_tasks()
        assert ctrl.tasks[0].name == "Saved"

    def test_empty_when_no_file(self, ctrl):
        ctrl.load_tasks()
        assert ctrl.tasks == []


class TestUpdateTask:
    def test_updates_name_and_description(self, ctrl):
        task = ctrl.create_task("Old", "old desc")
        ctrl.update_task(task, "New", "new desc")
        assert task.name == "New"
        assert task.description == "new desc"

    def test_persists_update(self, ctrl, storage):
        task = ctrl.create_task("Old", "")
        ctrl.update_task(task, "New", "")
        assert storage.load_tasks()[0].name == "New"

    def test_updates_active_timer_name(self, ctrl):
        task = ctrl.create_task("Old", "")
        ctrl.toggle_timer(task.id)
        ctrl.update_task(task, "New", "")
        assert ctrl.active_entries[task.id].task_name == "New"


class TestDeleteTask:
    def test_removed_from_tasks(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.delete_task(task.id)
        assert task not in ctrl.tasks

    def test_persists_deletion(self, ctrl, storage):
        task = ctrl.create_task("T", "")
        ctrl.delete_task(task.id)
        assert storage.load_tasks() == []

    def test_discards_active_timer(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        ctrl.delete_task(task.id)
        assert task.id not in ctrl.active_entries

    def test_unknown_id_is_noop(self, ctrl):
        ctrl.delete_task("nonexistent-id")


# ── Timer logic ───────────────────────────────────────────────────────────────


class TestToggleTimer:
    def test_start_creates_entry(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        assert task.id in ctrl.active_entries

    def test_started_entry_is_running(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        assert ctrl.active_entries[task.id].is_running()

    def test_pause_stops_running(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        ctrl.toggle_timer(task.id)
        assert ctrl.active_entries[task.id].is_paused()

    def test_pause_accumulates_seconds(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        time.sleep(0.05)
        ctrl.toggle_timer(task.id)
        assert ctrl.active_entries[task.id].total_seconds > 0

    def test_resume_clears_paused_at(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        ctrl.toggle_timer(task.id)
        ctrl.toggle_timer(task.id)
        entry = ctrl.active_entries[task.id]
        assert entry.paused_at is None
        assert entry.is_running()

    def test_unknown_task_id_is_noop(self, ctrl):
        ctrl.toggle_timer("no-such-task")
        assert "no-such-task" not in ctrl.active_entries


class TestStopTimer:
    def test_returns_none_when_no_entry(self, ctrl):
        assert ctrl.stop_timer("nonexistent") is None

    def test_removes_from_active_entries(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        ctrl.stop_timer(task.id)
        assert task.id not in ctrl.active_entries

    def test_sets_end_time(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        entry = ctrl.stop_timer(task.id)
        assert entry.end_time is not None

    def test_persists_entry(self, ctrl, storage):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        ctrl.stop_timer(task.id)
        assert len(storage.load_entries()) == 1

    def test_accumulates_running_time(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        time.sleep(0.05)
        entry = ctrl.stop_timer(task.id)
        assert entry.total_seconds > 0

    def test_stop_paused_timer_preserves_accumulated(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        time.sleep(0.05)
        ctrl.toggle_timer(task.id)
        paused_seconds = ctrl.active_entries[task.id].total_seconds
        entry = ctrl.stop_timer(task.id)
        assert entry.total_seconds == pytest.approx(paused_seconds, abs=0.01)

    def test_saves_daily_stats(self, ctrl, storage):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        time.sleep(0.05)
        ctrl.stop_timer(task.id)
        _, stats = storage.load_daily_data()
        assert "total_seconds" in stats
        assert stats["total_seconds"] > 0

    def test_daily_stats_total_accumulates_across_stops(self, ctrl, storage):
        t1 = ctrl.create_task("T1", "")
        t2 = ctrl.create_task("T2", "")
        ctrl.toggle_timer(t1.id)
        time.sleep(0.05)
        ctrl.stop_timer(t1.id)
        ctrl.toggle_timer(t2.id)
        time.sleep(0.05)
        ctrl.stop_timer(t2.id)
        _, stats = storage.load_daily_data()
        # total_seconds must cover both entries
        entries = storage.load_entries()
        expected = sum(e.total_seconds for e in entries)
        assert stats["total_seconds"] == pytest.approx(expected, abs=0.01)


class TestSaveAllTimers:
    def test_saves_all_running(self, ctrl, storage):
        t1 = ctrl.create_task("T1", "")
        t2 = ctrl.create_task("T2", "")
        ctrl.toggle_timer(t1.id)
        ctrl.toggle_timer(t2.id)
        ctrl.save_all_timers()
        assert ctrl.active_entries == {}
        assert len(storage.load_entries()) == 2

    def test_noop_when_no_active(self, ctrl):
        ctrl.save_all_timers()


# ── Queries ───────────────────────────────────────────────────────────────────


class TestGetTodaySeconds:
    def test_zero_when_no_activity(self, ctrl):
        task = ctrl.create_task("T", "")
        assert ctrl.get_today_seconds(task.id) == 0.0

    def test_includes_active_entry(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        assert ctrl.get_today_seconds(task.id) >= 0.0

    def test_includes_saved_entries(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        time.sleep(0.05)
        ctrl.stop_timer(task.id)
        assert ctrl.get_today_seconds(task.id) > 0

    def test_sums_saved_and_active(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        time.sleep(0.05)
        ctrl.stop_timer(task.id)
        saved = ctrl.get_today_seconds(task.id)
        ctrl.toggle_timer(task.id)
        time.sleep(0.05)
        total = ctrl.get_today_seconds(task.id)
        assert total > saved


class TestGetTotalTodaySeconds:
    def test_zero_with_no_tasks(self, ctrl):
        assert ctrl.get_total_today_seconds() == 0.0

    def test_zero_with_tasks_but_no_time(self, ctrl):
        ctrl.create_task("T1", "")
        ctrl.create_task("T2", "")
        assert ctrl.get_total_today_seconds() == 0.0

    def test_sums_single_stopped_task(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        time.sleep(0.05)
        ctrl.stop_timer(task.id)
        assert ctrl.get_total_today_seconds() > 0

    def test_sums_multiple_stopped_tasks(self, ctrl):
        t1 = ctrl.create_task("T1", "")
        t2 = ctrl.create_task("T2", "")
        ctrl.toggle_timer(t1.id)
        time.sleep(0.05)
        ctrl.stop_timer(t1.id)
        s1 = ctrl.get_today_seconds(t1.id)
        ctrl.toggle_timer(t2.id)
        time.sleep(0.05)
        ctrl.stop_timer(t2.id)
        s2 = ctrl.get_today_seconds(t2.id)
        total = ctrl.get_total_today_seconds()
        assert total == pytest.approx(s1 + s2, abs=0.01)

    def test_includes_live_active_entries(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        assert ctrl.get_total_today_seconds() >= 0.0

    def test_combines_saved_and_active(self, ctrl):
        t1 = ctrl.create_task("T1", "")
        t2 = ctrl.create_task("T2", "")
        ctrl.toggle_timer(t1.id)
        time.sleep(0.05)
        ctrl.stop_timer(t1.id)
        ctrl.toggle_timer(t2.id)
        total = ctrl.get_total_today_seconds()
        assert total >= ctrl.get_today_seconds(t1.id)


class TestComputeDailyStats:
    def test_empty_entries(self, ctrl):
        stats = ctrl._compute_daily_stats([])
        assert stats == {"total_seconds": 0.0}

    def test_sums_completed_entries(self, ctrl, storage):
        from datetime import datetime
        from cronos_cli.models import TimeEntry
        now = datetime.now().isoformat(timespec="seconds")
        entries = [
            TimeEntry(task_id="t1", task_name="T1", start_time=now, end_time=now, total_seconds=30.0),
            TimeEntry(task_id="t2", task_name="T2", start_time=now, end_time=now, total_seconds=70.0),
        ]
        stats = ctrl._compute_daily_stats(entries)
        assert stats["total_seconds"] == pytest.approx(100.0)

    def test_excludes_incomplete_entries(self, ctrl):
        from datetime import datetime
        from cronos_cli.models import TimeEntry
        now = datetime.now().isoformat(timespec="seconds")
        entries = [
            TimeEntry(task_id="t1", task_name="T1", start_time=now, end_time=None, total_seconds=50.0),
        ]
        stats = ctrl._compute_daily_stats(entries)
        assert stats["total_seconds"] == pytest.approx(0.0)


class TestGetStatusIcon:
    def test_no_timer(self, ctrl):
        task = ctrl.create_task("T", "")
        assert ctrl.get_status_icon(task.id) == " "

    def test_running(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        assert ctrl.get_status_icon(task.id) == "▶"

    def test_paused(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        ctrl.toggle_timer(task.id)
        assert ctrl.get_status_icon(task.id) == "⏸"

    def test_unknown_task_id(self, ctrl):
        assert ctrl.get_status_icon("no-such-id") == " "


# ── Subtask feature ───────────────────────────────────────────────────────────


class TestToggleComplete:
    def test_marks_task_completed(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_complete(task.id)
        assert task.status == TaskStatus.COMPLETED

    def test_unmarks_completed_task(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_complete(task.id)
        ctrl.toggle_complete(task.id)
        assert task.status == TaskStatus.NONE

    def test_persists(self, ctrl, storage):
        task = ctrl.create_task("T", "")
        ctrl.toggle_complete(task.id)
        assert storage.load_tasks()[0].status == TaskStatus.COMPLETED

    def test_works_on_subtask(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "")
        ctrl.toggle_complete(sub.id)
        assert sub.status == TaskStatus.COMPLETED

    def test_unknown_id_is_noop(self, ctrl):
        ctrl.toggle_complete("no-such-id")


class TestFindTask:
    def test_finds_top_level(self, ctrl):
        task = ctrl.create_task("T", "")
        assert ctrl._find_task(task.id) is task

    def test_finds_subtask(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "")
        assert ctrl._find_task(sub.id) is sub

    def test_returns_none_for_unknown(self, ctrl):
        assert ctrl._find_task("no-such") is None


class TestFindParent:
    def test_returns_none_for_top_level(self, ctrl):
        task = ctrl.create_task("T", "")
        assert ctrl._find_parent(task.id) is None

    def test_returns_parent_for_subtask(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "")
        assert ctrl._find_parent(sub.id) is parent

    def test_returns_none_for_unknown(self, ctrl):
        assert ctrl._find_parent("no-such") is None


class TestIsSubtask:
    def test_top_level_is_not_subtask(self, ctrl):
        task = ctrl.create_task("T", "")
        assert not ctrl.is_subtask(task.id)

    def test_subtask_is_subtask(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "")
        assert ctrl.is_subtask(sub.id)


class TestCreateSubtask:
    def test_returns_task(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "desc")
        assert sub is not None
        assert sub.name == "S"
        assert sub.description == "desc"

    def test_added_to_parent_subtasks(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "")
        assert sub in parent.subtasks

    def test_persisted(self, ctrl, storage):
        parent = ctrl.create_task("P", "")
        ctrl.create_subtask(parent.id, "S", "")
        loaded = storage.load_tasks()
        assert len(loaded[0].subtasks) == 1
        assert loaded[0].subtasks[0].name == "S"

    def test_unknown_parent_returns_none(self, ctrl):
        result = ctrl.create_subtask("no-such-id", "S", "")
        assert result is None


class TestDeleteTaskSubtasks:
    def test_delete_subtask_removes_from_parent(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "")
        ctrl.delete_task(sub.id)
        assert sub not in parent.subtasks

    def test_delete_subtask_persists(self, ctrl, storage):
        parent = ctrl.create_task("P", "")
        ctrl.create_subtask(parent.id, "S", "")
        sub = parent.subtasks[0]
        ctrl.delete_task(sub.id)
        loaded = storage.load_tasks()
        assert loaded[0].subtasks == []

    def test_delete_parent_removes_subtask_timers(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "")
        ctrl.toggle_timer(sub.id)
        ctrl.delete_task(parent.id)
        assert sub.id not in ctrl.active_entries

    def test_delete_active_subtask_discards_entry(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "")
        ctrl.toggle_timer(sub.id)
        ctrl.delete_task(sub.id)
        assert sub.id not in ctrl.active_entries


class TestGetOwnSeconds:
    def test_zero_when_no_activity(self, ctrl):
        task = ctrl.create_task("T", "")
        assert ctrl.get_own_seconds(task.id) == 0.0

    def test_includes_active_entry(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        assert ctrl.get_own_seconds(task.id) >= 0.0

    def test_does_not_include_subtasks(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "")
        ctrl.toggle_timer(sub.id)
        time.sleep(0.05)
        ctrl.stop_timer(sub.id)
        assert ctrl.get_own_seconds(parent.id) == 0.0


class TestGetTodaySecondsAggregation:
    def test_top_level_includes_subtask_time(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "")
        ctrl.toggle_timer(sub.id)
        time.sleep(0.05)
        ctrl.stop_timer(sub.id)
        assert ctrl.get_today_seconds(parent.id) > 0

    def test_subtask_returns_own_time_only(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "")
        ctrl.toggle_timer(sub.id)
        time.sleep(0.05)
        ctrl.stop_timer(sub.id)
        sub_secs = ctrl.get_today_seconds(sub.id)
        parent_secs = ctrl.get_today_seconds(parent.id)
        assert sub_secs == pytest.approx(parent_secs, abs=0.01)

    def test_aggregates_multiple_subtasks(self, ctrl):
        parent = ctrl.create_task("P", "")
        s1 = ctrl.create_subtask(parent.id, "S1", "")
        s2 = ctrl.create_subtask(parent.id, "S2", "")
        ctrl.toggle_timer(s1.id)
        time.sleep(0.05)
        ctrl.stop_timer(s1.id)
        ctrl.toggle_timer(s2.id)
        time.sleep(0.05)
        ctrl.stop_timer(s2.id)
        total = ctrl.get_today_seconds(parent.id)
        assert total >= ctrl.get_own_seconds(s1.id) + ctrl.get_own_seconds(s2.id)


class TestToggleTimerSubtasks:
    def test_starting_subtask_pauses_sibling(self, ctrl):
        parent = ctrl.create_task("P", "")
        s1 = ctrl.create_subtask(parent.id, "S1", "")
        s2 = ctrl.create_subtask(parent.id, "S2", "")
        ctrl.toggle_timer(s1.id)
        ctrl.toggle_timer(s2.id)
        assert ctrl.active_entries[s1.id].is_paused()
        assert ctrl.active_entries[s2.id].is_running()

    def test_resuming_subtask_pauses_running_sibling(self, ctrl):
        parent = ctrl.create_task("P", "")
        s1 = ctrl.create_subtask(parent.id, "S1", "")
        s2 = ctrl.create_subtask(parent.id, "S2", "")
        ctrl.toggle_timer(s1.id)
        ctrl.toggle_timer(s2.id)  # s1 paused, s2 running
        ctrl.toggle_timer(s1.id)  # resume s1 -> s2 should be paused
        assert ctrl.active_entries[s2.id].is_paused()
        assert ctrl.active_entries[s1.id].is_running()

    def test_starting_subtask_pauses_parent_timer(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "")
        ctrl.toggle_timer(parent.id)
        ctrl.toggle_timer(sub.id)
        assert ctrl.active_entries[parent.id].is_paused()
        assert ctrl.active_entries[sub.id].is_running()

    def test_starting_top_level_pauses_running_subtask(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "")
        ctrl.toggle_timer(sub.id)
        ctrl.toggle_timer(parent.id)
        assert ctrl.active_entries[sub.id].is_paused()
        assert ctrl.active_entries[parent.id].is_running()


class TestGetEffectiveStatusIcon:
    def test_idle_when_no_activity(self, ctrl):
        task = ctrl.create_task("T", "")
        assert ctrl.get_effective_status_icon(task.id) == " "

    def test_own_running_returns_running(self, ctrl):
        task = ctrl.create_task("T", "")
        ctrl.toggle_timer(task.id)
        assert ctrl.get_effective_status_icon(task.id) == "▶"

    def test_subtask_running_shows_running_on_parent(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "")
        ctrl.toggle_timer(sub.id)
        assert ctrl.get_effective_status_icon(parent.id) == "▶"

    def test_subtask_paused_shows_paused_on_parent(self, ctrl):
        parent = ctrl.create_task("P", "")
        sub = ctrl.create_subtask(parent.id, "S", "")
        ctrl.toggle_timer(sub.id)
        ctrl.toggle_timer(sub.id)
        assert ctrl.get_effective_status_icon(parent.id) == "⏸"
