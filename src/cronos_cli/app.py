from __future__ import annotations

from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, Rule

from cronos_cli.controller import CronosController
from cronos_cli.models import Task
from cronos_cli.storage import StorageManager
from cronos_cli.ui_helpers import FlatItem
from cronos_cli.widgets import DetailPanel, SummaryPanel, TaskTablePanel


# ── Modals ────────────────────────────────────────────────────────────────────


class ConfirmDialog(ModalScreen):
    """Yes / No confirmation dialog."""

    BINDINGS = [
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Container(id="confirm-box"):
            yield Label(self._message, id="confirm-msg")
            yield Rule()
            yield Label("  y: Yes     n / Esc: No  ", id="confirm-hint")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class TaskFormScreen(ModalScreen):
    """Create or edit a task / subtask."""

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self, task: Optional[Task] = None, parent: Optional[Task] = None
    ) -> None:
        super().__init__()
        self._edit_task = task
        self._parent_task = parent

    def compose(self) -> ComposeResult:
        if self._edit_task:
            title = (
                f"Edit Subtask  ·  {self._parent_task.name}"
                if self._parent_task
                else "Edit Task"
            )
        else:
            title = (
                f"New Subtask  ·  {self._parent_task.name}"
                if self._parent_task
                else "New Task"
            )
        with Container(id="task-form"):
            yield Label(title, id="form-title")
            yield Rule()
            yield Label("Name:")
            yield Input(
                value=self._edit_task.name if self._edit_task else "",
                placeholder="Task name (required)",
                id="name-input",
            )
            yield Label("Description:")
            yield Input(
                value=self._edit_task.description if self._edit_task else "",
                placeholder="Optional description",
                id="desc-input",
            )
            yield Rule()
            yield Label("  Ctrl+S: Save     Esc: Cancel  ", id="form-hint")

    def on_mount(self) -> None:
        self.query_one("#name-input", Input).focus()

    def action_save(self) -> None:
        name = self.query_one("#name-input", Input).value.strip()
        if not name:
            self.query_one("#name-input", Input).focus()
            return
        desc = self.query_one("#desc-input", Input).value.strip()
        self.dismiss({"name": name, "description": desc})

    def action_cancel(self) -> None:
        self.dismiss(None)


# ── Main screen ───────────────────────────────────────────────────────────────


