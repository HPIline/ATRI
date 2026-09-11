"""动作库导出工具：把 Cerebellum 内置/标定关键帧写成统一 JSON。

供 Webots 标定脚本或本地工具调用，导出后可直接用 atri.action_library 导入，
也可由 Cerebellum.play_action() 回放。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .action_library import ACTION_SCHEMA_VERSION, validate_action
from .cerebellum import Cerebellum


def frames_to_action(
    action_id: str,
    frames: List[Dict[str, float]],
    duration_s: float = 0.02,
    name: Optional[str] = None,
    description: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把关键帧列表转换为 action_library 标准 JSON。"""
    action_frames = [
        {
            "index": i,
            "duration_s": duration_s,
            "joints": {name: float(value) for name, value in frame.items()},
        }
        for i, frame in enumerate(frames)
    ]
    action: Dict[str, Any] = {
        "schema_version": ACTION_SCHEMA_VERSION,
        "action_id": action_id,
        "name": name or action_id,
        "frames": action_frames,
    }
    if description:
        action["description"] = description
    if meta:
        action["meta"] = meta
    errors = validate_action(action)
    if errors:
        raise ValueError("导出动作校验失败:\n" + "\n".join(errors))
    return action


def export_walk(
    output_path: str | Path,
    steps: int = 4,
    period_s: float = 0.4,
    duration_s: float = 0.02,
    **gait_kwargs: Any,
) -> str:
    """把 Cerebellum.generate_gait() 的步态关键帧导出为 walk.json。"""
    frames = Cerebellum().generate_gait(steps=steps, period_s=period_s, **gait_kwargs)
    action = frames_to_action(
        "walk",
        frames,
        duration_s=duration_s,
        name="前进",
        description="由 Cerebellum.generate_gait() 导出的双足步态关键帧",
        meta={"source": "atri-generated", "steps": steps, "period_s": period_s},
    )
    out = Path(output_path)
    out.write_text(json.dumps(action, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(out)
