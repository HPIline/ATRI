#!/usr/bin/env python3
"""用真实元件尺寸校验设计模型：装得下吗？重量对不对？

数据来源：`design/components.json`（由外部部件库/白皮书提供，
本脚本只做校验，不负责选型）。

校验三件事：
  1. 尺寸配合 —— 元件能否放进对应的安装空腔
  2. 质量闭合 —— 模型口径（link 质量合计）vs 元件口径（BOM 清单核算）
  3. 力矩重算 —— 用真实质量重新推导关节需求（质量变大会放大需求）

输出：design/handoff/fit_report.md
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]  # design/v1-22dof/archive → repo
sys.path.insert(0, str(HERE))

sys.path.insert(0, str(REPO / "design"))
import geometry  # noqa: E402
import gen_handoff  # noqa: E402
import gen_urdf  # noqa: E402

OUT_DIR = HERE / "handoff"
COMPONENTS = HERE / "components.json"


# --------------------------------------------------------------------------
# 配合校验
# --------------------------------------------------------------------------
def fits(part_mm: List[float], cavity_mm: List[float],
         clearance_mm: float = 0.5) -> Tuple[bool, str]:
    """元件能否放入空腔。允许任意姿态，故各维排序后比较。

    clearance_mm 是每边所需的装配余量。
    """
    p = sorted(part_mm, reverse=True)
    c = sorted([v - 2 * clearance_mm for v in cavity_mm], reverse=True)
    if any(x < 0 for x in c):
        return False, "空腔净空不足"
    ok = all(p[i] <= c[i] + 1e-9 for i in range(3))
    if ok:
        slack = [round(c[i] - p[i], 1) for i in range(3)]
        return True, f"可放入（余量 {slack[0]}/{slack[1]}/{slack[2]} mm）"
    detail = "、".join(
        f"{p[i]:.1f}>{c[i]:.1f}" for i in range(3) if p[i] > c[i] + 1e-9
    )
    return False, f"放不下（超出：{detail} mm）"


def check_placements(model: Dict[str, Any],
                     comps: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for p in comps["placements"]:
        link = next((l for l in model["links"] if l["name"] == p["link"]), None)
        if link is None:
            out.append({**p, "ok": False, "verdict": f"link {p['link']} 不存在"})
            continue
        sx, sy, sz = geometry.bounding_box(link["geometry"])
        wall = comps.get("cavity_wall_mm", 2.5)
        inner = [sx - 2 * wall, sy - 2 * wall, sz - 2 * wall]
        ok, verdict = fits(p["size_mm"], inner)
        out.append({
            "component": p["component"],
            "link": p["link"],
            "part_size_mm": p["size_mm"],
            "cavity_outer_mm": [round(v, 1) for v in (sx, sy, sz)],
            "cavity_inner_mm": [round(v, 1) for v in inner],
            "ok": ok,
            "verdict": verdict,
        })
    return out


def check_servo_housing(model: Dict[str, Any],
                        comps: Dict[str, Any]) -> List[Dict[str, Any]]:
    """舵机能否被关节壳容纳。

    关节壳是 sphere_shell / cylinder，其"内腔"按外径减去壳壁估算。
    """
    servo = next(c for c in comps["components"] if c["role"] == "servo_s")
    sv = servo["size_mm"]
    servo_diag = math.sqrt(sum(v * v for v in sv))  # 最保守：按体对角线

    out = []
    for link in model["links"]:
        g = link["geometry"]
        if g["type"] == "sphere_shell":
            inner_d = 2.0 * g["inner_r_mm"]
        elif g["type"] == "cylinder":
            inner_d = 2.0 * g["radius_mm"]
            inner_d = min(inner_d, g["height_mm"])
        else:
            continue
        # 判据：若该壳体要**整体包住**舵机，内腔必须能容纳舵机的体对角线。
        # 严格判据就是 inner_d >= servo_diag，不做任何经验折扣。
        ok = inner_d >= servo_diag
        if ok:
            verdict = f"可整体包住（余量 {inner_d - servo_diag:.0f} mm）"
        else:
            verdict = (f"无法整体包住：内径 {inner_d:.0f} mm < 体对角线 "
                       f"{servo_diag:.0f} mm（需放大至 ≥{servo_diag:.0f} mm，"
                       f"或改为外部支架夹持而非全包）")
        out.append({
            "component": servo["name"],
            "link": link["name"],
            "housing_inner_d_mm": round(inner_d, 1),
            "servo_bbox_mm": sv,
            "servo_diag_mm": round(servo_diag, 1),
            "ok": ok,
            "verdict": verdict,
        })
    return out


# --------------------------------------------------------------------------
# 质量闭合
# --------------------------------------------------------------------------
def mass_rollup(model: Dict[str, Any], comps: Dict[str, Any]) -> Dict[str, Any]:
    """模型口径 vs 元件口径的质量闭合（v2 起两者均已含舵机/电子件/线束）。"""
    servo = next(c for c in comps["components"] if c["role"] == "servo_s")
    joint_n = len(model["joints"])
    servo_total = servo["mass_g"] * joint_n

    groups: Dict[str, Dict[str, float]] = {}
    for c in comps["components"]:
        if c["role"] == "servo_s":
            continue
        qty = c.get("qty", 1)
        g = groups.setdefault(c["category"], {"mass_g": 0.0, "items": []})
        g["mass_g"] += c["mass_g"] * qty
        g["items"].append(c["name"])

    groups["舵机"] = {"mass_g": servo_total,
                    "items": [f"{servo['name']} × {joint_n}"]}

    electronics = sum(g["mass_g"] for k, g in groups.items() if k != "舵机")
    # v2 起 link 质量已含"结构 + 舵机 + 电子件 + 分摊线束"，因此两侧口径必须一致：
    #   模型侧 = sum(link mass)
    #   元件侧 = 舵机 + 电子件 + 结构估算 + 线束 + 紧固件
    # 两侧相等即说明"模型质量分布"与"BOM 清单"自洽。
    model_total = sum(l["mass_kg"] for l in model["links"]) * 1000.0
    struct_design = model_total

    real_struct = comps.get("structure_mass_estimate_g", 0.0)
    real_total = (servo_total + electronics + real_struct
                  + comps["cable_mass_g"] + comps["fastener_mass_g"])

    return {
        "servo_count": joint_n,
        "servo_each_g": servo["mass_g"],
        "servo_total_g": servo_total,
        "electronics_g": round(electronics, 1),
        "groups": {k: round(v["mass_g"], 1) for k, v in groups.items()},
        "group_items": {k: list(v["items"]) for k, v in groups.items()},
        "design_structure_g": round(struct_design, 1),
        "real_structure_estimate_g": real_struct,
        "design_total_g": round(model_total, 1),
        "real_total_g": round(real_total, 1),
        "overrun_g": round(real_total - model_total, 1),
        "overrun_pct": round((real_total / model_total - 1) * 100, 1),
    }


# --------------------------------------------------------------------------
# 用真实质量重算力矩
# --------------------------------------------------------------------------
def retorque(model: Dict[str, Any], comps: Dict[str, Any],
             mass: Dict[str, Any]) -> Dict[str, Any]:
    """按真实总重重新推导需求力矩（只改总重，几何不变）。"""
    old_total = gen_handoff.total_mass_of(model)
    new_total = mass["real_total_g"] / 1000.0

    rows = []
    for j in sorted(model["joints"], key=lambda x: x["id"]):
        t = gen_handoff.joint_torque(model, j)
        # 重力项与载荷成正比；单腿支撑项按总重等比放大
        scale = new_total / old_total
        new_req = t["required_torque_nm"] * scale
        rows.append({
            "joint": t["joint"],
            "old_required_nm": t["required_torque_nm"],
            "new_required_nm": round(new_req, 3),
            "driver": t["requirements_driver"],
            "tier_before": t["torque_tier"],
            "tier_after": gen_handoff._tier(new_req),
        })
    worst = max(rows, key=lambda r: r["new_required_nm"])
    return {
        "old_total_kg": round(old_total, 3),
        "new_total_kg": round(new_total, 3),
        "scale": round(new_total / old_total, 3),
        "joints": rows,
        "worst": worst,
    }


# --------------------------------------------------------------------------
# 报告
# --------------------------------------------------------------------------
def emit_report(model: Dict[str, Any], comps: Dict[str, Any],
                placements: List[Dict[str, Any]],
                housings: List[Dict[str, Any]],
                mass: Dict[str, Any],
                torque: Dict[str, Any]) -> Path:
    def mark(ok: bool) -> str:
        return "✅" if ok else "❌"

    pl_rows = "\n".join(
        f"| {p['component']} | `{p['link']}` | "
        f"{'×'.join(f'{v:.0f}' for v in p['part_size_mm'])} | "
        f"{'×'.join(f'{v:.0f}' for v in p['cavity_inner_mm'])} | "
        f"{mark(p['ok'])} {p['verdict']} |"
        for p in placements
    )
    hs_rows = "\n".join(
        f"| `{h['link']}` | {h['housing_inner_d_mm']:.1f} | "
        f"{h['servo_diag_mm']:.1f} | {mark(h['ok'])} {h['verdict']} |"
        for h in housings
    )
    mg_rows = "\n".join(
        f"| {k} | {v:.0f} | {', '.join(mass['group_items'].get(k, []))} |"
        for k, v in sorted(mass["groups"].items(), key=lambda kv: -kv[1])
    )
    tq_rows = "\n".join(
        f"| `{r['joint']}` | {r['old_required_nm']:.3f} | "
        f"**{r['new_required_nm']:.3f}** | "
        f"{'↑' if r['tier_after'] != r['tier_before'] else ''}"
        f"{r['tier_before']}→{r['tier_after']} |"
        for r in sorted(torque["joints"],
                        key=lambda x: -x["new_required_nm"])[:12]
    )

    bad_p = [p for p in placements if not p["ok"]]
    bad_h = [h for h in housings if not h["ok"]]

    md = f"""# 元件配合与质量校验报告

