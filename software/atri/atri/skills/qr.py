"""二维码循迹技能：解码二维码 → 解析**路径** → 逐段执行 → 回报标称位移。

赛题原文：**「② 二维码循迹：识别二维码并按指示路径行走。」**

支持两种 payload：

**路径**
```json
{"schema":"atri.path.v1",
 "path":[{"action":"walk","steps":3},{"action":"turn","deg":90},{"action":"walk","steps":2}]}
```
（``schema`` 可省；带版本号是为了将来对齐主办方格式留落脚点。）

**单条指令（旧格式，继续可用）**
```json
{"action":"walk","steps":3}
```

## 执行语义（四条，都是刻意的）

1. **整条路径先校验，再动手**：能静态判定的非法（schema 不认识、未知动作、步数/角度越界、
   段数或总步数超预算）一律在**发出任何动作之前**拦下，错误精确到 ``path[i]``。
   ``qrgen`` 生成时也走同一套严格的校验 —— 换句话说，**我们自己造的码不可能带静态非法段**，
   所以真出现这种载荷，意味着码是外来的或被损坏的：按一条已知损坏的路径走一半，
   比停在原地更糟。（运行期才暴露的失败——比如小脑层报错——仍会逐段停下并报 ``path[i]``。）
2. **任一段失败即停**，报出第几段、什么原因，不跳过继续走。
3. **段与段之间也检查中止信号**：任务级超时若只在单段轨迹内部生效，
   一条 6 段路径会跑成 6 倍时长。
4. **标称位移是标称的**：结果里的 ``trace`` 带 ``status="nominal-uncalibrated"`` 时，
   表示那是几何折算的设计值，**不是实测**。真机走到哪了要等 ``config/odometry.json`` 标定。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..config import MAX_BARS, MAX_STEPS, MAX_TURN_DEG, VALID_ACTIONS
from ..odometry import NominalOdometry
from ..path_plan import Path, PathError, PathSegment, normalize_segment, parse_payload
from .base import (
    Skill,
    SkillContext,
    as_finite_float,
    as_int_in_range,
    failed,
    perception_data,
)


def parse_qr_payload(raw: Any) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """把二维码载荷规范成动作列表，返回 ``(steps, 失败原因)``。

    兼容旧单动作对象与 ``{"path":[...]}`` 序列。**这是给生成端 / 外部调用方用的接口**；
    技能内部走 :func:`atri.path_plan.parse_payload`（那条路带 schema 与预算校验）。
    """
    try:
        path = parse_payload(raw, strict=False)
    except PathError as exc:
        return None, str(exc)
    return [seg.to_dict() for seg in path.segments], None


class QRCodeSkill(Skill):
    name = "qr"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        path, reason = self._resolve_path(ctx)
        if path is None:
            return failed(self.name, reason or "未能取得二维码路径")

        total = len(path.segments)
        executed: List[Dict[str, Any]] = []

        for index, segment in enumerate(path.segments):
            if self._aborted(ctx):
                executed.append({"index": index, "action": segment.action, "status": "aborted"})
                return self._result(
                    path, executed, ctx, status="aborted",
                    reason=f"第 {index + 1}/{total} 段前收到中止信号（超时或外部停止）",
                )
            try:
                # 逐段校验：失败信息统一带 path[i]，与生成端的报错格式一致
                clean = normalize_segment(segment.action, segment.params)
                detail = self._execute_segment(ctx, str(clean["action"]), clean)
            except PathError as exc:
                return self._segment_failure(path, executed, ctx, index, total, segment, str(exc))
            except (ValueError, OverflowError) as exc:
                return self._segment_failure(
                    path, executed, ctx, index, total, segment, f"{type(exc).__name__}: {exc}"
                )
            executed.append(
                {"index": index, "action": segment.action, "status": "ok", "detail": detail}
            )

        return self._result(path, executed, ctx, status="ok")

    # ────────────────── 取路径 ──────────────────

    def _resolve_path(self, ctx: SkillContext) -> Tuple[Optional[Path], Optional[str]]:
        obs, reason = perception_data(ctx, "qr", optional=True)
        if reason:
            return None, reason

        payload = obs.get("payload")
        if payload is None:
            if ctx.channel_ready("qr"):
                return None, "二维码已识别但未解出指令 payload"
            # 感知通道未接入的 Mock 场景才允许用任务卡兜底指令
            payload = ctx.params.get("default_payload", {"action": "walk", "steps": 3})

        try:
            # strict=True：整条路径先全量校验（见模块 docstring 第 1 条）。
            # 理由：能被静态判定的非法（未知动作、越界步数）说明这份 payload 是
            # 外来的或被损坏的 —— qrgen 自己生成时保证合法。按一个已知损坏的路径
            # 走一半，比停在原地更糟。运行期才暴露的失败仍逐段报 path[i]。
            return parse_payload(payload, strict=True), None
        except PathError as exc:
            return None, f"二维码路径非法：{exc}"

    # ────────────────── 执行单段 ──────────────────

    def _execute_segment(
        self, ctx: SkillContext, action: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        if action == "walk":
            steps = as_int_in_range(params.get("steps", 3), 1, MAX_STEPS)
            if steps is None:
                raise ValueError(f"steps 非法: {params.get('steps')!r}（应为 1..{MAX_STEPS} 整数）")
            print(f"  [QR] 段 walk: steps={steps}")
            return ctx.cerebellum.walk(steps=steps, **ctx.gait)

        if action == "turn":
            deg = as_finite_float(params.get("deg", 30.0))
            if deg is None or abs(deg) > MAX_TURN_DEG:
                raise ValueError(
                    f"deg 非法: {params.get('deg')!r}（应为 ±{MAX_TURN_DEG:g} 内的有限数值）"
                )
            print(f"  [QR] 段 turn: deg={deg}")
            # 踩步转体（cerebellum.turn）：若干步正弦步态叠加髋偏航。
            # 不再只把左右髋拧一个角度——那样在实物上不产生任何转向。
            return ctx.cerebellum.turn(deg, **ctx.gait)

        if action == "dance":
            bars = as_int_in_range(params.get("bars", 2), 1, MAX_BARS)
            if bars is None:
                raise ValueError(f"bars 非法: {params.get('bars')!r}（应为 1..{MAX_BARS} 整数）")
            print(f"  [QR] 段 dance: bars={bars}")
            return ctx.cerebellum.dance(bars=bars)

        if action not in VALID_ACTIONS:
            raise PathError(f"未知动作 {action!r}，可选: {sorted(VALID_ACTIONS)}")
        print(f"  [QR] 段 {action}")
        return ctx.cerebellum.execute_motion(action, params)

    # ────────────────── 结果组装 ──────────────────

    @staticmethod
    def _aborted(ctx: SkillContext) -> bool:
        checker = getattr(ctx.cerebellum, "aborted", None)
        return bool(checker()) if callable(checker) else False

    def _segment_failure(
        self,
        path: Path,
        executed: List[Dict[str, Any]],
        ctx: SkillContext,
        index: int,
        total: int,
        segment: PathSegment,
        detail: str,
    ) -> Dict[str, Any]:
        executed.append(
            {"index": index, "action": segment.action, "status": "failed", "error": detail}
        )
        return self._result(
            path, executed, ctx, status="failed",
            reason=(
                f"path[{index}]: 第 {index + 1}/{total} 段（{segment.describe()}）执行失败：{detail}"
            ),
        )

    def _result(
        self,
        path: Path,
        executed: List[Dict[str, Any]],
        ctx: SkillContext,
        status: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        trace = NominalOdometry.from_config().simulate(path)
        ctx.tts(f"执行二维码指令：{path.describe()}")

        payload: Dict[str, Any] = {
            "skill": self.name,
            "status": status,
            "action": path.segments[0].action if len(path.segments) == 1 else "path",
            "path_len": len(path.segments),
            "path": path.to_dict(),
            "segments": executed,
            # ⚠ 标称值：status=nominal-uncalibrated 时不可当作实测指标
            "trace": trace.to_dict(),
        }
        if reason:
            payload["reason"] = reason
        # 向后兼容：单段路径仍把该段执行细节放在 detail 里
        if len(executed) == 1 and executed[0].get("status") == "ok":
            payload["detail"] = executed[0].get("detail")
        return payload
