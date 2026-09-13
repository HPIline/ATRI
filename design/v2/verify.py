"""工程验证：赛规、力矩、质量、电压、G0。"""
from __future__ import annotations

from typing import Any, Dict

from . import bom
import json
from pathlib import Path
from .profile import (
    ANKLE,
    CONTEST,
    MASS,
    SERVO,
    V1,
    ankle_torque_nm,
    dof_counts,
    envelope_mm,
    scale_from_v1,
)


def report() -> Dict[str, Any]:
    env = envelope_mm()
    dof = dof_counts()
    m = MASS["design_limit_g"]
    walk = ankle_torque_nm(m, ANKLE["k_walk"])
    hold = ankle_torque_nm(m, ANKLE["k_hold"])
    snapshot=json.loads((Path(__file__).parent/'out/assembly-snapshot.json').read_text())
    al=sum(p['volume_mm3']*.0027 for p in snapshot['parts'] if p['kind']=='al')
    close = bom.cart("close")
    retail = bom.cart("retail")
    envelope_ok = (
        env["height_mm"] <= CONTEST["height_max_mm"]
        and env["width_mm"] <= CONTEST["width_max_mm"]
        and env["depth_mm"] <= CONTEST["depth_max_mm"]
    )
    dof_ok = (
        dof["total"] >= CONTEST["dof_min"]
        and dof["leg_l"] >= CONTEST["leg_dof_min"]
        and dof["leg_r"] >= CONTEST["leg_dof_min"]
        and dof["upper_torso"] >= CONTEST["upper_torso_min"]
    )
    walk_util = walk / SERVO["rated_nm"]
    hold_util = hold / SERVO["rated_nm"]
    v_ok = SERVO["voltage_range_v"][0] <= 12.6 <= SERVO["voltage_range_v"][1]
    return {
        "envelope": env,
        "envelope_ok": envelope_ok,
        "dof": dof,
        "dof_ok": dof_ok,
        "mass_design_g": m,
        "mass_hard_g": MASS["hard_limit_g"],
        "aluminum_g": round(al, 1),
        "aluminum_ok": al <= MASS["structure_al_budget_g"],
        "ankle_walk_nm": round(walk, 3),
        "ankle_hold_nm": round(hold, 3),
        "ankle_walk_util": round(walk_util, 3),
        "ankle_hold_util": round(hold_util, 3),
        "walk_util_ok": walk_util <= ANKLE["util_walk_max"],
        "hold_rated_ok": hold <= SERVO["rated_nm"],
        "knee_scaled_nm": round(scale_from_v1(V1["knee_nm"], V1["mass_g"], m), 3),
        "trunk_roll_scaled_nm": round(
            scale_from_v1(V1["trunk_roll_nm"], V1["mass_g"], m), 3
        ),
        "voltage_3s_ok": v_ok,
        "g0_close_cny": close["total_cny"],
        "g0_retail_cny": retail["total_cny"],
        "g0_close_ok": close["total_cny"] <= 3000,
        "g0_retail_ok": retail["total_cny"] <= 3200,
        "gates": {
            "G0": "close 购物车 ≤¥3000 且 12V SKU 截图；retail ¥109×20 不通过",
            "G1": "1 只 C018 循环 0.8/1.0/1.2 N·m ×30 min，壳温 ≤65°C",
            "G2": "单腿铝骡机外推整机 ≤2300 g，验收 ≤2450 g",
            "G3": "赛方书面：头/夹爪是否计入上肢躯干；尺寸量法；可否换电",
            "G4": "无 hip_yaw 时 ±30°/90° 转向误差 ≤10°，失败需重新评审，不自动加回 yaw",
            "G5": "三路舵机 + SBC 同步冲击不复位",
            "G6": "相机+QR+人脸+TTS+舵机环。Pi4B 实机计算和电源预算待验证",
            "G7": "走、转、踢对准、抓放先于外壳冻结",
        },
        "rated_nm": SERVO["rated_nm"],
        "stall_nm": SERVO["stall_nm"],
    }


