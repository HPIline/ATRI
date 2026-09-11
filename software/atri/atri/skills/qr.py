"""二维码循迹技能：解码 JSON 指令并下发给小脑。"""
from __future__ import annotations

import json
from typing import Any, Dict

from ..config import MAX_BARS, MAX_STEPS, MAX_TURN_DEG, VALID_ACTIONS
from .base import (
    Skill,
    SkillContext,
    as_finite_float,
    as_int_in_range,
    failed,
    perception_data,
)


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
            # 感知通道未接入的 Mock 场景才允许用任务卡兜底指令
            payload = ctx.params.get("default_payload", {"action": "walk", "steps": 3})

        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError) as exc:
                return failed(self.name, f"二维码 payload 不是合法 JSON: {exc}")
        if not isinstance(payload, dict):
            return failed(
                self.name, f"二维码 payload 必须是 JSON 对象，实际为 {type(payload).__name__}"
            )

        action = payload.get("action")
        if not isinstance(action, str) or action not in VALID_ACTIONS:
            return failed(self.name, f"未知动作: {action!r}，可选 {sorted(VALID_ACTIONS)}")

        try:
            if action == "walk":
                steps = as_int_in_range(payload.get("steps", 3), 1, MAX_STEPS)
                if steps is None:
                    return failed(
                        self.name,
                        f"steps 非法: {payload.get('steps')!r}（应为 1..{MAX_STEPS} 整数）",
                    )
                print(f"  [QR] decoded action={action}, steps={steps}")
                result = ctx.cerebellum.walk(steps=steps, **ctx.gait)
            elif action == "turn":
                deg = as_finite_float(payload.get("deg", 30.0))
                if deg is None or abs(deg) > MAX_TURN_DEG:
                    return failed(
                        self.name,
                        f"deg 非法: {payload.get('deg')!r}（应为 ±{MAX_TURN_DEG:g} 内的有限数值）",
                    )
                print(f"  [QR] decoded action={action}, deg={deg}")
                result = ctx.cerebellum.set_pose(
                    {"left_hip_yaw": deg / 3.0, "right_hip_yaw": deg / 3.0}
                )
            elif action == "dance":
                bars = as_int_in_range(payload.get("bars", 2), 1, MAX_BARS)
                if bars is None:
                    return failed(
                        self.name,
                        f"bars 非法: {payload.get('bars')!r}（应为 1..{MAX_BARS} 整数）",
                    )
                print(f"  [QR] decoded action={action}, bars={bars}")
                result = ctx.cerebellum.dance(bars=bars)
            else:
                print(f"  [QR] decoded action={action}")
                result = ctx.cerebellum.execute_motion(action, obs)
        except (ValueError, OverflowError) as exc:
            # 小脑层第二道防线抛错时转为技能失败，不让异常冒到 FSM
            return failed(self.name, f"{type(exc).__name__}: {exc}")

        ctx.tts(f"执行二维码指令：{action}")
        return {"skill": self.name, "status": "ok", "action": action, "detail": result}
