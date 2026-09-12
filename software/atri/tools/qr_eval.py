#!/usr/bin/env python3
"""T-02 二维码循迹评测：识别鲁棒性 + 指令回放正确率。

产出两张表要用的真实数字（对应 ``docs/research/项目文档/BOM与阶段性指标.md``）：

| 指标 | 目标 | 本工具怎么量 |
|---|---|---|
| 二维码识别成功率 | ≥ 90%（固定光照、≤1 m） | 真二维码渲染到场景里，加各种畸变后真解码，统计成功率 |
| 二维码 JSON 指令执行正确率 | ≥ 95%（10 组指令回放） | 编码 → 解码 → 解析 → **真执行**，比对逐段动作与参数 |

## 为什么按"二维码像素宽度"扫，而不是直接按米

解码器只关心码在画面里占多少像素；"多少米"要经过相机内参换算，而内参是**我们假设的**。
所以主扫描轴用像素宽度（可复现、无需标定），另外给一张**名义距离对照表**，
把相机型号/视场角/打印尺寸都写明，并标注为**名义值**。

## 三个解码器都测

``opencv`` / ``aruco`` / ``wechat`` 各跑同一批图，用成功率决定主用哪个——
和 T-01 里 YuNet 对 Haar 的对照是同一套做法。WeChat 模型缺失时该行自动跳过并注明。

用法：
    .venv-face/bin/python software/atri/tools/qr_eval.py \\
        --report design/handoff/T-02-二维码识别鲁棒性报告.md \\
        --json design/results/t02_qr_eval.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# tools/ 位于 <repo>/software/atri/tools/ 下：上溯 3 层才是仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
SOFTWARE_ROOT = REPO_ROOT / "software" / "atri"
sys.path.insert(0, str(SOFTWARE_ROOT))

from atri.config import MAX_STEPS, MAX_TURN_DEG  # noqa: E402
from atri.odometry import NominalOdometry  # noqa: E402
from atri.path_plan import Path as QrPath  # noqa: E402
from atri.path_plan import parse_payload  # noqa: E402
from atri.qrgen import QRCodeGenerator  # noqa: E402

# 名义相机假设：1280×720、水平视场 60°。仅用于把像素宽度换算成"大概多少厘米"。
CAMERA_WIDTH_PX = 1280
CAMERA_HEIGHT_PX = 720
CAMERA_HFOV_DEG = 60.0
NOMINAL_FOCAL_PX = (CAMERA_WIDTH_PX / 2.0) / math.tan(math.radians(CAMERA_HFOV_DEG / 2.0))
# 现场二维码卡片的打印边长假设（cm）。真实尺寸应由赛题/队伍定，这里是名义值。
NOMINAL_CARD_CM = 6.0

DEFAULT_ECC = "M"
DEFAULT_PATHS: List[List[Dict[str, Any]]] = [
    [{"action": "walk", "steps": 3}],
    [{"action": "walk", "steps": 3}, {"action": "turn", "deg": 90}],
    [{"action": "turn", "deg": 45}, {"action": "walk", "steps": 2}],
    [{"action": "walk", "steps": 2}, {"action": "turn", "deg": -90}, {"action": "walk", "steps": 2}],
    [{"action": "walk", "steps": 5}],
    [{"action": "turn", "deg": 90}, {"action": "walk", "steps": 4}, {"action": "turn", "deg": -45}],
    [{"action": "walk", "steps": 1}, {"action": "walk", "steps": 1}, {"action": "walk", "steps": 1}],
    [{"action": "turn", "deg": 135}, {"action": "walk", "steps": 3}],
    [{"action": "walk", "steps": 4}, {"action": "turn", "deg": 30}, {"action": "walk", "steps": 1}],
    [{"action": "dance", "bars": 1}, {"action": "walk", "steps": 2}],
]


# ────────────────────────── 渲染 ──────────────────────────


@dataclass
class Scenario:
    label: str
    group: str
    frame: Any
    note: str = ""
    level: Optional[float] = None   # 该组扰动的强度（尺寸=px，旋转=度，模糊=k，…）
    in_target: bool = False         # 是否落在 BOM 判据条件内（固定光照、≤1 m）


def make_card(payload: str, ecc: str = DEFAULT_ECC, box_size: int = 10, border: int = 4) -> Any:
    """生成二维码"卡片"图（白底黑码），返回 BGR 数组。"""
    import cv2
    import qrcode

    generator = QRCodeGenerator(error_correction=ecc, box_size=box_size, border=border)
    tmp = REPO_ROOT / "本地数据" / "_qr_tmp.png"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    generator.generate_payload(payload, tmp)
    card = cv2.imread(str(tmp), cv2.IMREAD_COLOR)
    tmp.unlink(missing_ok=True)
    if card is None:
        raise RuntimeError("二维码卡片渲染失败")
    return card


def place_on_scene(card: Any, target_width_px: int, canvas: Tuple[int, int] = (CAMERA_HEIGHT_PX, CAMERA_WIDTH_PX)) -> Any:
    """把卡片缩放后贴到场景中央（模拟相机看到的画面）。"""
    import cv2

    h, w = canvas
    scale = target_width_px / float(card.shape[1])
    resized = cv2.resize(card, (target_width_px, max(1, int(card.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    frame = np.full((h, w, 3), 210, dtype=np.uint8)  # 浅灰地面
    y0 = (h - resized.shape[0]) // 2
    x0 = (w - resized.shape[1]) // 2
    frame[y0:y0 + resized.shape[0], x0:x0 + resized.shape[1]] = resized
    return frame


def _rotate(frame: Any, deg: float) -> Any:
    import cv2

    h, w = frame.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(frame, matrix, (w, h), borderValue=(210, 210, 210))


def _perspective(frame: Any, tilt_deg: float) -> Any:
    """模拟相机斜视二维码：把上边压窄。"""
    import cv2

    h, w = frame.shape[:2]
    shrink = w * 0.5 * math.sin(math.radians(tilt_deg))
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[shrink, 0], [w - shrink, 0], [w, h], [0, h]])
    matrix = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(frame, matrix, (w, h), borderValue=(210, 210, 210))


def _blur(frame: Any, ksize: int) -> Any:
    import cv2

    if ksize <= 0:
        return frame
    k = ksize if ksize % 2 == 1 else ksize + 1
    return cv2.GaussianBlur(frame, (k, k), 0)


def _brightness(frame: Any, factor: float) -> Any:
    out = frame.astype(np.float32) * factor
    return np.clip(out, 0, 255).astype(np.uint8)


def _noise(frame: Any, sigma: float, seed: int = 0) -> Any:
    if sigma <= 0:
        return frame
    rng = np.random.default_rng(seed)
    out = frame.astype(np.float32) + rng.normal(0, sigma, frame.shape)
    return np.clip(out, 0, 255).astype(np.uint8)


def nominal_distance_cm(width_px: int, card_cm: float = NOMINAL_CARD_CM) -> float:
    """名义距离： ``d = f·S / w``。**基于假设的相机内参，不是实测**。"""
    if width_px <= 0:
        return float("inf")
    return NOMINAL_FOCAL_PX * card_cm / float(width_px)


def build_scenarios(payload: str, ecc: str = DEFAULT_ECC) -> List[Scenario]:
    """一组"基线 + 单一扰动"的场景。一次只动一个变量，便于归因。"""
    card = make_card(payload, ecc=ecc)
    base = place_on_scene(card, 250)
    out: List[Scenario] = [Scenario("基线（250 px / 无扰动）", "baseline", base, level=250.0, in_target=True)]

    for width in (150, 100, 80, 60, 45):
        out.append(
            Scenario(
                f"尺寸 {width} px",
                "size",
                place_on_scene(card, width),
                note=f"名义 {nominal_distance_cm(width):.0f} cm",
                level=float(width),
                # 判据写的是「固定光照、≤1 m」：按名义距离换算，≥80 px 才落在 1 m 以内
                in_target=width >= 80,
            )
        )
    for deg in (10, 20, 30, 45, 60):
        out.append(Scenario(f"旋转 {deg}°", "rotation", _rotate(base, deg), level=float(deg)))
    for tilt in (20, 40, 55):
        out.append(Scenario(f"倾斜（透视）{tilt}°", "perspective", _perspective(base, tilt), level=float(tilt)))
    for k in (3, 5, 7, 9):
        out.append(Scenario(f"模糊 k={k}", "blur", _blur(base, k), level=float(k)))
    for factor in (0.4, 0.6, 0.8, 1.3):
        # 「固定光照」按正常照明理解：×0.8 与 ×1.3 落在判据内，×0.4/×0.6 属暗光扰动
        out.append(
            Scenario(
                f"亮度 ×{factor}", "brightness", _brightness(base, factor),
                level=float(factor), in_target=factor >= 0.8,
            )
        )
    for sigma in (5, 15, 30):
        out.append(Scenario(f"噪声 σ={sigma}", "noise", _noise(base, sigma), level=float(sigma)))
    # 组合场景：现场最可能遇到的样子
    hard = _noise(_blur(_rotate(place_on_scene(card, 100), 20), 3), 10)
    out.append(Scenario("组合：100 px + 旋转 20° + 模糊 3 + 噪声 10", "combined", hard))
    hard2 = _perspective(_blur(place_on_scene(card, 80), 5), 40)
    out.append(Scenario("组合：80 px + 透视 40° + 模糊 5", "combined", hard2))
    return out


# ────────────────────────── 评测 ──────────────────────────


@dataclass
class DecoderScore:
    decoder: str
    available: bool
    reason: str = ""
    hits: Dict[str, bool] = field(default_factory=dict)
    in_target: Dict[str, bool] = field(default_factory=dict)   # 仅判据条件内的场景
    total_ms: float = 0.0

    @property
    def success(self) -> int:
        return sum(1 for v in self.hits.values() if v)

    @property
    def count(self) -> int:
        return len(self.hits)

    @property
    def rate(self) -> float:
        return self.success / self.count if self.count else 0.0

    @property
    def target_success(self) -> int:
        return sum(1 for v in self.in_target.values() if v)

    @property
    def target_count(self) -> int:
        return len(self.in_target)

    @property
    def target_rate(self) -> float:
        return self.target_success / self.target_count if self.target_count else 0.0


def evaluate_decoders(
    scenarios: Sequence[Scenario], expected: str, model_dir: Path, names: Sequence[str]
) -> List[DecoderScore]:
    from atri.perception.qr import build_qr_decoder

    scores: List[DecoderScore] = []
    for name in names:
        kwargs = {"model_dir": model_dir} if name == "wechat" else {}
        decoder = build_qr_decoder(name, **kwargs)
        ok, reason = decoder.available()
        score = DecoderScore(decoder=name, available=ok, reason=reason)
        if not ok:
            scores.append(score)
            continue
        for scenario in scenarios:
            if scenario.group == "baseline" or True:
                start = time.perf_counter()
                result = decoder.decode(scenario.frame)
                score.total_ms += (time.perf_counter() - start) * 1000.0
            hit = bool(result.found and result.data == expected)
            score.hits[scenario.label] = hit
            if scenario.in_target:
                score.in_target[scenario.label] = hit
        scores.append(score)
    return scores


@dataclass
class ReplayResult:
    cases: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def correct(self) -> int:
        return sum(1 for c in self.cases if c["matched"])

    @property
    def rate(self) -> float:
        return self.correct / len(self.cases) if self.cases else 0.0


def evaluate_replay(model_dir: Path, decoder_name: str = "opencv") -> ReplayResult:
    """10 组指令回放：编码 → 解码 → 解析 → **真执行**，比对逐段动作与参数。"""
    from atri.cerebellum import Cerebellum, MockServoBus
    from atri.perception.qr import build_qr_decoder
    from atri.skills.base import SkillContext
    from atri.skills.qr import QRCodeSkill
    from atri.voice import MockTTS

    kwargs = {"model_dir": model_dir} if decoder_name == "wechat" else {}
    decoder = build_qr_decoder(decoder_name, **kwargs)
    skill = QRCodeSkill()
    result = ReplayResult()

    for index, segments in enumerate(DEFAULT_PATHS, 1):
        path = parse_payload({"path": segments})
        card = make_card(path.to_json())
        frame = place_on_scene(card, 250)

        decoded = decoder.decode(frame)
        record: Dict[str, Any] = {
            "index": index,
            "intended": segments,
            "decoded_ok": decoded.found,
            "payload_matched": False,
            "executed": None,
            "matched": False,
        }
        if not decoded.found:
            result.cases.append(record)
            continue
        try:
            parsed = parse_payload(decoded.data)
        except Exception as exc:
            record["error"] = f"解析失败: {exc}"
            result.cases.append(record)
            continue
        # 规范化后逐段比对：parse_payload 会把 deg 统一成 float、补齐默认值，
        # 所以两边都过一遍解析再比，避免 90 与 90.0 这种假差异。
        intended_norm = [seg.to_dict() for seg in path.segments]
        decoded_norm = [seg.to_dict() for seg in parsed.segments]
        record["payload_matched"] = decoded_norm == intended_norm

        bus = MockServoBus()
        cerebellum = Cerebellum(servo_bus=bus, sleeper=lambda dt: None)
        ctx = SkillContext(
            task_id="T-02",
            task_name="二维码循迹",
            params={},
            cerebellum=cerebellum,
            tts_engine=MockTTS(),
            gait={},
        )
        outcome = skill.run(
            _with_observation(ctx, {"qr": {"found": True, "payload": decoded.data}})
        )
        executed = [
            {"action": seg.get("action"), "status": seg.get("status")}
            for seg in outcome.get("segments", [])
        ]
        record["executed"] = executed
        record["executed_segments"] = decoded_norm
        record["matched"] = (
            record["payload_matched"]
            and outcome.get("status") == "ok"
            and len(executed) == len(intended_norm)
            and all(seg.get("status") == "ok" for seg in executed)
            and [seg.get("action") for seg in executed] == [seg["action"] for seg in intended_norm]
        )
        result.cases.append(record)

    return result


def _with_observation(ctx: Any, observation: Dict[str, Any]) -> Any:
    ctx.observation = observation
    return ctx


# ────────────────────────── 报告 ──────────────────────────


def _label_of(scenarios: Sequence[Scenario], group: str, level: float) -> Optional[str]:
    """按 (扰动组, 档位) 反查场景标签，供耐受边界表使用。"""
    for scenario in scenarios:
        if scenario.group == group and scenario.level is not None and abs(scenario.level - level) < 1e-9:
            return scenario.label
    return None


def render_report(
    decoder_scores: Sequence[DecoderScore],
    scenarios: Sequence[Scenario],
    replay: ReplayResult,
    payload_bytes: int,
    ecc: str,
    card_info: Dict[str, Any],
    model_dir: Path,
    platform_info: Optional[Dict[str, str]] = None,
) -> str:
    def pct(x: float) -> str:
        return f"{x * 100:.1f}%"

    best = max((s for s in decoder_scores if s.available), key=lambda s: s.rate, default=None)

    lines: List[str] = []
    lines.append("# T-02 二维码循迹 · 识别鲁棒性实测报告")
    lines.append("")
    lines.append("> 由 `software/atri/tools/qr_eval.py` 自动生成，**数字全部本机跑出**，未做手工润色。")
    lines.append("> 方案：`design/handoff/T-02-二维码循迹-方案.md`")
    lines.append("")
    lines.append("## 0. 复现命令")
    lines.append("")
    lines.append("```bash")
    lines.append(" ".join(sys.argv))
    lines.append("```")
    lines.append("")
    lines.append("## 1. 被测对象")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    for key, value in (platform_info or {}).items():
        lines.append(f"| {key} | {value} |")
    lines.append(f"| 测试 payload | 路径格式（`atri.path.v1`），{payload_bytes} 字节 |")
    lines.append(f"| 纠错级别 | {ecc} |")
    lines.append(f"| 二维码版本 / 模块数 | {card_info.get('version')} / {card_info.get('modules')} |")
    lines.append(f"| 卡片像素尺寸 | {card_info.get('image_px')} px（box_size={card_info.get('box_size')}）|")
    lines.append(f"| 场景画布 | {CAMERA_WIDTH_PX}×{CAMERA_HEIGHT_PX}（模拟相机画面）|")
    lines.append(f"| 名义相机 | 水平视场 {CAMERA_HFOV_DEG:g}°，f≈{NOMINAL_FOCAL_PX:.0f} px |")
    lines.append(f"| 名义卡片边长 | {NOMINAL_CARD_CM:g} cm |")
    lines.append("")
    lines.append("## 2. 识别成功率（按解码器）")
    lines.append("")
    lines.append("| 解码器 | 可用 | 全扫描成功率 | 判据子集成功率 | 成功/总数 | 平均单帧耗时 | 备注 |")
    lines.append("|---|---|---|---|---|---|---|")
    for score in decoder_scores:
        if not score.available:
            lines.append(f"| {score.decoder} | ❌ | — | — | — | — | {score.reason[:60]} |")
            continue
        mean_ms = score.total_ms / score.count if score.count else 0.0
        lines.append(
            f"| {score.decoder} | ✅ | {pct(score.rate)} | {pct(score.target_rate)} | "
            f"{score.success}/{score.count} | {mean_ms:.1f} ms | |"
        )
    lines.append("")
    if best is not None:
        lines.append(f"**主用解码器：`{best.decoder}`**（本次扫描中成功率最高：{pct(best.rate)}）。")
    lines.append("")

    lines.append("## 3. 逐场景明细")
    lines.append("")
    available = [s for s in decoder_scores if s.available]
    header = "| 场景 | 说明 | " + " | ".join(s.decoder for s in available) + " |"
    lines.append(header)
    lines.append("|---|---|" + "---|" * len(available))
    for scenario in scenarios:
        cells = []
        for score in available:
            hit = score.hits.get(scenario.label)
            cells.append("—" if hit is None else ("✅" if hit else "❌"))
        lines.append(f"| {scenario.label} | {scenario.note} | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("### 3.1 判据条件子集（BOM 写的是「固定光照、≤ 1 m」）")
    lines.append("")
    lines.append("全扫描里包含明显超出判据条件的极端扰动（45 px 的码、55° 斜视、暗光 ×0.4、模糊 k=9）。")
    lines.append("下表按 BOM 的原话**只取落在判据条件内的场景**，规则写明如下、可复核：")
    lines.append("")
    lines.append("- **固定光照** → 只算亮度 ×0.8 与 ×1.3（×0.4/×0.6 属暗光，排除）")
    lines.append("- **≤ 1 m 距离** → 只算名义距离 ≤1 m 的尺寸档（码宽 ≥80 px；按 §4 的名义换算）")
    lines.append("- 其余扰动（旋转 / 透视 / 模糊 / 噪声 / 组合）不计入该子集")
    lines.append("")
    lines.append("| 解码器 | 判据子集成功率 | 成功/总数 | 目标 ≥90% |")
    lines.append("|---|---|---|---|")
    for score in decoder_scores:
        if not score.available:
            continue
        mark = "✅" if score.target_rate >= 0.9 else "❌"
        lines.append(
            f"| {score.decoder} | {pct(score.target_rate)} | "
            f"{score.target_success}/{score.target_count} | {mark} |"
        )
    lines.append("")

    lines.append("### 3.2 各扰动的耐受边界（仍能解出的最严档位）")
    lines.append("")
    lines.append("| 扰动 | 含义 | " + " | ".join(x.decoder for x in decoder_scores if x.available) + " |")
    lines.append("|---|---|" + "---|" * len([x for x in decoder_scores if x.available]))
    boundaries = [
        ("size", "**最小**可解码宽（px）", "min"),
        ("rotation", "最大可解旋转（°）", "max"),
        ("perspective", "最大可解透视倾角（°）", "max"),
        ("blur", "最大可解高斯模糊（k）", "max"),
        ("noise", "最大可解噪声（σ）", "max"),
    ]
    for group, desc, mode in boundaries:
        cells = []
        for score in decoder_scores:
            if not score.available:
                continue
            levels = [sc.level for sc in scenarios if sc.group == group and sc.level is not None]
            passing = [lv for lv in levels if score.hits.get(_label_of(scenarios, group, lv))]
            if not passing:
                cells.append("全部失败")
            elif mode == "min":
                cells.append(f"{min(passing):.0f}")
            else:
                cells.append(f"{max(passing):.0f}")
        lines.append(f"| {group} | {desc} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("> 「全部失败」= 该扰动下所有档位都解不出。亮度组不是单调的（偏离 ×1.0 越远越难），不列入本表。")
    lines.append("")

    lines.append("## 4. 名义距离对照（**基于假设的相机内参，不是实测**）")
    lines.append("")
    lines.append(f"按 `d = f·S / w`，f≈{NOMINAL_FOCAL_PX:.0f} px（{CAMERA_WIDTH_PX}×{CAMERA_HEIGHT_PX} / HFOV {CAMERA_HFOV_DEG:g}°），"
                 f"卡片边长 {NOMINAL_CARD_CM:g} cm：")
    lines.append("")
    lines.append("| 码宽像素 | 名义距离 |")
    lines.append("|---|---|")
    for width in (250, 150, 100, 80, 60, 45):
        lines.append(f"| {width} px | {nominal_distance_cm(width):.0f} cm |")
    lines.append("")
    lines.append("> ⚠️ 现场相机型号、视场角、卡片实际尺寸都会让这张表偏移。")
    lines.append("> 它只用来把\"像素宽度\"翻译成\"大概多远\"，**不能当作实测距离指标**。")
    lines.append("")

    lines.append("## 5. 指令执行正确率（10 组指令回放）")
    lines.append("")
    lines.append("协议：生成路径二维码 → **真解码** → 解析 → **真执行**（MockServoBus + 真小脑层），")
    lines.append("比对逐段动作与参数是否与预期完全一致。")
    lines.append("")
    lines.append("| 指标 | 实测 | 目标（BOM与阶段性指标.md） | 判定 |")
    lines.append("|---|---|---|---|")
    ok = "✅" if replay.rate >= 0.95 else "❌"
    lines.append(
        f"| 二维码 JSON 指令执行正确率 | {pct(replay.rate)}（{replay.correct}/{len(replay.cases)}）"
        f" | ≥95% | {ok} |"
    )
    lines.append("")
    lines.append("| # | 预期路径 | 解出 payload | 执行段序列 | 判定 |")
    lines.append("|---|---|---|---|---|")
    for case in replay.cases:
        intended = " → ".join(
            f"{s['action']}({','.join(f'{k}={v}' for k, v in s.items() if k != 'action')})"
            for s in case["intended"]
        )
        # 用解析后的段（含参数）渲染执行序列；executed 只带动作与状态
        exec_segments = case.get("executed_segments") or []
        exec_text = " → ".join(
            f"{seg['action']}({','.join(f'{k}={v}' for k, v in seg.items() if k != 'action')})"
            for seg in exec_segments
        ) or "—"
        lines.append(
            f"| {case['index']} | {intended} | {'✅' if case['payload_matched'] else '❌'} | "
            f"{exec_text} | {'✅' if case['matched'] else '❌'} |"
        )
    lines.append("")

    lines.append("## 6. 口径声明（不可省）")
    lines.append("")
    lines.append("- 本报告量的是**识别**：图像里的二维码能否被解出并与原文完全一致（逐字节比对）。")
    lines.append("- **到位误差（S-02 的 `path_error_mm_max: 50`）未测**：小脑层没有位移/里程计，")
    lines.append("  路径终点只有标称值（`atri.odometry`，标注 `nominal-uncalibrated`）。")
    lines.append("- 场景畸变是**程序合成**的，不是真实相机拍的：真实反光、运动模糊、")
    lines.append("  打印质量、相机噪声分布都比合成图更复杂。本报告**不能替代实机联调**。")
    lines.append("- 名义距离表基于假设的相机内参（§4），不是实测。")
    lines.append("")
    lines.append(f"## 7. 模型目录")
    lines.append("")
    lines.append(f"`{model_dir}`（WeChatQRCode 四个文件共约 1 MB；缺失则该行标 ❌ 并给出原因）")
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="T-02 二维码识别鲁棒性评测")
    parser.add_argument("--report", default=None, help="markdown 报告输出路径")
    parser.add_argument("--json", default=None, help="机器可读结果输出路径")
    parser.add_argument("--models", default=str(REPO_ROOT / "models"), help="模型根目录")
    parser.add_argument("--ecc", default=DEFAULT_ECC, choices=["L", "M", "Q", "H"])
    parser.add_argument("--decoders", default="opencv,aruco,wechat", help="逗号分隔的解码器名单")
    parser.add_argument("--only-decoder", default=None, help="只跑指定解码器（回放用）")
    args = parser.parse_args(argv)

    model_dir = Path(args.models) / "wechat_qrcode"
    names = [n.strip() for n in args.decoders.split(",") if n.strip()]

    payload_path = parse_payload({"path": DEFAULT_PATHS[1]})
    expected = payload_path.to_json()
    print(f"测试 payload: {expected}")
    print(f"  字节数 {len(expected.encode('utf-8'))} | 纠错 {args.ecc}")

    # 生成一次以取得容量信息（版本 / 模块数 / 像素尺寸）
    gen = QRCodeGenerator(error_correction=args.ecc)
    tmp = REPO_ROOT / "本地数据" / "_qr_info.png"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    gen.generate_payload(expected, tmp)
    card_info = gen.last_info
    tmp.unlink(missing_ok=True)

    scenarios = build_scenarios(expected, ecc=args.ecc)
    print(f"场景数: {len(scenarios)}")

    print("评测解码器…")
    scores = evaluate_decoders(scenarios, expected, model_dir, names)
    for score in scores:
        if score.available:
            print(f"  {score.decoder:8s} 成功率 {score.rate*100:.1f}%  ({score.success}/{score.count})")
        else:
            print(f"  {score.decoder:8s} 不可用: {score.reason[:70]}")

    replay_decoder = args.only_decoder or next(
        (s.decoder for s in sorted((x for x in scores if x.available), key=lambda x: -x.rate)), "opencv"
    )
    print(f"指令回放（解码器 {replay_decoder}）…")
    replay = evaluate_replay(model_dir, replay_decoder)
    print(f"  执行正确率 {replay.rate*100:.1f}%  ({replay.correct}/{len(replay.cases)})")

    import platform as _platform

    import cv2 as _cv2

    platform_info = {
        "开发机": f"{_platform.system()} {_platform.machine()} / Python {_platform.python_version()}",
        "OpenCV": _cv2.__version__,
        "numpy": np.__version__,
        "目标平台": "树莓派 4B（**未实测**，本报告数字与之无关）",
    }
    report = render_report(
        scores, scenarios, replay, len(expected.encode("utf-8")), args.ecc, card_info,
        model_dir, platform_info,
    )

    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"报告已写入: {out}")
    if args.json:
        out_json = Path(args.json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(
            json.dumps(
                {
                    "platform": platform_info,
                    "payload_bytes": len(expected.encode("utf-8")),
                    "ecc": args.ecc,
                    "card": card_info,
                    "scenarios": [
                        {"label": s.label, "group": s.group, "note": s.note} for s in scenarios
                    ],
                    "decoders": [
                        {
                            "decoder": s.decoder,
                            "available": s.available,
                            "reason": s.reason,
                            "success": s.success,
                            "count": s.count,
                            "rate": round(s.rate, 4),
                            "hits": s.hits,
                        }
                        for s in scores
                    ],
                    "replay": {"rate": round(replay.rate, 4), "cases": replay.cases},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"JSON 已写入: {out_json}")
    if not args.report and not args.json:
        print(report)

    best_rate = max((s.rate for s in scores if s.available), default=0.0)
    return 0 if (best_rate >= 0.9 and replay.rate >= 0.95) else 2


if __name__ == "__main__":
    raise SystemExit(main())
