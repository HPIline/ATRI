"""动作库 JSON 格式校验器。

关键帧动作库规范：
{
  "schema_version": "1.0",
  "action_id": "walk",
  "name": "前进",
  "description": "可选描述",
  "loop": false,
  "frames": [
    {
      "index": 0,
      "duration_s": 0.2,
      "joints": {"left_hip_pitch": 8.0, ...},
      "comment": "可选"
    }
  ],
  "meta": {"source": "webots-calibration", "author": "..."}
}

约定：
- joints 的键必须来自 atri.config.JOINTS（22 DOF 关节名）
- duration_s > 0
- 该格式可直接由 Webots 标定脚本导出，也可由 atri.cerebellum 导入执行
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import JOINTS

ACTION_SCHEMA_VERSION = "1.0"
REQUIRED_FIELDS = {"schema_version", "action_id", "frames"}


class ActionLibraryError(ValueError):
    pass


def validate_action(data: Dict[str, Any]) -> List[str]:
    """返回动作库数据的校验错误列表；无错误时返回空列表。"""
    errors: List[str] = []

    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        errors.append(f"缺少必需字段: {sorted(missing)}")

    if data.get("schema_version") != ACTION_SCHEMA_VERSION:
        errors.append(f"schema_version 应为 {ACTION_SCHEMA_VERSION!r}")

    if not data.get("action_id"):
        errors.append("action_id 不能为空")

    frames = data.get("frames")
    if not isinstance(frames, list):
        errors.append("frames 必须为数组")
        return errors
    if not frames:
        errors.append("frames 不能为空数组")
        return errors

    for i, frame in enumerate(frames):
        prefix = f"frames[{i}]"
        if not isinstance(frame, dict):
            errors.append(f"{prefix} 必须是对象")
            continue
        if "duration_s" not in frame:
            errors.append(f"{prefix} 缺少 duration_s")
        else:
            try:
                duration = float(frame["duration_s"])
                if duration <= 0:
                    errors.append(f"{prefix}.duration_s 必须大于 0")
            except (TypeError, ValueError):
                errors.append(f"{prefix}.duration_s 必须是数字")
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            errors.append(f"{prefix} 缺少 joints 对象")
            continue
        for joint in joints:
            if joint not in JOINTS:
                errors.append(f"{prefix}.joints 包含未知关节: {joint}")
    return errors


def load_action(path: str | Path, strict: bool = False) -> Dict[str, Any]:
    """读取动作库 JSON。strict=True 时校验失败抛 ActionLibraryError。"""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    errors = validate_action(data)
    if strict and errors:
        raise ActionLibraryError("动作库校验失败:\n" + "\n".join(errors))
    return data
