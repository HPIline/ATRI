"""二维码循迹技能：解码 JSON 指令并下发给小脑。"""
from __future__ import annotations

import json
from typing import Any, Dict

from .base import Skill, SkillContext


class QRCodeSkill(Skill):
    name = "qr"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        obs = ctx.perceive("qr")
        payload = obs.get("payload")
        if payload is None:
            payload = ctx.params.get("default_payload", {"action": "walk", "steps": 3})

        if isinstance(payload, str):
            payload = json.loads(payload)

        action = str(payload.get("action", "walk"))
        steps = int(payload.get("steps", 3))
        print(f"  [QR] decoded action={action}, steps={steps}")

        if action == "walk":
            result = ctx.cerebellum.walk(steps=steps)
        elif action == "turn":
            deg = int(payload.get("deg", 30))
            result = ctx.cerebellum.set_pose({"left_hip_yaw": deg / 3.0, "right_hip_yaw": deg / 3.0})
        else:
            result = ctx.cerebellum.execute_motion(action, obs)

        ctx.tts(f"执行二维码指令：{action}")
        return {"skill": self.name, "status": "ok", "action": action, "detail": result}
