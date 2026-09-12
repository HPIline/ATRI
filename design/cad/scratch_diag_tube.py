#!/usr/bin/env python3
"""一次性诊断脚本（第 11 轮 · 管-舵机让位 / 躯干框架连通性 / 头颈簇）。

⚠️ **只读诊断**：不改任何几何、不写 `out/**`。判定原语与 `interference.py` 同源
   —— `Shape.intersect()` 的**真布尔求交**，不是包围盒。

⚠️ 与官方脚本的一处口径差异（本脚本更严）：
   `assembly.py` / `interference.py` 用 `Workplane.val()` 取零件实体，而 `val()`
   只返回 **objects[0]** —— 多实体零件（如 `torso_frame` 有 3 个 solid）**只被查了第一块**。
   本脚本对每个零件的**全部 solid** 两两求交后求和（`intersect_all()`），
   所以本脚本报出的体积 ≥ 官方口径。

三个模式：
    --mode tube   管 × 邻件：把相交体反变换回**管件局部坐标系**（管轴 = 局部 Z，
                  管体占 z ∈ [z0, z0+length]），给出"舵机从哪一侧、沿轴哪一段穿出来"。
    --mode torso  `torso_frame()` 的连通分量拆分：每块实体的体积/包围盒/特征归属，
                  以及两两之间的**最近点距离**（为什么断开、桥接肋该落在哪）。
    --mode neck   头颈簇（cage/servo/head_shell/相机/RPi）成对干涉表 + 世界包围盒。
    --all          一次装配、三个模式全跑（省一次 1–3 分钟的装配）。

用法：
    .venv-cad/bin/python design/cad/scratch_diag_tube.py --mode tube
    .venv-cad/bin/python design/cad/scratch_diag_tube.py --all
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

import cadquery as cq
from OCP.gp import gp_Trsf, gp_Pnt

import assembly as A
import skeleton as sk

Mat = List[List[float]]


# --------------------------------------------------------------------------
# 4×4 刚体矩阵工具（与 assembly.py 同一份约定：行主序、R|t）
# --------------------------------------------------------------------------
def inv_rigid(m: Mat) -> Mat:
    """刚体矩阵求逆：R^T | −R^T·t（装配矩阵都是旋转+平移，无缩放）。"""
    rt = [[m[j][i] for j in range(3)] for i in range(3)]
    t = [m[i][3] for i in range(3)]
    tt = [-sum(rt[i][k] * t[k] for k in range(3)) for i in range(3)]
    return [rt[i] + [tt[i]] for i in range(3)] + [[0.0, 0.0, 0.0, 1.0]]


def trsf_of(m: Mat) -> gp_Trsf:
    t = gp_Trsf()
    t.SetValues(m[0][0], m[0][1], m[0][2], m[0][3],
                m[1][0], m[1][1], m[1][2], m[1][3],
                m[2][0], m[2][1], m[2][2], m[2][3])
    return t


def xform(shape: cq.Shape, m: Mat) -> cq.Shape:
    return shape.transformShape(cq.Matrix(trsf_of(m)))


def rot_only(m: Mat, v: Sequence[float]) -> Tuple[float, float, float]:
    x, y, z = v
    return (m[0][0] * x + m[0][1] * y + m[0][2] * z,
            m[1][0] * x + m[1][1] * y + m[1][2] * z,
            m[2][0] * x + m[2][1] * y + m[2][2] * z)


def bb_of(shapes: Sequence[cq.Shape]):
    bb = None
    for s in shapes:
        b = s.BoundingBox()
        bb = b if bb is None else bb.add(b)
    return bb


def bb_overlap(a: Sequence[cq.Shape], b: Sequence[cq.Shape]) -> bool:
    ba, bb = bb_of(a), bb_of(b)
    return (min(ba.xmax, bb.xmax) - max(ba.xmin, bb.xmin) > 0 and
            min(ba.ymax, bb.ymax) - max(ba.ymin, bb.ymin) > 0 and
            min(ba.zmax, bb.zmax) - max(ba.zmin, bb.zmin) > 0)


def intersect_all(sa: Sequence[cq.Shape], sb: Sequence[cq.Shape]
                  ) -> Tuple[Optional[cq.Shape], float, int]:
    """全部 solid 两两真布尔求交；返回（合并体或 None，体积合计，成功对数）。"""
    commons: List[cq.Shape] = []
    total = 0.0
    n = 0
    for x in sa:
        for y in sb:
            if not bb_overlap([x], [y]):
                continue
            try:
                c = x.intersect(y)
            except Exception:  # noqa: BLE001
                continue
            if c is None:
                continue
            v = float(c.Volume())
            if v <= 0.0:
                continue
            commons.append(c)
            total += v
            n += 1
    if not commons:
        return None, 0.0, 0
    if len(commons) == 1:
        return commons[0], total, n
    return cq.Compound.makeCompound(commons), total, n


def min_dist(a: cq.Shape, b: cq.Shape
             ) -> Tuple[Optional[float], Tuple[float, float, float],
                        Tuple[float, float, float], str]:
    """两形状最近距离（OCC BRepExtrema）。返回（距离或 None, 点1, 点2, 错误）。"""
    try:
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        d = BRepExtrema_DistShapeShape(a.wrapped, b.wrapped)
        d.Perform()
        if not d.IsDone():
            return None, (0, 0, 0), (0, 0, 0), "IsDone=False"
        v = float(d.Value())
        if v <= 0.0:
            return 0.0, (0, 0, 0), (0, 0, 0), ""
        p1, p2 = d.PointOnShape1(1), d.PointOnShape2(1)
        return (v, (p1.X(), p1.Y(), p1.Z()), (p2.X(), p2.Y(), p2.Z()), "")
    except Exception as exc:  # noqa: BLE001
        return None, (0, 0, 0), (0, 0, 0), f"{type(exc).__name__}: {exc}"


def tube_metrics(s: cq.Shape) -> Dict[str, Any]:
    """相交体在**已变换到管局部系**后的定位指标。"""
    bb = s.BoundingBox()
    try:
        c = s.Center().toTuple()
    except Exception:  # noqa: BLE001
        c = ((bb.xmin + bb.xmax) / 2.0, (bb.ymin + bb.ymax) / 2.0,
             (bb.zmin + bb.zmax) / 2.0)
    az = math.degrees(math.atan2(c[1], c[0]))
    rmin, rmax = 1e9, -1e9
    azs: List[float] = []
    try:
        for v in s.Vertices():
            x, y, z = v.toTuple()
            r = math.hypot(x, y)
            rmin, rmax = min(rmin, r), max(rmax, r)
            azs.append(math.degrees(math.atan2(y, x)))
    except Exception:  # noqa: BLE001
        pass
    span = None
    if azs:
        azs_sorted = sorted(azs)
        gaps = [(azs_sorted[(i + 1) % len(azs_sorted)] - azs_sorted[i]) % 360.0
                for i in range(len(azs_sorted))]
        k = max(range(len(gaps)), key=lambda i: gaps[i])
        span = (azs_sorted[(k + 1) % len(azs_sorted)], azs_sorted[k])
    return {
        "x": (bb.xmin, bb.xmax), "y": (bb.ymin, bb.ymax), "z": (bb.zmin, bb.zmax),
        "z_len": bb.zmax - bb.zmin,
        "centroid": c,
        "azimuth_deg": az,
        "r": (None if rmin > 1e8 else rmin, None if rmax < -1e8 else rmax),
        "az_span": span,
        "n_vertices": len(azs),
    }


def inside(shape: cq.Shape, p: Sequence[float]) -> bool:
    try:
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier
        from OCP.TopAbs import TopAbs_State
        c = BRepClass3d_SolidClassifier(shape.wrapped, gp_Pnt(*p), 1e-6)
        return c.State() == TopAbs_State.TopAbs_IN
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------
# 装配体加载
# --------------------------------------------------------------------------
def load():
    kin = A.Kin(A.DESIGN / "atri.urdf")
    placements = json.loads(
        (A.DESIGN / "placements.json").read_text(encoding="utf-8"))
    items, log = A.build_assembly(kin, placements)
    bad = [l for l in log if not l.get("ok")]
    print(f"[装配] 零件 {len(items)} 个（失败 {len(bad)}）")
    for b in bad:
        print(f"  [ERR] {b['name']}: {b.get('err')}")
    n_multi = 0
    parts: Dict[str, List[cq.Shape]] = {}
    for n, w in items:
        ss = w.solids().vals()
        if len(ss) > 1:
            n_multi += 1
            print(f"  [多实体] {n}: {len(ss)} 个 solid")
        parts[n] = ss
    print(f"[装配] 多实体零件 {n_multi} 个")
    return kin, items, parts


def tube_specs() -> Dict[str, Dict[str, Any]]:
    """link → limb_tube 参数（来自 assembly.LINK_BULK，不另写一套）。"""
    out: Dict[str, Dict[str, Any]] = {}
    for link, parts in A.LINK_BULK.items():
        for pname, kw in parts:
            if pname == "limb_tube":
                out[f"{link}__limb_tube"] = dict(kw)
    return out


# --------------------------------------------------------------------------
# 模式 1：管 × 邻件
# --------------------------------------------------------------------------
def mode_tube(kin: A.Kin, parts: Dict[str, List[cq.Shape]], min_vol: float) -> None:
    specs = tube_specs()
    print("=" * 112)
    print("【模式 tube】管 × 邻件干涉 —— 相交体在**管局部坐标系**中的定位")
    print("  局部系约定：管轴 = 局部 Z；管体占 z ∈ [z0, z0+length]；"
          "方位角 0° = +X 侧，90° = +Y 侧")
    print("  管几何：OD 40 / ID 34.2（壁半径 17.1…20.0）；"
          "减重窗中心在 ±X（0°/180°）；M3 锁紧孔在 90°/210°/330°、z=6 与 z=length−6")
    print("=" * 112)
    fam_total = 0.0
    fam_pairs = 0
    for name, kw in specs.items():
        if name not in parts:
            print(f"\n!! {name} 不在装配体里")
            continue
        tube = parts[name]
        m = kin.world[name.split("__")[0]]
        mi = inv_rigid(m)
        length = float(kw.get("length", 0.0))
        z0 = float(kw.get("z0", 0.0))
        tv = sum(float(s.Volume()) for s in tube)
        rows = []
        for other, ss in parts.items():
            if other == name or "limb_tube" in other:
                continue
            if not bb_overlap(tube, ss):
                continue
            common, vol, npair = intersect_all(tube, ss)
            if common is None or vol <= min_vol:
                continue
            local = xform(common, mi)
            met = tube_metrics(local)
            rows.append((vol, other, met, npair))
        rows.sort(key=lambda r: -r[0])
        invaded = sum(r[0] for r in rows)
        fam_total += invaded
        fam_pairs += len(rows)
        print(f"\n--- {name}  长 {length:.1f}  z0 {z0:.1f}  "
              f"管体 z ∈ [{z0:.1f}, {z0 + length:.1f}]  自身体积 {tv:.0f} mm³")
        if not rows:
            print("    （无干涉）")
            continue
        print(f"    被侵占合计 {invaded:.0f} mm³（自身体积的 {invaded / tv * 100:.1f}%），"
              f"{len(rows)} 对")
        print("    | 邻件 | 体积 mm³ | 占管 % | 局部 X | 局部 Y | 局部 Z（轴向） | "
              "轴向段 | 半径范围 | 方位角 | 方位区间 |")
        print("    |---|---|---|---|---|---|---|---|---|---|")
        for vol, other, met, npair in rows:
            az = met["az_span"]
            azs = "—" if az is None else f"{az[0]:.0f}°…{az[1]:.0f}°"
            r = met["r"]
            rs = "—" if r[0] is None else f"{r[0]:.1f}…{r[1]:.1f}"
            print(f"    | `{other}` | {vol:.0f} | {vol / tv * 100:.1f} | "
                  f"[{met['x'][0]:.1f},{met['x'][1]:.1f}] | "
                  f"[{met['y'][0]:.1f},{met['y'][1]:.1f}] | "
                  f"[{met['z'][0]:.1f},{met['z'][1]:.1f}] | "
                  f"{met['z_len']:.1f} | {rs} | {met['azimuth_deg']:.0f}° | {azs} |")
        servo_rows = [r for r in rows if r[1].startswith("servo__")]
        if servo_rows:
            print("    · 舵机伙伴在管局部系的位姿（关节原点 = 输出轴与舵盘交点）：")
            for vol, other, met, _ in servo_rows:
                jname = other[len("servo__"):]
                mj = A.mat_mul(mi, kin.joint_world(jname))
                o = (mj[0][3], mj[1][3], mj[2][3])
                ax = rot_only(mj, kin.joints[jname]["axis"])
                st = float(A.JOINT_SCHEME.get(jname, {}).get("stagger", 0.0) or 0.0)
                print(f"      - {jname}: 原点局部 ({o[0]:+.2f}, {o[1]:+.2f}, {o[2]:+.2f})"
                      f"，轴局部 ({ax[0]:+.2f}, {ax[1]:+.2f}, {ax[2]:+.2f})"
                      f"，stagger {st:.1f}，轴线距管轴 {math.hypot(o[0], o[1]):.2f} mm")
    print(f"\n【族汇总】{fam_pairs} 对，合计 {fam_total:.0f} mm³")


# --------------------------------------------------------------------------
# 模式 2：torso_frame 连通分量
# --------------------------------------------------------------------------
def mode_torso() -> None:
    print("=" * 112)
    print("【模式 torso】torso_frame() 实体拆分 + 最近点距离")
    print("=" * 112)
    w = sk.torso_frame()
    solids = w.solids().vals()
    tot = sum(float(s.Volume()) for s in solids)
    print(f"Workplane.objects = {len(w.objects)}；solid 数 = {len(solids)}"
          f"（=1 才是单一可打印体）；体积合计 {tot:.0f} mm³；"
          f"is_valid = {[bool(s.isValid()) for s in solids]}")
    for i, so in enumerate(solids, 1):
        bb = so.BoundingBox()
        print(f"  实体 {i}: 体积 {float(so.Volume()):9.0f} mm³  "
              f"x[{bb.xmin:7.2f},{bb.xmax:7.2f}] "
              f"y[{bb.ymin:7.2f},{bb.ymax:7.2f}] "
              f"z[{bb.zmin:7.2f},{bb.zmax:7.2f}]  "
              f"尺寸 {bb.xlen:.1f}×{bb.ylen:.1f}×{bb.zlen:.1f}")
    if len(solids) > 1:
        print("\n  两两最近点（为什么断开、桥接肋该落在哪）：")
        for i in range(len(solids)):
            for j in range(i + 1, len(solids)):
                v, p1, p2, err = min_dist(solids[i], solids[j])
                if v is None:
                    print(f"  实体{i + 1} ↔ 实体{j + 1}: 距离计算失败（{err}）")
                    continue
                print(f"  实体{i + 1} ↔ 实体{j + 1}: 最近距离 {v:.3f} mm；"
                      f"点1 ({p1[0]:.2f}, {p1[1]:.2f}, {p1[2]:.2f})；"
                      f"点2 ({p2[0]:.2f}, {p2[1]:.2f}, {p2[2]:.2f})")

    probes = {
        "trunk_pitch 叉臂": (0.0, 25.0, 0.0),
        "电池仓层板(60×56 挖空外)": (40.0, 0.0, 19.3),
        "主舱立柱(避开 Ø5 走线孔)": (53.0, 48.0, 40.0),
        "电控层板(52×60 挖空外)": (35.0, 0.0, 43.3),
        "上环边框(x∈44..54)": (49.0, 0.0, 64.5),
        "上环边框(y∈42..52)": (0.0, 47.0, 64.5),
        "颈座顶板(64..69)": (20.0, 15.0, 66.5),
        "颈座 shelf(60..62.6)": (25.0, 15.0, 61.3),
        "胸段立柱(±26,±20)": (26.0, 20.0, 60.0),
        "肩 pylon 竖板(x=16)": (16.0, 45.0, 11.8),
        "肩笼座圆柱(y=66..80 上部)": (0.0, 70.0, 11.8),
        "肩笼座圆柱(−Y 对称)": (0.0, -70.0, 11.8),
        "肩笼座下部残片(+Y)": (0.0, 70.0, -2.0),
        "肩笼座下部残片(−Y)": (0.0, -70.0, -2.0),
        "下筋(y=±54,z=−1.2..2.8)": (40.0, 54.0, 0.5),
        "后立柱下延(z=−9.3..9.3)": (-50.0, 48.0, 0.0),
        "电池压条(y=±53,z≈20.6)": (0.0, -53.0, 21.0),
    }
    print("\n  特征探针（点落在哪块实体里；OUT = 空腔/不属于本件）：")
    for label, p in probes.items():
        hit = [i + 1 for i, so in enumerate(solids) if inside(so, p)]
        print(f"    {label:30s} {str(p):22s} → 实体 {hit if hit else 'OUT'}")

    # −Y 残片到底存不存在？用探针盒与各实体求交算体积
    print("\n  ±Y 笼座下部残片体积（探针盒 y∈[66,80] 或 [−80,−66]，z∈[−6,0.2]）：")
    for sign in (1, -1):
        probe = sk.box(40.0, 14.0, 6.2, at=(0.0, sign * 66.0, -6.0)).val()
        for i, so in enumerate(solids, 1):
            try:
                c = so.intersect(probe)
                v = float(c.Volume()) if c is not None else 0.0
            except Exception:  # noqa: BLE001
                v = -1.0
            if v > 1.0:
                print(f"    y{'+' if sign > 0 else '−'} 残片 ∩ 实体{i} = {v:.1f} mm³")


# --------------------------------------------------------------------------
# 模式 3：头颈簇
# --------------------------------------------------------------------------
def mode_neck(parts: Dict[str, List[cq.Shape]], min_vol: float) -> None:
    names = sorted(n for n in parts
                   if ("head" in n or "neck" in n or n.startswith("elec__")
                       or "torso" in n or "backpack" in n))
    print("=" * 112)
    print("【模式 neck】头颈簇 / 躯干上部成对干涉（零位，全部 solid 两两求和）")
    print("=" * 112)
    rows = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            if not bb_overlap(parts[a], parts[b]):
                continue
            common, vol, npair = intersect_all(parts[a], parts[b])
            if common is None or vol <= min_vol:
                continue
            bb = common.BoundingBox()
            rows.append((vol, a, b, bb))
    rows.sort(key=lambda r: -r[0])
    print("| # | A | B | 体积 mm³ | 世界包围盒 |")
    print("|---|---|---|---|---|")
    for k, (vol, a, b, bb) in enumerate(rows, 1):
        print(f"| {k} | `{a}` | `{b}` | **{vol:.0f}** | "
              f"x[{bb.xmin:.1f},{bb.xmax:.1f}] y[{bb.ymin:.1f},{bb.ymax:.1f}] "
              f"z[{bb.zmin:.1f},{bb.zmax:.1f}] |")
    if not rows:
        print("（无）")
    print("\n关键件世界包围盒（看层高关系）：")
    for n in names:
        bb = bb_of(parts[n])
        print(f"  {n}: x[{bb.xmin:7.2f},{bb.xmax:7.2f}] "
              f"y[{bb.ymin:7.2f},{bb.ymax:7.2f}] z[{bb.zmin:7.2f},{bb.zmax:7.2f}]")


def mode_torsosols(parts: Dict[str, List[cq.Shape]], min_vol: float) -> None:
    """`torso_frame` 每一块 solid 与全机其它件的干涉。

    为什么必须查：官方 `interference.py` 用 `Workplane.val()`，只查 `objects[0]`，
    即**只查了躯干框架的第 1 块**。一旦把 3 块并成 1 块（本任务的 B），
    原来"看不见"的干涉会进入官方统计 —— 这里先把它清点出来。
    """
    key = "torso_upper__torso_frame"
    print("=" * 112)
    print("【模式 torsosols】torso_frame 每块 solid × 全机其它件（官方工具看不到的口径）")
    print("=" * 112)
    if key not in parts:
        print(f"!! {key} 不在装配体里")
        return
    solids = parts[key]
    print(f"{key} 有 {len(solids)} 块 solid：")
    for i, s in enumerate(solids, 1):
        bb = s.BoundingBox()
        print(f"  solid {i}: V={float(s.Volume()):9.0f} mm³ "
              f"z[{bb.zmin:.1f},{bb.zmax:.1f}]")
    for i, s in enumerate(solids, 1):
        rows = []
        for other, ss in parts.items():
            if other == key:
                continue
            if not bb_overlap([s], ss):
                continue
            common, vol, npair = intersect_all([s], ss)
            if common is None or vol <= min_vol:
                continue
            bb = common.BoundingBox()
            rows.append((vol, other, bb))
        rows.sort(key=lambda r: -r[0])
        print(f"\n  solid {i} 的干涉（{len(rows)} 对）：")
        for vol, other, bb in rows:
            print(f"    {vol:9.0f} mm³  `{other}`  "
                  f"x[{bb.xmin:.1f},{bb.xmax:.1f}] y[{bb.ymin:.1f},{bb.ymax:.1f}] "
                  f"z[{bb.zmin:.1f},{bb.zmax:.1f}]")
        if not rows:
            print("    （无）")


def mode_spigot(min_vol: float) -> None:
    """同一 link 两端的两套关节模块（父端叉 / 子端笼）能否共存？

    管子只是"套在两端 Φ34 插接芯棒上的套筒"。若两端芯棒在轴向上互相重叠，
    那么**无论管子做成什么形状**都不可能同时套住两根芯棒 —— 这是"管端族"的根因。
    本模式只做零件级真布尔，不装整机（秒级）。
    """
    print("=" * 112)
    print("【模式 spigot】同一 link 两端关节模块的轴向占用 vs link 长度")
    print("=" * 112)
    cage = sk.joint_cage(shaft="+y", parent="+z")
    cages = cage.solids().vals()
    cb = bb_of(cages)
    print(f"joint_cage（子端笼）: 局部 z[{cb.zmin:.2f},{cb.zmax:.2f}]，"
          f"芯棒基面 z_cap_top = {sk.Z_TOP + 2.0 + sk.PLATE_T:.2f}（= 管口最浅位置）")
    fork_std = sk.limb_fork(shaft="+y", parent="+z", compact=False, spigot=True)
    fork_cmp = sk.limb_fork(shaft="+y", parent="+z", compact=True, spigot=True)
    for label, fk in (("标准叉（髋/膝/肩）", fork_std), ("紧凑叉（肘）", fork_cmp)):
        fs = fk.solids().vals()
        fb = bb_of(fs)
        print(f"{label}: 局部 z[{fb.zmin:.2f},{fb.zmax:.2f}]；"
              f"z 最负端 = 芯棒尖端（管口最深位置）")
    print()
    trials = [
        ("大腿/小腿（link 62.8）", 62.8, fork_std),
        ("上臂（link 47.1）", 47.1, fork_std),
        ("前臂（link 39.2）", 39.2, fork_cmp),
    ]
    for label, L, fk in trials:
        fs = fk.solids().vals()
        placed_cage = [xform(s, A.mat_trans(0.0, 0.0, -L)) for s in cages]
        common, vol, npair = intersect_all(fs, placed_cage)
        fb, pb = bb_of(fs), bb_of(placed_cage)
        print(f"--- {label}")
        print(f"    父端叉局部 z[{fb.zmin:.2f},{fb.zmax:.2f}]；"
              f"子端笼（平移到 z=-{L}）z[{pb.zmin:.2f},{pb.zmax:.2f}]")
        print(f"    叉 ∩ 笼 = {vol:.0f} mm³（{npair} 对 solid）")
        if common is not None:
            cb2 = common.BoundingBox()
            print(f"    重叠区 z[{cb2.zmin:.2f},{cb2.zmax:.2f}]"
                  f"（轴向重叠 {cb2.zmax - cb2.zmin:.2f} mm）")
        # 当前管子的端面位置（z0=-L → 管体 z∈[−L,0]）
        print(f"    当前管体 z[{-L:.2f},0.00]；"
              f"若两端让到芯棒基面则管长只剩 "
              f"{L - 27.35 - 17.35:.2f} mm（标准叉）/ "
              f"{L - 16.0 - 17.35:.2f} mm（紧凑叉）")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="第 11 轮一次性诊断")
    ap.add_argument("--mode",
                    choices=("tube", "torso", "neck", "torsosols", "spigot"),
                    default="tube")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--min", type=float, default=1.0)
    args = ap.parse_args(argv)

    modes = (("tube", "torso", "neck", "torsosols", "spigot")
             if args.all else (args.mode,))
    if "torso" in modes:
        mode_torso()
    if "spigot" in modes:
        mode_spigot(args.min)
    if any(m in modes for m in ("tube", "neck", "torsosols")):
        kin, items, parts = load()
        if "tube" in modes:
            mode_tube(kin, parts, args.min)
        if "neck" in modes:
            mode_neck(parts, args.min)
        if "torsosols" in modes:
            mode_torsosols(parts, args.min)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
