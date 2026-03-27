from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Task:
    name: str
    description: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    subtasks: list["Task"] = field(default_factory=list)
    status: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "subtasks": [s.to_dict() for s in self.subtasks],
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            created_at=data["created_at"],
            subtasks=[Task.from_dict(s) for s in data.get("subtasks", [])],
            status=data.get("status", ""),
        )


@dataclass
class TimeEntry:
    task_id: str
    task_name: str
    start_time: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    end_time: Optional[str] = None
    paused_at: Optional[str] = None
    total_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "paused_at": self.paused_at,
            "total_seconds": self.total_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TimeEntry:
        return cls(
            id=data["id"],
            task_id=data["task_id"],
            task_name=data["task_name"],
            start_time=data["start_time"],
            end_time=data.get("end_time"),
            paused_at=data.get("paused_at"),
            total_seconds=data.get("total_seconds", 0.0),
        )

    def is_running(self) -> bool:
        return self.end_time is None and self.paused_at is None

    def is_paused(self) -> bool:
        return self.end_time is None and self.paused_at is not None

    def elapsed_seconds(self) -> float:
        """Total elapsed seconds (including current running period if active)."""
        if self.end_time is not None:
            return self.total_seconds
        if self.paused_at is not None:
            return self.total_seconds
        # Currently running: add time since last start
        start = datetime.fromisoformat(self.start_time)
        return self.total_seconds + (datetime.now() - start).total_seconds()
