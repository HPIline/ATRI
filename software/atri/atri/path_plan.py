"""二维码路径指令：schema、校验与向后兼容。

赛题原文（第 3 轮 T6 复取）：**「② 二维码循迹：识别二维码并按指示路径行走。」**
重点是「按指示**路径**」——二维码要能表达一条路径，而不只是一条指令。
本模块定义这份路径的表达与校验，并且是**生成端（qrgen）与执行端（skills/qr）共用的唯一口径**：
生成得出来但跑不通的二维码，不该被造出来。

## 格式

```json
{
  "schema": "atri.path.v1",
  "path": [
    {"action": "walk", "steps": 3},
    {"action": "turn", "deg": 90},
    {"action": "walk", "steps": 2}
  ]
}
```

## 向后兼容

旧的单指令格式 ``{"action":"walk","steps":3}`` **继续可用**，被解析为**单段路径**。
理由很实际：现场可能已经印好二维码，不能因为换了 schema 就把它们作废。
解析结果里的 ``source`` 字段会标明这次是走的新格式还是旧格式（``path`` / ``legacy``）。

## 边界从哪来

每段的取值范围一律复用 :mod:`atri.config` 的 ``MAX_STEPS`` / ``MAX_TURN_DEG`` / ``MAX_BARS`` /
``VALID_ACTIONS``，与 qrgen、执行端同源，避免三处各写一份边界。
路径整体再加两道闸：段数上限 ``MAX_PATH_SEGMENTS``、总步数预算 ``MAX_PATH_TOTAL_STEPS``。

> ⚠ 赛题**未规定**路径的表达格式（主办方口径待确认，见
> ``design/handoff/第3轮-T6-小人形组合规核对.md`` 的 Q3）。
> 所以这里定义的是**我们自己的格式**，并带 ``schema`` 字段以便将来对齐或兼容多种格式。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .config import MAX_BARS, MAX_STEPS, MAX_TURN_DEG, VALID_ACTIONS
from .validation import as_finite_float, as_int_in_range

PATH_SCHEMA = "atri.path.v1"

# 路径整体上限。段数不用太大：一个二维码能承载的字符有限（版本 40 / 纠错 L 约 2953 字节），
# 而且现场"走一条 16 段的路径"本身就已经不现实了。
MAX_PATH_SEGMENTS = 16
# 总步数预算：单段最多 MAX_STEPS，整条路径再设一个上限，防止"20 段 × 20 步"这种跑不完的指令。
MAX_PATH_TOTAL_STEPS = 60

# 可用于路径的动作。语义上路径主要是 walk/turn，其余动作允许出现但需自行承担现场效果。
PATH_ACTIONS = tuple(sorted(VALID_ACTIONS))


class PathError(ValueError):
    """路径 payload 非法。"""


# ────────────────────────── 单段校验 ──────────────────────────


def validate_segment(action: Any, params: Dict[str, Any]) -> None:
    """校验一段路径指令；非法即抛 :class:`PathError`。

    这是**唯一**的段校验实现：``qrgen`` 生成前、``skills/qr`` 执行前都调它。
    """
    if not isinstance(action, str) or action not in VALID_ACTIONS:
        raise PathError(f"未知动作 {action!r}，可选: {sorted(VALID_ACTIONS)}")
    if not isinstance(params, dict):
        raise PathError(f"{action} 的参数必须是对象，实际为 {type(params).__name__}")

    if action == "walk":
        if as_int_in_range(params.get("steps", 3), 1, MAX_STEPS) is None:
            raise PathError(f"walk.steps 非法: {params.get('steps')!r}（应为 1..{MAX_STEPS} 整数）")
    elif action == "turn":
        deg = as_finite_float(params.get("deg", 30.0))
        if deg is None or abs(deg) > MAX_TURN_DEG:
            raise PathError(
                f"turn.deg 非法: {params.get('deg')!r}（应为 ±{MAX_TURN_DEG:g} 内的有限数值）"
            )
    elif action == "dance":
        if as_int_in_range(params.get("bars", 2), 1, MAX_BARS) is None:
            raise PathError(f"dance.bars 非法: {params.get('bars')!r}（应为 1..{MAX_BARS} 整数）")


def normalize_segment(action: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """校验并补齐默认值，返回可直接执行的规范化段。"""
    validate_segment(action, params)
    clean: Dict[str, Any] = {"action": action}
    if action == "walk":
        clean["steps"] = as_int_in_range(params.get("steps", 3), 1, MAX_STEPS)
    elif action == "turn":
        clean["deg"] = as_finite_float(params.get("deg", 30.0))
    elif action == "dance":
        clean["bars"] = as_int_in_range(params.get("bars", 2), 1, MAX_BARS)
    # 其余动作（kick/carry/grasp/release）无必填参数，参数原样带上（已确认是 dict）
    for key, value in params.items():
        clean.setdefault(key, value)
    return clean


# ────────────────────────── 路径对象 ──────────────────────────


@dataclass
class PathSegment:
    action: str
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"action": self.action, **self.params}

    def describe(self) -> str:
        if self.action == "walk":
            return f"走 {self.params.get('steps')} 步"
        if self.action == "turn":
            return f"转 {self.params.get('deg')}°"
        if self.action == "dance":
            return f"舞 {self.params.get('bars')} 小节"
        return self.action


@dataclass
class Path:
    """一条路径 = 若干段有序指令。"""

    segments: List[PathSegment]
    schema: str = PATH_SCHEMA
    source: str = "path"  # path（新格式）/ legacy（旧单指令格式）

    def __post_init__(self) -> None:
        if not self.segments:
            raise PathError("路径不能为空")
        if len(self.segments) > MAX_PATH_SEGMENTS:
            raise PathError(f"路径段数 {len(self.segments)} 超过上限 {MAX_PATH_SEGMENTS}")
        if self.total_steps > MAX_PATH_TOTAL_STEPS:
            raise PathError(
                f"路径总步数 {self.total_steps}（各段 walk.steps 之和）"
                f"超过预算 {MAX_PATH_TOTAL_STEPS}"
            )

    @property
    def total_steps(self) -> int:
        """全部 walk 段的步数之和。宽松解析时参数可能还没校验，脏值按 0 计（留给执行段报错）。"""
        total = 0
        for seg in self.segments:
            if seg.action != "walk":
                continue
            try:
                total += max(0, int(seg.params.get("steps", 0)))
            except (TypeError, ValueError):
                continue
        return total

    @property
    def total_turn_deg(self) -> float:
        total = 0.0
        for seg in self.segments:
            if seg.action != "turn":
                continue
            try:
                value = float(seg.params.get("deg", 0.0))
            except (TypeError, ValueError):
                continue
            total += abs(value)
        return total

    @property
    def is_legacy(self) -> bool:
        return self.source == "legacy"

    def to_payload(self) -> Dict[str, Any]:
        """序列化为可写进二维码的 payload（旧格式路径会还原成旧格式）。"""
        if self.is_legacy:
            return self.segments[0].to_dict()
        return {
            "schema": self.schema,
            "path": [seg.to_dict() for seg in self.segments],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, separators=(",", ":"))

    def describe(self) -> str:
        return " → ".join(seg.describe() for seg in self.segments)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "source": self.source,
            "segments": [seg.to_dict() for seg in self.segments],
            "total_steps": self.total_steps,
            "total_turn_deg": self.total_turn_deg,
            "describe": self.describe(),
        }


# ────────────────────────── 解析 / 构造 ──────────────────────────


def _segment_from_raw(action: Any, params: Dict[str, Any], index: int, strict: bool) -> PathSegment:
    """把一项原始段转成 :class:`PathSegment`；``strict=True`` 时顺带全量校验。"""
    if strict:
        try:
            clean = normalize_segment(action, params)
        except PathError as exc:
            raise PathError(f"path[{index}]: {exc}") from exc
        return PathSegment(
            action=str(action), params={k: v for k, v in clean.items() if k != "action"}
        )
    if not isinstance(action, str) or not action:
        raise PathError(f"path[{index}]: action 必须是非空字符串，实际为 {action!r}")
    return PathSegment(action=action, params=dict(params))


def parse_payload(payload: Any, strict: bool = True) -> Path:
    """把二维码 payload 解析成 :class:`Path`。

    接受 dict 或 JSON 字符串；兼容旧单指令格式；``schema`` 不认识时报错而不是猜。

    ``strict=False`` 时只做**结构与预算**校验（schema / 是否数组 / 每项是否对象 /
    ``action`` 是否非空字符串 / 段数与总步数上限），单段的参数（步数、角度）留给
    **执行该段时**再校验。执行端选这条路，是为了让"后面某段非法"不至于让
    前面已经合法的段一步都不走 —— 现场能走一段是一段，报错照样精确到 ``path[i]``。
    生成端（qrgen）用默认的 ``strict=True``：造得出来就必须跑得通。
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise PathError(f"payload 不是合法 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise PathError(f"payload 必须是 JSON 对象，实际为 {type(payload).__name__}")

    # 新格式
    if "path" in payload:
        declared = payload.get("schema")
        if declared is not None and declared != PATH_SCHEMA:
            raise PathError(
                f"不认识的 schema {declared!r}（本代码只认 {PATH_SCHEMA!r}）——"
                "不做猜测式兼容，请对齐格式后再用"
            )
        raw_segments = payload["path"]
        if not isinstance(raw_segments, (list, tuple)):
            raise PathError(f"path 必须是数组，实际为 {type(raw_segments).__name__}")
        segments: List[PathSegment] = []
        for index, raw in enumerate(raw_segments):
            if not isinstance(raw, dict):
                raise PathError(f"path[{index}] 必须是对象，实际为 {type(raw).__name__}")
            action = raw.get("action")
            params = {k: v for k, v in raw.items() if k != "action"}
            segments.append(_segment_from_raw(action, params, index, strict))
        return Path(segments=segments, schema=PATH_SCHEMA, source="path")

    # 旧格式：单条指令
    if "action" in payload:
        action = payload.get("action")
        params = {k: v for k, v in payload.items() if k != "action"}
        segment = _segment_from_raw(action, params, 0, strict)
        return Path(segments=[segment], schema=PATH_SCHEMA, source="legacy")

    raise PathError("payload 既没有 path 也没有 action，无法解析")


def build_path(segments: Sequence[Dict[str, Any]], schema: str = PATH_SCHEMA) -> Path:
    """从 ``[{"action":..., ...}, ...]`` 构造路径（生成端用）。"""
    return parse_payload({"schema": schema, "path": [dict(seg) for seg in segments]})


def wrap_legacy(action: str, params: Optional[Dict[str, Any]] = None) -> Path:
    """把单条指令包装成单段路径（兼容入口）。"""
    return parse_payload({"action": action, **(params or {})})
