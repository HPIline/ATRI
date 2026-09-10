#!/usr/bin/env python3
"""A.T.R.I. 设计数据包 → 仿真运行器。

纯标准库实现，无第三方依赖。产出 JSON / CSV / SVG 结果。

用法：
    python3 design/run_sim.py --list
    python3 design/run_sim.py --scenario S-03-carry
    python3 design/run_sim.py --all --episodes 10
    python3 design/run_sim.py --sweep dropout

重要声明
--------
本脚本执行的是**运动学 + 规则控制器层面的仿真**，不是刚体动力学仿真。
它验证的是：关节限位可达性、视觉伺服收敛性、舵机非理想特性影响、
以及域随机化下的成功率趋势。

它**不**验证：双足行走的物理稳定性（需要 Webots / PyBullet 等刚体引擎）。
所有输出必须标注为"设计阶段仿真结果"，不得当作实机实测数据。
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "软件" / "atri"))

from atri.config import JOINTS, GROUP_DOF  # noqa: E402
from realistic_sim import (  # noqa: E402
    NoisyPerception,
    RealisticServoBus,
    load_package,
    sample_randomization,
)

RESULTS_DIR = HERE / "results"
FIGURES_DIR = HERE / "figures"

# 视觉伺服默认参数
SERVO_DEFAULTS = {
    "max_iter": 8,
    "converged_tol_cm": 1.0,
    "gain": 0.5,
    "max_step_cm": 4.0,
    "oscillation_window": 3,
    "search_steps": 2,
}


# --------------------------------------------------------------------------
# 视觉伺服闭环
# --------------------------------------------------------------------------
def servo_loop(
    perception: NoisyPerception,
    target_x_cm: float,
    gain: float = 0.5,
    tol_cm: float = 1.0,
    max_iter: int = 8,
    max_step_cm: float = 4.0,
    seed: int = 0,
) -> Dict[str, Any]:
    """迭代视觉伺服：感知 -> 算误差 -> 限幅微调 -> 再感知。

    返回每轮误差历史与收敛状态。

    这里模拟的是"机器人朝向微调后重新观测目标"的过程：
    机器人位置越接近目标，观测到的横向偏移越小。
    """
    rng = random.Random(seed)
    robot_x_cm = 0.0          # 机器人当前位置
    history: List[float] = []
    lost_recoveries = 0
    adapted_gain = gain

    for it in range(max_iter):
        # 真实相对偏移
        true_offset = target_x_cm - robot_x_cm
        perception.set_ball_position(x_cm=true_offset, distance_cm=12.0)
        obs = perception.detect_ball().data

        if not obs.get("found", True):
            # 目标丢失：执行搜索（模拟转头扫描）
            lost_recoveries += 1
            robot_x_cm += rng.uniform(-0.5, 0.5)
            history.append(float("nan"))
            if lost_recoveries > SERVO_DEFAULTS["search_steps"]:
                return {
                    "converged": False,
                    "reason": "target_lost",
                    "iterations": it + 1,
                    "history": history,
                    "final_error_cm": None,
                    "lost_recoveries": lost_recoveries,
                }
            continue

        err = float(obs.get("x_cm", 0.0))
        history.append(round(err, 4))

        if abs(err) < tol_cm:
            return {
                "converged": True,
                "reason": "tolerance_met",
                "iterations": it + 1,
                "history": history,
                "final_error_cm": round(err, 4),
                "lost_recoveries": lost_recoveries,
                "final_gain": round(adapted_gain, 4),
            }

        # 振荡检测：误差反复变大则降低增益
        if len(history) >= 3:
            recent = [h for h in history[-3:] if not math.isnan(h)]
            if len(recent) == 3 and abs(recent[2]) > abs(recent[1]) > abs(recent[0]):
                adapted_gain *= 0.5

        # 限幅微调：步长随误差衰减，防止过冲振荡
        step = max(-max_step_cm, min(max_step_cm, adapted_gain * err))
        robot_x_cm += step

    return {
        "converged": False,
        "reason": "max_iterations",
        "iterations": max_iter,
        "history": history,
        "final_error_cm": round(history[-1], 4) if history else None,
        "lost_recoveries": lost_recoveries,
        "final_gain": round(adapted_gain, 4),
    }


# --------------------------------------------------------------------------
# 场景执行
# --------------------------------------------------------------------------
def run_scenario(
    scenario: Dict[str, Any],
    profile: str = "nominal",
    randomize: bool = False,
    seed: int = 20260910,
) -> Dict[str, Any]:
    """跑一个场景，返回结果。"""
    rng = random.Random(seed)
    domain = load_package("domain_random")
    sampled = sample_randomization(domain, rng) if randomize else {}

    servo = RealisticServoBus(seed=seed)
    perception = NoisyPerception(profile=profile, seed=seed)

    sid = scenario["id"]
    initial = scenario.get("initial", {})

    # ---- 舵机可行性：检查目标角能否在限位内到达 ----
    target_angles = {"left_knee_pitch": 45.0, "left_hip_pitch": 20.0}
    applied = {}
    for name, deg in target_angles.items():
        lo, hi = JOINTS[name]["limit_deg"]
        applied[name] = max(lo, min(hi, deg))

    # ---- 视觉伺服（搬运 / 踢球场景）----
    servo_result = None
    if sid in ("S-03-carry", "S-04-kick"):
        offset_mm = float(initial.get("object_position_mm", [0, 0, 0])[0])
        if sid == "S-04-kick":
            offset_mm = float(initial.get("ball_position_mm", [0, 0, 0])[0])
        servo_result = servo_loop(
            perception,
            target_x_cm=offset_mm / 10.0,
            seed=seed,
        )

    # ---- 舵机非理想特性推进 ----
    steps = 40
    for i in range(steps):
        servo.set_angle(JOINTS["left_hip_pitch"]["id"], 10.0 * math.sin(i / 5.0))
        servo.step()

    ok = True
    reason = "ok"
    if servo_result is not None and not servo_result["converged"]:
        ok = False
        reason = servo_result["reason"]

    # 域随机化下的一致性检查
    if sampled:
        mass = sampled.get("mass_kg", 1.65)
        if mass > 1.75 or mass < 1.55:
            ok = False
            reason = "mass_out_of_range"

    return {
        "scenario_id": sid,
        "scenario_name": scenario.get("name", ""),
        "profile": profile,
        "randomized": randomize,
        "seed": seed,
        "ok": ok,
        "reason": reason,
        "servo": servo_result,
        "servo_bus_stats": servo.stats(),
        "perception_stats": perception.stats(),
        "applied_angles": applied,
        "sampled_domain": {k: (round(v, 4) if isinstance(v, float) else v)
                           for k, v in sampled.items()},
    }


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------
def write_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ["scenario_id", "profile", "randomized", "seed", "ok", "reason",
              "iterations", "final_error_cm", "dropout_rate_observed"]
    lines = [",".join(header)]
    for r in rows:
        s = r.get("servo") or {}
        p = r.get("perception_stats") or {}
        lines.append(",".join(str(x) for x in [
            r["scenario_id"],
            r["profile"],
            int(r["randomized"]),
            r["seed"],
            int(r["ok"]),
            r["reason"],
            s.get("iterations", ""),
            s.get("final_error_cm", ""),
            p.get("dropout_rate_observed", ""),
        ]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_svg_curve(series: Dict[str, List[float]], path: Path,
                    title: str = "Servo convergence") -> None:
    """纯标准库绘制收敛曲线 SVG。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    W, H = 760, 420
    ml, mr, mt, mb = 70, 30, 50, 60
    pw, ph = W - ml - mr, H - mt - mb

    all_vals = [v for s in series.values() for v in s if not math.isnan(v)]
    if not all_vals:
        all_vals = [0.0, 1.0]
    ymax = max(all_vals) * 1.15 or 1.0
    ymin = min(0.0, min(all_vals) * 1.15)
    xmax = max(len(s) for s in series.values()) or 1

    colors = ["#2b7fd4", "#d4572b", "#2ba36a", "#8b5cf6", "#e0a800", "#d63a7a"]

    def sx(i: int) -> float:
        return ml + (i / max(1, xmax - 1)) * pw if xmax > 1 else ml

    def sy(v: float) -> float:
        rng = (ymax - ymin) or 1.0
        return mt + ph - ((v - ymin) / rng) * ph

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
        f'<text x="{W/2}" y="28" text-anchor="middle" font-size="17" '
        f'font-family="Helvetica,Arial,sans-serif" fill="#1a1a1a">{title}</text>',
    ]

    # 网格与 y 轴刻度
    for k in range(6):
        v = ymin + (ymax - ymin) * k / 5.0
        y = sy(v)
        parts.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{ml+pw}" y2="{y:.1f}" '
                     f'stroke="#e6e6e6" stroke-width="1"/>')
        parts.append(f'<text x="{ml-10}" y="{y+4:.1f}" text-anchor="end" '
                     f'font-size="11" font-family="Helvetica,Arial,sans-serif" '
                     f'fill="#555">{v:.2f}</text>')

    # 收敛阈值线
    parts.append(f'<line x1="{ml}" y1="{sy(1.0):.1f}" x2="{ml+pw}" '
                 f'y2="{sy(1.0):.1f}" stroke="#999" stroke-width="1" '
                 f'stroke-dasharray="5,4"/>')
    parts.append(f'<text x="{ml+pw-4}" y="{sy(1.0)-6:.1f}" text-anchor="end" '
                 f'font-size="11" font-family="Helvetica,Arial,sans-serif" '
                 f'fill="#777">tolerance 1.0 cm</text>')

    # 坐标轴
    parts.append(f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{mt+ph}" '
                 f'stroke="#333" stroke-width="1.5"/>')
    parts.append(f'<line x1="{ml}" y1="{mt+ph}" x2="{ml+pw}" y2="{mt+ph}" '
                 f'stroke="#333" stroke-width="1.5"/>')
    parts.append(f'<text x="{ml+pw/2}" y="{H-20}" text-anchor="middle" '
                 f'font-size="13" font-family="Helvetica,Arial,sans-serif" '
                 f'fill="#333">iteration</text>')
    parts.append(f'<text x="18" y="{mt+ph/2}" text-anchor="middle" font-size="13" '
                 f'font-family="Helvetica,Arial,sans-serif" fill="#333" '
                 f'transform="rotate(-90 18 {mt+ph/2})">lateral error (cm)</text>')

    for idx, (label, vals) in enumerate(series.items()):
        color = colors[idx % len(colors)]
        pts = []
        for i, v in enumerate(vals):
            if math.isnan(v):
                continue
            pts.append(f"{sx(i):.1f},{sy(v):.1f}")
        if len(pts) >= 2:
            parts.append(f'<polyline points="{" ".join(pts)}" fill="none" '
                         f'stroke="{color}" stroke-width="2.2"/>')
        for i, v in enumerate(vals):
            if math.isnan(v):
                continue
            parts.append(f'<circle cx="{sx(i):.1f}" cy="{sy(v):.1f}" r="3" '
                         f'fill="{color}"/>')
        ly = mt + 16 + idx * 19
        parts.append(f'<line x1="{ml+pw-150}" y1="{ly}" x2="{ml+pw-128}" '
                     f'y2="{ly}" stroke="{color}" stroke-width="2.5"/>')
        parts.append(f'<text x="{ml+pw-122}" y="{ly+4}" font-size="11" '
                     f'font-family="Helvetica,Arial,sans-serif" '
                     f'fill="#333">{label}</text>')

    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def write_svg_bars(data: Dict[str, float], path: Path,
                   title: str = "Success rate by condition",
                   ylabel: str = "success rate") -> None:
    """纯标准库绘制柱状图 SVG。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    W, H = 760, 420
    ml, mr, mt, mb = 70, 30, 50, 90
    pw, ph = W - ml - mr, H - mt - mb
    items = list(data.items())
    if not items:
        items = [("n/a", 0.0)]
    vmax = max(max(v for _, v in items), 1.0)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
        f'<text x="{W/2}" y="28" text-anchor="middle" font-size="17" '
        f'font-family="Helvetica,Arial,sans-serif" fill="#1a1a1a">{title}</text>',
    ]
    for k in range(6):
        v = vmax * k / 5.0
        y = mt + ph - (v / vmax) * ph
        parts.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{ml+pw}" y2="{y:.1f}" '
                     f'stroke="#e6e6e6" stroke-width="1"/>')
        parts.append(f'<text x="{ml-10}" y="{y+4:.1f}" text-anchor="end" '
                     f'font-size="11" font-family="Helvetica,Arial,sans-serif" '
                     f'fill="#555">{v:.2f}</text>')

    parts.append(f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{mt+ph}" '
                 f'stroke="#333" stroke-width="1.5"/>')
    parts.append(f'<line x1="{ml}" y1="{mt+ph}" x2="{ml+pw}" y2="{mt+ph}" '
                 f'stroke="#333" stroke-width="1.5"/>')
    parts.append(f'<text x="18" y="{mt+ph/2}" text-anchor="middle" font-size="13" '
                 f'font-family="Helvetica,Arial,sans-serif" fill="#333" '
                 f'transform="rotate(-90 18 {mt+ph/2})">{ylabel}</text>')

    slot = pw / len(items)
    bw = slot * 0.55
    for i, (label, val) in enumerate(items):
        x = ml + slot * i + (slot - bw) / 2
        h = (val / vmax) * ph
        y = mt + ph - h
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                     f'height="{h:.1f}" fill="#2b7fd4"/>')
        parts.append(f'<text x="{x+bw/2:.1f}" y="{y-6:.1f}" text-anchor="middle" '
                     f'font-size="11" font-family="Helvetica,Arial,sans-serif" '
                     f'fill="#1a1a1a">{val:.2f}</text>')
        parts.append(f'<text x="{x+bw/2:.1f}" y="{mt+ph+18:.1f}" '
                     f'text-anchor="middle" font-size="11" '
                     f'font-family="Helvetica,Arial,sans-serif" fill="#333" '
                     f'transform="rotate(-25 {x+bw/2:.1f} {mt+ph+18:.1f})">'
                     f'{label}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def load_scenarios() -> List[Dict[str, Any]]:
    return load_package("scenario_set")["scenarios"]


def cmd_list() -> int:
    for s in load_scenarios():
        print(f"{s['id']:<14} {s['name']:<14} skill={s['skill']}")
    return 0


def cmd_run(only: Optional[str], episodes: int, profile: str,
            randomize: bool, seed: int) -> int:
    scenarios = load_scenarios()
    if only:
        scenarios = [s for s in scenarios if s["id"] == only]
        if not scenarios:
            print(f"未找到场景: {only}")
            return 2

    all_rows: List[Dict[str, Any]] = []
    per_scenario_success: Dict[str, List[int]] = {}

    for sc in scenarios:
        results = []
        for ep in range(episodes):
            r = run_scenario(sc, profile=profile, randomize=randomize,
                             seed=seed + ep)
            results.append(r)
            all_rows.append(r)
        succ = sum(1 for r in results if r["ok"])
        per_scenario_success[sc["id"]] = [succ, len(results)]
        print(f"{sc['id']:<14} {sc['name']:<14} 成功 {succ}/{len(results)}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = RESULTS_DIR / f"sim_{profile}{'_rand' if randomize else ''}.csv"
    write_csv(all_rows, csv_path)
    print(f"\n已写出 CSV: {csv_path}")

    rates = {k: (v[0] / v[1] if v[1] else 0.0) for k, v in per_scenario_success.items()}
    write_svg_bars(
        rates,
        FIGURES_DIR / f"success_rate_{profile}{'_rand' if randomize else ''}.svg",
        title=f"Scenario success rate (profile={profile}, "
              f"randomize={'on' if randomize else 'off'}, episodes={episodes})",
    )
    print(f"已写出图表: {FIGURES_DIR}")

    # 收敛曲线（以搬运场景为例）
    carry = next((s for s in scenarios if s["id"] == "S-03-carry"), None)
    if carry:
        series: Dict[str, List[float]] = {}
        for off_cm, label in ((5.0, "offset 5cm"), (12.0, "offset 12cm"),
                              (20.0, "offset 20cm")):
            p = NoisyPerception(profile=profile, seed=seed)
            res = servo_loop(p, target_x_cm=off_cm, seed=seed)
            series[label] = res["history"]
        svg = FIGURES_DIR / f"convergence_{profile}.svg"
        write_svg_curve(series, svg,
                        title=f"Visual servo convergence (profile={profile})")
        print(f"已写出收敛曲线: {svg}")

    return 0 if all(r["ok"] for r in all_rows) else 1


def cmd_sweep(axis: str, episodes: int, seed: int) -> int:
    """扫描一个扰动轴，产出失效边界数据。"""
    profiles = ["ideal", "nominal", "harsh", "adversarial"]
    sc = next(s for s in load_scenarios() if s["id"] == "S-03-carry")

    rates: Dict[str, float] = {}
    rows: List[Dict[str, Any]] = []
    for prof in profiles:
        ok = 0
        for ep in range(episodes):
            r = run_scenario(sc, profile=prof, randomize=True, seed=seed + ep)
            rows.append(r)
            ok += 1 if r["ok"] else 0
        rates[prof] = ok / episodes if episodes else 0.0
        print(f"profile={prof:<12} randomize=on  成功 {ok}/{episodes}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(rows, RESULTS_DIR / f"sweep_{axis}.csv")
    write_svg_bars(
        rates, FIGURES_DIR / f"sweep_{axis}.svg",
        title=f"Robustness sweep by perception profile ({axis})",
    )
    print(f"\n已写出: {RESULTS_DIR / f'sweep_{axis}.csv'}")
    print(f"已写出: {FIGURES_DIR / f'sweep_{axis}.svg'}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="A.T.R.I. 设计数据包仿真（运动学层面，非刚体动力学）"
    )
    ap.add_argument("--list", action="store_true", help="列出场景")
    ap.add_argument("--scenario", type=str, default=None, help="只跑单个场景")
    ap.add_argument("--all", action="store_true", help="跑全部场景")
    ap.add_argument("--episodes", type=int, default=5, help="每个场景的重复次数")
    ap.add_argument("--profile", type=str, default="nominal",
                    choices=["ideal", "nominal", "harsh", "adversarial"])
    ap.add_argument("--randomize", action="store_true", help="启用域随机化")
    ap.add_argument("--sweep", type=str, default=None,
                    help="扫描模式，如 perception")
    ap.add_argument("--seed", type=int, default=20260910)
    args = ap.parse_args(argv)

    if args.list:
        return cmd_list()
    if args.sweep:
        return cmd_sweep(args.sweep, args.episodes, args.seed)
    if args.scenario or args.all:
        return cmd_run(args.scenario, args.episodes, args.profile,
                       args.randomize, args.seed)

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
