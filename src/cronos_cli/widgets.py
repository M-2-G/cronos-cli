from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable, Input, Label, Static

from cronos_cli.models import Task, TaskStatus
from cronos_cli.ui_helpers import (
    FlatItem,
    complete_cell,
    fmt_time,
    fmt_time_big,
    icon_cell,
    time_cell,
)

if TYPE_CHECKING:
    from cronos_cli.controller import CronosController


# ── TaskTablePanel ─────────────────────────────────────────────────────────────


class TaskTablePanel(Vertical):
    """A labelled task DataTable with optional filter bar.

    Posts:
        SelectionChanged — cursor moved to a different row.
        ExpandToggled   — user pressed Enter on a collapsible task row.
    """

    class SelectionChanged(Message):
        def __init__(self, item: Optional[FlatItem]) -> None:
            super().__init__()
            self.item = item

    class ExpandToggled(Message):
        def __init__(self, task_id: str, panel: "TaskTablePanel") -> None:
            super().__init__()
            self.task_id = task_id
            self.panel = panel

    def __init__(
        self,
        title: str,
        header_id: str,
        table_id: str,
        show_filter: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._header_id = header_id
        self._table_id = table_id
        self._show_filter = show_filter
        self._filter_text: str = ""
        self._tasks: list[Task] = []
        self._expanded: set[str] = set()
        self._flat_items: list[FlatItem] = []
        self._ctrl: Optional[CronosController] = None

    def compose(self) -> ComposeResult:
        yield Label(f"  {self._title}", id=self._header_id)
        if self._show_filter:
            yield Input(placeholder="Filter tasks...", id="filter-input")
        yield DataTable(id=self._table_id, cursor_type="row")

    def on_mount(self) -> None:
        table = self._table
        table.add_column(" ", key="status")
        table.add_column(" ", key="done")
        table.add_column("Task Name", key="name")
        table.add_column("Time Today", key="time")
        if self._show_filter:
            self.query_one("#filter-input", Input).display = False

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def is_table_focused(self) -> bool:
        return self._table.has_focus

    @property
    def selected_item(self) -> Optional[FlatItem]:
        row = self._table.cursor_row
        if 0 <= row < len(self._flat_items):
            return self._flat_items[row]
        return None

    def rebuild(
        self, tasks: list[Task], expanded: set[str], ctrl: CronosController
    ) -> None:
        """Rebuild the table from fresh task data."""
        self._tasks = tasks
        self._expanded = expanded
        self._ctrl = ctrl
        self._do_rebuild()

    def focus_task(self, task_id: str) -> bool:
        """Focus the table and move cursor to task_id. Returns True if found."""
        for i, item in enumerate(self._flat_items):
            if item.task.id == task_id:
                self._table.focus()
                self._table.move_cursor(row=i)
                return True
        return False

    def tick_update(self, ids_to_update: set[str], ctrl: CronosController) -> None:
        """Update status and time cells in-place (no full rebuild)."""
        table = self._table
        visible = {item.task.id for item in self._flat_items}
        for task_id in ids_to_update:
            if task_id not in visible:
                continue
            if ctrl.is_subtask(task_id):
                icon = ctrl.get_status_icon(task_id)
                secs = ctrl.get_own_seconds(task_id)
            else:
                icon = ctrl.get_effective_status_icon(task_id)
                secs = ctrl.get_today_seconds(task_id)
            try:
                table.update_cell(task_id, "status", icon_cell(icon))
                table.update_cell(task_id, "time", time_cell(secs, icon))
            except Exception:
                pass

    # ── Internal ──────────────────────────────────────────────────────────────

    @property
    def _table(self) -> DataTable:
        return self.query_one(DataTable)

    @property
    def _header(self) -> Label:
        return self.query_one(Label)

    def _do_rebuild(self) -> None:
        table = self._table
        saved_id: Optional[str] = None
        if table.row_count > 0 and 0 <= table.cursor_row < len(self._flat_items):
            saved_id = self._flat_items[table.cursor_row].task.id

        self._flat_items = self._build_flat_items()

        # Resolve cursor target before touching the table so we can move in one shot
        target = 0
        if saved_id is not None:
            for i, item in enumerate(self._flat_items):
                if item.task.id == saved_id:
                    target = i
                    break
            else:
                parent = self._ctrl._find_parent(saved_id) if self._ctrl else None
                if parent:
                    for i, item in enumerate(self._flat_items):
                        if item.task.id == parent.id:
                            target = i
                            break

        with self.app.batch_update():
            table.clear()
            for item in self._flat_items:
                if item.is_subtask:
                    ic = self._ctrl.get_status_icon(item.task.id)
                    name = f"  └ {item.task.name}"
                    secs = self._ctrl.get_own_seconds(item.task.id)
                else:
                    ic = self._ctrl.get_effective_status_icon(item.task.id)
                    has_subs = bool(item.task.subtasks)
                    if has_subs:
                        marker = " ▾" if item.task.id in self._expanded else " ▸"
                        name = f"{item.task.name}{marker}"
                    else:
                        name = item.task.name
                    secs = self._ctrl.get_today_seconds(item.task.id)
                table.add_row(
                    icon_cell(ic),
                    complete_cell(item.task.status),
                    name,
                    time_cell(secs, ic),
                    key=item.task.id,
                )
            if table.row_count > 0:
                table.move_cursor(row=min(target, table.row_count - 1))

    def _build_flat_items(self) -> list[FlatItem]:
        q = self._filter_text.lower().strip()
        items: list[FlatItem] = []
        for task in self._tasks:
            if not q:
                items.append(FlatItem(task=task))
                if task.id in self._expanded and task.subtasks:
                    for sub in task.subtasks:
                        items.append(FlatItem(task=sub, parent=task))
            else:
                task_matches = q in task.name.lower()
                matching_subs = [s for s in task.subtasks if q in s.name.lower()]
                if not task_matches and not matching_subs:
                    continue
                items.append(FlatItem(task=task))
                if task_matches:
                    if task.id in self._expanded and task.subtasks:
                        for sub in task.subtasks:
                            items.append(FlatItem(task=sub, parent=task))
                else:
                    for sub in matching_subs:
                        items.append(FlatItem(task=sub, parent=task))
        return items

    # ── Event handlers ─────────────────────────────────────────────────────────

    def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
        self.post_message(self.SelectionChanged(self.selected_item))

    def on_input_changed(self, event: Input.Changed) -> None:
        self._filter_text = event.value
        self._do_rebuild()
        title_text = (
            f"  {self._title}  ·  /{self._filter_text}/"
            if self._filter_text
            else f"  {self._title}"
        )
        self._header.update(title_text)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._table.focus()

    def on_key(self, event) -> None:
        if self._show_filter:
            fi = self.query_one("#filter-input", Input)
            if event.key == "slash" and not fi.has_focus:
                fi.display = True
                fi.focus()
                event.stop()
                return
            if event.key == "escape" and fi.display:
                self._filter_text = ""
                fi.value = ""
                fi.display = False
                self._do_rebuild()
                self._header.update(f"  {self._title}")
                self._table.focus()
                event.stop()
                return

        if not self._table.has_focus:
            return
        if event.key == "j":
            self._table.action_cursor_down()
            event.stop()
        elif event.key == "k":
            self._table.action_cursor_up()
            event.stop()
        elif event.key == "enter":
            item = self.selected_item
            if item:
                target = item.parent if item.is_subtask else item.task
                if target.subtasks:
                    self.post_message(self.ExpandToggled(target.id, self))
            event.stop()


# ── DetailPanel ────────────────────────────────────────────────────────────────


class DetailPanel(Vertical):
    """Shows the big timer and details for the currently selected task."""

    def compose(self) -> ComposeResult:
        yield Label("  Selected Task", id="detail-header")
        yield Static("", id="task-detail")
        yield DataTable(id="subtask-detail-table", show_cursor=False)

    def on_mount(self) -> None:
        sub_table = self.query_one("#subtask-detail-table", DataTable)
        sub_table.add_column(" ", key="status")
        sub_table.add_column(" ", key="done")
        sub_table.add_column("Subtask", key="name")
        sub_table.add_column("Time", key="time")
        self.query_one("#task-detail", Static).update(
            "\n\n[dim]No task selected[/dim]"
        )
        sub_table.display = False

    def update_detail(self, item: Optional[FlatItem], ctrl: CronosController) -> None:
        detail = self.query_one("#task-detail", Static)
        sub_table = self.query_one("#subtask-detail-table", DataTable)

        if item is None:
            detail.update("\n\n[dim]No task selected[/dim]")
            sub_table.display = False
            return

        task = item.task
        if item.is_subtask:
            secs = ctrl.get_own_seconds(task.id)
            ic = ctrl.get_status_icon(task.id)
        else:
            secs = ctrl.get_today_seconds(task.id)
            ic = ctrl.get_effective_status_icon(task.id)

        big = fmt_time_big(secs)
        lines: list[str] = ["", ""]

        if ic == "▶":
            lines.append(f"[bold green]{big}[/bold green]")
            lines.append("")
            lines.append("[green]▶  Running[/green]")
        elif ic == "⏸":
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

        if not item.is_subtask and task.subtasks:
            sub_table.display = True
            sub_table.clear()
            for sub in task.subtasks:
                sub_ic = ctrl.get_status_icon(sub.id)
                sub_secs = ctrl.get_own_seconds(sub.id)
                sub_table.add_row(
                    icon_cell(sub_ic),
                    complete_cell(sub.status),
                    sub.name,
                    time_cell(sub_secs, sub_ic),
                )
        else:
            sub_table.display = False


# ── SummaryPanel ───────────────────────────────────────────────────────────────


class SummaryPanel(Vertical):
    """Shows per-task and total time tracked today."""

    def compose(self) -> ComposeResult:
        yield Label("  Today's Summary", id="summary-header")
        yield DataTable(id="summary-table", show_cursor=False)

    def on_mount(self) -> None:
        table = self.query_one("#summary-table", DataTable)
        table.add_column(" ", key="done")
        table.add_column("Task", key="task")
        table.add_column("Total Time", key="total")

    def update_summary(self, tasks: list[Task], ctrl: CronosController) -> None:
        summary = self.query_one("#summary-table", DataTable)
        summary.clear()
        has_time = False
        for task in tasks:
            secs = ctrl.get_today_seconds(task.id)
            if secs > 0:
                summary.add_row(complete_cell(task.status), task.name, fmt_time(secs))
                has_time = True
        if not has_time:
            summary.add_row(Text(" "), "No time tracked today", "──────")
        else:
            total = ctrl.get_total_today_seconds()
            summary.add_row(Text(" "), "─────────────", "─────────")
            summary.add_row(
                Text(" "), "[bold]Total[/bold]", f"[bold]{fmt_time(total)}[/bold]"
            )