> 自动生成：`design/check_fit.py`。输入为 `design/components.json`
> （外部部件库提供的**真实**元件尺寸与质量），
> 校验对象为本项目的设计模型。**本报告只做校验，不做选型。**

> ⚠️ **口径声明（2026-09-12 重生成）**：本报告已按现行口径重新生成 ——
> 结构件【实算】 **1390 g / 81 件**，整机 **≈3036 g（纸面推算，重量方案未定案）**，
> 质量闭合为 **模型口径 3037 g ↔ 元件口径 3036 g**。
> 力矩：**最大关节是踝**（需求 1.446 N·m = 【官方】额定 0.98 N·m 的 **147.5%**）；
> `trunk_roll` 在订正重力力臂口径后为 **0.246 N·m = 45.1%（不再超额定）**——
> 旧值 1.84 N·m / 194% 来自 `perpendicular_arm()` 把沿轴分量算进力臂的口径错误，
> 见 `design/handoff/线程报告-力矩力臂口径修正.md`。两套口径（零姿态静力 / 限位内最不利）
> 的逐关节明细见 `design/handoff/hardware_requirements.json` 的 `torque_check`；
> **超额定的是 10 个腿部关节**（踝/膝/髋，由单腿支撑工况决定），
> **其力矩判据应看【官方】额定 0.98 N·m**，
> 历史『堵转 × 50% = 1.47 N·m』比官方额定乐观 50%，仅作并列参考。
> 历史口径（6d4b077 的 3437 g ↔ 3436 g、包络 418 × 223 × 129 mm）已被
> `design/handoff/装配一致性修正记录.md` §4.4 / §8.3 取代；订正过程见
> `design/handoff/过期口径修正记录.md`。
> ⚠️ **已知未回填项**：`components.json` 里舵机外形仍是旧值 45.2 × 24.7 × 35.0
> （官方/实测为 **45.40 × 24.80 × 39.60，无安装耳**，见 `总体参数汇总表.md` §2.2），
> 所以第 2.2 节「舵机 → 关节壳」的判定按旧外形算，需随重量方案一并回填。

