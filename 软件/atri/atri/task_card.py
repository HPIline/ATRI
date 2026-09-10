"""JSON 任务卡：统一描述五项赛题的业务参数。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

VALID_SKILLS = {"face", "qr", "carry", "kick", "dance", "idle"}
REQUIRED_FIELDS = {"task_id", "name", "skills"}


class TaskCardError(ValueError):
    pass


@dataclass
class TaskCard:
    task_id: str
    name: str
    skills: List[str]
    params: Dict[str, Any] = field(default_factory=dict)
    timeout_s: float = 120.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskCard":
        missing = REQUIRED_FIELDS - set(data.keys())
        if missing:
            raise TaskCardError(f"task card missing fields: {sorted(missing)}")
        skills = data.get("skills") or []
        if not isinstance(skills, list) or not skills:
            raise TaskCardError("skills must be a non-empty list")
        unknown = [s for s in skills if s not in VALID_SKILLS]
        if unknown:
            raise TaskCardError(f"unknown skills: {unknown}")
        try:
            timeout = float(data.get("timeout_s", 120.0))
        except (TypeError, ValueError) as exc:
            raise TaskCardError("timeout_s must be a number") from exc
        return cls(
            task_id=str(data["task_id"]),
            name=str(data["name"]),
            skills=[str(s) for s in skills],
            params=dict(data.get("params") or {}),
            timeout_s=timeout,
        )

    @classmethod
    def load(cls, path: str | Path) -> "TaskCard":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "skills": self.skills,
            "params": self.params,
            "timeout_s": self.timeout_s,
        }
