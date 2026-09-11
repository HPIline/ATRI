"""JSON 任务卡：统一描述五项赛题的业务参数。"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from .skills import SKILL_NAMES

# 合法技能与 Brain 的注册表同源（skills.DEFAULT_SKILLS），避免校验层与运行层漂移。
VALID_SKILLS = SKILL_NAMES
REQUIRED_FIELDS = {"task_id", "name", "skills"}
KNOWN_FIELDS = REQUIRED_FIELDS | {"params", "timeout_s"}
DEFAULT_TIMEOUT_S = 120.0


class TaskCardError(ValueError):
    pass


def _reject_constant(value: str) -> Any:
    """json.load 的 parse_constant 钩子：拒绝 JSON 标准之外的 NaN/Infinity。"""
    raise TaskCardError(f"任务卡包含非法常量 {value}：JSON 不允许 NaN/Infinity")


@dataclass
class TaskCard:
    task_id: str
    name: str
    skills: List[str]
    params: Dict[str, Any] = field(default_factory=dict)
    timeout_s: float = DEFAULT_TIMEOUT_S

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskCard":
        if not isinstance(data, dict):
            raise TaskCardError(f"任务卡必须是 JSON 对象，实际为 {type(data).__name__}")
        missing = REQUIRED_FIELDS - set(data.keys())
        if missing:
            raise TaskCardError(f"task card missing fields: {sorted(missing)}")
        skills = data.get("skills") or []
        if not isinstance(skills, list) or not skills:
            raise TaskCardError("skills must be a non-empty list")
        if not all(isinstance(item, str) for item in skills):
            raise TaskCardError("skills must be a list of strings")
        unknown = [item for item in skills if item not in VALID_SKILLS]
        if unknown:
            raise TaskCardError(f"unknown skills: {unknown}")

        unknown_fields = sorted(set(data) - KNOWN_FIELDS)
        if unknown_fields:
            print(f"警告：任务卡 {data.get('task_id')!r} 含未知字段 {unknown_fields}，已忽略")

        timeout = data.get("timeout_s", DEFAULT_TIMEOUT_S)
        if isinstance(timeout, bool):
            raise TaskCardError(f"timeout_s must be a finite positive number, got {timeout!r}")
        try:
            timeout = float(timeout)
        except (TypeError, ValueError) as exc:
            raise TaskCardError(f"timeout_s must be a number, got {timeout!r}") from exc
        if not math.isfinite(timeout) or timeout <= 0.0:
            raise TaskCardError(f"timeout_s must be a finite positive number, got {timeout!r}")

        params = data.get("params") or {}
        if not isinstance(params, dict):
            raise TaskCardError("params must be an object")

        return cls(
            task_id=str(data["task_id"]),
            name=str(data["name"]),
            skills=[str(item) for item in skills],
            params=dict(params),
            timeout_s=timeout,
        )

    @classmethod
    def load(cls, path: str | Path) -> "TaskCard":
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh, parse_constant=_reject_constant)
        except TaskCardError:
            raise
        except json.JSONDecodeError as exc:
            raise TaskCardError(f"任务卡 JSON 解析失败: {exc}") from exc
        except UnicodeDecodeError as exc:
            # UnicodeDecodeError 是 ValueError 子类，既不是 OSError 也不是
            # JSONDecodeError，不显式捕获会裸抛成 traceback
            raise TaskCardError(f"任务卡不是 UTF-8 编码: {exc}") from exc
        except OSError as exc:
            raise TaskCardError(f"任务卡读取失败: {exc}") from exc
        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "skills": self.skills,
            "params": self.params,
            "timeout_s": self.timeout_s,
        }
