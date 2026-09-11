#!/usr/bin/env python3
"""从 robot_model.json + placements.json 渲染《新架构参数总表》。

用法：
    python3 design/gen_spec_sheet.py                 # 写出 design/handoff/新架构参数总表.md
    python3 design/gen_spec_sheet.py --stdout        # 只打印

为什么要有它：参数总表是"人看的视图"，**不得手工维护**——
一旦手写就会与 L1 模型漂移。本脚本让表格永远等于模型当前值。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import gen_handoff  # noqa: E402
import gen_urdf  # noqa: E402

MODEL = HERE / "robot_model.json"
PLACEMENTS = HERE / "placements.json"
REFERENCE = HERE / "reference" / "tonypi_pro_baseline.json"
OUT = HERE / "handoff" / "新架构参数总表.md"


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="渲染新架构参数总表")
    ap.add_argument("--stdout", action="store_true", help="只打印，不写文件")
    args = ap.parse_args(argv)

    m: Dict[str, Any] = json.loads(MODEL.read_text(encoding="utf-8"))
    pl: Dict[str, Any] = json.loads(PLACEMENTS.read_text(encoding="utf-8"))
    ref: Dict[str, Any] = json.loads(REFERENCE.read_text(encoding="utf-8"))

    ov = m["overall"]
    budget = m["mass_budget"]
    servo_by_joint = {s["joint"]: s for s in pl["servos"]}
    total_mass = sum(l["mass_kg"] for l in m["links"])
    torques = sorted(
        ((j["name"], gen_handoff.joint_torque(m, j)) for j in m["joints"]),
        key=lambda kv: -kv[1]["required_torque_nm"])
    ts = m["servo_defaults"]
    crit = gen_handoff.torque_criteria(m)
    ankle_torque = next((t for n, t in torques if n == "left_ankle_pitch"), None)
    rated_cont = crit["continuous_rated_torque_nm"]
    rated_peak = crit["peak_torque_nm"]

    L: List[str] = []
    A = L.append

    A("# A.T.R.I. 新架构参数总表（v3 · CAD 实装口径）")
    A("")
    A("> **本文件由 `design/gen_spec_sheet.py` 从 `robot_model.json` + `placements.json` 生成，请勿手工编辑。**")
    A(f"> 模型版本 {m.get('version')}　参考机：{ref['name']}（{ref['source']}）")
    A("> 相关：`placements.json`（机器可读的配件位置）、`atri.urdf`（含真实质量与舵机体积）、"
      "`fit_report.md`（配合与质量闭合）、`design/reference/tonypi_pro_baseline.json`")
    A("")
    A("---")
    A("")
    A("## 1. 整机参数")
    A("")
    A("| 项 | 数值 | 说明 |")
    A("|---|---|---|")
    ie = m.get("installed_envelope_mm")
    if ie:
        A(f"| 身高 × 宽 × 厚（**实装**） | **{ie['height_mm']:.0f} × {ie['width_mm']:.0f} × "
          f"{ie['depth_mm']:.0f} mm** | 赛题上限 600 × 300 × 300；"
          f"来源：{ie['source']} |")
        A(f"| 身高 × 宽 × 厚（基元/运动学） | {ov['height_mm']:.1f} × {ov['width_mm']:.1f} × "
          f"{ov['depth_mm']:.1f} mm | 关节链几何累加，不含支架与舵机笼厚度 |")
    else:
        A(f"| 身高 × 宽 × 厚 | **{ov['height_mm']:.0f} × {ov['width_mm']:.0f} × "
          f"{ov['depth_mm']:.0f} mm** | 赛题上限 600 × 300 × 300 |")
    A(f"| 整机质量 | **{total_mass:.3f} kg** | 含 22 舵机 + 电子件 + 电池 + 线束紧固件 |")
    A(f"| 自由度 | **{len(m['joints'])} DOF** | 腿 {len([j for j in m['joints'] if 'hip' in j['name'] or 'knee' in j['name'] or 'ankle' in j['name']])}"
      f" + 臂 {len([j for j in m['joints'] if 'shoulder' in j['name'] or 'elbow' in j['name'] or 'gripper' in j['name']])}"
      f" + 躯干 {len([j for j in m['joints'] if 'trunk' in j['name']])}"
      f" + 头 {len([j for j in m['joints'] if 'head' in j['name']])}"
      f"（赛题要求 ≥18，且上肢+躯干 ≥10） |")
    A(f"| 舵机 | {ts['model']} × {len(pl['servos'])} | "
      f"堵转 {ts['stall_torque_nm']:.2f} N·m / **连续额定 {rated_cont:.2f} N·m（主判据）** / "
      f"峰值 {rated_peak:.2f} N·m（堵转×50%） / {ts['mass_g']:.0f} g |")
    A(f"| 供电 | 3S 11.1 V（{ts['voltage_nominal_v']} V 标称，9.0–12.6 V） | 赛题要求 ≥7.4 V |")
    A(f"| 主控 | 树莓派 4B（4 GB）+ STM32F405 下位机 | 电子件+电池合计 {budget['electronics_g']:.0f} g，见第 5.2 节 |")
    A("")
    A("---")
    A("")
    A("## 2. 与参考机（TonyPi Pro）的对齐情况")
    A("")
    A("| 维度 | 参考机 | 本机 v3 | 判定 |")
    A("|---|---|---|---|")
    A(f"| 身高 | {ref['envelope_mm']['height']:.0f} mm | **{ov['height_mm']:.0f} mm** | ✅ 对齐 |")
    A(f"| 宽度 | {ref['envelope_mm']['width']:.0f} mm | {ov['width_mm']:.0f} mm | ✅ 基本一致 |")
    A(f"| 厚度 | {ref['envelope_mm']['depth']:.0f} mm | {ov['depth_mm']:.0f} mm | ⚠️ 深 {ov['depth_mm'] - ref['envelope_mm']['depth']:.0f} mm（见下） |")
    A(f"| 自由度 | {ref['dof']['total']} | **{len(m['joints'])}** | 多 2 个躯干关节（赛题『上肢+躯干 ≥10』要求） |")
    A(f"| 每腿 / 每臂 / 头 | {ref['dof']['per_leg']} / {ref['dof']['per_arm']} / {ref['dof']['head']} | "
      f"5 / 4 / 2 | ✅ 一致（每臂 4 含末端 1） |")
    A(f"| 质量 | {ref['mass_kg']} kg | **{total_mass:.3f} kg** | 多 2 只舵机 + 树莓派方案（参考机为 CM4 类）|")
    A(f"| 舵机电压 | 身体 {ref['servos']['body']['voltage_v']} V 高压总线（头部为 "
      f"{ref['servos']['head']['voltage_v']} 微型舵机）| 11.1 V 全总线 | ✅ 同高压总线路线，且更统一 |")
    A(f"| 结构材料 | {ref['material']} | 打印 PETG（结构预算 {budget['structure_g']:.0f} g）| ⚠️ 参考机铝板件更轻，见第 6 节 |")
    A("")
    A("**偏离说明（已记录，不是疏漏）：**")
    A("")
    for d in m["reference_baseline"]["deviations"]:
        A(f"- {d}")
    A("")
    A("---")
    A("")
    A("## 3. 质量预算（五档，全部摊入 link 质量）")
    A("")
    A("| 档 | 质量 (g) | 占比 | 说明 |")
    A("|---|---|---|---|")
    for label, key, note in (
        ("结构件", "structure_g", "关节壳 / 连杆 / 足板，面密度法分配"),
        ("舵机", "servos_g", f"{len(pl['servos'])} × {ts['mass_g']:.0f} g"),
        ("电子件+电池", "electronics_g", "含 3S 11.1 V 2000 mAh 电池"),
        ("线束+紧固件", "harness_fasteners_g", "按质量比例摊派到各 link"),
    ):
        v = budget[key]
        A(f"| {label} | {v:.0f} | {v / budget['total_g'] * 100:.1f}% | {note} |")
    A(f"| **合计** | **{budget['total_g']:.0f}** | 100% | = URDF 的 sum(link mass) |")
    A("")
    A("> v1 的问题：link 质量是『结构占位预算』（合计 1650 g），既不含舵机也不含电子件 → "
      "导出的 URDF 总质量 1.80 kg，与实物口径差 300+ g，**喂给刚体引擎的动力学是错的**。"
      "v2 已修正为真实分布，`check_fit.py` 的质量闭合现为 ±0 g。")
    A("")
    if m.get("reduction_paths"):
        A(f"> 结构件质量来源：{budget.get('structure_source', '—')}")
        A("")
        A("### 3.1 减重路径（**待决策**）")
        A("")
        A("当前口径是 **CAD 实装（未执行任何减重）**；下表的数字来自协作者 "
          "`项目文档/骨架结构与集成方案.md` §7，采购前必须择一执行。"
          "踝关节占判据百分比由 `τ ≈ 0.49 × 整机质量` 复算、向上取整，"
          "主判据对**连续额定 0.98 N·m**，峰值口径（1.47 N·m）单列作短时参考。")
        A("")
        A("| 路径 | 做法 | 结构件 (g) | 整机 (kg) | 占连续额定 0.98 | 占峰值 1.47 | 代价 |")
        A("|---|---|---|---|---|---|---|")
        for r in m["reduction_paths"]:
            sg = r.get("structure_g")
            sg_s = f"{sg[0]}–{sg[1]}" if isinstance(sg, list) else "—"
            tk = r.get("total_kg")
            tk_s = f"{tk[0]}–{tk[1]}" if isinstance(tk, list) else f"{tk}"
            ap, pk = r.get("ankle_pct_continuous"), r.get("ankle_pct_peak")
            ap_s = f"{ap[0]}–{ap[1]}%" if isinstance(ap, list) else f"{ap}%"
            pk_s = f"{pk[0]}–{pk[1]}%" if isinstance(pk, list) else f"{pk}%"
            A(f"| **{r['id']} {r['name']}** | {r['method']} | {sg_s} | {tk_s} | {ap_s} | {pk_s} | {r['cost']} |")
        A("")
        A(f"**建议**：{m.get('reduction_recommendation', '')}")
        A("")
        A("> ⚠️ **按主判据（连续额定 0.98 N·m）复核：A 路径 125–135%、B 路径 110–120%、"
          "C 路径 150%，全部 >100%，三条减重路径均未达标** —— 减重后仍须继续减重"
          "或换更大扭矩舵机；峰值列（1.47 N·m）只作短时参考，不能据此判定达标。")
        A("")
        A(f"> {m.get('reduction_pending', '')}")
        A("")
    A("---")
    A("")
    A("## 4. 关节总表（22）")
    A("")
    A("| id | 关节 | 父 link | 子 link | 轴向 | 限位 (°) | 原点 (mm，父 link 系) | 驱动舵机装在哪 |")
    A("|---|---|---|---|---|---|---|---|")
    for j in sorted(m["joints"], key=lambda x: x["id"]):
        s = servo_by_joint[j["name"]]
        ax = " ".join(str(a) for a in j["axis"])
        lo, hi = j["limit_deg"]
        o = ", ".join(f"{v:.1f}" for v in j["origin_xyz_mm"])
        A(f"| {j['id']} | `{j['name']}` | `{j['parent']}` | `{j['child']}` | {ax} | "
          f"{lo} … {hi} | {o} | `{s['mounted_on_link']}` |")
    A("")
    A("---")
    A("")
    A("## 5. 配件位置总表")
    A("")
    A("### 5.1 舵机（22 只，全部同型号）")
    A("")
    A(f"型号 `{ts['model']}`　尺寸 {ts['size_mm'][0]} × {ts['size_mm'][1]} × {ts['size_mm'][2]} mm　"
      f"质量 {ts['mass_g']:.0f} g　协议 {ts['protocol']}")
    A("")
    A("| 关节 | id | 安装 link | 位置 (mm) | 轴向 |")
    A("|---|---|---|---|---|")
    for s in sorted(pl["servos"], key=lambda x: x["id"]):
        ax = " ".join(str(a) for a in s["axis"])
        o = ", ".join(f"{v:.1f}" for v in s["position_mm"])
        A(f"| `{s['joint']}` | {s['id']} | `{s['mounted_on_link']}` | {o} | {ax} |")
    A("")
    A("> 舵机位置 = 它驱动的那个关节的原点（父 link 系）。舵机**体积已写入 URDF 的 visual/collision**，"
      "但关节壳（球壳）包不住 45.2 mm 的舵机，实物靠**外部支架夹持**，见 `fit_report.md` 第 2.2 节。")
    A("")
    A("### 5.2 电子件与电池（10 件）")
    A("")
    A("| 名称 | 宿主 link | 位置 (mm) | 尺寸 (mm) | 质量 (g) | 备注 |")
    A("|---|---|---|---|---|---|")
    for e in pl["electronics"]:
        sz = " × ".join(f"{v:.0f}" for v in e["size_mm"])
        o = ", ".join(f"{v:.0f}" for v in e["position_mm"])
        A(f"| {e['name']} | `{e['link']}` | {o} | {sz} | {e['mass_g']:.0f} | {e.get('note', '')} |")
    A("")
    A("### 5.3 结构件（23 个 link）")
    A("")
    A("| link | 部位 | 基元 | 包围盒 (mm) | 结构质量 (g) | link 总质量 (g) |")
    A("|---|---|---|---|---|---|")
    for st in pl["structures"]:
        bb = " × ".join(f"{v:.0f}" for v in st["bbox_mm"])
        A(f"| `{st['link']}` | {st['group']} | {st['primitive']} | {bb} | "
          f"{st['structure_mass_g']:.0f} | {st['total_link_mass_g']:.0f} |")
    A("")
    A("---")
    A("")
    A("## 6. 力矩包络与判据")
    A("")
    A(f"单腿支撑工况：`τ ≈ 0.49 × 整机总质量`（CoP 偏移 25 mm × 动载系数 2.0，见 `gen_handoff.py`）。")
    A(f"整机 {total_mass:.3f} kg → 腿部关节需求 ≈ {0.4905 * total_mass:.2f} N·m。")
    A("")
    A(f"| 关节 | 需求 (N·m) | 占**连续额定** {rated_cont:.2f} | 占峰值 {rated_peak:.2f}（堵转×50%） | 主导因素 |")
    A("|---|---|---|---|---|")
    for name, t in torques[:8]:
        r = t["required_torque_nm"]
        flag = " ❌" if t["exceeds_continuous_rated"] else ""
        A(f"| `{name}` | **{r:.3f}** | "
          f"{gen_handoff.pct_str(t['margin_vs_continuous_rated'])}{flag} | "
          f"{gen_handoff.pct_str(t['margin_vs_peak'])} | {t['requirements_driver']} |")
    A("")
    A("**判据口径（重要）**：")
    A("")
    A(f"- ✅ **主判据 = 官方连续额定 {rated_cont:.2f} N·m**（额定负载 10 kg·cm，"
      "对应额定电流 900 mA，可持续工况）。出处：12V/30kg 级兄弟型号 DFRobot SER0070 参数表 "
      "+ 飞特《产品规格书》STS3235 5-8，见 `design/handoff/STS3215-官方规格书核验.md`。"
      "⚠️ 属 **12V 变体推断值，待实测**：仓库入库的唯一 STS3215 官方规格书是 7.4V 版，"
      f"额定仅 0.49 N·m（按此下限踝关节约 "
      f"{gen_handoff.pct_str(ankle_torque['required_torque_nm'] / 0.49)}）。")
    A(f"- ⚠️ **峰值参考 = 堵转 × 50% = {rated_peak:.2f} N·m**：取自参考机实测选型习惯"
      f"（{ref['mass_kg']} kg / {ref['dof']['total']} DOF 量产人形用 "
      f"{ref['servos']['body']['stall_torque_kgcm']:.0f} kg·cm 堵转舵机）。"
      "**只能作短时峰值上限，比官方额定乐观 50%，不是连续设计值。**")
    A("- ℹ️ 早期『额定 1.0 N·m 无出处』的说法**方向正确**（量级对），现按 12V 变体推断值 "
      "0.98 N·m 采用；但它仍不是本 SKU 的 12V 规格书，故标『待实测』，"
      "不能据此写成已达标的乐观结论。")
    A("- ⚠️ **仍待实测**：买 1 只 STS3215（12V 版）实测连续扭矩与温升，"
      "这是唯一能同时消除『额定值不确定』和『3S 末端电压降额』两个问题的动作。")
    over = [(name, t) for name, t in torques if t["exceeds_continuous_rated"]]
    if over:
        A("")
        names = "、".join(f"`{n}` {t['required_torque_nm']:.3f} N·m"
                          f"（{gen_handoff.pct_str(t['margin_vs_continuous_rated'])}）"
                          for n, t in over)
        A(f"- ❌ **当前状态：{len(over)} 个关节超连续额定** —— {names}。"
          f"成因是结构件按 CAD 实装口径计 {budget['structure_g']:.0f} g："
          "**必须执行第 3.1 节的减重路径（推荐 A+B）或换更大扭矩舵机**，"
          "否则这些关节在连续工况下超载。")

    A("")
    A("---")
    A("")
    A("## 7. 怎么拿去建模与仿真")
    A("")
    A("| 用途 | 用哪个文件 | 说明 |")
    A("|---|---|---|")
    A("| 刚体动力学（PyBullet / MuJoCo / Webots） | `design/atri.urdf`（交接包内同名副本） | "
      f"23 link / 22 joint，**质量已含舵机与电子件**（合计 {total_mass * 1000:.0f} g），舵机体积已进 collision |")
    A("| 零件位置与参数（程序读） | `design/placements.json` | 22 舵机 + 10 电子件 + 23 结构件的宿主/坐标/尺寸/质量 |")
    A("| CAD / 装配建模 | 本表第 4、5 节 | 含关节原点与配件坐标，可直接作为装配基准 |")
    A("| 舵机非理想特性 | `design/packages/servo_spec.json` | 死区/间隙/延迟/扭矩饱和；额定口径已更新 |")
    A("")
    A("```python")
    A("# PyBullet 载入示例")
    A('import pybullet as p')
    A('p.connect(p.GUI); p.setGravity(0, 0, -9.81)')
    A('robot = p.loadURDF("design/atri.urdf", useFixedBase=False)')
    A(f"# 质量核对：sum(link mass) 应等于 {total_mass:.3f} kg（v3 CAD 实装口径）")
    A("```")
    A("")
    A("**两个已知的仿真保真度限制（别当没看见）：**")
    A("")
    A("1. **惯量按主壳基元 + link 总质量计算**，舵机/电子件的质量已计入总质量，"
      "但其自身转动惯量按『同质化』处理 —— 对行走稳定性评估影响有限，对高动态动作要复核。")
    A("2. **舵机附加体长边统一沿 x 轴摆放**（设计暂定），详细设计定支架朝向时需复核。")
    A("")
    A("---")
    A("")
    A("## 8. 复现命令")
    A("")
    A("```bash")
    A("python3 design/gen_v2_baseline.py --check    # 看当前模型版本")
    A("python3 design/gen_urdf.py --summary --validate --write")
    A("python3 design/gen_handoff.py                # 交接包 + 附件")
    A("python3 design/check_fit.py                  # 配合与质量闭合")
    A("python3 design/gen_spec_sheet.py             # 本表")
    A("python3 design/gen_drawings.py && python3 design/gen_render.py")
    A("cd 软件/atri && python3 -m unittest discover -s tests")
    A("```")
    A("")

    text = "\n".join(L)
    if args.stdout:
        print(text)
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"已写出: {OUT}  ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
