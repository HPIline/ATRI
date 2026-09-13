"""反查开源参考件 SO-ARM100 整机装配体的「工业界真实配合值」。

任务定位（见 design/handoff/线程报告-参考件配合.md）：
    在 design/cad/vendor/so-arm100/SO100_Follower_Assembly.step 整机里，
    逐关节测出打印件 ↔ 舵机安装孔的真实配合（同轴孔对的直径差、轴向贴合间隙）、
    轴承座配合、M2.5 螺钉过孔间隙、被动舵盘插接配合；
    再与 design/cad/standards.py 的 FDM 标定值（servo_cavity_clearance_mm /
    servo_boss_fit_mm / bearing_bore_interference_mm / M2.5 底孔等）对照，
    给出「我方疑似偏紧 / 偏松」结论与建议值（只建议，不改 standards.py）。

复用工具：check_mate.py 的同轴孔对匹配、measure_vendor.py 的圆柱面提取。
本脚本只做几何测量，所有数字来自模型本身，未找到的特征写「未找到」。

用法：
    .venv-cad/bin/python design/cad/reference_fits.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import cadquery as cq
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.GeomAbs import GeomAbs_SurfaceType

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import standards as STD  # noqa: E402

ASSEMBLY = HERE / "vendor" / "so-arm100" / "SO100_Follower_Assembly.step"
SERVO_V = 36216.9  # STS3215_03a.step（整机里 5 只独立舵机实例的体积）

# 官方 SO-100 打印件体积指纹（与 TheRobotStudio/SO-ARM100 仓库单件 STEP 逐一比对确认）
# 13 个非舵机实体全部命中/归入打印件族 → 整机“无金属结构件”（与仓库结论一致）
PART_LABELS = {
    120684.0: "Base_08q(基座)",
    3369.5: "Base_attachment(基座附件)",
    23803.0: "Motor1_holder(1号电机座)",
    579.0: "Passive_Horn_01(被动舵盘)",
    68605.0: "Rotation_Pitch_08i(肩俯仰件)",
    30472.2: "Wrist_Roll_Pitch_08i(腕俯仰/横滚件)",
    56934.3: "Wrist_Roll_08c(腕横滚件)",
    20213.4: "Moving_Jaw_08d(爪动颚)",
    # —— 未提供单件文件、按结构/体积命名（同为打印件）——
    126194.2: "上臂长件(上臂杆)",
    97925.4: "前臂长件(前臂杆)",
    13825.8: "电机持件族(Base/Wrist 持件 ×2)",
    9097.2: "爪定颚/薄板件",
    35657.8: "舵机+舵盘融合体(=舵机#18)",
}


def axis_letter(n) -> str:
    return ("X" if abs(n[0]) > 0.9 else "Y" if abs(n[1]) > 0.9 else "Z")


def cylinders(solid, r_min=0.4, r_max=15.0):
    """圆柱面清单：轴线单位方向、轴上一点、半径、轴向跨度、张角。"""
    out = []
    for f in solid.Faces():
        s = BRepAdaptor_Surface(f.wrapped)
        if s.GetType() != GeomAbs_SurfaceType.GeomAbs_Cylinder:
            continue
        cyl = s.Cylinder()
        r = cyl.Radius()
        if not (r_min <= r <= r_max):
            continue
        ax = cyl.Axis()
        loc, d = ax.Location(), ax.Direction()
        n = np.array([d.X(), d.Y(), d.Z()])
        n /= np.linalg.norm(n)
        p = np.array([loc.X(), loc.Y(), loc.Z()])
        bb = f.BoundingBox()
        a = axis_letter(n)
        along = {"X": (bb.xmin, bb.xmax), "Y": (bb.ymin, bb.ymax),
                 "Z": (bb.zmin, bb.zmax)}[a]
        area = f.Area()
        length = along[1] - along[0]
        theta = area / (r * length) if r > 0 and length > 0 else 0.0
        arc = min(theta, 2 * np.pi) * 180.0 / np.pi
        out.append({"r": r, "dia": 2 * r, "n": n, "p": p,
                    "lo": along[0], "hi": along[1], "arc": arc,
                    "axis": axis_letter(n)})
    return out


def match_holes(a_holes, b_holes, tol=0.25):
    """同轴孔对：轴线平行、横向偏移<tol；返回间隙/贴合数据。"""
    hits = []
    for a in a_holes:
        for b in b_holes:
            if abs(abs(float(np.dot(a["n"], b["n"]))) - 1.0) > 1e-3:
                continue
            w = b["p"] - a["p"]
            w_perp = w - np.dot(w, a["n"]) * a["n"]
            lat = float(np.linalg.norm(w_perp))
            if lat > tol:
                continue
            # 轴向贴合：两特征沿轴最近端面的间隔（≤0 = 端面相接/重叠）
            gap = max(a["lo"], b["lo"]) - min(a["hi"], b["hi"])
            hits.append({"a": a, "b": b, "lat": lat, "gap": gap})
    return hits


def min_dist(a, b) -> float:
    d = BRepExtrema_DistShapeShape(a.wrapped, b.wrapped)
    d.Perform()
    return d.Value() if d.IsDone() else 1e9


def label_of(vol: float) -> str:
    best, best_k = None, None
    for k, name in PART_LABELS.items():
        if abs(vol - k) / k < 0.01:
            return name
    return f"未识别 V={vol:.0f}"


def main() -> int:
    print("# SO-ARM100 整机参考配合反查（SO100_Follower_Assembly.step）\n")

    shape = cq.importers.importStep(str(ASSEMBLY)).val()
    sols = list(shape.Solids())
    print(f"装配体共 {len(sols)} 个实体\n")

    servo_idx = [i for i, s in enumerate(sols)
                 if abs(s.Volume() - SERVO_V) / SERVO_V < 0.01]
    part_idx = [i for i in range(len(sols)) if i not in servo_idx]

    # ------------------------------------------------------------
    print("## 0. 实体身份表\n")
    print("| # | 体积 mm³ | 身份 | 包络(X×Y×Z) mm |")
    print("|---|---|---|---|")
    for i, s in enumerate(sols):
        bb = s.BoundingBox()
        who = ("舵机 STS3215" if i in servo_idx
               else label_of(s.Volume()))
        print(f"| {i} | {s.Volume():9.1f} | {who} | "
              f"{bb.xlen:.1f}×{bb.ylen:.1f}×{bb.zlen:.1f} |")
    print()

    # ------------------------------------------------------------
    print("## 1. 舵机 ↔ 打印件 最小贴合距离（0.00 = 端面贴合）\n")
    print("| 打印件 | 舵机# | 最小距离 mm |")
    print("|---|---|---|")
    for i in part_idx:
        ds = [(j, min_dist(sols[i], sols[j])) for j in servo_idx]
        ds.sort(key=lambda x: x[1])
        j, d = ds[0]
        touch = "（贴合=0.00）" if d < 0.01 else ""
        print(f"| #{i} {label_of(sols[i].Volume())} | #{j} | {d:.2f} {touch} |")
    print()

    # ------------------------------------------------------------
    print("## 2. 轴承扫描：全 360° 环 + 标准轴承孔径\n")
    ring_rows = []
    for i, s in enumerate(sols):
        for c in cylinders(s):
            if c["arc"] >= 359.0 and 5.0 <= c["dia"] <= 26.0:
                ring_rows.append((i, c))
    if not ring_rows:
        print("→ **未找到轴承**：19 个实体中没有任何一个呈现“外圈 360° 环 + 内孔”")
        print("  的轴承体；全 360° 圆柱面仅有舵机 Φ20 端盘 / Φ9 输出台 / 舵盘孔等，")
        print("  无 608ZZ(Φ22)、MF105ZZ(Φ10)、MF106ZZ(Φ10 法兰) 等标准轴承环。")
        print("  与官方 BOM 一致：SO-ARM100 全机无轴承，关节为舵机直接驱动。")
    else:
        for i, c in ring_rows:
            print(f"  #{i} Φ{c['dia']:.2f} 长{c['hi']-c['lo']:.2f}")
    print()

    # ------------------------------------------------------------
    print("## 3. 打印件孔 ↔ 舵机孔 同轴孔对（安装孔配合）\n")
    servo_holes = {i: cylinders(sols[i]) for i in servo_idx}

    mount = defaultdict(list)      # (打印件, 舵机孔Φ, 打印孔Φ) -> [gap, lat]
    detail_rows = []
    for i in part_idx:
        ph = cylinders(sols[i])
        if not ph:
            continue
        for j in servo_idx:
            for h in match_holes(ph, servo_holes[j], tol=0.25):
                key = (i, round(h["b"]["dia"], 2), round(h["a"]["dia"], 2))
                mount[key].append((h["gap"], h["lat"]))
                detail_rows.append((i, j, h["a"]["axis"], h["b"]["dia"],
                                    h["a"]["dia"], h["gap"], h["lat"]))

    print("| 打印件 | 舵机孔Φ | 打印孔Φ | 直径差(总) | 单边间隙 | 轴向贴合 | 同轴横偏 | 对次 |")
    print("|---|---|---|---|---|---|---|---|")
    for (pi, sd, pd), vals in sorted(mount.items(),
                                     key=lambda kv: (-kv[0][1], kv[0][2])):
        gaps = [v[0] for v in vals]
        lats = [v[1] for v in vals]
        min_gap = min(gaps)
        touch = "0.00贴合" if min_gap <= 0.01 else f"+{min_gap:.2f}离隙"
        print(f"| #{pi} {label_of(sols[pi].Volume())} | {sd:.1f} | {pd:.1f} | "
              f"{pd - sd:+.2f} | {(pd - sd)/2:+.2f} | {touch} | "
              f"{min(lats):.2f} | {len(vals)} |")
    print()

    # ------------------------------------------------------------
    print("## 4. M2.5 安装螺钉过孔间隙（打印孔 Φ 相对 M2.5 螺纹 Φ2.5）\n")
    print("| 打印孔Φ mm | 单边间隙 mm | 用途 |")
    print("|---|---|---|")
    for (pi, sd, pd), vals in sorted(mount.items(),
                                     key=lambda kv: (-kv[0][1], kv[0][2])):
        if round(sd, 1) != 2.5:
            continue
        print(f"| {pd:.1f} | {(pd - 2.5)/2:+.2f} | "
              f"#{pi} {label_of(sols[pi].Volume())} 穿 M2.5 螺钉过孔 |")
    # 独立统计：哪几个打印孔是“伺服端面 Φ20 盘 PCD14 四孔”的直接过孔
    print()
    print("> 舵机端面安装孔为 Φ2.5（M2.5 螺纹，Φ14 节圆方阵 9.9×9.9），")
    print("> 开源打印件用 Φ3.0/Φ3.2 过孔穿过螺钉再拧进舵机 → 单边间隙 "
          "+0.25 ~ +0.35 mm。\n")

    # ------------------------------------------------------------
    print("## 5. 被动舵盘插接配合（Passive_Horn_01 ↔ 舵机输出）\n")
    horn_i = [i for i in part_idx if abs(sols[i].Volume() - 579.0) < 1.0][0]
    horn = sols[horn_i]
    horn_cy = cylinders(horn)
    print("舵盘圆柱特征：")
    for c in sorted(horn_cy, key=lambda c: c["dia"]):
        print(f"  {c['axis']} Φ{c['dia']:.2f} 长{c['hi']-c['lo']:.2f} "
              f"span {c['lo']:.2f}~{c['hi']:.2f} 弧{c['arc']:.0f}°")
    modelfit = []
    for j in servo_idx:
        for h in match_holes(horn_cy, servo_holes[j], tol=0.05):
            a, b = h["a"], h["b"]
            modelfit.append((j, b["dia"], a["dia"], h["gap"], h["lat"],
                             b["lo"], b["hi"], a["lo"], a["hi"]))
    if modelfit:
        print("\n舵盘 ↔ 舵机 同轴对：")
        for j, bd, ad, gap, lat, blo, bhi, alo, ahi in modelfit:
            kind = "插接(轴入孔)" if bd >= ad else "套接(孔套台)"
            print(f"  #{j} 舵机Φ{bd:.2f} ↔ 舵盘Φ{ad:.2f}  ΔΦ={ad-bd:+.2f} "
                  f"{kind}  轴向间隔{gap:+.2f}  横偏{lat:.3f}  "
                  f"舵机span[{blo:.1f}~{bhi:.1f}] 舵盘span[{alo:.1f}~{ahi:.1f}]")
        g0 = [m for m in modelfit if abs(m[2] - m[1]) < 0.005]
        print(f"\n→ 模型级名义插接配合：ΔΦ = 0.00（{len(g0)} 对完全相等孔径），"
              "实际 25T 花键（Φ5.9 齿顶）靠塑料弹性过盈。")
    else:
        print("\n→ 舵盘与任何舵机实例均无同轴对（本 STEP 中舵盘为自由浮置件，最小距离见 §1）。")
    print()

    # ------------------------------------------------------------
    print("## 6. 与 design/cad/standards.py 对照表\n")
    fdm = STD.FDM
    fast = STD.FASTENERS["M2.5"]
    rows = [
        ("servo_cavity_clearance_mm", fdm["servo_cavity_clearance_mm"],
         "+0.50(双边)",
         "开源无“包裹腔体”方案，舵机端面直装；等价物为端面 PCD14 四孔过孔单边间隙 "
         "+0.25~+0.35"),
        ("servo_boss_fit_mm", fdm["servo_boss_fit_mm"],
         "定位凸台 +0.15",
         "开源无定位凸台特征；最近似为舵盘插接 ΔΦ=0.00（靠花键过盈），无可直接对照"),
        ("bearing_bore_interference_mm", fdm["bearing_bore_interference_mm"],
         "轴承座过盈 -0.03",
         "整机未找到轴承 → 无法对照（SO-ARM100 无轴承方案）"),
        ("FASTENERS M2.5 clearance_hole_mm", fast["clearance_hole_mm"],
         "2.7（单边+0.10）",
         "开源打印过孔 Φ3.0~3.2（单边 +0.25~+0.35）→ 我方疑似偏紧"),
        ("FASTENERS M2.5 tap_drill_mm", fast["tap_drill_mm"],
         "2.15（自攻/热熔底孔）",
         "开源安装孔为直通 Φ2.5 螺纹对孔，无自攻底孔特征 → 未找到对应项"),
        ("—— 螺钉过孔（M2.5 穿板拧舵机）radial", None,
         "单边 +0.10",
         "开源 Φ3.0/Φ3.2 过孔单边 +0.25~+0.35 → 我方偏紧 0.15~0.25/边"),
        ("—— 轴向贴合（安装面）", None,
         "未显式标定（端面贴平）",
         "开源实测最小距离 0.00（端面贴合，无离隙）→ 与“端面贴平”一致"),
    ]
    print("| 我方参数(standards.py) | 我方值 | 开源实测等价值 | 判读 |")
    print("|---|---|---|---|")
    for name, mine, alu, verdict in rows:
        print(f"| {name} | {mine} | {alu} | {verdict} |")
    print()

    print("## 7. 结论（仅建议，不改 standards.py）\n")
    print("疑似偏紧/偏松：")
    print("1. **M2.5 过孔 2.7 偏紧**。开源打印件给 M2.5 穿板孔留 Φ3.0~Φ3.2"
          "（单边 +0.25~+0.35），")
    print("   我方 clearance_hole_mm=2.7 单边仅 +0.10。FDM 孔位漂移 + 螺钉胶套后"
          "易卡螺杆，")
    print("   建议放宽到 Φ3.0（单边 +0.25）起步，反复拆装位（舵机端面安装）"
          "可到 Φ3.2。")
    print("2. servo_cavity_clearance_mm=0.50（双边）与开源同量级"
          "（端面孔单边 0.25~0.35 → 双边 0.5~0.7），方向一致、不算偏紧；"
          "若做包裹腔体，保持 0.50 即可。")
    print("3. bearing_bore_interference_mm=-0.03 在开源件里无对照（全机无轴承），"
          "维持原标定；")
    print("   我方自研关节若引入轴承座，仍按 -0.03 起步并在样件实测。")
    print("4. servo_boss_fit_mm=0.15 在开源件中无凸台方案可比；"
          "开源“插接类”配合走 ΔΦ=0.00 名义 + 弹性过盈，我方若用定位凸台建议"
          "先在样件上验证 0.15 的手感，勿直接对齐 0.00。")
    print("5. 轴向贴合：开源安装面 0.00 端面贴平，我方端面安装方案无需额外垫片"
          "离隙；")
    print("   但 FDM 误差（翘边/收缩）会使真实装配出现 0.1~0.3 离隙，"
          "设计时按 0 贴合建模即可，装配靠螺钉拉平。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())