---

## 一、结论摘要

| 检查项 | 结果 |
|---|---|
| 电子件装入空腔 | {len(placements) - len(bad_p)}/{len(placements)} 通过 |
| 舵机装入关节壳 | {len(housings) - len(bad_h)}/{len(housings)} 通过 |
| 质量闭合 | 模型口径 {mass['design_total_g']:.0f} g ↔ 元件口径 **{mass['real_total_g']:.0f} g**，差 {mass['overrun_g']:+.0f} g（{mass['overrun_pct']:+.1f}%） |
| 力矩需求 | 按真实总重放大 **×{torque['scale']}**，最大关节 {torque['worst']['joint']} 需 **{torque['worst']['new_required_nm']:.2f} N·m** |

---

## 二、尺寸配合

### 2.1 电子件 → 安装空腔

（空腔 = link 外形尺寸 − 2 × {comps.get('cavity_wall_mm', 2.5)} mm 壁厚 − 0.5 mm/边装配余量）

| 元件 | 安装位置 | 元件尺寸 (mm) | 空腔净空 (mm) | 判定 |
|---|---|---|---|---|
{pl_rows}

### 2.2 舵机 → 关节壳

舵机外形 {'×'.join(f'{v:.1f}' for v in next(c for c in comps['components'] if c['role'] == 'servo_s')['size_mm'])} mm，
体对角线 {housings[0]['servo_diag_mm'] if housings else 0:.1f} mm。

