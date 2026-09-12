"""物品搬运技能（T-03）：对准目标 → 夹取 → 平移 → 对准放置区 → 释放。

## 两步对准，两步都要"看见"

1. **目标物对准**：多轮横向视觉伺服（``lateral_servo``），偏差进死区才夹取；
   不收敛且偏差超 ``give_up_cm`` 就**宁可失败也不盲抓**。
2. **放置区对准**（T-03 做实新增）：走到位后如果"放置区"通道真的接入了
   （摄像头 + 地标，见 ``perception/opencv.py::detect_place``），先对准再释放；
   **通道接入但没看见地标 → 失败且不释放**，不把"没看见"当成"放好了"。
   通道完全没接入（纯 Mock / 没有地标方案）时按任务卡参数释放，并在结果里
   如实回报 ``place.status = "channel-unavailable"``。

## 参数为什么要可改

机器人结构与零件**尚未定案**、**没有实物**，所以下面 ``CARRY_DEFAULTS`` 里每一个
数都是**设计值**。实物到手后按「任务卡 params > ``config/carry.json`` > 代码默认值」
的优先级回填（见 :mod:`atri.tuning`），不必改这个文件。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..config import MAX_STEPS
from ..tuning import load_tuning, param_or
from .base import (
    Skill,
    SkillContext,
    _int_param,
    as_finite_float,
    failed,
    lateral_servo,
    perception_data,
)

# 代码默认值 = 设计值（未标定）。键名同时也是 config/carry.json 里可覆盖的键。
CARRY_DEFAULTS: Dict[str, Any] = {
    # —— 目标物对准（第一步）——
    "deadband_cm": 2.0,        # 闭环收敛目标：进这个横向偏差就算"对准"
    "max_iters": 5,            # 单次任务内最多纠几轮
    "step_gain": 0.5,          # 每轮偏航步长 = clamp(x_cm × gain, ±clamp) 度
    "step_clamp_deg": 10.0,    # 单轮最大偏航（越大越快，也越容易超调）
    # 夹取门槛：**夹爪实际能容忍**多大横向偏差。默认 = 死区（没对准就不夹，fail-safe）；
    # 实机量出夹爪容差后可放宽，但要自己承担"斜着夹"的后果。
    "grasp_tolerance_cm": 2.0,
    # —— 放置区对准（第二步）——
    "place_align": True,      # 通道接入了才生效；通道没接入自动跳过
    "place_deadband_cm": 2.5,
    "place_max_iters": 5,
    "place_give_up_cm": 5.0,  # 超过它就不释放（避免把东西丢在地上）
    # —— 行走 ——
    "step_length_cm": 2.0,    # 名义步长；实机位移须用 config/odometry.json 标定
    "min_steps": 2,
    "max_distance_cm": 2.0 * MAX_STEPS,   # 40cm：与舵机/小脑单指令上限对齐
}


def _num(ctx: SkillContext, tuning: Dict[str, Any], key: str, *, integer: bool = False) -> float:
    """按 任务卡 > tuning 文件 > 代码默认值 取值，并做合法性校验后回落默认值。"""
    default = CARRY_DEFAULTS[key]
    raw = param_or(ctx.params, tuning, key, default)
    if integer:
        value = _int_param({key: raw}, key, int(default))
        return float(value)
    value = as_finite_float(raw)
    if value is None or value <= 0.0:
        return float(default)
    return float(value)


def _flag(ctx: SkillContext, tuning: Dict[str, Any], key: str) -> bool:
    """布尔项：任务卡写 true/false 覆盖 tuning 与默认值；其余写法一律按默认值。"""
    default = bool(CARRY_DEFAULTS[key])
    raw = param_or(ctx.params, tuning, key, default)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
    return default


class CarrySkill(Skill):
    name = "carry"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        t = load_tuning("carry", CARRY_DEFAULTS)
        tuning = t.values

        obs, reason = perception_data(ctx, "object")
        if reason:
            return failed(self.name, reason)

        target = obs.get("target") or ctx.params.get("target") or "红块"
        raw_distance = obs.get("distance_cm", ctx.params.get("distance_cm"))
        distance_cm = as_finite_float(raw_distance)
        max_distance = _num(ctx, tuning, "max_distance_cm")
        if distance_cm is None or distance_cm <= 0.0:
            return failed(self.name, f"搬运距离非法或缺测距: {raw_distance!r}")
        if distance_cm > max_distance:
            return failed(
                self.name, f"搬运距离 {distance_cm:g}cm 超出上限 {max_distance:g}cm"
            )
        x_cm = as_finite_float(obs.get("x_cm"))
        if x_cm is None:
            x_cm = 0.0

        # —— 第一步：对准目标物 ——
        x_cm, iterations, aligned, reason = lateral_servo(
            ctx,
            "object",
            x_cm,
            _num(ctx, tuning, "deadband_cm"),
            int(_num(ctx, tuning, "max_iters", integer=True)),
            _num(ctx, tuning, "step_gain"),
            _num(ctx, tuning, "step_clamp_deg"),
        )
        if reason:
            return failed(self.name, reason)

        tolerance = _num(ctx, tuning, "grasp_tolerance_cm")
        print(
            f"  [Carry] 目标={target}, 距离={distance_cm}cm, 横向={x_cm}cm, "
            f"迭代={iterations}, 对准={aligned}"
        )
        if abs(x_cm) > tolerance:
            # 失败也要把过程量带出去：调参时最需要知道"纠了几轮、最后差多少"。
            result = failed(
                self.name,
                f"闭环后横向偏差 {x_cm:g}cm 超过夹取容差 {tolerance:g}cm"
                f"（迭代 {iterations} 轮未对准），放弃抓取",
            )
            result.update({
                "iterations": iterations,
                "aligned": aligned,
                "align_x_cm": x_cm,
                "grasp_tolerance_cm": tolerance,
                "distance_cm": distance_cm,
                "target": target,
                "tuning_source": t.source_path.name if t.overridden else "code-defaults",
            })
            return result
        if not aligned:
            # 没进死区但仍在夹取容差内：**如实标注**，不把"凑合夹"说成"对准了"。
            print(
                f"  [Carry] ⚠ 未进死区（{abs(x_cm):g}cm > 死区），但 ≤ 夹取容差 "
                f"{tolerance:g}cm，按设计容差继续夹取"
            )

        # —— 夹取 + 平移 ——
        step_length = _num(ctx, tuning, "step_length_cm")
        min_steps = int(_num(ctx, tuning, "min_steps", integer=True))
        steps = max(min_steps, int(distance_cm // step_length))
        steps = min(MAX_STEPS, steps)
        grasp_result = ctx.cerebellum.grasp()
        walk_result = ctx.cerebellum.walk(steps=steps, **ctx.gait)

        result: Dict[str, Any] = {
            "skill": self.name,
            "status": "ok",
            "target": target,
            "distance_cm": distance_cm,
            "distance_source": obs.get("distance_source", "uncalibrated"),
            "steps": steps,
            "step_length_cm": step_length,
            "planned_distance_cm": round(steps * step_length, 2),
            "iterations": iterations,
            "aligned": aligned,
            "align_x_cm": x_cm,
            "grasp_tolerance_cm": tolerance,
            "grasp_within_tolerance": abs(x_cm) <= tolerance,
            "grasp": grasp_result,
            "walk": walk_result,
            # 参数出处：让报告能说清"这是标定值还是设计值"
            "tuning_source": t.source_path.name if t.overridden else "code-defaults",
            "tuning_overridden": list(t.overridden),
            "tuning_warnings": list(t.warnings),
        }

        # —— 第二步：对准放置区（通道接入了才做）——
        place = self._align_place(ctx, tuning)
        result["place"] = place
        if place["status"] == "failed":
            # 已经夹着东西但放不准：停住，不释放（宁可任务失败，也不把物品丢在任意位置）。
            ctx.tts("放置区没对准，暂停释放")
            result["status"] = "failed"
            result["reason"] = place["reason"]
            return result

        release_result = ctx.cerebellum.release()
        result["release"] = release_result
        ctx.tts(f"已将{target}搬运至目标区")
        return result

    def _align_place(self, ctx: SkillContext, tuning: Dict[str, Any]) -> Dict[str, Any]:
        """放置区对准。返回带 ``status`` 的字典，三种结局都写明来源。"""
        align = _flag(ctx, tuning, "place_align")
        if not align:
            return {"status": "disabled", "source": "config", "reason": "place_align=false"}
        if not ctx.channel_ready("place"):
            # 没有地标方案 / 纯 Mock：按任务卡参数释放，但把这件事写在结果里。
            return {
                "status": "channel-unavailable",
                "source": "none",
                "reason": "无放置区感知通道（未接地标相机）；按任务卡参数释放",
            }

        obs, reason = perception_data(ctx, "place")
        if reason:
            return {"status": "failed", "source": "perception", "reason": reason}
        x_start = as_finite_float(obs.get("x_cm"))
        if x_start is None:
            return {
                "status": "failed",
                "source": "perception",
                "reason": f"放置区横向偏移缺失: {obs.get('x_cm')!r}",
            }

        x_cm, iterations, aligned, reason = lateral_servo(
            ctx,
            "place",
            x_start,
            _num(ctx, tuning, "place_deadband_cm"),
            int(_num(ctx, tuning, "place_max_iters", integer=True)),
            _num(ctx, tuning, "step_gain"),
            _num(ctx, tuning, "step_clamp_deg"),
        )
        if reason:
            return {"status": "failed", "source": "perception", "reason": reason}
        give_up = _num(ctx, tuning, "place_give_up_cm")
        if abs(x_cm) > give_up:
            return {
                "status": "failed",
                "source": "perception",
                "x_cm": x_cm,
                "iterations": iterations,
                "reason": f"放置区横向偏差 {x_cm:g}cm 超过 {give_up:g}cm，未释放（避免盲放）",
            }
        print(f"  [Carry] 放置区对准: 横向={x_cm}cm, 迭代={iterations}, 对准={aligned}")
        return {
            "status": "aligned",
            "source": "perception",
            "x_cm": x_cm,
            "x_start_cm": x_start,
            "iterations": iterations,
            "aligned": aligned,
            "distance_source": obs.get("distance_source", "uncalibrated"),
        }
