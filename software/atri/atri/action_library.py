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
- joints 的键必须来自 atri.config.JOINTS（22 DOF 关节名），值为该关节限位内的有限数字
- duration_s 为有限正数
- 该格式可直接由 Webots 标定脚本导出，也可由 atri.cerebellum 导入执行
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import JOINTS

ACTION_SCHEMA_VERSION = "1.0"
REQUIRED_FIELDS = {"schema_version", "action_id", "frames"}


class ActionLibraryError(ValueError):
    pass


def _is_number(value: Any) -> bool:
    """bool 是 int 的子类，但作为关节角/时长没有意义，需排除。"""
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _reject_constant(token: str) -> Any:
    # json 默认接受 NaN/Infinity 字面量，动作库不允许这种非标准 JSON
    raise ActionLibraryError(f"动作库 JSON 含非标准字面量: {token}")


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
        elif not _is_number(frame["duration_s"]):
            errors.append(f"{prefix}.duration_s 必须是数字，收到 {frame['duration_s']!r}")
        else:
            try:
                duration = float(frame["duration_s"])
            except OverflowError:
                errors.append(f"{prefix}.duration_s 超出可表示范围")
            else:
                if not math.isfinite(duration):
                    errors.append(f"{prefix}.duration_s 必须是有限数值，收到 {frame['duration_s']!r}")
                elif duration <= 0:
                    errors.append(f"{prefix}.duration_s 必须大于 0")
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            errors.append(f"{prefix} 缺少 joints 对象")
            continue
        for joint, value in joints.items():
            if joint not in JOINTS:
                errors.append(f"{prefix}.joints 包含未知关节: {joint}")
                continue
            if not _is_number(value):
                errors.append(f"{prefix}.joints.{joint} 必须是数字，收到 {value!r}")
                continue
            try:
                angle = float(value)
            except OverflowError:
                errors.append(f"{prefix}.joints.{joint} 超出可表示范围")
                continue
            if not math.isfinite(angle):
                errors.append(f"{prefix}.joints.{joint} 必须是有限数值，收到 {value!r}")
                continue
            lo, hi = JOINTS[joint]["limit_deg"]
            if not lo <= angle <= hi:
                errors.append(f"{prefix}.joints.{joint}={angle} 超出限位 [{lo}, {hi}]")
    return errors


def load_action(path: str | Path, strict: bool = False) -> Dict[str, Any]:
    """读取动作库 JSON。strict=True 时校验失败抛 ActionLibraryError。

    拒绝 NaN/Infinity 字面量（非标准 JSON，Python 的 json 默认会接受）。
    读取/解码/解析失败一律转 ActionLibraryError：动作库是外部文件，
    调用方只应处理一种异常类型。
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh, parse_constant=_reject_constant)
    except ActionLibraryError:
        raise
    except json.JSONDecodeError as exc:
        raise ActionLibraryError(f"动作库 JSON 解析失败: {exc}") from exc
    except UnicodeDecodeError as exc:
        # UnicodeDecodeError 是 ValueError 子类，既不是 OSError 也不是 JSONDecodeError
        raise ActionLibraryError(f"动作库不是 UTF-8 编码: {exc}") from exc
    except OSError as exc:
        raise ActionLibraryError(f"动作库读取失败: {exc}") from exc
    if not isinstance(data, dict):
        raise ActionLibraryError(
            f"动作库必须是 JSON 对象，实际为 {type(data).__name__}"
        )
    errors = validate_action(data)
    if strict and errors:
        raise ActionLibraryError("动作库校验失败:\n" + "\n".join(errors))
    return data
