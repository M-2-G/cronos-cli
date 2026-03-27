from __future__ import annotations

from typing import Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, Rule, Static

from cronos_cli.controller import CronosController
from cronos_cli.models import Task
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


def _icon_cell(icon: str) -> Text:
    """Rich Text for a status icon cell with matching color."""
    if icon == "▶":
        return Text.from_markup("[green]▶[/green]")
    if icon == "⏸":
        return Text.from_markup("[bright_yellow]⏸[/bright_yellow]")
    return Text(" ")


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

    def __init__(self, task: Optional[Task] = None) -> None:
        super().__init__()
        self._edit_task = task

    def compose(self) -> ComposeResult:
        title = "Edit Task" if self._edit_task else "New Task"
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
    """Left: task list.  Right top: selected-task detail.  Right bottom: daily summary."""

    BINDINGS = [
        Binding("space", "toggle_timer", "Start/Pause", show=True),
        Binding("s", "stop_timer", "Stop", show=True),
        Binding("n", "new_task", "New", show=True),
        Binding("e", "edit_task", "Edit", show=True),
        Binding("d", "delete_task", "Delete", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("q", "quit_app", "Quit", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.ctrl = CronosController(StorageManager())
        self._tick_handle = None

    # ── Compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-layout"):
            with Vertical(id="left-panel"):
                yield Label("  Tasks", id="tasks-header")
                yield DataTable(id="task-table", cursor_type="row")
            with Vertical(id="right-panel"):
                with Vertical(id="detail-panel"):
                    yield Label("  Selected Task", id="detail-header")
                    yield Static("", id="task-detail")
                with Vertical(id="summary-panel"):
                    yield Label("  Today's Summary", id="summary-header")
                    yield DataTable(id="summary-table", show_cursor=False)
        yield Footer()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        task_table = self.query_one("#task-table", DataTable)
        task_table.add_column(" ", key="status")
        task_table.add_column("Task Name", key="name")
        task_table.add_column("Time Today", key="time")

        summary_table = self.query_one("#summary-table", DataTable)
        summary_table.add_column("Task", key="task")
        summary_table.add_column("Total Time", key="total")

        self._load_and_refresh()
        self._tick_handle = self.set_interval(1.0, self._on_tick)
        task_table.focus()

    def on_unmount(self) -> None:
        if self._tick_handle is not None:
            self._tick_handle.stop()

    # ── Event handlers ────────────────────────────────────────────────────────

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "task-table":
            self._refresh_detail()

    def on_key(self, event) -> None:
        table = self.query_one("#task-table", DataTable)
        if not table.has_focus:
            return
        if event.key == "j":
            table.action_cursor_down()
            event.stop()
        elif event.key == "k":
            table.action_cursor_up()
            event.stop()

    # ── Display refresh ───────────────────────────────────────────────────────

    def _load_and_refresh(self) -> None:
        self.ctrl.load_tasks()
        self._rebuild_task_table()
        self._rebuild_summary()
        self._refresh_detail()

    def _rebuild_task_table(self) -> None:
        table = self.query_one("#task-table", DataTable)
        saved_row = table.cursor_row if table.row_count > 0 else 0
        table.clear()
        for task in self.ctrl.tasks:
            icon = self.ctrl.get_status_icon(task.id)
            table.add_row(
                _icon_cell(icon),
                task.name,
                _time_cell(self.ctrl.get_today_seconds(task.id), icon),
                key=task.id,
            )
        if table.row_count > 0:
            table.move_cursor(row=min(saved_row, table.row_count - 1))

    def _rebuild_summary(self) -> None:
        summary = self.query_one("#summary-table", DataTable)
        summary.clear()
        has_time = False
        for task in self.ctrl.tasks:
            secs = self.ctrl.get_today_seconds(task.id)
            if secs > 0:
                summary.add_row(task.name, fmt_time(secs))
                has_time = True
        if not has_time:
            summary.add_row("No time tracked today", "──────")
        else:
            total = self.ctrl.get_total_today_seconds()
            summary.add_row("─────────────", "─────────")
            summary.add_row("[bold]Total[/bold]", f"[bold]{fmt_time(total)}[/bold]")

    def _refresh_detail(self) -> None:
        detail = self.query_one("#task-detail", Static)
        task = self._selected_task()
        if task is None:
            detail.update("\n\n[dim]No task selected[/dim]")
            return

        secs = self.ctrl.get_today_seconds(task.id)
        icon = self.ctrl.get_status_icon(task.id)
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

        detail.update("\n".join(lines))

    def _on_tick(self) -> None:
        if not self.ctrl.active_entries:
            return
        table = self.query_one("#task-table", DataTable)
        for task_id in list(self.ctrl.active_entries.keys()):
            icon = self.ctrl.get_status_icon(task_id)
            try:
                table.update_cell(
                    task_id, "time",
                    _time_cell(self.ctrl.get_today_seconds(task_id), icon),
                )
            except Exception:
                pass
        self._rebuild_summary()
        self._refresh_detail()

    # ── Selection ─────────────────────────────────────────────────────────────

    def _selected_task(self) -> Optional[Task]:
        table = self.query_one("#task-table", DataTable)
        if table.row_count == 0:
            return None
        row = table.cursor_row
        if 0 <= row < len(self.ctrl.tasks):
            return self.ctrl.tasks[row]
        return None

    # ── Actions (UI → controller → refresh) ──────────────────────────────────

    def action_toggle_timer(self) -> None:
        task = self._selected_task()
        if not task:
            return
        self.ctrl.toggle_timer(task.id)
        self._rebuild_task_table()
        self._rebuild_summary()
        self._refresh_detail()

    def action_stop_timer(self) -> None:
        task = self._selected_task()
        if not task:
            return
        self.ctrl.stop_timer(task.id)
        self._rebuild_task_table()
        self._rebuild_summary()
        self._refresh_detail()

    def action_new_task(self) -> None:
        def on_result(data: Optional[dict]) -> None:
            if data:
                self.ctrl.create_task(data["name"], data["description"])
                self._rebuild_task_table()
                self._rebuild_summary()
                self._refresh_detail()
                self.query_one("#task-table", DataTable).focus()

        self.app.push_screen(TaskFormScreen(), on_result)

    def action_edit_task(self) -> None:
        task = self._selected_task()
        if not task:
            return

        def on_result(data: Optional[dict]) -> None:
            if data:
                self.ctrl.update_task(task, data["name"], data["description"])
                self._rebuild_task_table()
                self._rebuild_summary()
                self._refresh_detail()
                self.query_one("#task-table", DataTable).focus()

        self.app.push_screen(TaskFormScreen(task), on_result)

    def action_delete_task(self) -> None:
        task = self._selected_task()
        if not task:
            return

        def on_result(confirmed: bool) -> None:
            if confirmed:
                self.ctrl.delete_task(task.id)
                self._rebuild_task_table()
                self._rebuild_summary()
                self._refresh_detail()
                self.query_one("#task-table", DataTable).focus()

        self.app.push_screen(
            ConfirmDialog(f'Delete task "{task.name}"?'),
            on_result,
        )

    def action_refresh(self) -> None:
        self._load_and_refresh()

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
