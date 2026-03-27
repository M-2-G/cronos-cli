from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rich.text import Text

from cronos_cli.models import Task, TaskStatus


def fmt_time(seconds: float) -> str:
    total = max(0, int(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


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
    rows = ["", "", ""]
    for ch in fmt_time(seconds):
        r0, r1, r2 = _BIG_CHARS.get(ch, ("   ", "   ", "   "))
        rows[0] += r0
        rows[1] += r1
        rows[2] += r2
    return "\n".join(rows)


def time_cell(seconds: float, icon: str) -> Text:
    time_str = fmt_time(seconds)
    if icon == "▶":
        return Text.from_markup(f"[green]{time_str}[/green]")
    if icon == "⏸":
        return Text.from_markup(f"[bright_yellow]{time_str}[/bright_yellow]")
    return Text(time_str)


def complete_cell(status: TaskStatus) -> Text:
    if status == TaskStatus.COMPLETED:
        return Text.from_markup("[green]✓[/green]")
    return Text(" ")


def icon_cell(icon: str) -> Text:
    if icon == "▶":
        return Text.from_markup("[green]▶[/green]")
    if icon == "⏸":
        return Text.from_markup("[bright_yellow]⏸[/bright_yellow]")
    return Text(" ")


@dataclass
class FlatItem:
    task: Task
    parent: Optional[Task] = None

    @property
    def is_subtask(self) -> bool:
        return self.parent is not None
