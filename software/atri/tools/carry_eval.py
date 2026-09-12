#!/usr/bin/env python3
"""T-03 物品搬运评测：色块检测实测 + 图像在环闭环 + 参数边界表。

**先说清这个工具测的是什么、不是什么**（本项目最容易被误读的地方）：

| 测的 | 怎么测 | 能不能写进材料 |
|---|---|---|
| 色块检测在**程序合成图像**上的成功率与横向误差 | 真 ``OpenCVPerception.detect_object`` 跑在合成图上 | 能，但必须写"合成图，不是实机相机" |
| **闭环控制律在图像在环下**能不能收敛 | 合成图 → 真检测器 → 真 ``CarrySkill`` → 真 ``Cerebellum`` | 能，但必须写「合成图 + 一维几何」 |
| "机器人转 1° 目标在画面里移几厘米"（gain）对收敛的影响 | 用针孔几何算出 gain，扫参数出**边界表** | 能，这是调参依据 |
| **实机抓取成功率** | —— | **不能**。没有样机、没有相机、没有夹爪 |

所以本工具的产出只有两类用途：① 证明**代码路径真的能跑**（不是纸面设计）；
② 给出**实物到手后该往哪儿调**的定量边界。任何一处都不等于"实物上做到了"。

## 为什么主扫描轴是 gain 而不是"多少厘米"

闭环收敛与否由 **gain = 相机焦距(px) / 物距(cm)** 决定（"身体转 1°，目标在画面里
横移多少厘米"）。现有 Mock 里 gain 固定写 1.5 cm/°，而按针孔几何推，
12 cm 物距下的真实 gain ≈ 0.21 cm/°（差 7 倍）。**这个差直接决定闭环够不够轮数**，
所以本工具把 gain 当主变量扫，并给出每个 gain 下的可纠正偏差上限。

## 用法

    .venv-face/bin/python software/atri/tools/carry_eval.py \\
        --report design/handoff/T-03-搬运-方案与评测报告.md \\
        --json design/results/t03_carry_eval.json

需要 numpy + opencv（本工具跑的是**真检测器**，不是替身）；缺依赖会明确报错并退出 2。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# tools/ 位于 <repo>/software/atri/tools/ 下：上溯 3 层才是仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
SOFTWARE_ROOT = REPO_ROOT / "software" / "atri"
sys.path.insert(0, str(SOFTWARE_ROOT))

try:
    import numpy as np
except ImportError:  # pragma: no cover - 环境问题，不是逻辑分支
    print("需要 numpy：请用 .venv-face/bin/python 运行（见 docs/process/工程说明.md）")
    raise SystemExit(2)

try:
    import cv2
except ImportError:  # pragma: no cover
    print("需要 opencv：请用 .venv-face/bin/python 运行，或 pip install opencv-contrib-python==4.11.0.86")
    raise SystemExit(2)

from atri.cerebellum import Cerebellum, MockServoBus  # noqa: E402
from atri.config import MAX_STEPS  # noqa: E402
from atri.perception import OpenCVPerception  # noqa: E402
from atri.skills.base import SkillContext  # noqa: E402
from atri.skills.carry import CARRY_DEFAULTS, CarrySkill  # noqa: E402
from atri.tuning import load_tuning  # noqa: E402

# 名义相机：1280×720、水平视场 60°（与 tools/qr_eval.py 同一套名义假设，便于互相引用）
NOMINAL_WIDTH_PX = 1280
NOMINAL_HFOV_DEG = 60.0
NOMINAL_FOCAL_PX = (NOMINAL_WIDTH_PX / 2.0) / math.tan(math.radians(NOMINAL_HFOV_DEG / 2.0))

FRAME_W, FRAME_H = 320, 240          # 评测帧尺寸：够小能快跑，够大不让色块贴边
# B 段用**同一台相机**在 320×240 下的焦距：由视场角定义，不是拍的脑袋。
#   f = (W/2) / tan(HFOV/2) = 277.1 px  →  像素当量 ppcm = f / 物距(cm)
FRAME_FOCAL_PX = (FRAME_W / 2.0) / math.tan(math.radians(NOMINAL_HFOV_DEG / 2.0))
FOV_HALF_CM_AT = lambda d_cm: d_cm * math.tan(math.radians(NOMINAL_HFOV_DEG / 2.0))  # noqa: E731

PIXELS_PER_CM = 10.0                 # A 段固定像素当量（只考察检测鲁棒性，不涉及几何）
TARGET_SIZE_CM = 4.0                 # 目标物名义边长（红块 4cm）
RED_BGR = (0, 0, 255)
BLUE_BGR = (255, 0, 0)
BG_BGR = (40, 40, 40)
OCCLUDE_BGR = (128, 128, 128)        # 灰：S=0，不进任何色域掩膜

RNG_SEED = 20260913

# B 段两种参数：① 代码默认值 ② 按针孔 gain 推荐的参数（用于证明"该怎么调"）
RECOMMENDED_PARAMS: Dict[str, Any] = {"max_iters": 15, "step_gain": 1.0}

# 边界表的扫描上限（cm）：超过它在桌面上已无意义；表里显示 ≥ 表示"上限内都能纠"
CAP_CM = 60.0


# ────────────────────────── 合成图像 ──────────────────────────


@dataclass
class Patch:
    """一块合成色块：中心像素 + 边长像素 + BGR。

    ``h=None`` 表示正方形（size × size）；给 ``h`` 就画成条形——遮挡场景需要
    **全高**的挡条，否则红块被中间挖个洞仍是一个连通区，连 boundingRect 都不变，
    "遮挡"就成了假场景。
    """

    cx: float
    cy: float
    size: int
    bgr: Tuple[int, int, int]
    h: Optional[int] = None


def make_frame(
    patches: Sequence[Patch],
    noise_sigma: float = 0.0,
    blur: int = 0,
    brightness: float = 1.0,
    seed: int = RNG_SEED,
) -> Any:
    """按补丁列表合成一帧 BGR 图。扰动顺序固定（亮度→模糊→噪声），保证可复现。"""
    img = np.full((FRAME_H, FRAME_W, 3), BG_BGR, dtype=np.uint8)
    for patch in patches:
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


def object_patch(x_cm: float, size: int = 28) -> Patch:
    """按"横向偏差 x_cm"把红块放到画面里（+x 在画面右侧）。"""
    cx = FRAME_W / 2.0 + PIXELS_PER_CM * x_cm
    return Patch(cx=cx, cy=FRAME_H / 2.0, size=size, bgr=RED_BGR)


def detector(**kwargs: Any) -> OpenCVPerception:
    """构造被测的真检测器（默认：只有像素当量、没有焦距 → 距离必须标 uncalibrated）。"""
    params: Dict[str, Any] = {"pixels_per_cm": PIXELS_PER_CM}
    params.update(kwargs)
    return OpenCVPerception(**params)


# ────────────────────── A. 色块检测扫描 ──────────────────────


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
    in_criteria: bool = False   # 是否落在 BOM 判据条件内（≤1m、固定光照、无遮挡）


def detector_scan() -> Tuple[List[DetectorRow], Dict[str, Any]]:
    """扫"真检测器 + 合成图"：偏移 / 尺度 / 亮度 / 噪声 / 模糊 / 干扰 / 遮挡。"""
    rows: List[DetectorRow] = []
    det = detector()

    def run(group: str, label: str, x_true_cm: float, frame: Any,
            note: str = "", in_criteria: bool = False, use: Any = None) -> None:
        result = (use or det).detect_object(frame=frame)
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

    # ① 横向偏移：目标在画面里左右移动（判据内：干净画面、固定光照）
    for x_cm in (-6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0):
        run("偏移", f"x={x_cm:+.0f}cm", x_cm, make_frame([object_patch(x_cm)]),
            in_criteria=True)

    # ② 尺度：目标像素尺寸（= 物距的函数）
    for size in (8, 12, 20, 28, 48, 80):
        run("尺度", f"边长={size}px", 0.0, make_frame([Patch(FRAME_W / 2, FRAME_H / 2, size, RED_BGR)]),
            note=f"等效物距≈{NOMINAL_FOCAL_PX * 4.0 / size:.0f}cm"
                 "（按 1280 宽/60° 名义相机折算，仅作直观参照）",
            in_criteria=True)

    # ③ 亮度（HSV 的 V 门限是 80，太暗必然检不到——这正是要量出来的）
    for gain in (0.3, 0.5, 0.8, 1.0, 1.3):
        note = "HSV 的 V 门限是 80：太暗必然检不到（现场要开补光或降门限）" if gain <= 0.3 else ""
        run("亮度", f"×{gain}", 0.0, make_frame([object_patch(0.0)], brightness=gain),
            note=note, in_criteria=gain >= 0.8)

    # ④ 高斯噪声
    for sigma in (0.0, 8.0, 16.0, 32.0, 48.0):
        run("噪声", f"σ={sigma:g}", 0.0, make_frame([object_patch(0.0)], noise_sigma=sigma),
            in_criteria=sigma <= 16.0)

    # ⑤ 运动模糊
    for k in (0, 5, 9, 15):
        run("模糊", f"核={k or '无'}", 0.0, make_frame([object_patch(0.0)], blur=k),
            in_criteria=k <= 9)

    # ⑥ 背景干扰：非红杂块（灰、蓝、绿）——不该被当成目标
    clutter = [
        Patch(30, 40, 36, OCCLUDE_BGR),
        Patch(280, 200, 40, (0, 255, 0)),
        Patch(60, 210, 30, (0, 200, 255)),
    ]
    run("干扰", "3 个异色块", 0.0, make_frame(clutter + [object_patch(0.0)]), in_criteria=True)

    # ⑦ 遮挡：全高挡条盖住红块左半边的一部分（连通区变小 → 中心**系统性右偏**）
    for cover in (0.2, 0.4, 0.6):
        bar_w = int(round(28 * cover))
        patches = [
            object_patch(0.0),
            Patch(FRAME_W / 2 - 14 + bar_w / 2, FRAME_H / 2, bar_w, OCCLUDE_BGR, h=28),
        ]
        run("遮挡", f"遮 {int(cover * 100)}%", 0.0, make_frame(patches),
            note="全高挡条盖住左侧：检出中心会系统性右偏（面积加权估心解决不了）")

    # ⑧ 距离口径：无焦距 vs 有焦距——必须标清 calibrated / uncalibrated
    run("距离口径", "无焦距", 0.0, make_frame([object_patch(0.0)]), use=detector())
    run("距离口径", "有焦距", 0.0, make_frame([object_patch(0.0)]),
        use=detector(focal_px=NOMINAL_FOCAL_PX, object_size_cm=4.0))

    criteria = [r for r in rows if r.in_criteria]
    summary = {
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


# ──────────────── B. 图像在环：真检测器 + 真技能 + 一维几何 ────────────────


class RenderedObjectPerception:
    """把"机器人转到哪 → 目标在画面里在哪"渲染成一张**真图**，交给真检测器。

    模型（全部假设都写在这里，报告 §3 原样引用）：
      · 相机在机器人头上，320×240、水平视场 60° → 焦距 ``f = 277.1 px``；
      · 像素当量 ``ppcm = f / 物距``（**有焦距**，所以检测器的距离估算是
        ``calibrated`` 口径，不是像素当量兜底）；
      · 目标 4cm 见方，初始横向偏差 ``x_true``，身体转过 ``yaw`` 度后相对偏差
        ``x_rel = x_true − 物距·tan(yaw)``（"转过去，目标就往画面中间靠"）；
      · 成像 ``cx_px = W/2 + ppcm · x_rel``；超出画面按**截断**渲染（真实相机也是这样）；
      · **假设髋偏航指令角 = 身体实际转角**（未标定，见未测项 C1/C2）。

    只提供 ``detect_object``：故意**不**提供 ``detect_place``，于是搬运技能的第二步
    会如实回报"放置区通道未接入"，与实机没有地标时的行为一致。
    """

    name = "rendered-opencv"

    def __init__(self, bus: MockServoBus, x_true_cm: float, distance_cm: float,
                 noise_sigma: float = 0.0, blur: int = 0, brightness: float = 1.0) -> None:
        self.bus = bus
        self.x_true_cm = float(x_true_cm)
        self.distance_cm = float(distance_cm)
        self.noise_sigma = float(noise_sigma)
        self.blur = int(blur)
        self.brightness = float(brightness)
        self.pixels_per_cm = FRAME_FOCAL_PX / self.distance_cm
        self.size_px = max(4, int(round(TARGET_SIZE_CM * self.pixels_per_cm)))
        self.detector = OpenCVPerception(
            pixels_per_cm=self.pixels_per_cm,
            focal_px=FRAME_FOCAL_PX,
            object_size_cm=TARGET_SIZE_CM,
        )
        self.off_frame = False

    def yaw_deg(self) -> float:
        from atri.config import JOINTS

        left = self.bus.angles.get(JOINTS["left_hip_yaw"]["id"], 0.0)
        right = self.bus.angles.get(JOINTS["right_hip_yaw"]["id"], 0.0)
        return 0.5 * (left + right)

    def x_rel_cm(self) -> float:
        return self.x_true_cm - self.distance_cm * math.tan(math.radians(self.yaw_deg()))

    def grab(self) -> Any:
        x_rel = self.x_rel_cm()
        cx = FRAME_W / 2.0 + self.pixels_per_cm * x_rel
        self.off_frame = not (0 <= cx <= FRAME_W)
        patch = Patch(cx=cx, cy=FRAME_H / 2.0, size=self.size_px, bgr=RED_BGR)
        return make_frame([patch], noise_sigma=self.noise_sigma, blur=self.blur,
                          brightness=self.brightness)

    def detect_object(self, frame: Any = None) -> Any:
        img = self.grab() if frame is None else frame
        return self.detector.detect_object(frame=img)


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
    align_x_cm: Optional[float]
    steps: Optional[int]
    place_status: str
    reason: str = ""
    off_frame_any: bool = False


def run_image_in_loop(
    x_true_cm: float,
    distance_cm: float,
    variant: str = "代码默认",
    params: Optional[Dict[str, Any]] = None,
    **render: Any,
) -> LoopRow:
    """跑一次真搬运任务：真 CarrySkill + 真 Cerebellum + 合成图 + 真检测器。"""
    bus = MockServoBus()
    cerebellum = Cerebellum(servo_bus=bus, sleeper=lambda dt: None)
    perception = RenderedObjectPerception(bus, x_true_cm, distance_cm, **render)

    ctx = SkillContext(
        task_id="T-03",
        task_name="物品搬运",
        params=dict(params or {}),
        cerebellum=cerebellum,
        perception=perception,
        tts_engine=None,
    )
    outcome = CarrySkill().run(ctx)
    place = outcome.get("place") or {}
    return LoopRow(
        variant=variant,
        x_true_cm=x_true_cm,
        distance_cm=distance_cm,
        gain_cm_per_deg=round(distance_cm * math.tan(math.radians(1.0)), 4),
        fov_limit_cm=round(FOV_HALF_CM_AT(distance_cm), 2),
        status=str(outcome.get("status")),
        ok=str(outcome.get("status")) == "ok",
        iterations=int(outcome.get("iterations") or 0),
        align_x_cm=outcome.get("align_x_cm"),
        steps=outcome.get("steps"),
        place_status=str(place.get("status", "")),
        reason=str(outcome.get("reason") or ""),
        off_frame_any=perception.off_frame,
    )


def image_in_loop_scan() -> List[LoopRow]:
    """同一批场景跑两套参数：代码默认 vs 按针孔 gain 推荐值。"""
    rows: List[LoopRow] = []
    for distance_cm in (8.0, 12.0, 20.0):
        for x_true_cm in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0):
            rows.append(run_image_in_loop(x_true_cm, distance_cm, variant="代码默认"))
            rows.append(
                run_image_in_loop(
                    x_true_cm, distance_cm, variant="推荐参数", params=RECOMMENDED_PARAMS
                )
            )
    # 现实扰动（噪声 σ=16、模糊核 5、偏暗 0.9），都落在 A 段判据条件内
    for x_true_cm in (2.0, 4.0):
        rows.append(run_image_in_loop(
            x_true_cm, 12.0, variant="代码默认", noise_sigma=16.0, blur=5, brightness=0.9))
        rows.append(run_image_in_loop(
            x_true_cm, 12.0, variant="推荐参数", params=RECOMMENDED_PARAMS,
            noise_sigma=16.0, blur=5, brightness=0.9))
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
    """复算 ``skills/base.py::lateral_servo`` 的同一套迭代（一维几何，无图像）。

    这里刻意**不 import 技能层**：边界表要能在纯数学层跑几万次，且必须能独立
    核对技能层实现是否与之一致（``tests/test_carry_tuning.py`` 里有一条对照断言）。
    """
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
    """在给定参数下，"能在迭代上限内把偏差压到 ≤ 夹取容差" 的最大初始横向偏差（0.1cm 精度）。"""
    best: Optional[float] = None
    x = 0.2
    while x <= x0_cap:
        final, _iters, _converged = simulate_servo(x, **params)
        if abs(final) <= tolerance_cm:
            best = round(x, 1)
        x = round(x + 0.1, 2)
    return best


def boundary_table() -> Dict[str, Any]:
    """两族：针孔几何的 gain 随物距变化 vs 现有 Mock 的 gain(1.5)；再给 max_iters/step_gain 的影响。

    扫描上限 ``CAP_CM = 60``：超出它的偏差在桌面上已无意义（人形本体 40cm），
    表里显示 ``≥60`` 只表示"在这套参数下 60cm 以内都能纠"。
    """
    deadband = float(CARRY_DEFAULTS["deadband_cm"])
    tolerance = float(CARRY_DEFAULTS["grasp_tolerance_cm"])
    step_gain = float(CARRY_DEFAULTS["step_gain"])
    clamp = float(CARRY_DEFAULTS["step_clamp_deg"])
    max_iters = int(CARRY_DEFAULTS["max_iters"])

    cap = CAP_CM
    rows: List[Dict[str, Any]] = []
    for distance_cm in (6.0, 8.0, 12.0, 20.0, 40.0):
        gain = round(distance_cm * math.tan(math.radians(1.0)), 4)
        for iters in (3, 5, 8, 12, 20):
            rows.append({
                "gain_cm_per_deg": gain,
                "distance_cm": distance_cm,
                "max_iters": iters,
                "fov_half_cm": round(FOV_HALF_CM_AT(distance_cm), 2),
                "max_offset_cm": max_reachable_cm(
                    cap, tolerance, gain_cm_per_deg=gain, deadband_cm=deadband,
                    max_iters=iters, step_gain=step_gain, step_clamp_deg=clamp),
            })
    # 现有 Mock 的 gain（1.5）= 等价于"物距 86cm"，一并列出做对照
    mock_rows: List[Dict[str, Any]] = []
    for iters in (3, 5, 8, 12):
        mock_rows.append({
            "gain_cm_per_deg": 1.5,
            "max_iters": iters,
            "max_offset_cm": max_reachable_cm(
                cap, tolerance, gain_cm_per_deg=1.5, deadband_cm=deadband,
                max_iters=iters, step_gain=step_gain, step_clamp_deg=clamp),
        })
    # 步长增益的影响（gain 取 12cm 物距的针孔值）
    gain12 = round(12.0 * math.tan(math.radians(1.0)), 4)
    gain_rows: List[Dict[str, Any]] = []
    for sg in (0.3, 0.5, 0.8, 1.0, 1.5):
        for cl in (10.0, 20.0, 45.0):
            gain_rows.append({
                "step_gain": sg,
                "step_clamp_deg": cl,
                "max_offset_cm": max_reachable_cm(
                    cap, tolerance, gain_cm_per_deg=gain12, deadband_cm=deadband,
                    max_iters=max_iters, step_gain=sg, step_clamp_deg=cl),
            })
    recommended_rows: List[Dict[str, Any]] = []
    for distance_cm in (6.0, 8.0, 12.0, 20.0, 40.0):
        gain = round(distance_cm * math.tan(math.radians(1.0)), 4)
        fov = round(FOV_HALF_CM_AT(distance_cm), 2)
        default_reach = max_reachable_cm(
            cap, tolerance, gain_cm_per_deg=gain, deadband_cm=deadband,
            max_iters=max_iters, step_gain=step_gain, step_clamp_deg=clamp)
        rec_reach = max_reachable_cm(
            cap, tolerance, gain_cm_per_deg=gain, deadband_cm=deadband,
            max_iters=int(RECOMMENDED_PARAMS["max_iters"]),
            step_gain=float(RECOMMENDED_PARAMS["step_gain"]), step_clamp_deg=clamp)
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
            "deadband_cm": deadband, "grasp_tolerance_cm": tolerance,
            "step_gain": step_gain, "step_clamp_deg": clamp, "max_iters": max_iters,
            "gain_model": "gain = 物距 × tan(1°)，即相机像素当量/f；等效于针孔模型",
            "accept_model": "可纠正 = 在迭代上限内最终偏差 ≤ 夹取容差",
            "cap_cm": cap,
        },
        "by_distance": rows,
        "recommended": recommended_rows,
        "mock_gain_1p5": mock_rows,
        "step_gain_sweep_12cm": gain_rows,
    }


# ────────────────────────── 报告 ──────────────────────────


def _pct(hit: int, total: int) -> str:
    return f"{hit}/{total}（{100.0 * hit / total:.1f}%）" if total else "—"


def build_report(det_rows: List[DetectorRow], det_sum: Dict[str, Any],
                 loop_rows: List[LoopRow], bounds: Dict[str, Any]) -> str:
    lines: List[str] = []
    add = lines.append

    add("# T-03 物品搬运 · 方案与评测报告")
    add("")
    add("> 生成命令（本报告所有数字都由它一次跑出，可直接复跑核对）：")
    add("> ```")
    add("> .venv-face/bin/python software/atri/tools/carry_eval.py \\")
    add(">     --report design/handoff/T-03-搬运-方案与评测报告.md \\")
    add(">     --json design/results/t03_carry_eval.json")
    add("> ```")
    add(">")
    add("> **本报告测的是代码与几何，不是实物。** 没有样机、没有相机、没有夹爪，")
    add("> 因此这里没有、也不会有「抓取成功率」这类实机指标；")
    add("> 全部数字的适用范围写在 §1 与 §5，引用前请先读那两节。")
    add("")
    add("## 1. 这份评测是什么、不是什么")
    add("")
    add("| 段 | 测什么 | 用的真代码 | 数据来源 | 能写进材料吗 |")
    add("|---|---|---|---|---|")
    add("| A | 色块检测成功率 / 横向误差 | `perception/opencv.py::detect_object` | **程序合成图像**（cv2 画出来的） | 能，但必须写「合成图，非实机相机」 |")
    add("| B | 搬运闭环端到端能否收敛 | 真 `CarrySkill` + 真 `Cerebellum` + 真检测器 | 合成图 + 一维几何（`x_rel = x_true − D·tanθ`） | 能，但必须写「合成图 + 一维几何」 |")
    add("| C | 参数边界（可纠正多大偏差） | 与 `skills/base.py::lateral_servo` 同式复算 | 纯数学 | 能，这是**调参依据** |")
    add("")
    add("**不能**从本报告得出的结论：实机抓取成功率、夹爪能不能夹住、步态能不能走过去、")
    add("放置区在真实光照下能不能检出。这些都要实物，见 §5。")
    add("")
    add("## 2. A 段：色块检测（合成图，真检测器）")
    add("")
    add(f"- 判据条件内（干净画面、固定光照、无遮挡、噪σ≤16、模糊核≤9）："
        f"**{_pct(det_sum['criteria_found'], det_sum['criteria_total'])}** 检出")
    add(f"- 全扫描（含故意做坏的：偏暗、强噪、重模糊、遮挡）："
        f"**{_pct(det_sum['found'], det_sum['total'])}** 检出")
    if "criteria_max_abs_error_cm" in det_sum:
        add(f"- 判据条件内横向误差：最大 {det_sum['criteria_max_abs_error_cm']} cm、"
            f"平均 {det_sum['criteria_mean_abs_error_cm']} cm（像素当量 {PIXELS_PER_CM:g} px/cm 下的量化误差）")
    add(f"- 距离口径标记：{ '、'.join(det_sum['distance_sources']) }"
        "（无焦距时必须是 `uncalibrated`——它**不是**实测距离）")
    add("")
    add("| 组 | 场景 | 真值 x_cm | 检出 | 测得 x_cm | 误差 cm | 距离来源 | 备注 |")
    add("|---|---|---|---|---|---|---|---|")
    for row in det_rows:
        add(f"| {row.group} | {row.label} | {row.x_true_cm:+.1f} | "
            f"{'✅' if row.found else '❌'} | "
            f"{'—' if row.x_cm is None else f'{row.x_cm:+.2f}'} | "
            f"{'—' if row.error_cm is None else f'{row.error_cm:+.2f}'} | "
            f"{row.distance_source or '—'} | {row.note} |")
    add("")
    add("## 3. B 段：图像在环闭环（真技能 + 真检测器 + 合成图）")
    add("")
    add("模型假设（**这些假设本身就是未标定项**）：相机 320×240、水平视场 60° → 焦距")
    add(f"`f = {FRAME_FOCAL_PX:.1f} px`，像素当量 `ppcm = f / 物距`（有焦距 ⇒ 检测器距离")
    add("估算是 `calibrated` 口径）；目标 4cm 见方；身体转过 `yaw` 度后相对偏差")
    add("`x_rel = x_true − 物距·tan(yaw)`；成像 `cx = W/2 + ppcm·x_rel`，超出画面截断渲染；")
    add("并假设**髋偏航指令角 = 身体实际转角**（未标定，见未测项 C1/C2）。")
    add("")
    add(f"同一批场景跑两套参数：**代码默认**（`max_iters=5, step_gain=0.5`）与"
        f"**推荐参数**（`max_iters={RECOMMENDED_PARAMS['max_iters']}, "
        f"step_gain={RECOMMENDED_PARAMS['step_gain']}`，依据 §4 的边界表）。")
    add("")
    variants: Dict[str, List[LoopRow]] = {}
    for row in loop_rows:
        variants.setdefault(row.variant, []).append(row)
    add("| 参数组 | 成功 | 说明 |")
    add("|---|---|---|")
    for name, group in variants.items():
        ok_n = sum(1 for r in group if r.ok)
        add(f"| {name} | **{_pct(ok_n, len(group))}** | "
            f"{'代码里的设计值' if name == '代码默认' else '边界表推出的调参方向'} |")
    add("")
    add("失败原因分布（比成功率有用：失败都发生在哪一步）：")
    add("")
    add("| 参数组 | 失败原因 | 次数 |")
    add("|---|---|---|")
    for name, group in variants.items():
        reasons: Dict[str, int] = {}
        for row in group:
            if not row.ok:
                key = ("闭环后仍超夹取容差（不下发抓取）" if "夹取容差" in row.reason
                       else (row.reason or "其他"))
                reasons[key] = reasons.get(key, 0) + 1
        if not reasons:
            add(f"| {name} | （无失败） | 0 |")
        for key, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
            add(f"| {name} | {key} | {count} |")
    add("")
    add("逐场景明细（`出画` = 闭环过程中目标曾跑出视场，画面截断会让检出中心失真）：")
    add("")
    add("| 参数组 | 真值 x_cm | 物距 cm | gain cm/° | 视场半宽 cm | 结果 | 迭代 | 闭环后偏差 cm | 放置区 | 出画 |")
    add("|---|---|---|---|---|---|---|---|---|---|")
    for row in loop_rows:
        ok_text = "✅ ok" if row.ok else "❌ " + row.status
        x_text = "—" if row.align_x_cm is None else f"{row.align_x_cm:+.2f}"
        add(f"| {row.variant} | {row.x_true_cm:+.1f} | {row.distance_cm:g} | "
            f"{row.gain_cm_per_deg:g} | ±{row.fov_limit_cm:g} | "
            f"{ok_text} | {row.iterations} | {x_text} | "
            f"{row.place_status} | {'是' if row.off_frame_any else '否'} |")
    add("")
    add("`放置区 = channel-unavailable` 是**预期行为**：本段故意不给放置区通道（实机没地标时同理），")
    add("技能会如实回报「没有放置区感知通道」，而不是假装对准了。")
    add("")
    add("## 4. C 段：参数边界表（实物到手后照着这张表调）")
    add("")
    a = bounds["assumptions"]
    add(f"当前代码默认值：死区 {a['deadband_cm']:g} cm、夹取容差 {a['grasp_tolerance_cm']:g} cm、"
        f"步长增益 {a['step_gain']:g}、单轮钳位 {a['step_clamp_deg']:g}°、迭代上限 {a['max_iters']}。")
    add(f"gain 模型：{a['gain_model']}；判定模型：{a['accept_model']}。")
    add("")
    add("**「最大可纠正初始偏差」= 在这套参数下、迭代上限之内能把偏差压到 ≤ 夹取容差的最大 x。**")
    add("超出它的场景不会「凑合夹」：技能直接判失败、不下发抓取（见 §3 失败原因）。")
    add("")
    cap = float(a.get("cap_cm", 60.0))

    def cell(value: Optional[float]) -> str:
        if value is None:
            return "—"
        return f"≥{cap:g} cm" if value >= cap else f"{value:g} cm"

    add("| 物距 cm | gain cm/° | 视场半宽 cm | 迭代上限 3 | 5（现值） | 8 | 12 | 20 |")
    add("|---|---|---|---|---|---|---|---|")
    by_dist: Dict[float, Dict[int, Optional[float]]] = {}
    fov_of: Dict[float, float] = {}
    for row in bounds["by_distance"]:
        by_dist.setdefault(row["distance_cm"], {})[row["max_iters"]] = row["max_offset_cm"]
        fov_of[row["distance_cm"]] = row.get("fov_half_cm", float("nan"))
    for distance_cm, iters in by_dist.items():
        gain = next(r["gain_cm_per_deg"] for r in bounds["by_distance"]
                    if r["distance_cm"] == distance_cm)
        cells = " | ".join(cell(iters.get(k)) for k in (3, 5, 8, 12, 20))
        add(f"| {distance_cm:g} | {gain:g} | ±{fov_of[distance_cm]:g} | {cells} |")
    add("")
    add("⚠ **视场半宽是硬上限**：目标跑出画面就检不到（技能判失败），参数再好也纠不了。")
    add("上表的参数能力只有在「目标始终看得见」时才可用——所以实机还得考虑「先转过去看一眼」的搜索策略。")
    add("")
    add("对照：现有 Mock 用的 gain = 1.5 cm/°（等价物距 86 cm）：")
    add("")
    add("| gain cm/° | 迭代上限 | 最大可纠正偏差 |")
    add("|---|---|---|")
    for row in bounds["mock_gain_1p5"]:
        add(f"| {row['gain_cm_per_deg']} | {row['max_iters']} | {cell(row['max_offset_cm'])} |")
    add("")
    add("步长增益/钳位的影响（gain 取 12 cm 物距的针孔值）：")
    add("")
    add("| step_gain | 钳位 10° | 钳位 20° | 钳位 45° |")
    add("|---|---|---|---|")
    sweep: Dict[float, Dict[float, Optional[float]]] = {}
    for row in bounds["step_gain_sweep_12cm"]:
        sweep.setdefault(row["step_gain"], {})[row["step_clamp_deg"]] = row["max_offset_cm"]
    for sg, clamps in sweep.items():
        cells = " | ".join(cell(clamps.get(c)) for c in (10.0, 20.0, 45.0))
        add(f"| {sg:g} | {cells} |")
    add("")
    add("### 4.1 结论：这套参数该怎么调（数据来自上表，不是拍脑袋）")
    add("")
    add(f"推荐值取 `max_iters={RECOMMENDED_PARAMS['max_iters']}`、"
        f"`step_gain={RECOMMENDED_PARAMS['step_gain']}`：")
    add("")
    add("| 物距 cm | gain cm/° | 视场半宽 cm | 默认参数可纠正 | 推荐参数可纠正 | 是否覆盖整个视场 |")
    add("|---|---|---|---|---|---|")
    for row in bounds["recommended"]:
        add(f"| {row['distance_cm']:g} | {row['gain_cm_per_deg']:g} | ±{row['fov_half_cm']:g} | "
            f"{cell(row['default_reach_cm'])} | {cell(row['recommended_reach_cm'])} | "
            f"{'✅' if row['covers_fov'] else '❌'} |")
    add("")
    add("读法：**只要「推荐参数可纠正」≥「视场半宽」，就意味着「目标只要看得见，就能对准」**——")
    add("这是闭环在下层能做到的极限；再远的偏差属于「看不见」，要靠转头搜索而不是靠调参。")
    add("")
    add("⚠ 但这条推荐**不能直接上实机**：它建立在「髋偏航指令角 = 身体实际转角」这个未标定假设上。")
    add("实机第一步应当是量这个映射（发 10° 看真转了多少），把实测 gain 写进 `config/carry.json`，")
    add("再按上表复核 `max_iters` 够不够。")
    add("")
    add("## 5. 诚实缺口清单（这些没有测，测不了，或没接）")
    add("")
    add("| # | 缺口 | 为什么没测 | 怎么才能测 |")
    add("|---|---|---|---|")
    add("| 1 | **实机抓取成功率** | 没有样机、没有夹爪 | 样机 + 标定物，跑 N 次记成功率 |")
    add("| 2 | **真实相机上的色块检测** | 没有相机；A 段是程序合成图 | 打印色块卡 + 真相机，按同一批场景重跑本工具 |")
    add("| 3 | **像素当量 ppcm / 焦距未标定** | 没有相机内参 | 棋盘格标定 → 回填 `config/carry.json` 与本工具的 `--pixels-per-cm` |")
    add("| 4 | **髋偏航指令 → 身体实际转角**未标定 | 无位移/里程计 | 实机量：发 10° 看转了多少；写进 `config/odometry.json` |")
    add("| 5 | **步长 → 实际位移**未标定 | 同上 | 直走 N 步量距离 |")
    add("| 6 | **放置区地标方案未定** | 赛题没规定用不用地标 | 定了之后：真地标 + `detect_place` 标定 |")
    add("| 7 | **夹取/释放的机械是否夹得住** | 无实物 | 样机实测；`grasp/release` 目前是角度序列，力矩与摩擦未知 |")
    add("| 8 | Webots 控制器仍注入**静态** MockPerception | 仿真侧未接摄像头 | 在 Webots 里给机器人加 Camera + 接 `OpenCVPerception` |")
    add("")
    add("## 6. 与实物对接：改哪里、量什么")
    add("")
    add("1. **相机标定**后写 `software/atri/config/carry.json`：")
    add("   `step_gain`（≈ 像素当量 px/cm，即 f/D）、`deadband_cm`（夹爪能容忍多大偏差）。")
    add("2. **位移标定**后写 `config/odometry.json` 与 `step_length_cm`。")
    add("3. **不用改代码**：优先级是 任务卡 params > `config/carry.json` > 代码默认值；")
    add("   现场想临时换参数就写在任务卡里（`software/atri/task_cards/T-03_carry.json`）。")
    add("4. 多轮迭代不够（§4 表里「迭代上限」那几列）就加大 `max_iters` 或 `step_gain`；")
    add("   单轮转太多会超调，`step_clamp_deg` 是刹车。")
    add("")
    add("---")
    add("")
    add(f"报告由 `tools/carry_eval.py` 生成；场景表 `design/packages/scenario_set.json`（S-03）")
    add("只规定了变化轴，本工具按 T-01/T-02 同一套做法把轴落成**可复跑的具体场景**。")
    return "\n".join(lines) + "\n"


# ────────────────────────── 入口 ──────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="T-03 物品搬运评测（合成图 + 闭环 + 边界表）")
    parser.add_argument("--report", default=None, help="markdown 报告输出路径")
    parser.add_argument("--json", default=None, help="机器可读结果输出路径")
    parser.add_argument("--no-loop", action="store_true", help="跳过 B 段（图像在环，最慢的一段）")
    args = parser.parse_args(argv)

    print("=" * 64)
    print("T-03 搬运评测：A 色块检测 / B 图像在环闭环 / C 参数边界")
    print("=" * 64)

    t = load_tuning("carry", CARRY_DEFAULTS, warn=None)
    print(f"参数出处：{t.provenance()}")
    for message in t.warnings:
        print(f"  ⚠ {message}")

    det_rows, det_sum = detector_scan()
    print(f"[A] 检出 判据条件 {det_sum['criteria_found']}/{det_sum['criteria_total']}、"
          f"全扫描 {det_sum['found']}/{det_sum['total']}")

    loop_rows: List[LoopRow] = [] if args.no_loop else image_in_loop_scan()
    if loop_rows:
        grouped: Dict[str, List[LoopRow]] = {}
        for row in loop_rows:
            grouped.setdefault(row.variant, []).append(row)
        parts = [
            f"{name} {sum(1 for r in group if r.ok)}/{len(group)}"
            for name, group in grouped.items()
        ]
        print(f"[B] 图像在环：成功 " + "、".join(parts))

    bounds = boundary_table()
    print("[C] 参数边界表已算出（§4）")

    payload = {
        "meta": {
            "tool": "tools/carry_eval.py",
            "task": "T-03",
            "generated_note": "合成图 + 一维几何 + 真检测器/真技能；不是实机指标",
            "pixels_per_cm": PIXELS_PER_CM,
            "frame": [FRAME_W, FRAME_H],
            "nominal_focal_px": round(NOMINAL_FOCAL_PX, 2),
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
            },
            "rows": [row.__dict__ for row in loop_rows],
        },
        "boundary": bounds,
    }

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON → {out}")
    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(build_report(det_rows, det_sum, loop_rows, bounds), encoding="utf-8")
        print(f"报告 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