| 关节壳 link | 壳内径 (mm) | 舵机体对角 (mm) | 判定 |
|---|---|---|---|
{hs_rows}

---

## 三、质量闭合

| 类别 | 质量 (g) | 明细 |
|---|---|---|
{mg_rows}
| **元件口径**（BOM 清单核算） | **{mass['real_total_g']:.0f}** | 舵机 + 电子件 + 结构估算 + 线束 + 紧固件 |
| **模型口径**（link 质量合计） | {mass['design_total_g']:.0f} | 结构 + 舵机 + 电子件 + 分摊线束（v2 起已全部摊入 link） |

**差异 {mass['overrun_g']:+.0f} g（{mass['overrun_pct']:+.1f}%）**
（两口径相等 = 模型质量分布与 BOM 清单自洽；URDF 的 sum(link mass) 即实物口径总重）

---

## 四、力矩需求重算

按真实总重 {torque['new_total_kg']:.3f} kg（原 {torque['old_total_kg']:.3f} kg）
等比放大后的需求（前 12 项）：

| 关节 | 原需求 (N·m) | 新需求 (N·m) | 档位变化 |
|---|---|---|---|
{tq_rows}

---

## 五、必须处理的问题

"""
    if bad_p:
        md += "### 尺寸放不下\n\n"
        for p in bad_p:
            md += (f"- **{p['component']}** → `{p['link']}`：{p['verdict']}\n"
                   f"  - 元件 {'×'.join(f'{v:.0f}' for v in p['part_size_mm'])} mm，"
                   f"空腔净空 {'×'.join(f'{v:.0f}' for v in p['cavity_inner_mm'])} mm\n")
    if bad_h:
        md += "\n### 舵机装不进关节壳\n\n"
        for h in bad_h:
            md += f"- `{h['link']}`：{h['verdict']}\n"
    if mass["overrun_g"] > 0:
        md += (f"\n### 质量超预算\n\n"
               f"超出 {mass['overrun_g']:+.0f} g。"
               f"需要：缩减结构件 / 换更轻舵机 / 调整质量预算口径。\n")
    md += (f"\n### 力矩档位变化\n\n"
           f"总重放大 ×{torque['scale']}，需重新核对舵机档位是否仍然够用。\n")

    out = OUT_DIR / "fit_report.md"
    out.write_text(md, encoding="utf-8")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    if not COMPONENTS.exists():
        print(f"缺少 {COMPONENTS}")
        return 2
    model = gen_urdf.load_model()
    comps = json.loads(COMPONENTS.read_text(encoding="utf-8"))

    placements = check_placements(model, comps)
    housings = check_servo_housing(model, comps)
    mass = mass_rollup(model, comps)
    torque = retorque(model, comps, mass)

    print("=" * 70)
    print("元件配合与质量校验")
    print("=" * 70)
    print("\n尺寸配合（电子件 → 空腔）:")
    for p in placements:
        flag = "OK  " if p["ok"] else "FAIL"
        print(f"  [{flag}] {p['component']:<28} -> {p['link']:<14} {p['verdict']}")
    print("\n舵机 → 关节壳:")
    for h in housings:
        flag = "OK  " if h["ok"] else "FAIL"
        print(f"  [{flag}] {h['link']:<22} 内径{h['housing_inner_d_mm']:>6.1f}mm  {h['verdict']}")
    print("\n质量闭合:")
    for k, v in sorted(mass["groups"].items(), key=lambda kv: -kv[1]):
        print(f"  {k:<12} {v:>7.0f} g")
    print(f"  {'元件口径':<12} {mass['real_total_g']:>7.0f} g")
    print(f"  {'模型口径':<12} {mass['design_total_g']:>7.0f} g")
    print(f"  {'差异':<12} {mass['overrun_g']:>+7.0f} g "
          f"({mass['overrun_pct']:+.1f}%)")
    print("\n力矩重算（总重 ×%.3f）:" % torque["scale"])
    for r in sorted(torque["joints"], key=lambda x: -x["new_required_nm"])[:6]:
        chg = "" if r["tier_after"] == r["tier_before"] else \
              f"  <-- 档位 {r['tier_before']}→{r['tier_after']}"
        print(f"  {r['joint']:<22} {r['old_required_nm']:>6.3f} -> "
              f"{r['new_required_nm']:>6.3f} N·m{chg}")

    path = emit_report(model, comps, placements, housings, mass, torque)
    print(f"\n报告已写出: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