def markdown(r: Dict[str, Any] | None = None) -> str:
    r = r or report()
    env = r["envelope"]
    lines = [
        "# ATRI-v2 A 路线工程验证",
        "",
        "> 生成自 `design/v2/verify.py`。力矩用额定 **0.98 N·m**，不用堵转×50%。",
        "> 腰横滚现机权威是 **0.442 N·m / 45.1%**（力臂口径订正后）。旧 90° 力臂错值已作废。",
        "",
        "## 赛规",
        "",
        f"| 包络 | {env['height_mm']:.1f} × {env['width_mm']:.1f} × {env['depth_mm']:.1f} mm | 上限 600×300×300 | {'PASS' if r['envelope_ok'] else 'FAIL'} |",
        f"| DOF | 总 {r['dof']['total']} / 腿 {r['dof']['leg_l']}+{r['dof']['leg_r']} / 上肢躯干 {r['dof']['upper_torso']}（不含头） | ≥18 / ≥4 / ≥10 | {'PASS' if r['dof_ok'] else 'FAIL'} |",
        f"| 3S 12.6 V | 舵机 4–14 V | {'PASS' if r['voltage_3s_ok'] else 'FAIL'} |",
        "",
        "## 质量",
        "",
        f"- 设计限 **{r['mass_design_g']:.0f} g**，验收硬限 **{r['mass_hard_g']:.0f} g**",
        f"- 当前铝件按同源CAD体积计算 **{r['aluminum_g']:.0f} g**（预算 650 g）{'PASS' if r['aluminum_ok'] else 'FAIL'}",
        "- 舵机 20×55 g = 1100 g 是地板。超质量后必须复核完整结构与物料，不能删除必要线束或擅改DOF",
        "",
        "## 踝关节（主判据）",
        "",
        f"公式：`τ = (m - 85 g) × 9.81 × 0.025 × k`，与现机 3036 g → 1.446 N·m 同口径。",
        "",
        f"| 工况 | k | τ | / 0.98 | 判定 |",
        f"|---|---:|---:|---:|---|",
        f"| 慢步（赛题无竞速） | 1.4 | {r['ankle_walk_nm']:.3f} N·m | {r['ankle_walk_util']*100:.1f}% | {'PASS ≤85%' if r['walk_util_ok'] else 'FAIL'} |",
        f"| 站立保持（现机口径） | 2.0 | {r['ankle_hold_nm']:.3f} N·m | {r['ankle_hold_util']*100:.1f}% | {'仍超额定（诚实）' if not r['hold_rated_ok'] else 'PASS'} |",
        "",
        f"膝按质量比例缩放 ≈ **{r['knee_scaled_nm']:.3f} N·m**。腰横滚缩放 ≈ **{r['trunk_roll_scaled_nm']:.3f} N·m**（约 34% 额定）。",
        "",
        "**结论：A 路线在 k=2.0 下踝仍超连续额定；它只在慢步 k=1.4 且质量打进 2.30 kg 时闭合。必须过 G1 循环温升，不能用堵转 2.94 当设计值。**",
        "",
        "## G0 预算",
        "",
        f"- close（舵机目标价 ¥90 + Pi4B预算预留）：**¥{r['g0_close_cny']:.0f}** {'PASS ≤3000' if r['g0_close_ok'] else 'FAIL'}",
        f"- retail（微雪 ¥109 + 更高外设）：**¥{r['g0_retail_cny']:.0f}** {'仍超 3200' if not r['g0_retail_ok'] else 'PASS'}",
        "",
        "## 门禁",
        "",
    ]
    for k, v in r["gates"].items():
        lines.append(f"- **{k}**：{v}")
    lines += [
        "",
        "## 尚未用实物关闭的项",
        "",
        "- STS3215 连续 0.98 N·m 的温升（本SKU官方额定值；温升仍须实测）",
        "- 铝板实称 vs DXF 面积",
        "- 20 ms 步态在无 STM32 时的总线抖动",
        "- 转向无 yaw 是否够用（G4）",
        "",
    ]
    return "\n".join(lines) + "\n"
