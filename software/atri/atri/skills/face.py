"""人脸技能：真识别优先，未配置真识别通路时沿用原有感知接口路径。

**真识别通路**（需 ``ctx.face_recognizer`` + ``ctx.frame_source``，构造见 ``sim.build_face_recognizer``）：
    取帧 → 检测 → 对齐 → 128 维特征 → 人脸库比对 → 播报姓名 / 显式拒识
    检出 bbox 后开环映射到 ``head_yaw`` / ``head_pitch``（T-01 头部随动）
这是 T-01 的实际能力，实测见 ``design/handoff/T-01-LFW评测报告.md``；
随动公式与未标定声明见 ``design/handoff/T-01-头部随动.md``。

**退化通路**（未配置上述两者时）保留原有实现不变：走感知接口，数据来源写在 ``source`` 字段里。
只有姓名、没有 bbox 时不转头，结果 ``gaze="skipped"``。

> 对外口径（2026-09-12 落地）：赛题原文是「人脸识别」，真识别通路优先。
> 退化通路仍允许 ``source="params"`` 的 ``expect_names[0]`` 兜底，演示日志必须打印 source，
> 不得把这条路径说成识别成功率。
> 头部随动是开环像素偏差映射，像素当量未标定，不能写成实机对准精度。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from ..config import clamp_angle
from .base import Skill, SkillContext, as_finite_float, failed, perception_data

DEFAULT_EXPECT_NAMES = ["测试员A"]
UNKNOWN_SPEECH = "对不起，我不认识你"
NO_FACE_SPEECH = "我没有看到人脸"

# 像素偏差 → 角度：每 10 px ≈ 1°。未标定，任务卡可覆写。
DEFAULT_GAZE_DEG_PER_PX = 0.1
# 无 shape、任务卡也没给分辨率时的画面尺寸假设（常见 VGA，未标定）。
DEFAULT_FRAME_WIDTH = 640.0
DEFAULT_FRAME_HEIGHT = 480.0
# 画面右偏（+dx）应对应右转。本仓库 +head_yaw 视为左转（俯视 CCW），故 yaw 取负号。
DEFAULT_GAZE_YAW_SIGN = -1.0
# 画面下偏（+dy，图像坐标 y 向下）应对应低头。本仓库 +head_pitch 视为低头，故 pitch 取正号。
DEFAULT_GAZE_PITCH_SIGN = 1.0


def _bbox_tuple(raw: Any) -> Optional[Tuple[float, float, float, float]]:
    """从 FaceBox / FaceResult / dict / 序列里取出 (x, y, w, h)。非法则 None。"""
    if raw is None:
        return None
    if hasattr(raw, "bbox"):
        raw = raw.bbox
    elif hasattr(raw, "box"):
        box = raw.box
        raw = getattr(box, "bbox", None) if box is not None else None
    if isinstance(raw, dict):
        raw = raw.get("bbox")
    try:
        x, y, w, h = (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if not all(math.isfinite(v) for v in (x, y, w, h)):
        return None
    if w <= 0.0 or h <= 0.0:
        return None
    return x, y, w, h


def _bbox_from_recognition(result: Any) -> Optional[Tuple[float, float, float, float]]:
    """优先用已识别的 best，否则退到检出列表里的第一张。"""
    best = getattr(result, "best", None)
    bbox = _bbox_tuple(best)
    if bbox is not None:
        return bbox
    for face in getattr(result, "faces", None) or []:
        bbox = _bbox_tuple(face)
        if bbox is not None:
            return bbox
    return None


def _positive_or_default(params: Dict[str, Any], key: str, default: float) -> float:
    value = as_finite_float(params.get(key, default))
    if value is None or value <= 0.0:
        return default
    return value


def _sign_or_default(params: Dict[str, Any], key: str, default: float) -> float:
    value = as_finite_float(params.get(key, default))
    if value is None or value == 0.0:
        return default
    return 1.0 if value > 0.0 else -1.0


def _frame_size(frame: Any, params: Dict[str, Any]) -> Tuple[float, float]:
    """画面宽高：任务卡 > 帧 shape > VGA 默认。"""
    width = as_finite_float(params.get("frame_width"))
    height = as_finite_float(params.get("frame_height"))
    if width is not None and height is not None and width > 0.0 and height > 0.0:
        return width, height
    shape = getattr(frame, "shape", None)
    try:
        if shape is not None and len(shape) >= 2:
            h, w = float(shape[0]), float(shape[1])
            if math.isfinite(h) and math.isfinite(w) and h > 0.0 and w > 0.0:
                return w, h
    except (TypeError, ValueError, IndexError):
        pass
    return DEFAULT_FRAME_WIDTH, DEFAULT_FRAME_HEIGHT


def map_bbox_to_head(
    bbox: Tuple[float, float, float, float],
    frame_width: float,
    frame_height: float,
    *,
    yaw_deg_per_px: float = DEFAULT_GAZE_DEG_PER_PX,
    pitch_deg_per_px: float = DEFAULT_GAZE_DEG_PER_PX,
    yaw_sign: float = DEFAULT_GAZE_YAW_SIGN,
    pitch_sign: float = DEFAULT_GAZE_PITCH_SIGN,
) -> Tuple[float, float]:
    """把框中心相对画面中心的像素偏差映射成限位内的 yaw/pitch。"""
    x, y, w, h = bbox
    dx = (x + w / 2.0) - frame_width / 2.0
    dy = (y + h / 2.0) - frame_height / 2.0
    yaw = clamp_angle("head_yaw", yaw_sign * dx * yaw_deg_per_px)
    pitch = clamp_angle("head_pitch", pitch_sign * dy * pitch_deg_per_px)
    return yaw, pitch


def _hold_gaze() -> Dict[str, Any]:
    return {"gaze": "hold", "head_yaw": None, "head_pitch": None}


def _skip_gaze() -> Dict[str, Any]:
    return {"gaze": "skipped", "head_yaw": None, "head_pitch": None}


class FaceSkill(Skill):
    name = "face"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        if ctx.face_recognizer is not None and ctx.frame_source is not None:
            return self._run_recognition(ctx)
        return self._run_perception(ctx)

    # ────────────────── 真识别通路（新增） ──────────────────

    def _run_recognition(self, ctx: SkillContext) -> Dict[str, Any]:
        expect = self._expect_names(ctx)
        frame = ctx.grab_frame()
        if frame is None:
            out = failed(self.name, "取帧来源返回空帧")
            out.update(_skip_gaze())
            return out

        result = ctx.face_recognizer.recognize(frame)
        name = result.recognized_name
        best = result.best

        if name is None:
            # 拒识 / 无人脸：**绝不猜**。没认出来就是没认出来，不从任务卡借名字。
            # 头部：回中或保持——这里选择保持，不对着噪声/未过阈值的框转。
            if result.found:
                ctx.tts(UNKNOWN_SPEECH)
                payload = {
                    "skill": self.name,
                    "status": "rejected",
                    "reason": "人脸已检出但相似度未达阈值，判定为不认识",
                    "source": "recognition",
                    "name": None,
                    "face_count": len(result.faces),
                    "faces": [f.to_dict() for f in result.faces],
                }
                payload.update(_hold_gaze())
                return payload
            ctx.tts(NO_FACE_SPEECH)
            payload = {
                "skill": self.name,
                "status": "no_face",
                "reason": "画面中未检出人脸",
                "source": "recognition",
                "name": None,
                "face_count": 0,
                "faces": [],
            }
            payload.update(_hold_gaze())
            return payload

        name = str(name)
        if expect and name not in expect:
            out = failed(self.name, f"识别到 {name}，不在预期名单 {expect}")
            out.update(_skip_gaze())
            return out

        ctx.tts(f"你好，{name}")
        payload = {
            "skill": self.name,
            "status": "ok",
            "name": name,
            "source": "recognition",
            # 置信度用相似度表示：这是**实测**得到的可比量，不是拍出来的 0.93
            "confidence": round(best.similarity, 4) if best else 0.0,
            "similarity": round(best.similarity, 4) if best else None,
            "margin": round(best.margin, 4) if best else None,
            "face_count": len(result.faces),
            "faces": [f.to_dict() for f in result.faces],
        }
        payload.update(self._track_bbox(ctx, _bbox_from_recognition(result), frame))
        return payload

    # ────────────────── 退化通路（原有实现，未改动识别口径） ──────────────────

    def _expect_names(self, ctx: SkillContext) -> List[str]:
        """解析任务卡的 expect_names。语义与原实现保持一致（空列表按未配置处理）。"""
        raw_expect = ctx.params.get("expect_names")
        if raw_expect is None:
            return []
        if isinstance(raw_expect, (list, tuple)):
            return [str(item) for item in (raw_expect or DEFAULT_EXPECT_NAMES)]
        return [str(raw_expect)]

    def _run_perception(self, ctx: SkillContext) -> Dict[str, Any]:
        obs, reason = perception_data(ctx, "face", optional=True)
        if reason:
            out = failed(self.name, reason)
            out.update(_skip_gaze())
            return out

        expect = self._expect_names(ctx)

        name = obs.get("name")
        source = "perception"
        if not name:
            if ctx.channel_ready("face"):
                out = failed(self.name, "未获得人脸感知结果")
                out.update(_skip_gaze())
                return out
            fallback = expect or DEFAULT_EXPECT_NAMES
            name = fallback[0]
            source = "params"
        name = str(name)
        if expect and name not in expect:
            out = failed(self.name, f"识别到 {name}，不在预期名单 {expect}")
            out.update(_skip_gaze())
            return out

        confidence = as_finite_float(obs.get("confidence", 0.93))
        if confidence is None:
            confidence = 0.0

        ctx.tts(f"你好，{name}")
        payload = {
            "skill": self.name,
            "status": "ok",
            "name": name,
            "confidence": confidence,
            "source": source,
        }
        # 只有姓名没有 bbox → 不瞎转。有 bbox 才开环对准。
        payload.update(self._track_bbox(ctx, _bbox_tuple(obs), frame=None))
        return payload

    def _track_bbox(
        self,
        ctx: SkillContext,
        bbox: Optional[Tuple[float, float, float, float]],
        frame: Any,
    ) -> Dict[str, Any]:
        """有合法 bbox 则映射并 ``set_pose``；没有 bbox 或没有小脑则 skipped。"""
        if bbox is None:
            return _skip_gaze()
        setter = getattr(ctx.cerebellum, "set_pose", None) if ctx.cerebellum is not None else None
        if setter is None:
            return _skip_gaze()

        params = ctx.params or {}
        deg_per_px = _positive_or_default(params, "gaze_deg_per_px", DEFAULT_GAZE_DEG_PER_PX)
        yaw_gain = _positive_or_default(params, "gaze_yaw_deg_per_px", deg_per_px)
        pitch_gain = _positive_or_default(params, "gaze_pitch_deg_per_px", deg_per_px)
        frame_w, frame_h = _frame_size(frame, params)
        yaw, pitch = map_bbox_to_head(
            bbox,
            frame_w,
            frame_h,
            yaw_deg_per_px=yaw_gain,
            pitch_deg_per_px=pitch_gain,
            yaw_sign=_sign_or_default(params, "gaze_yaw_sign", DEFAULT_GAZE_YAW_SIGN),
            pitch_sign=_sign_or_default(params, "gaze_pitch_sign", DEFAULT_GAZE_PITCH_SIGN),
        )
        applied = setter({"head_yaw": yaw, "head_pitch": pitch})
        if isinstance(applied, dict):
            applied_yaw = as_finite_float(applied.get("head_yaw"))
            applied_pitch = as_finite_float(applied.get("head_pitch"))
            if applied_yaw is not None:
                yaw = applied_yaw
            if applied_pitch is not None:
                pitch = applied_pitch
        return {
            "gaze": "tracked",
            "head_yaw": round(float(yaw), 4),
            "head_pitch": round(float(pitch), 4),
        }
