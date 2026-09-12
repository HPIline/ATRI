"""二维码循迹技能：解码 JSON 指令（单动作或路径序列）并下发给小脑。"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from ..config import MAX_BARS, MAX_STEPS, MAX_TURN_DEG, VALID_ACTIONS
from .base import (
    Skill,
    SkillContext,
    as_finite_float,
    as_int_in_range,
    failed,
    perception_data,
)


def _dispatch_action(ctx: SkillContext, payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """执行单条二维码动作。成功返回 (result, None)，失败返回 (None, reason)。"""
    action = payload.get("action")
    if not isinstance(action, str) or action not in VALID_ACTIONS:
        return None, f"未知动作: {action!r}，可选 {sorted(VALID_ACTIONS)}"

    try:
        if action == "walk":
            steps = as_int_in_range(payload.get("steps", 3), 1, MAX_STEPS)
            if steps is None:
                return None, f"steps 非法: {payload.get('steps')!r}（应为 1..{MAX_STEPS} 整数）"
            print(f"  [QR] decoded action={action}, steps={steps}")
            result = ctx.cerebellum.walk(steps=steps, **ctx.gait)
        elif action == "turn":
            deg = as_finite_float(payload.get("deg", 30.0))
            if deg is None or abs(deg) > MAX_TURN_DEG:
                return None, (
                    f"deg 非法: {payload.get('deg')!r}（应为 ±{MAX_TURN_DEG:g} 内的有限数值）"
                )
            print(f"  [QR] decoded action={action}, deg={deg}")
            result = ctx.cerebellum.turn(deg)
        elif action == "dance":
            bars = as_int_in_range(payload.get("bars", 2), 1, MAX_BARS)
            if bars is None:
                return None, f"bars 非法: {payload.get('bars')!r}（应为 1..{MAX_BARS} 整数）"
            print(f"  [QR] decoded action={action}, bars={bars}")
            result = ctx.cerebellum.dance(bars=bars)
        else:
            print(f"  [QR] decoded action={action}")
            result = ctx.cerebellum.execute_motion(action, payload)
    except (ValueError, OverflowError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return {"action": action, "detail": result}, None


def parse_qr_payload(raw: Any) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """把二维码载荷规范成动作列表。兼容旧单动作对象和新 path 序列。"""
    payload = raw
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError) as exc:
            return None, f"二维码 payload 不是合法 JSON: {exc}"
    if not isinstance(payload, dict):
        return None, f"二维码 payload 必须是 JSON 对象，实际为 {type(payload).__name__}"

    if "path" in payload:
        path = payload.get("path")
        if not isinstance(path, list) or not path:
            return None, "path 必须是非空动作列表"
        steps: List[Dict[str, Any]] = []
        for i, item in enumerate(path):
            if not isinstance(item, dict):
                return None, f"path[{i}] 必须是 JSON 对象，实际为 {type(item).__name__}"
            steps.append(item)
        return steps, None
    return [payload], None


class QRCodeSkill(Skill):
    name = "qr"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        obs, reason = perception_data(ctx, "qr", optional=True)
        if reason:
            return failed(self.name, reason)

        payload = obs.get("payload")
        if payload is None:
            if ctx.channel_ready("qr"):
                return failed(self.name, "二维码已识别但未解出指令 payload")
            payload = ctx.params.get("default_payload", {"action": "walk", "steps": 3})

        steps, err = parse_qr_payload(payload)
        if err:
            return failed(self.name, err)

        executed: List[Dict[str, Any]] = []
        last_action = None
        last_detail = None
        for i, item in enumerate(steps):
            result, err = _dispatch_action(ctx, item)
            if err:
                prefix = f"path[{i}] " if len(steps) > 1 else ""
                return failed(self.name, prefix + err)
            assert result is not None
            executed.append(result)
            last_action = result["action"]
            last_detail = result["detail"]

        label = last_action if len(executed) == 1 else f"path({len(executed)})"
        ctx.tts(f"执行二维码指令：{label}")
        out: Dict[str, Any] = {
            "skill": self.name,
            "status": "ok",
            "action": last_action,
            "detail": last_detail,
            "steps": executed,
        }
        if len(executed) > 1:
            out["path_len"] = len(executed)
        return out
