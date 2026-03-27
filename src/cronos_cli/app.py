from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, Rule, Static

from cronos_cli.controller import CronosController
from cronos_cli.models import Task, TaskStatus
from cronos_cli.storage import StorageManager


def fmt_time(seconds: float) -> str:
    total = max(0, int(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# 3-row box-drawing digits — each character is exactly 3 columns wide.
# "HH:MM:SS" (8 chars × 3 cols) = 24 columns total.
_BIG_CHARS: dict[str, tuple[str, str, str]] = {
    "0": ("┌─┐", "│ │", "└─┘"),
    "1": (" ╷ ", " │ ", " ╵ "),
    "2": ("╶─┐", "┌─┘", "└─╴"),
    "3": ("╶─┐", "╶─┤", "╶─┘"),
    "4": ("╷ ╷", "└─┤", "  ╵"),
    "5": ("┌─╴", "└─┐", "╶─┘"),
    "6": ("┌─╴", "├─┐", "└─┘"),
    "7": ("╶─┐", "  │", "  ╵"),
    "8": ("┌─┐", "├─┤", "└─┘"),
    "9": ("┌─┐", "└─┤", "╶─┘"),
    ":": (" ╷ ", "   ", " ╵ "),
}


def fmt_time_big(seconds: float) -> str:
    """Render time as 3-row box-drawing art — visually ~2× the normal height."""
    rows = ["", "", ""]
    for ch in fmt_time(seconds):
        r0, r1, r2 = _BIG_CHARS.get(ch, ("   ", "   ", "   "))
        rows[0] += r0
        rows[1] += r1
        rows[2] += r2
    return "\n".join(rows)


def _time_cell(seconds: float, icon: str) -> Text:
    """Rich Text for a timer cell: green=running, bright_yellow=paused, plain=idle."""
    time_str = fmt_time(seconds)
    if icon == "▶":
        return Text.from_markup(f"[green]{time_str}[/green]")
    if icon == "⏸":
        return Text.from_markup(f"[bright_yellow]{time_str}[/bright_yellow]")
    return Text(time_str)


def _complete_cell(status: TaskStatus) -> Text:
    """Rich Text for the completion status cell."""
    if status == TaskStatus.COMPLETED:
        return Text.from_markup("[green]✓[/green]")
    return Text(" ")


def _icon_cell(icon: str) -> Text:
    """Rich Text for a status icon cell with matching color."""
    if icon == "▶":
        return Text.from_markup("[green]▶[/green]")
    if icon == "⏸":
        return Text.from_markup("[bright_yellow]⏸[/bright_yellow]")
    return Text(" ")


# ── Flat task list item ────────────────────────────────────────────────────────


@dataclass
class FlatItem:
    task: Task
    parent: Optional[Task] = None

    @property
    def is_subtask(self) -> bool:
        return self.parent is not None


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
    """Create or edit a task."""

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
            title = f"Edit Subtask  ·  {self._parent_task.name}" if self._parent_task else "Edit Task"
        else:
            title = f"New Subtask  ·  {self._parent_task.name}" if self._parent_task else "New Task"
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
    """Left: today + all-tasks panels.  Right: selected-task detail + daily summary."""

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
        self._today_items: list[FlatItem] = []
        self._all_items: list[FlatItem] = []

    # ── Compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-layout"):
            with Vertical(id="left-panel"):
                with Vertical(id="today-panel"):
                    yield Label("  Today", id="today-header")
                    yield DataTable(id="today-table", cursor_type="row")
                with Vertical(id="all-tasks-panel"):
                    yield Label("  All Tasks", id="all-tasks-header")
                    yield DataTable(id="task-table", cursor_type="row")
            with Vertical(id="right-panel"):
                with Vertical(id="detail-panel"):
                    yield Label("  Selected Task", id="detail-header")
                    yield Static("", id="task-detail")
                    yield DataTable(id="subtask-detail-table", show_cursor=False)
                with Vertical(id="summary-panel"):
                    yield Label("  Today's Summary", id="summary-header")
                    yield DataTable(id="summary-table", show_cursor=False)
        yield Footer()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        for table_id in ("today-table", "task-table"):
            t = self.query_one(f"#{table_id}", DataTable)
            t.add_column(" ", key="status")
            t.add_column(" ", key="done")
            t.add_column("Task Name", key="name")
            t.add_column("Time Today", key="time")

        summary_table = self.query_one("#summary-table", DataTable)
        summary_table.add_column(" ", key="done")
        summary_table.add_column("Task", key="task")
        summary_table.add_column("Total Time", key="total")

        sub_table = self.query_one("#subtask-detail-table", DataTable)
        sub_table.add_column(" ", key="status")
        sub_table.add_column(" ", key="done")
        sub_table.add_column("Subtask", key="name")
        sub_table.add_column("Time", key="time")

        self._load_and_refresh()
        self._tick_handle = self.set_interval(1.0, self._on_tick)

        # Focus today-table if it has rows, else all-tasks
        if self.query_one("#today-table", DataTable).row_count > 0:
            self.query_one("#today-table", DataTable).focus()
        else:
            self.query_one("#task-table", DataTable).focus()

    def on_unmount(self) -> None:
        if self._tick_handle is not None:
            self._tick_handle.stop()

    # ── Event handlers ────────────────────────────────────────────────────────

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id in ("today-table", "task-table"):
            self._refresh_detail()

    def on_key(self, event) -> None:
        if event.key == "ctrl+j":
            self.query_one("#task-table", DataTable).focus()
            event.stop()
            return
        if event.key == "ctrl+k":
            self.query_one("#today-table", DataTable).focus()
            event.stop()
            return
        focused = self._focused_table()
        if focused is None:
            return
        if event.key == "j":
            focused.action_cursor_down()
            event.stop()
        elif event.key == "k":
            focused.action_cursor_up()
            event.stop()
        elif event.key == "enter":
            self.action_toggle_expand()
            event.stop()

    # ── Selection helpers ──────────────────────────────────────────────────────

    def _focused_table(self) -> Optional[DataTable]:
        for tid in ("today-table", "task-table"):
            t = self.query_one(f"#{tid}", DataTable)
            if t.has_focus:
                return t
        return None

    def _focused_items(self) -> list[FlatItem]:
        today = self.query_one("#today-table", DataTable)
        return self._today_items if today.has_focus else self._all_items

    def _selected_flat_item(self) -> Optional[FlatItem]:
        table = self._focused_table()
        if table is None:
            return None
        items = self._focused_items()
        row = table.cursor_row
        if 0 <= row < len(items):
            return items[row]
        return None

    def _selected_task(self) -> Optional[Task]:
        item = self._selected_flat_item()
        return item.task if item else None

    # ── Display refresh ───────────────────────────────────────────────────────

    def _load_and_refresh(self) -> None:
        self.ctrl.load_tasks()
        self._rebuild_both_tables()
        self._rebuild_summary()
        self._refresh_detail()

    def _is_today_task(self, task: Task) -> bool:
        """True if task or any subtask has been active today (persists across restarts)."""
        if task.id in self.ctrl.active_entries:
            return True
        for sub in task.subtasks:
            if sub.id in self.ctrl.active_entries:
                return True
        return self.ctrl.get_today_seconds(task.id) > 0

    def _build_items(self, today_only: bool) -> list[FlatItem]:
        items: list[FlatItem] = []
        for task in self.ctrl.tasks:
            if self._is_today_task(task) != today_only:
                continue
            items.append(FlatItem(task=task))
            if task.id in self._expanded and task.subtasks:
                for sub in task.subtasks:
                    items.append(FlatItem(task=sub, parent=task))
        return items

    def _fill_table(self, table: DataTable, items: list[FlatItem]) -> None:
        table.clear()
        for item in items:
            if item.is_subtask:
                icon = self.ctrl.get_status_icon(item.task.id)
                name = f"  └ {item.task.name}"
                secs = self.ctrl.get_own_seconds(item.task.id)
            else:
                icon = self.ctrl.get_effective_status_icon(item.task.id)
                has_subs = bool(item.task.subtasks)
                if has_subs:
                    marker = " ▾" if item.task.id in self._expanded else " ▸"
                    name = f"{item.task.name}{marker}"
                else:
                    name = item.task.name
                secs = self.ctrl.get_today_seconds(item.task.id)
            table.add_row(
                _icon_cell(icon),
                _complete_cell(item.task.status),
                name,
                _time_cell(secs, icon),
                key=item.task.id,
            )

    def _rebuild_table(self, table_id: str, items: list[FlatItem], saved_id: Optional[str]) -> None:
        table = self.query_one(f"#{table_id}", DataTable)
        self._fill_table(table, items)
        # Restore cursor
        target = 0
        if saved_id is not None:
            for i, item in enumerate(items):
                if item.task.id == saved_id:
                    target = i
                    break
            else:
                parent = self.ctrl._find_parent(saved_id)
                if parent:
                    for i, item in enumerate(items):
                        if item.task.id == parent.id:
                            target = i
                            break
        if table.row_count > 0:
            table.move_cursor(row=min(target, table.row_count - 1))

    def _rebuild_both_tables(self) -> None:
        today_table = self.query_one("#today-table", DataTable)
        all_table = self.query_one("#task-table", DataTable)

        # Save cursors before rebuild
        saved_today = (
            self._today_items[today_table.cursor_row].task.id
            if today_table.row_count > 0 and 0 <= today_table.cursor_row < len(self._today_items)
            else None
        )
        saved_all = (
            self._all_items[all_table.cursor_row].task.id
            if all_table.row_count > 0 and 0 <= all_table.cursor_row < len(self._all_items)
            else None
        )

        self._today_items = self._build_items(today_only=True)
        self._all_items = self._build_items(today_only=False)

        self._rebuild_table("today-table", self._today_items, saved_today)
        self._rebuild_table("task-table", self._all_items, saved_all)

    def _rebuild_summary(self) -> None:
        summary = self.query_one("#summary-table", DataTable)
        summary.clear()
        has_time = False
        for task in self.ctrl.tasks:
            secs = self.ctrl.get_today_seconds(task.id)
            if secs > 0:
                summary.add_row(_complete_cell(task.status), task.name, fmt_time(secs))
                has_time = True
        if not has_time:
            summary.add_row(Text(" "), "No time tracked today", "──────")
        else:
            total = self.ctrl.get_total_today_seconds()
            summary.add_row(Text(" "), "─────────────", "─────────")
            summary.add_row(Text(" "), "[bold]Total[/bold]", f"[bold]{fmt_time(total)}[/bold]")

    def _refresh_detail(self) -> None:
        detail = self.query_one("#task-detail", Static)
        sub_table = self.query_one("#subtask-detail-table", DataTable)
        item = self._selected_flat_item()

        if item is None:
            detail.update("\n\n[dim]No task selected[/dim]")
            sub_table.display = False
            return

        task = item.task
        if item.is_subtask:
            secs = self.ctrl.get_own_seconds(task.id)
            icon = self.ctrl.get_status_icon(task.id)
        else:
            secs = self.ctrl.get_today_seconds(task.id)
            icon = self.ctrl.get_effective_status_icon(task.id)

        big = fmt_time_big(secs)
        lines: list[str] = ["", ""]  # top padding

        if icon == "▶":
            lines.append(f"[bold green]{big}[/bold green]")
            lines.append("")
            lines.append("[green]▶  Running[/green]")
        elif icon == "⏸":
            lines.append(f"[bold bright_yellow]{big}[/bold bright_yellow]")
            lines.append("")
            lines.append("[bright_yellow]⏸  Paused[/bright_yellow]")
        else:
            lines.append(f"[bold]{big}[/bold]")
            lines.append("")
            lines.append("[dim]No active timer[/dim]")

        lines += ["", "─" * 22, ""]
        lines.append(f"[bold]{task.name}[/bold]")
        if task.description:
            lines.append(f"[dim]{task.description}[/dim]")
        if task.status == TaskStatus.COMPLETED:
            lines.append("[green]✓  Completed[/green]")

        detail.update("\n".join(lines))

        # Subtask table — only for top-level tasks that have subtasks
        if not item.is_subtask and task.subtasks:
            sub_table.display = True
            sub_table.clear()
            for sub in task.subtasks:
                sub_icon = self.ctrl.get_status_icon(sub.id)
                sub_secs = self.ctrl.get_own_seconds(sub.id)
                sub_table.add_row(
                    _icon_cell(sub_icon),
                    _complete_cell(sub.status),
                    sub.name,
                    _time_cell(sub_secs, sub_icon),
                )
        else:
            sub_table.display = False

    def _on_tick(self) -> None:
        if not self.ctrl.active_entries:
            return

        # Collect IDs to update: active entries + their parents
        ids_to_update: set[str] = set(self.ctrl.active_entries.keys())
        for task_id in list(self.ctrl.active_entries.keys()):
            parent = self.ctrl._find_parent(task_id)
            if parent:
                ids_to_update.add(parent.id)

        for table_id, items in (("today-table", self._today_items), ("task-table", self._all_items)):
            table = self.query_one(f"#{table_id}", DataTable)
            visible = {item.task.id for item in items}
            for task_id in ids_to_update:
                if task_id not in visible:
                    continue
                if self.ctrl.is_subtask(task_id):
                    icon = self.ctrl.get_status_icon(task_id)
                    secs = self.ctrl.get_own_seconds(task_id)
                else:
                    icon = self.ctrl.get_effective_status_icon(task_id)
                    secs = self.ctrl.get_today_seconds(task_id)
                try:
                    table.update_cell(task_id, "time", _time_cell(secs, icon))
                except Exception:
                    pass

        self._rebuild_summary()
        self._refresh_detail()

    # ── Actions (UI → controller → refresh) ──────────────────────────────────

    def action_toggle_timer(self) -> None:
        task = self._selected_task()
        if not task:
            return
        self.ctrl.toggle_timer(task.id)
        self._rebuild_both_tables()
        self._rebuild_summary()
        self._refresh_detail()
        # If the task just moved to today, follow it there
        if self._is_today_task(self.ctrl._find_task(task.id) or task):
            today_table = self.query_one("#today-table", DataTable)
            for i, item in enumerate(self._today_items):
                if item.task.id == task.id:
                    today_table.focus()
                    today_table.move_cursor(row=i)
                    break

    def action_stop_timer(self) -> None:
        task = self._selected_task()
        if not task:
            return
        self.ctrl.stop_timer(task.id)
        self._rebuild_both_tables()
        self._rebuild_summary()
        self._refresh_detail()

    def action_new_task(self) -> None:
        def on_result(data: Optional[dict]) -> None:
            if data:
                self.ctrl.create_task(data["name"], data["description"])
                self._rebuild_both_tables()
                self._rebuild_summary()
                self._refresh_detail()
                self.query_one("#task-table", DataTable).focus()

        self.app.push_screen(TaskFormScreen(), on_result)

    def action_add_subtask(self) -> None:
        item = self._selected_flat_item()
        if item is None:
            return
        parent = item.parent if item.is_subtask else item.task
        focused_id = self._focused_table().id

        def on_result(data: Optional[dict]) -> None:
            if data:
                self.ctrl.create_subtask(parent.id, data["name"], data["description"])
                self._expanded.add(parent.id)
                self._rebuild_both_tables()
                self._rebuild_summary()
                self._refresh_detail()
                self.query_one(f"#{focused_id}", DataTable).focus()

        self.app.push_screen(TaskFormScreen(parent=parent), on_result)

    def action_toggle_expand(self) -> None:
        item = self._selected_flat_item()
        if item is None:
            return
        target = item.parent if item.is_subtask else item.task
        if not target.subtasks:
            return
        if target.id in self._expanded:
            self._expanded.discard(target.id)
        else:
            self._expanded.add(target.id)
        self._rebuild_both_tables()

    def action_edit_task(self) -> None:
        item = self._selected_flat_item()
        if item is None:
            return
        task = item.task
        parent = item.parent if item.is_subtask else None
        focused_id = self._focused_table().id

        def on_result(data: Optional[dict]) -> None:
            if data:
                self.ctrl.update_task(task, data["name"], data["description"])
                self._rebuild_both_tables()
                self._rebuild_summary()
                self._refresh_detail()
                self.query_one(f"#{focused_id}", DataTable).focus()

        self.app.push_screen(TaskFormScreen(task, parent=parent), on_result)

    def action_delete_task(self) -> None:
        task = self._selected_task()
        if not task:
            return
        focused_id = self._focused_table().id

        def on_result(confirmed: bool) -> None:
            if confirmed:
                self.ctrl.delete_task(task.id)
                self._rebuild_both_tables()
                self._rebuild_summary()
                self._refresh_detail()
                self.query_one(f"#{focused_id}", DataTable).focus()

        self.app.push_screen(
            ConfirmDialog(f'Delete "{task.name}"?'),
            on_result,
        )

    def action_complete_task(self) -> None:
        task = self._selected_task()
        if not task:
            return
        self.ctrl.toggle_complete(task.id)
        self._rebuild_both_tables()
        self._rebuild_summary()
        self._refresh_detail()

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