class MainScreen(Screen):
    """Coordinates the three panels and owns the controller."""

    BINDINGS = [
        Binding("space", "toggle_timer", "Start/Pause", show=True),
        Binding("s", "stop_timer", "Stop", show=True),
        Binding("w", "complete_task", "Complete", show=True),
        Binding("n", "new_task", "New", show=True),
        Binding("a", "add_subtask", "Subtask", show=True),
        Binding("e", "edit_task", "Edit", show=True),
        Binding("d", "delete_task", "Delete", show=True),
        Binding("Q", "quit_app", "Quit", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.ctrl = CronosController(StorageManager())
        self._tick_handle = None
        self._expanded: set[str] = set()

    # ── Compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-layout"):
            with Vertical(id="left-panel"):
                yield TaskTablePanel(
                    "Today",
                    header_id="today-header",
                    table_id="today-table",
                    id="today-panel",
                )
                yield TaskTablePanel(
                    "All Tasks",
                    header_id="all-tasks-header",
                    table_id="task-table",
                    show_filter=True,
                    id="all-tasks-panel",
                )
            with Vertical(id="right-panel"):
                yield DetailPanel(id="detail-panel")
                yield SummaryPanel(id="summary-panel")
        yield Footer()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._load_and_refresh()
        self._tick_handle = self.set_interval(1.0, self._on_tick)
        today = self.query_one("#today-panel", TaskTablePanel)
        if today._table.row_count > 0:
            today._table.focus()
        else:
            self.query_one("#all-tasks-panel", TaskTablePanel)._table.focus()

    def on_unmount(self) -> None:
        if self._tick_handle is not None:
            self._tick_handle.stop()

    # ── Message handlers ───────────────────────────────────────────────────────

    def on_task_table_panel_selection_changed(
        self, msg: TaskTablePanel.SelectionChanged
    ) -> None:
        self.query_one(DetailPanel).update_detail(msg.item, self.ctrl)

    def on_task_table_panel_expand_toggled(
        self, msg: TaskTablePanel.ExpandToggled
    ) -> None:
        if msg.task_id in self._expanded:
            self._expanded.discard(msg.task_id)
        else:
            self._expanded.add(msg.task_id)
        # Only the panel that owns the task needs to rebuild
        panel = msg.panel
        panel.rebuild(panel._tasks, self._expanded, self.ctrl)
        self.query_one(DetailPanel).update_detail(panel.selected_item, self.ctrl)

    # ── Key handling ───────────────────────────────────────────────────────────

    def on_key(self, event) -> None:
        if event.key == "ctrl+j":
            panel = self.query_one("#all-tasks-panel", TaskTablePanel)
            panel._table.focus()
            self.query_one(DetailPanel).update_detail(panel.selected_item, self.ctrl)
            event.stop()
        elif event.key == "ctrl+k":
            panel = self.query_one("#today-panel", TaskTablePanel)
            panel._table.focus()
            self.query_one(DetailPanel).update_detail(panel.selected_item, self.ctrl)
            event.stop()

    # ── Selection helpers ──────────────────────────────────────────────────────

    def _focused_panel(self) -> Optional[TaskTablePanel]:
        for panel in self.query(TaskTablePanel):
            if panel.is_table_focused:
                return panel
        return None

    def _selected_item(self) -> Optional[FlatItem]:
        panel = self._focused_panel()
        return panel.selected_item if panel else None

    def _selected_task(self) -> Optional[Task]:
        item = self._selected_item()
        return item.task if item else None

    # ── Data helpers ───────────────────────────────────────────────────────────

    def _is_today_task(self, task: Task) -> bool:
        if task.id in self.ctrl.active_entries:
            return True
        for sub in task.subtasks:
            if sub.id in self.ctrl.active_entries:
                return True
        return self.ctrl.get_today_seconds(task.id) > 0

    # ── Refresh ────────────────────────────────────────────────────────────────

    def _load_and_refresh(self) -> None:
        self.ctrl.load_tasks()
        self._rebuild_panels()

    def _rebuild_panels(self) -> None:
        today_tasks = [t for t in self.ctrl.tasks if self._is_today_task(t)]
        all_tasks = [t for t in self.ctrl.tasks if not self._is_today_task(t)]

        self.query_one("#today-panel", TaskTablePanel).rebuild(
            today_tasks, self._expanded, self.ctrl
        )
        self.query_one("#all-tasks-panel", TaskTablePanel).rebuild(
            all_tasks, self._expanded, self.ctrl
        )

        selected = self._selected_item()
        self.query_one(DetailPanel).update_detail(selected, self.ctrl)
        self.query_one(SummaryPanel).update_summary(self.ctrl.tasks, self.ctrl)

    def _on_tick(self) -> None:
        if not self.ctrl.active_entries:
            return

        ids_to_update: set[str] = set(self.ctrl.active_entries.keys())
        for task_id in list(self.ctrl.active_entries.keys()):
            parent = self.ctrl._find_parent(task_id)
            if parent:
                ids_to_update.add(parent.id)

        for panel in self.query(TaskTablePanel):
            panel.tick_update(ids_to_update, self.ctrl)

        self.query_one(SummaryPanel).update_summary(self.ctrl.tasks, self.ctrl)
        selected = self._selected_item()
        self.query_one(DetailPanel).update_detail(selected, self.ctrl)

    # ── Actions ────────────────────────────────────────────────────────────────

    def action_toggle_timer(self) -> None:
        task = self._selected_task()
        if not task:
            return
        was_today = self._is_today_task(task)
        self.ctrl.toggle_timer(task.id)
        real_task = self.ctrl._find_task(task.id)
        is_today_now = bool(real_task and self._is_today_task(real_task))

        if was_today != is_today_now:
            # Task migrated panels — full rebuild required
            self._rebuild_panels()
            if is_today_now:
                self.query_one("#today-panel", TaskTablePanel).focus_task(task.id)
        else:
            # Same panel — update cells in-place, no flicker
            self._inplace_timer_update(task.id)

    def action_stop_timer(self) -> None:
        task = self._selected_task()
        if not task:
            return
        self.ctrl.stop_timer(task.id)
        # Stopped task keeps its today seconds, so it stays in the same panel
        self._inplace_timer_update(task.id)

    def _inplace_timer_update(self, task_id: str) -> None:
        """Update timer cells and panels in-place without a full table rebuild."""
        ids_to_update: set[str] = {task_id}
        parent = self.ctrl._find_parent(task_id)
        if parent:
            ids_to_update.add(parent.id)
        for panel in self.query(TaskTablePanel):
            panel.tick_update(ids_to_update, self.ctrl)
        selected = self._selected_item()
        self.query_one(DetailPanel).update_detail(selected, self.ctrl)
        self.query_one(SummaryPanel).update_summary(self.ctrl.tasks, self.ctrl)

    def action_new_task(self) -> None:
        def on_result(data: Optional[dict]) -> None:
            if data:
                self.ctrl.create_task(data["name"], data["description"])
                self._rebuild_panels()
                self.query_one("#all-tasks-panel", TaskTablePanel)._table.focus()

        self.app.push_screen(TaskFormScreen(), on_result)

    def action_add_subtask(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        parent = item.parent if item.is_subtask else item.task
        focused_panel = self._focused_panel()

        def on_result(data: Optional[dict]) -> None:
            if data:
                self.ctrl.create_subtask(parent.id, data["name"], data["description"])
                self._expanded.add(parent.id)
                self._rebuild_panels()
                if focused_panel:
                    focused_panel._table.focus()

        self.app.push_screen(TaskFormScreen(parent=parent), on_result)

    def action_edit_task(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        task = item.task
        task_parent = item.parent if item.is_subtask else None
        focused_panel = self._focused_panel()

        def on_result(data: Optional[dict]) -> None:
            if data:
                self.ctrl.update_task(task, data["name"], data["description"])
                self._rebuild_panels()
                if focused_panel:
                    focused_panel._table.focus()

        self.app.push_screen(TaskFormScreen(task, parent=task_parent), on_result)

    def action_delete_task(self) -> None:
        task = self._selected_task()
        if not task:
            return
        focused_panel = self._focused_panel()

        def on_result(confirmed: bool) -> None:
            if confirmed:
                self.ctrl.delete_task(task.id)
                self._rebuild_panels()
                if focused_panel:
                    focused_panel._table.focus()

        self.app.push_screen(ConfirmDialog(f'Delete "{task.name}"?'), on_result)

    def action_complete_task(self) -> None:
        task = self._selected_task()
        if not task:
            return
        self.ctrl.toggle_complete(task.id)
        self._rebuild_panels()

    def action_quit_app(self) -> None:
        self.ctrl.save_all_timers()
        self.app.exit()


# ── App ───────────────────────────────────────────────────────────────────────


class CronosApp(App):
    """Cronos CLI — Time Tracking TUI."""

    CSS_PATH = "app.tcss"
    TITLE = "Cronos CLI"
    SUB_TITLE = "Time Tracker"

    def on_mount(self) -> None:
        self.push_screen(MainScreen())
