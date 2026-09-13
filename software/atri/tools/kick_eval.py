#!/usr/bin/env python3
"""T-04 踢球评测：绿球检测（有 cv2 才跑）+ 图像/几何在环闭环 + 参数边界表。

**先说清这个工具测的是什么、不是什么**（对齐 T-03 口径）：

| 测的 | 怎么测 | 能不能写进材料 |
|---|---|---|
| 绿球检测在**程序合成图像**上的成功率与横向误差 | 真 ``OpenCVPerception.detect_ball`` 跑在合成图上 | 能，但必须写"合成图，不是实机相机" |
| **闭环控制律**能不能把球对准再下发踢 | 合成图（有 cv2）或一维几何（无 cv2）→ 真 ``KickSkill`` | 能，但必须写「合成图/几何 + 未标定 gain」 |
| "机器人转 1° 球在画面里移几厘米"（gain）对收敛的影响 | 用针孔几何算出 gain，扫参数出**边界表** | 能，这是调参依据；**gain 未标定** |
| **实机踢球成功率** | —— | **不能**。没有样机、没有相机、没有球。未测项 B7 仍未测 |

缺 numpy/cv2 时：A 段跳过；B 段退回一维几何感知（仍跑真 KickSkill）；C 段纯数学照跑。
不要装系统包；有 ``.venv-face`` 再用它跑本脚本。

    .venv-face/bin/python software/atri/tools/kick_eval.py \\
        --report design/handoff/T-04-踢球-方案与评测报告.md
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
SOFTWARE_ROOT = REPO_ROOT / "software" / "atri"
sys.path.insert(0, str(SOFTWARE_ROOT))

HAS_NUMPY = False
HAS_CV2 = False
np: Any = None
cv2: Any = None
try:
    import numpy as np  # type: ignore

    HAS_NUMPY = True
except ImportError:
    np = None
try:
    import cv2  # type: ignore

    HAS_CV2 = True
except ImportError:
    cv2 = None

from atri.cerebellum import Cerebellum, MockServoBus  # noqa: E402
from atri.config import JOINTS  # noqa: E402
from atri.perception.base import PerceptionResult  # noqa: E402
from atri.skills.base import SkillContext  # noqa: E402
from atri.skills.kick import KICK_DEFAULTS, KickSkill  # noqa: E402
from atri.tuning import load_tuning  # noqa: E402

NOMINAL_WIDTH_PX = 1280
NOMINAL_HFOV_DEG = 60.0
NOMINAL_FOCAL_PX = (NOMINAL_WIDTH_PX / 2.0) / math.tan(math.radians(NOMINAL_HFOV_DEG / 2.0))

FRAME_W, FRAME_H = 320, 240
FRAME_FOCAL_PX = (FRAME_W / 2.0) / math.tan(math.radians(NOMINAL_HFOV_DEG / 2.0))


def fov_half_cm_at(d_cm: float) -> float:
    return d_cm * math.tan(math.radians(NOMINAL_HFOV_DEG / 2.0))


PIXELS_PER_CM = 10.0
BALL_DIAMETER_CM = 4.0
GREEN_BGR = (0, 220, 0)
BG_BGR = (40, 40, 40)
OCCLUDE_BGR = (128, 128, 128)
RNG_SEED = 20260913

# 踢球与搬运共用 lateral_servo；推荐参数与 T-03 同向（加大轮数与增益）。
# ⚠ 建立在「髋偏航指令角 = 身体实际转角」上，gain 未标定，不能直接上实机。
RECOMMENDED_PARAMS: Dict[str, Any] = {"max_iters": 15, "step_gain": 1.0}
CAP_CM = 60.0


# ────────────────────────── 合成图像 ──────────────────────────


@dataclass
class Patch:
    cx: float
    cy: float
    size: int
    bgr: Tuple[int, int, int]
    h: Optional[int] = None
    circle: bool = True


def make_frame(
    patches: Sequence[Patch],
    noise_sigma: float = 0.0,
    blur: int = 0,
    brightness: float = 1.0,
    seed: int = RNG_SEED,
) -> Any:
    """按补丁列表合成一帧 BGR 图。无 numpy/cv2 时不应被调用。"""
    if not HAS_NUMPY or not HAS_CV2:
        raise RuntimeError("合成图需要 numpy + opencv")
    img = np.full((FRAME_H, FRAME_W, 3), BG_BGR, dtype=np.uint8)
    for patch in patches:
        if patch.circle:
            radius = max(1, int(round(patch.size / 2.0)))
            cv2.circle(img, (int(round(patch.cx)), int(round(patch.cy))), radius, patch.bgr, -1)
        else:
            height = patch.size if patch.h is None else patch.h
            x0 = int(round(patch.cx - patch.size / 2.0))
            y0 = int(round(patch.cy - height / 2.0))
            cv2.rectangle(img, (x0, y0), (x0 + patch.size, y0 + height), patch.bgr, -1)
    if brightness != 1.0:
        img = np.clip(img.astype(np.float32) * brightness, 0, 255).astype(np.uint8)
    if blur > 0:
        k = blur if blur % 2 == 1 else blur + 1
        img = cv2.GaussianBlur(img, (k, k), 0)
    if noise_sigma > 0:
        rng = np.random.default_rng(seed)
        noisy = img.astype(np.float32) + rng.normal(0.0, noise_sigma, img.shape)
        img = np.clip(noisy, 0, 255).astype(np.uint8)
    return img


def ball_patch(x_cm: float, size: int = 28) -> Patch:
    cx = FRAME_W / 2.0 + PIXELS_PER_CM * x_cm
    return Patch(cx=cx, cy=FRAME_H / 2.0, size=size, bgr=GREEN_BGR, circle=True)


def detector(**kwargs: Any) -> Any:
    from atri.perception import OpenCVPerception

    params: Dict[str, Any] = {
        "pixels_per_cm": PIXELS_PER_CM,
        "ball_diameter_cm": BALL_DIAMETER_CM,
    }
    params.update(kwargs)
    return OpenCVPerception(**params)


# ────────────────────── A. 绿球检测扫描 ──────────────────────


@dataclass
class DetectorRow:
    group: str
    label: str
    x_true_cm: float
    found: bool
    x_cm: Optional[float]
    error_cm: Optional[float]
    distance_cm: Optional[float]
    distance_source: Optional[str]
    note: str = ""
    in_criteria: bool = False


def detector_scan() -> Tuple[List[DetectorRow], Dict[str, Any]]:
    if not HAS_NUMPY or not HAS_CV2:
        return [], {
            "skipped": True,
            "reason": "缺 numpy/cv2，A 段未跑",
            "total": 0,
            "found": 0,
            "criteria_total": 0,
            "criteria_found": 0,
            "criteria_errors_cm": [],
            "distance_sources": [],
        }

    rows: List[DetectorRow] = []
    det = detector()

    def run(
        group: str,
        label: str,
        x_true_cm: float,
        frame: Any,
        note: str = "",
        in_criteria: bool = False,
        use: Any = None,
    ) -> None:
        result = (use or det).detect_ball(frame=frame)
        data = result.data
        found = bool(data.get("found"))
        x_cm = data.get("x_cm") if found else None
        rows.append(
            DetectorRow(
                group=group,
                label=label,
                x_true_cm=x_true_cm,
                found=found,
                x_cm=x_cm,
                error_cm=(None if x_cm is None else round(x_cm - x_true_cm, 3)),
                distance_cm=data.get("distance_cm") if found else None,
                distance_source=data.get("distance_source") if found else None,
                note=note,
                in_criteria=in_criteria,
            )
        )

    for x_cm in (-6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0):
        run("偏移", f"x={x_cm:+.0f}cm", x_cm, make_frame([ball_patch(x_cm)]), in_criteria=True)

    for size in (8, 12, 20, 28, 48, 80):
        run(
            "尺度",
            f"直径={size}px",
            0.0,
            make_frame([Patch(FRAME_W / 2, FRAME_H / 2, size, GREEN_BGR, circle=True)]),
            note=f"等效物距≈{NOMINAL_FOCAL_PX * BALL_DIAMETER_CM / size:.0f}cm"
            "（按 1280 宽/60° 名义相机折算，仅作直观参照）",
            in_criteria=True,
        )

    for gain in (0.3, 0.5, 0.8, 1.0, 1.3):
        note = "HSV 的 V 门限是 80：太暗必然检不到（现场要开补光或降门限）" if gain <= 0.3 else ""
        run(
            "亮度",
            f"×{gain}",
            0.0,
            make_frame([ball_patch(0.0)], brightness=gain),
            note=note,
            in_criteria=gain >= 0.8,
        )

    for sigma in (0.0, 8.0, 16.0, 32.0, 48.0):
        run(
            "噪声",
            f"σ={sigma:g}",
            0.0,
            make_frame([ball_patch(0.0)], noise_sigma=sigma),
            in_criteria=sigma <= 16.0,
        )

    for k in (0, 5, 9, 15):
        run(
            "模糊",
            f"核={k or '无'}",
            0.0,
            make_frame([ball_patch(0.0)], blur=k),
            in_criteria=k <= 9,
        )

    clutter = [
        Patch(30, 40, 36, OCCLUDE_BGR, circle=False),
        Patch(280, 200, 40, (0, 0, 255), circle=False),
        Patch(60, 210, 30, (255, 0, 0), circle=False),
    ]
    run("干扰", "3 个异色块", 0.0, make_frame(clutter + [ball_patch(0.0)]), in_criteria=True)

    for cover in (0.2, 0.4, 0.6):
        bar_w = int(round(28 * cover))
        patches = [
            ball_patch(0.0),
            Patch(FRAME_W / 2 - 14 + bar_w / 2, FRAME_H / 2, bar_w, OCCLUDE_BGR, h=28, circle=False),
        ]
        run(
            "遮挡",
            f"遮 {int(cover * 100)}%",
            0.0,
            make_frame(patches),
            note="全高挡条盖住左侧：检出中心会系统性右偏",
        )

    empty = np.full((FRAME_H, FRAME_W, 3), BG_BGR, dtype=np.uint8)
    run("无球", "空画面", 0.0, empty, note="必须 found=False，技能不得下发踢", in_criteria=True)

    run("距离口径", "无焦距", 0.0, make_frame([ball_patch(0.0)]), use=detector())
    run(
        "距离口径",
        "有焦距",
        0.0,
        make_frame([ball_patch(0.0)]),
        use=detector(focal_px=NOMINAL_FOCAL_PX),
    )

    criteria = [r for r in rows if r.in_criteria]
    summary: Dict[str, Any] = {
        "skipped": False,
        "total": len(rows),
        "found": sum(1 for r in rows if r.found),
        "criteria_total": len(criteria),
        "criteria_found": sum(1 for r in criteria if r.found),
        "criteria_errors_cm": [abs(r.error_cm) for r in criteria if r.error_cm is not None],
        "distance_sources": sorted({r.distance_source for r in rows if r.distance_source}),
    }
    if summary["criteria_errors_cm"]:
        summary["criteria_max_abs_error_cm"] = round(max(summary["criteria_errors_cm"]), 3)
        summary["criteria_mean_abs_error_cm"] = round(
            sum(summary["criteria_errors_cm"]) / len(summary["criteria_errors_cm"]), 3
        )
    return rows, summary


# ──────────────── B. 图像/几何在环：真技能 ────────────────


class CountingCerebellum(Cerebellum):
    """记录 kick 下发次数，供「无球失败不下发踢」锁死。"""

    def __init__(self) -> None:
        super().__init__(servo_bus=MockServoBus(), sleeper=lambda dt: None)
        self.kick_calls = 0
        self.last_foot: Optional[str] = None

    def kick(self, foot: str = "right") -> Dict[str, Any]:  # type: ignore[override]
        self.kick_calls += 1
        self.last_foot = foot
        return super().kick(foot=foot)


class GeometricBallPerception:
    """无 cv2 时的一维几何感知：``x_obs = x_true − D·tan(yaw)``。

    gain = 物距 × tan(1°) **未标定**（假设髋偏航指令角 = 身体实际转角）。
    """

    name = "geometric-ball"

    def __init__(self, bus: MockServoBus, x_true_cm: float, distance_cm: float) -> None:
        self.bus = bus
        self.x_true_cm = float(x_true_cm)
        self.distance_cm = float(distance_cm)
        self.off_frame = False

    def yaw_deg(self) -> float:
        left = self.bus.angles.get(JOINTS["left_hip_yaw"]["id"], 0.0)
        right = self.bus.angles.get(JOINTS["right_hip_yaw"]["id"], 0.0)
        return 0.5 * (left + right)

    def x_rel_cm(self) -> float:
        return self.x_true_cm - self.distance_cm * math.tan(math.radians(self.yaw_deg()))

    def detect_ball(self, frame: Any = None) -> PerceptionResult:
        x_rel = self.x_rel_cm()
        half = fov_half_cm_at(self.distance_cm)
        self.off_frame = abs(x_rel) > half
        if self.off_frame:
            return PerceptionResult(kind="ball", data={"found": False}, confidence=0.0)
        return PerceptionResult(
            kind="ball",
            data={
                "found": True,
                "x_cm": round(x_rel, 2),
                "distance_cm": self.distance_cm,
                "distance_source": "geometry-uncalibrated",
            },
            confidence=0.85,
        )


class RenderedBallPerception:
    """有 cv2 时：把球按 yaw 几何画进真图，交给真 detect_ball。"""

    name = "rendered-opencv-ball"

    def __init__(
        self,
        bus: MockServoBus,
        x_true_cm: float,
        distance_cm: float,
        noise_sigma: float = 0.0,
        blur: int = 0,
        brightness: float = 1.0,
    ) -> None:
        self.bus = bus
        self.x_true_cm = float(x_true_cm)
        self.distance_cm = float(distance_cm)
        self.noise_sigma = float(noise_sigma)
        self.blur = int(blur)
        self.brightness = float(brightness)
        self.pixels_per_cm = FRAME_FOCAL_PX / self.distance_cm
        self.size_px = max(4, int(round(BALL_DIAMETER_CM * self.pixels_per_cm)))
        self.detector = detector(
            pixels_per_cm=self.pixels_per_cm,
            focal_px=FRAME_FOCAL_PX,
            ball_diameter_cm=BALL_DIAMETER_CM,
        )
        self.off_frame = False

    def yaw_deg(self) -> float:
        left = self.bus.angles.get(JOINTS["left_hip_yaw"]["id"], 0.0)
        right = self.bus.angles.get(JOINTS["right_hip_yaw"]["id"], 0.0)
        return 0.5 * (left + right)

    def x_rel_cm(self) -> float:
        return self.x_true_cm - self.distance_cm * math.tan(math.radians(self.yaw_deg()))

    def grab(self) -> Any:
        x_rel = self.x_rel_cm()
        cx = FRAME_W / 2.0 + self.pixels_per_cm * x_rel
        self.off_frame = not (0 <= cx <= FRAME_W)
        patch = Patch(cx=cx, cy=FRAME_H / 2.0, size=self.size_px, bgr=GREEN_BGR, circle=True)
        return make_frame(
            [patch],
            noise_sigma=self.noise_sigma,
            blur=self.blur,
            brightness=self.brightness,
        )

    def detect_ball(self, frame: Any = None) -> PerceptionResult:
        img = self.grab() if frame is None else frame
        return self.detector.detect_ball(frame=img)


class EmptyBallPerception:
    """空画面 / 无球：技能必须失败且不下发踢。"""

    name = "empty-ball"

    def detect_ball(self, frame: Any = None) -> PerceptionResult:
        return PerceptionResult(kind="ball", data={"found": False}, confidence=0.0)


@dataclass
class LoopRow:
    variant: str
    x_true_cm: float
    distance_cm: float
    gain_cm_per_deg: float
    fov_limit_cm: float
    status: str
    ok: bool
    iterations: int
    ball_x_cm: Optional[float]
    converged: Optional[bool]
    kick_calls: int
    reason: str = ""
    off_frame_any: bool = False
    mode: str = "geometry"


def run_kick_loop(
    x_true_cm: float,
    distance_cm: float,
    variant: str = "代码默认",
    params: Optional[Dict[str, Any]] = None,
    use_image: Optional[bool] = None,
    **render: Any,
) -> LoopRow:
    """跑一次真踢球任务。有 cv2 默认走合成图，否则走一维几何。"""
    if use_image is None:
        use_image = HAS_NUMPY and HAS_CV2
    cere = CountingCerebellum()
    if use_image:
        perception: Any = RenderedBallPerception(cere.bus, x_true_cm, distance_cm, **render)
        mode = "image"
    else:
        perception = GeometricBallPerception(cere.bus, x_true_cm, distance_cm)
        mode = "geometry"
    ctx = SkillContext(
        task_id="T-04",
        task_name="体育运动-踢球",
        params=dict(params or {}),
        cerebellum=cere,
        perception=perception,
        tts_engine=None,
    )
    outcome = KickSkill().run(ctx)
    return LoopRow(
        variant=variant,
        x_true_cm=x_true_cm,
        distance_cm=distance_cm,
        gain_cm_per_deg=round(distance_cm * math.tan(math.radians(1.0)), 4),
        fov_limit_cm=round(fov_half_cm_at(distance_cm), 2),
        status=str(outcome.get("status")),
        ok=str(outcome.get("status")) == "ok",
        iterations=int(outcome.get("iterations") or 0),
        ball_x_cm=outcome.get("ball_x_cm"),
        converged=outcome.get("converged"),
        kick_calls=cere.kick_calls,
        reason=str(outcome.get("reason") or ""),
        off_frame_any=bool(getattr(perception, "off_frame", False)),
        mode=mode,
    )


def image_in_loop_scan() -> List[LoopRow]:
    """同一批场景跑两套参数。距离轴对齐 S-04：10 / 15 / 25 cm。"""
    rows: List[LoopRow] = []
    for distance_cm in (10.0, 15.0, 25.0):
        for x_true_cm in (0.0, 0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 10.0):
            rows.append(run_kick_loop(x_true_cm, distance_cm, variant="代码默认"))
            rows.append(
                run_kick_loop(
                    x_true_cm, distance_cm, variant="推荐参数", params=RECOMMENDED_PARAMS
                )
            )
    if HAS_NUMPY and HAS_CV2:
        for x_true_cm in (2.0, 4.0):
            rows.append(
                run_kick_loop(
                    x_true_cm,
                    15.0,
                    variant="代码默认",
                    noise_sigma=16.0,
                    blur=5,
                    brightness=0.9,
                )
            )
            rows.append(
                run_kick_loop(
                    x_true_cm,
                    15.0,
                    variant="推荐参数",
                    params=RECOMMENDED_PARAMS,
                    noise_sigma=16.0,
                    blur=5,
                    brightness=0.9,
                )
            )
    return rows


# ──────────────────── C. 参数边界表（纯控制律） ────────────────────


def simulate_servo(
    x0_cm: float,
    gain_cm_per_deg: float,
    deadband_cm: float,
    max_iters: int,
    step_gain: float,
    step_clamp_deg: float,
) -> Tuple[float, int, bool]:
    """复算 ``skills/base.py::lateral_servo`` 的同一套迭代（一维几何，无图像）。"""
    yaw = 0.0
    x = x0_cm
    iters = 0
    while abs(x) > deadband_cm and iters < max_iters:
        step = max(-step_clamp_deg, min(step_clamp_deg, x * step_gain))
        yaw += step
        x = x0_cm - gain_cm_per_deg * yaw
        iters += 1
    return x, iters, abs(x) <= deadband_cm


def max_reachable_cm(x0_cap: float, tolerance_cm: float, **params: Any) -> Optional[float]:
    best: Optional[float] = None
    x = 0.2
    while x <= x0_cap:
        final, _iters, _converged = simulate_servo(x, **params)
        if abs(final) <= tolerance_cm:
            best = round(x, 1)
        x = round(x + 0.1, 2)
    return best


def boundary_table() -> Dict[str, Any]:
    deadband = float(KICK_DEFAULTS["deadband_cm"])
    step_gain = float(KICK_DEFAULTS["step_gain"])
    clamp = float(KICK_DEFAULTS["step_clamp_deg"])
    max_iters = int(KICK_DEFAULTS["max_iters"])
    cap = CAP_CM
    rows: List[Dict[str, Any]] = []
    for distance_cm in (6.0, 10.0, 15.0, 20.0, 40.0):
        gain = round(distance_cm * math.tan(math.radians(1.0)), 4)
        for iters in (3, 5, 8, 12, 20):
            rows.append({
                "gain_cm_per_deg": gain,
                "distance_cm": distance_cm,
                "max_iters": iters,
                "fov_half_cm": round(fov_half_cm_at(distance_cm), 2),
                "max_offset_cm": max_reachable_cm(
                    cap,
                    deadband,
                    gain_cm_per_deg=gain,
                    deadband_cm=deadband,
                    max_iters=iters,
                    step_gain=step_gain,
                    step_clamp_deg=clamp,
                ),
            })
    mock_rows: List[Dict[str, Any]] = []
    for iters in (3, 5, 8, 12):
        mock_rows.append({
            "gain_cm_per_deg": 1.5,
            "max_iters": iters,
            "max_offset_cm": max_reachable_cm(
                cap,
                deadband,
                gain_cm_per_deg=1.5,
                deadband_cm=deadband,
                max_iters=iters,
                step_gain=step_gain,
                step_clamp_deg=clamp,
            ),
        })
    gain15 = round(15.0 * math.tan(math.radians(1.0)), 4)
    gain_rows: List[Dict[str, Any]] = []
    for sg in (0.3, 0.5, 0.8, 1.0, 1.5):
        for cl in (10.0, 20.0, 45.0):
            gain_rows.append({
                "step_gain": sg,
                "step_clamp_deg": cl,
                "max_offset_cm": max_reachable_cm(
                    cap,
                    deadband,
                    gain_cm_per_deg=gain15,
                    deadband_cm=deadband,
                    max_iters=max_iters,
                    step_gain=sg,
                    step_clamp_deg=cl,
                ),
            })
    recommended_rows: List[Dict[str, Any]] = []
    for distance_cm in (6.0, 10.0, 15.0, 20.0, 40.0):
        gain = round(distance_cm * math.tan(math.radians(1.0)), 4)
        fov = round(fov_half_cm_at(distance_cm), 2)
        default_reach = max_reachable_cm(
            cap,
            deadband,
            gain_cm_per_deg=gain,
            deadband_cm=deadband,
            max_iters=max_iters,
            step_gain=step_gain,
            step_clamp_deg=clamp,
        )
        rec_reach = max_reachable_cm(
            cap,
            deadband,
            gain_cm_per_deg=gain,
            deadband_cm=deadband,
            max_iters=int(RECOMMENDED_PARAMS["max_iters"]),
            step_gain=float(RECOMMENDED_PARAMS["step_gain"]),
            step_clamp_deg=clamp,
        )
        recommended_rows.append({
            "distance_cm": distance_cm,
            "gain_cm_per_deg": gain,
            "fov_half_cm": fov,
            "default_reach_cm": default_reach,
            "recommended_reach_cm": rec_reach,
            "covers_fov": bool(rec_reach is not None and rec_reach >= fov),
        })
    return {
        "assumptions": {
            "deadband_cm": deadband,
            "step_gain": step_gain,
            "step_clamp_deg": clamp,
            "max_iters": max_iters,
            "min_distance_cm": float(KICK_DEFAULTS["min_distance_cm"]),
            "max_distance_cm": float(KICK_DEFAULTS["max_distance_cm"]),
            "gain_model": "gain = 物距 × tan(1°)，即针孔模型；**未标定**（髋偏航指令角 ≠ 已测身体转角）",
            "accept_model": "可纠正 = 在迭代上限内最终偏差 ≤ 死区（踢球：进死区才算对准；不收敛也仍会踢）",
            "cap_cm": cap,
        },
        "by_distance": rows,
        "recommended": recommended_rows,
        "mock_gain_1p5": mock_rows,
        "step_gain_sweep_15cm": gain_rows,
    }


# ────────────────────────── 报告 ──────────────────────────


def _pct(hit: int, total: int) -> str:
    return f"{hit}/{total}（{100.0 * hit / total:.1f}%）" if total else "—"


def _cell(value: Optional[float], cap: float) -> str:
    if value is None:
        return "—"
    return f"≥{cap:g} cm" if value >= cap else f"{value:g} cm"


def build_report(
    det_rows: List[DetectorRow],
    det_sum: Dict[str, Any],
    loop_rows: List[LoopRow],
    bounds: Dict[str, Any],
    *,
    eval_ran: bool,
    eval_note: str,
) -> str:
    lines: List[str] = []
    add = lines.append
    a = bounds["assumptions"]
    cap = float(a.get("cap_cm", 60.0))
    loop_mode = loop_rows[0].mode if loop_rows else "未跑"
    loop_label = "合成图 + 真 detect_ball" if loop_mode == "image" else "一维几何（无 cv2）"

    add("# T-04 体育运动-踢球 · 方案与评测报告")
    add("")
    add("> 生成命令（本报告所有数字都由它一次跑出，可直接复跑核对）：")
    add("> ```")
    add("> python3 software/atri/tools/kick_eval.py \\")
    add(">     --report design/handoff/T-04-踢球-方案与评测报告.md")
    add("> ```")
    add(">")
    add("> 有 `.venv-face` 时改用 `.venv-face/bin/python` 才能补 A 段合成绿球图；")
    add("> 本机无该环境，按任务要求不装系统包。")
    add(">")
    add("> **本报告测的是代码与几何，不是实物。** 没有样机、没有相机、没有球，")
    add("> 因此这里没有、也不会有「踢球成功率 ≥70%」这类实机指标（未测项 B7 **仍未测**）；")
    add("> 全部数字的适用范围写在 §1 与 §5，引用前请先读那两节。")
    add(">")
    add(f"> 本轮评测状态：{eval_note}")
    add("")
    add("## 1. 这份评测是什么、不是什么")
    add("")
    add("| 段 | 测什么 | 用的真代码 | 数据来源 | 能写进材料吗 |")
    add("|---|---|---|---|---|")
    add("| A | 绿球检测成功率 / 横向误差 | `perception/opencv.py::detect_ball` | **程序合成图像**（cv2 画出来的绿圆） | 能，但必须写「合成图，非实机相机」 |")
    add(f"| B | 踢球闭环端到端（对准 + 下发踢） | 真 `KickSkill` + 真 `Cerebellum` | {loop_label}；yaw 模型 `x_rel = x_true − D·tanθ` | 能，但必须写「合成图/几何 + **未标定 gain**」 |")
    add("| C | 参数边界（可纠正多大偏差） | 与 `skills/base.py::lateral_servo` 同式复算 | 纯数学 | 能，这是**调参依据** |")
    add("")
    add("**不能**从本报告得出的结论：实机踢球成功率、摆腿能不能碰到球、步态能不能走过去、")
    add("绿球在真实光照下能不能检出、gain 在这台机器上是多少。这些都要实物，见 §5。")
    add("")
    add("踢球与搬运的关键行为差：**搬运没对准就不夹；踢球不收敛也踢**")
    add("（接触即尽力而为）。所以 B 段「成功」= 技能 status=ok 且下发了一次 kick，")
    add("**不等于**球被踢动，更不等于赛题 ≥70%。")
    add("")
    add("## 2. A 段：绿球检测（合成图，真检测器）")
    add("")
    if det_sum.get("skipped"):
        add(f"**本段未跑**：{det_sum.get('reason', '缺 numpy/cv2')}。")
        add("本机无 `.venv-face`，按任务要求不装系统包。有依赖后用同一命令重跑即可补表。")
        add("")
    else:
        add(
            f"- 判据条件内（干净画面、固定光照、无遮挡、噪σ≤16、模糊核≤9、含「无球」负例）："
            f"**{_pct(det_sum['criteria_found'], det_sum['criteria_total'])}** 检出"
            "（「无球」场景期望 *不* 检出，计入分母但不计入 found）"
        )
        add(
            f"- 全扫描（含故意做坏的：偏暗、强噪、重模糊、遮挡）："
            f"**{_pct(det_sum['found'], det_sum['total'])}** 检出"
        )
        if "criteria_max_abs_error_cm" in det_sum:
            add(
                f"- 判据条件内横向误差：最大 {det_sum['criteria_max_abs_error_cm']} cm、"
                f"平均 {det_sum['criteria_mean_abs_error_cm']} cm"
                f"（像素当量 {PIXELS_PER_CM:g} px/cm 下的量化误差）"
            )
        add(
            f"- 距离口径标记：{'、'.join(det_sum.get('distance_sources') or [])}"
            "（无焦距时必须是 `uncalibrated`——它**不是**实测距离）"
        )
        add("")
        add("| 组 | 场景 | 真值 x_cm | 检出 | 测得 x_cm | 误差 cm | 距离来源 | 备注 |")
        add("|---|---|---|---|---|---|---|---|")
        for row in det_rows:
            add(
                f"| {row.group} | {row.label} | {row.x_true_cm:+.1f} | "
                f"{'✅' if row.found else '❌'} | "
                f"{'—' if row.x_cm is None else f'{row.x_cm:+.2f}'} | "
                f"{'—' if row.error_cm is None else f'{row.error_cm:+.2f}'} | "
                f"{row.distance_source or '—'} | {row.note} |"
            )
        add("")

    add("## 3. B 段：图像/几何在环闭环（真技能）")
    add("")
    add("模型假设（**这些假设本身就是未标定项**）：相机 320×240、水平视场 60° → 焦距")
    add(f"`f = {FRAME_FOCAL_PX:.1f} px`；身体转过 `yaw` 度后相对偏差")
    add("`x_rel = x_true − 物距·tan(yaw)`（与 T-03 同一套 yaw 模型）；")
    add("**gain = 物距 × tan(1°)，未标定**——假设髋偏航指令角 = 身体实际转角")
    add("（未测项 C1/C2）。球直径名义 4 cm（S-04 `ball_diameter_mm=40`）。")
    add("")
    add(
        f"同一批场景跑两套参数：**代码默认**（`max_iters={int(a['max_iters'])}, "
        f"step_gain={a['step_gain']:g}, deadband_cm={a['deadband_cm']:g}`）与"
        f"**推荐参数**（`max_iters={RECOMMENDED_PARAMS['max_iters']}, "
        f"step_gain={RECOMMENDED_PARAMS['step_gain']}`，依据 §4 的边界表）。"
    )
    add(f"本段数据来源：**{loop_label}**。")
    add("")
    if not loop_rows:
        add("**本段未跑**（`--no-loop` 或工具未执行）。")
        add("")
    else:
        variants: Dict[str, List[LoopRow]] = {}
        for row in loop_rows:
            variants.setdefault(row.variant, []).append(row)
        add("| 参数组 | 技能 ok（下发了踢） | 闭环收敛 | 说明 |")
        add("|---|---|---|---|")
        for name, group in variants.items():
            ok_n = sum(1 for r in group if r.ok)
            conv_n = sum(1 for r in group if r.converged)
            note = "代码里的设计值" if name == "代码默认" else "边界表推出的调参方向"
            add(f"| {name} | **{_pct(ok_n, len(group))}** | {_pct(conv_n, len(group))} | {note} |")
        add("")
        add("读法：踢球**不收敛也踢**，所以「技能 ok」会高于「闭环收敛」。")
        add("把「技能 ok」写成「踢球成功率」是口径错误。")
        add("")
        add("失败原因分布（比成功率有用：失败都发生在哪一步）：")
        add("")
        add("| 参数组 | 失败原因 | 次数 |")
        add("|---|---|---|")
        for name, group in variants.items():
            reasons: Dict[str, int] = {}
            for row in group:
                if not row.ok:
                    key = row.reason or "其他"
                    if "未命中" in key or "found" in key:
                        key = "球未检出 / 出画（不下发踢）"
                    reasons[key] = reasons.get(key, 0) + 1
            if not reasons:
                add(f"| {name} | （无失败） | 0 |")
            for key, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
                add(f"| {name} | {key} | {count} |")
        add("")
        add("逐场景明细（`出画` = 闭环过程中球曾跑出视场）：")
        add("")
        add("| 参数组 | 真值 x_cm | 物距 cm | gain cm/° | 视场半宽 cm | 结果 | 迭代 | 闭环后偏差 cm | 收敛 | 下发踢 | 出画 |")
        add("|---|---|---|---|---|---|---|---|---|---|---|")
        for row in loop_rows:
            ok_text = "✅ ok" if row.ok else "❌ " + row.status
            x_text = "—" if row.ball_x_cm is None else f"{row.ball_x_cm:+.2f}"
            conv = "—" if row.converged is None else ("是" if row.converged else "否")
            add(
                f"| {row.variant} | {row.x_true_cm:+.1f} | {row.distance_cm:g} | "
                f"{row.gain_cm_per_deg:g} | ±{row.fov_limit_cm:g} | "
                f"{ok_text} | {row.iterations} | {x_text} | {conv} | "
                f"{row.kick_calls} | {'是' if row.off_frame_any else '否'} |"
            )
        add("")

    add("## 4. C 段：参数边界表（实物到手后照着这张表调）")
    add("")
    add(
        f"当前代码默认值：死区 {a['deadband_cm']:g} cm、步长增益 {a['step_gain']:g}、"
        f"单轮钳位 {a['step_clamp_deg']:g}°、迭代上限 {a['max_iters']}、"
        f"距离门闩 [{a['min_distance_cm']:g}, {a['max_distance_cm']:g}] cm。"
    )
    add(f"gain 模型：{a['gain_model']}；判定模型：{a['accept_model']}。")
    add("")
    add("**「最大可纠正初始偏差」= 在这套参数下、迭代上限之内能把偏差压到 ≤ 死区的最大 x。**")
    add("超出它时技能**仍然会踢**（与搬运不同），只是 `converged=False`。")
    add("")
    add("| 物距 cm | gain cm/° | 视场半宽 cm | 迭代上限 3 | 5（现值） | 8 | 12 | 20 |")
    add("|---|---|---|---|---|---|---|---|")
    by_dist: Dict[float, Dict[int, Optional[float]]] = {}
    fov_of: Dict[float, float] = {}
    for row in bounds["by_distance"]:
        by_dist.setdefault(row["distance_cm"], {})[row["max_iters"]] = row["max_offset_cm"]
        fov_of[row["distance_cm"]] = row.get("fov_half_cm", float("nan"))
    for distance_cm, iters in by_dist.items():
        gain = next(
            r["gain_cm_per_deg"] for r in bounds["by_distance"] if r["distance_cm"] == distance_cm
        )
        cells = " | ".join(_cell(iters.get(k), cap) for k in (3, 5, 8, 12, 20))
        add(f"| {distance_cm:g} | {gain:g} | ±{fov_of[distance_cm]:g} | {cells} |")
    add("")
    add("⚠ **视场半宽是硬上限**：球跑出画面就检不到（技能判失败、**不下发踢**），参数再好也纠不了。")
    add("")
    add("对照：现有 Mock 用的 gain = 1.5 cm/°（等价物距 86 cm，**未标定**）：")
    add("")
    add("| gain cm/° | 迭代上限 | 最大可纠正偏差 |")
    add("|---|---|---|")
    for row in bounds["mock_gain_1p5"]:
        add(f"| {row['gain_cm_per_deg']} | {row['max_iters']} | {_cell(row['max_offset_cm'], cap)} |")
    add("")
    add("步长增益/钳位的影响（gain 取 15 cm 物距的针孔值，**未标定**）：")
    add("")
    add("| step_gain | 钳位 10° | 钳位 20° | 钳位 45° |")
    add("|---|---|---|---|")
    sweep: Dict[float, Dict[float, Optional[float]]] = {}
    for row in bounds["step_gain_sweep_15cm"]:
        sweep.setdefault(row["step_gain"], {})[row["step_clamp_deg"]] = row["max_offset_cm"]
    for sg, clamps in sweep.items():
        cells = " | ".join(_cell(clamps.get(c), cap) for c in (10.0, 20.0, 45.0))
        add(f"| {sg:g} | {cells} |")
    add("")
    add("### 4.1 结论：这套参数该怎么调（数据来自上表，不是拍脑袋）")
    add("")
    add(
        f"推荐值取 `max_iters={RECOMMENDED_PARAMS['max_iters']}`、"
        f"`step_gain={RECOMMENDED_PARAMS['step_gain']}`："
    )
    add("")
    add("| 物距 cm | gain cm/° | 视场半宽 cm | 默认参数可纠正 | 推荐参数可纠正 | 是否覆盖整个视场 |")
    add("|---|---|---|---|---|---|")
    for row in bounds["recommended"]:
        add(
            f"| {row['distance_cm']:g} | {row['gain_cm_per_deg']:g} | ±{row['fov_half_cm']:g} | "
            f"{_cell(row['default_reach_cm'], cap)} | {_cell(row['recommended_reach_cm'], cap)} | "
            f"{'✅' if row['covers_fov'] else '❌'} |"
        )
    add("")
    add("⚠ 这条推荐**不能直接上实机**：gain 未标定。实机第一步应当是量这个映射")
    add("（发 10° 看真转了多少），把实测 gain 写进 `config/kick.json`，再按上表复核。")
    add("")
    add("## 5. 诚实缺口清单（这些没有测，测不了，或没接）")
    add("")
    add("| # | 缺口 | 为什么没测 | 怎么才能测 |")
    add("|---|---|---|---|")
    add("| 1 | **实机踢球成功率（B7，赛题 ≥70%）** | 没有样机、没有球 | 样机 + 固定球位 10–20 cm，跑 N 次记接触/位移 |")
    add("| 2 | **真实相机上的绿球检测** | 没有相机；A 段是程序合成图 | 真球 + 真相机，按同一批场景重跑本工具 |")
    add("| 3 | **像素当量 ppcm / 焦距未标定** | 没有相机内参 | 棋盘格标定 → 回填 `config/kick.json` |")
    add("| 4 | **髋偏航指令 → 身体实际转角**未标定（gain） | 无位移/里程计 | 实机量：发 10° 看转了多少；写进 `config/odometry.json` |")
    add("| 5 | **摆腿接触几何**（脚能不能碰到球） | 踢球动作是预标定角度序列 | 样机上量脚尖工作空间 vs 球位 |")
    add("| 6 | **不收敛也踢**在实物上是否安全 | 代码层有意如此 | 实机确认：空踢会不会失稳 |")
    add("| 7 | Webots 控制器仍注入**静态** MockPerception | 仿真侧未接摄像头 | 在 Webots 里给机器人加 Camera + 接 `OpenCVPerception` |")
    add("")
    add("## 6. 与实物对接：改哪里、量什么")
    add("")
    add("1. **相机标定**后写 `software/atri/config/kick.json`：")
    add("   `step_gain`、`deadband_cm`（脚能容忍多大横向偏差）。")
    add("2. **不用改代码**：优先级是 任务卡 params > `config/kick.json` > 代码默认值。")
    add("3. 多轮不够就加大 `max_iters` 或 `step_gain`；单轮转太多会超调，`step_clamp_deg` 是刹车。")
    add("4. 距离不在 4–40 cm 技能直接失败、不下发踢——现场球位先量再改门闩。")
    add("")
    add("---")
    add("")
    add("报告由 `tools/kick_eval.py` 生成；场景表 `design/packages/scenario_set.json`（S-04）")
    add("只规定了变化轴（横向偏移 / 球距 10–25 cm），本工具按 T-03 同一套做法把轴落成可复跑场景。")
    add("未测项 B7（实机踢球成功率）**本轮不闭合**。")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="T-04 踢球评测（合成图/几何闭环 + 边界表）")
    parser.add_argument("--report", default=None, help="markdown 报告输出路径")
    parser.add_argument("--json", default=None, help="机器可读结果输出路径")
    parser.add_argument("--no-loop", action="store_true", help="跳过 B 段")
    args = parser.parse_args(argv)

    print("=" * 64)
    print("T-04 踢球评测：A 绿球检测 / B 闭环 / C 参数边界")
    print("=" * 64)
    print(f"numpy={'有' if HAS_NUMPY else '无'}  cv2={'有' if HAS_CV2 else '无'}")

    t = load_tuning("kick", KICK_DEFAULTS, warn=None)
    print(f"参数出处：{t.provenance()}")
    for message in t.warnings:
        print(f"  ⚠ {message}")

    if HAS_NUMPY and HAS_CV2:
        eval_note = "已跑评测（numpy + opencv 可用）"
    elif HAS_NUMPY:
        eval_note = "部分跑：有 numpy、无 opencv；A 段跳过，B 段走一维几何"
    else:
        eval_note = "本机无 `.venv-face`、系统 python 无 numpy/cv2：**几何闭环 + 边界表已跑**；A 段（合成绿球图）未跑、缺依赖。未装系统包。"
    print(f"口径：{eval_note}")

    det_rows, det_sum = detector_scan()
    if det_sum.get("skipped"):
        print(f"[A] 跳过：{det_sum.get('reason')}")
    else:
        print(
            f"[A] 检出 判据条件 {det_sum['criteria_found']}/{det_sum['criteria_total']}、"
            f"全扫描 {det_sum['found']}/{det_sum['total']}"
        )

    loop_rows: List[LoopRow] = [] if args.no_loop else image_in_loop_scan()
    if loop_rows:
        grouped: Dict[str, List[LoopRow]] = {}
        for row in loop_rows:
            grouped.setdefault(row.variant, []).append(row)
        parts = [
            f"{name} ok {sum(1 for r in group if r.ok)}/{len(group)} "
            f"收敛 {sum(1 for r in group if r.converged)}/{len(group)}"
            for name, group in grouped.items()
        ]
        print("[B] 闭环：" + "、".join(parts) + f"（模式 {loop_rows[0].mode}）")

    bounds = boundary_table()
    print("[C] 参数边界表已算出（§4）")

    payload = {
        "meta": {
            "tool": "tools/kick_eval.py",
            "task": "T-04",
            "generated_note": "合成图/一维几何 + 真检测器(若有)/真技能；不是实机指标；gain 未标定",
            "eval_note": eval_note,
            "has_numpy": HAS_NUMPY,
            "has_cv2": HAS_CV2,
            "pixels_per_cm": PIXELS_PER_CM,
            "frame": [FRAME_W, FRAME_H],
            "nominal_focal_px": round(NOMINAL_FOCAL_PX, 2),
            "gain_uncalibrated": True,
            "real_robot_success_rate": "未测",
            "tuning": {
                "source": t.source_path.name,
                "exists": t.source_exists,
                "overridden": list(t.overridden),
                "provenance": t.provenance(),
            },
        },
        "detector": {
            "summary": det_sum,
            "rows": [row.__dict__ for row in det_rows],
        },
        "image_in_loop": {
            "summary": {
                "total": len(loop_rows),
                "ok": sum(1 for r in loop_rows if r.ok),
                "converged": sum(1 for r in loop_rows if r.converged),
                "mode": loop_rows[0].mode if loop_rows else None,
            },
            "rows": [row.__dict__ for row in loop_rows],
        },
        "boundary": bounds,
    }

    if args.json:
        out = Path(args.json)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON → {out}")
    if args.report:
        out = Path(args.report)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            build_report(
                det_rows,
                det_sum,
                loop_rows,
                bounds,
                eval_ran=not det_sum.get("skipped") or bool(loop_rows),
                eval_note=eval_note,
            ),
            encoding="utf-8",
        )
        print(f"报告 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
