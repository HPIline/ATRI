#!/usr/bin/env python3
"""生成"零安装"交互式 3D 预览：一个自包含 HTML + 一个标准 GLB。

为什么自研 HTML 预览（而不是只依赖某个查看器）：
    - **零安装**：任何浏览器双击就开，不需要 vtk / Blender / 任何插件；
    - **可自动化**：由脚本从 CAD 实体直接生成，改完模型重跑一条命令即可；
    - **断网可用**：几何数据以 base64 内嵌，不依赖 CDN（比赛现场没网也能给评委看）。

**交互（第 11 轮新增）**：22 条关节滑条 + 5 个姿势预设 + 配合件半透明。

**冲突可视化（第 12 轮新增）**：每个零件按"最严重冲突档"着色 + 描边，配五档图例；
一个"只看冲突件"的隔离开关；点零件高亮它的对手件并列出体积/重合率/判定；重合体的
**包围盒热区**（近似）可叠加显示。档位判定的**唯一来源仍是 `fitcheck.verdict()`**，
本文件只做"判定串 → 颜色/档位"的映射，不复制阈值。
冲突表在**建几何那一次顺手算**（那时 `items` 真实体就在手上，不必再装配一遍），
随几何缓存落盘、并另存一个小 JSON `ATRI-conflicts.json`——
**重复出 HTML 不重算布尔求交**。

关键工程决定：
    几何**只在机械零位三角化一次**并缓存成 JSON；拖动滑条只改 4×4 矩阵，
    正运动学（FK）在 JS 里按 URDF 的 origin/axis/limit 现算——**不重新三角化**：

        .venv-cad/bin/python design/cad/preview.py --all            # 首次：建几何 + 出 HTML
        .venv-cad/bin/python design/cad/preview.py --all            # 之后：读缓存，秒级重出 HTML
        .venv-cad/bin/python design/cad/preview.py --all --rebuild  # 强制重建（改了 skeleton 等）

    缓存键 = 几何源文件 md5（skeleton/assembly/kit/parts/standards/urdf/placements）
    + `GEOM_VERSION` + 容差。**只改本文件的 HTML/JS 不会让缓存失效**；
    改三角化/法线/索引打包算法时要手动 bump `GEOM_VERSION`。

每个零件刚性挂在某个 link 上，渲染用的模型矩阵是
    M(link, q) = W_q(link) · W_0(link)⁻¹
（W_q = 当前姿态的 link 世界位姿，W_0 = 零位世界位姿；几何本身烘在零位世界系里）。
舵机机体挂在**父** link（被笼/抱架夹住，只有舵盘驱动子级）。

用法：
    .venv-cad/bin/python design/cad/preview.py --all            # 整机（读缓存 / 首次建缓存）
    .venv-cad/bin/python design/cad/preview.py --all --zero     # 打开时停在机械零位
    .venv-cad/bin/python design/cad/preview.py --part joint_cage
    .venv-cad/bin/python design/cad/preview.py --check          # 静态自检 + JS/Python FK 数值对拍
产出：
    out/preview/ATRI-preview.html            自包含交互预览（滑条/预设/半透明/冲突分档，双击即用）
    out/preview/ATRI-geometry-cache.json     三角化几何缓存（base64 内嵌二进制数组 + 冲突表）
    out/preview/ATRI-conflicts.json          冲突表（每对的重合体积/重合率/档位 + 热区盒，可单独读）
    out/preview/ATRI-assembly.glb            标准 glTF 二进制（机械零位）
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]  # cad/design/v1-22dof/archive → repo
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

import numpy as np
import cadquery as cq

import assembly as A
import render3d as R
import skeleton as sk
import fitcheck as FC          # 只用 is_joint_mate / joint_kind / overlap_report / verdict
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box

OUT = HERE / "out"
PREVIEW = OUT / "preview"
DESIGN = HERE.parent  # archive/.../design

# ⚠️ 改了三角化/法线/索引打包算法**或缓存字段结构**必须 +1，否则会复用旧缓存
#    （v6 = 冲突表 + 热区盒并入缓存；旧缓存没有这一节，会让预览退化成"无冲突数据"）
GEOM_VERSION = 6
CACHE_FILE = PREVIEW / "ATRI-geometry-cache.json"
HTML_FILE = PREVIEW / "ATRI-preview.html"
GLB_FILE = PREVIEW / "ATRI-assembly.glb"
CONFLICT_FILE = PREVIEW / "ATRI-conflicts.json"
MATE_ALPHA = 0.5
BLANK = "机械零位"
CONFLICT_MIN_VOL = 1.0      # 判"重合"的体积下限 mm³（与 audit_assembly.py 的 1.0 一致）
HEAT_BUDGET_S = 90.0        # 热区盒（重合体包围盒）计算预算，超时截断并在报告里写明

# 与渲染图一致的配色（同一套视觉语言，PPT 里能混用）
KIND_COLORS = {
    "bulk":    (140, 158, 184),
    "cage":    (33, 76, 133),
    "fork":    (51, 115, 173),
    "adapter": (77, 140, 140),
    "tube":    (115, 148, 115),
    "servo":   (64, 69, 82),
    "elec":    (217, 140, 51),
    "ground":  (90, 140, 110),
}
KIND_LABEL = {
    "bulk": "结构框架/大件", "cage": "关节笼", "fork": "连杆叉",
    "adapter": "紧凑转接块", "tube": "连杆管", "servo": "舵机（占位）",
    "elec": "电子件（占位）", "ground": "地平面（垫高）",
}

# --------------------------------------------------------------------------
# 冲突五档：**判定口径的唯一来源是 `fitcheck.verdict()`**。
# 这里只写"判定 → 颜色/档位"的映射 + 给 UI 看的阈值文案（文案与 fitcheck 的 docstring
# 一字对应，改 fitcheck 的阈值时这段文案也必须跟着改——`--check` 会做边界对拍）。
# --------------------------------------------------------------------------
CONFLICT_TIERS: List[Dict[str, Any]] = [
    {"id": "err", "label": "❌ 摆放错误", "color": [255, 69, 58], "rank": 3,
     "rule": "重合率 ≥30% 或 重合体积 ≥5000 mm³（两件被指派到同一块空间，改尺寸无解）"},
    {"id": "warn", "label": "⚠️ 让位不足", "color": [255, 159, 10], "rank": 2,
     "rule": "重合率 ≥5% 或 重合体积 ≥500 mm³（改尺寸/倒角/挪位可解）"},
    {"id": "dot", "label": "· 局部干涉", "color": [255, 214, 10], "rank": 1,
     "rule": "重合体积 >1 mm³，未达上两档（多是圆角/公差量级）"},
    {"id": "none", "label": "无冲突", "color": None, "rank": 0,
     "rule": "与任何零件的重合体积都 ≤1 mm³ —— 保留零件本色（不涂警告色）"},
    {"id": "mate", "label": "配合面（半透明）", "color": None, "rank": 0,
     "rule": "同关节 舵机×笼/叉/爪（含错轴抱架）→ alpha 0.5：**设计配合，不是冲突**"},
]
_TIER_RANK = {t["id"]: t["rank"] for t in CONFLICT_TIERS}
_TIER_INDEX = {t["id"]: i for i, t in enumerate(CONFLICT_TIERS)}


def tier_of(verdict: str) -> str:
    """`fitcheck.verdict()` 的判定串 → 档位 id（按标签首字符匹配，**不复制阈值**）。"""
    for t in CONFLICT_TIERS[:3]:
        if verdict.startswith(t["label"][0]):
            return t["id"]
    raise KeyError(f"未知判定 {verdict!r}——fitcheck.verdict 的输出变了？")

# --------------------------------------------------------------------------
# 姿势预设：**一处常量表**（单位度），改这里就够，别去 JS 里再抄一份。
#     - 取值一律按 URDF 限位夹紧（build 时会打印被夹紧的项，不静默改数）；
#     - 轴符号由 `design/atri.urdf` 的 axis 决定：臂/腿 pitch 轴为 +y，
#       **负值 = 往身前抬**（`A.DISPLAY_POSE_DEG` 就是这么摆的）。
# --------------------------------------------------------------------------
POSE_PRESETS: List[Tuple[str, Dict[str, float]]] = [
    (BLANK, {}),
    ("展示姿态", dict(A.DISPLAY_POSE_DEG)),
    ("招手", {
        "right_shoulder_pitch": -88.0, "right_elbow_pitch": -90.0,
        "right_shoulder_roll": -12.0, "left_shoulder_pitch": -14.0,
        "left_elbow_pitch": -22.0, "left_shoulder_roll": 6.0,
        "head_yaw": -14.0, "head_pitch": 4.0, "trunk_roll": -3.0,
        "right_gripper": 15.0,
    }),
    ("踢球", {
        "right_hip_pitch": -60.0, "right_knee_pitch": 62.0,
        "right_ankle_pitch": -24.0, "left_hip_pitch": 3.0, "left_knee_pitch": 3.0,
        "left_ankle_pitch": -3.0, "trunk_pitch": 6.0, "trunk_roll": 3.0,
        "left_shoulder_pitch": -30.0, "right_shoulder_pitch": 25.0,
        "left_elbow_pitch": -32.0, "right_elbow_pitch": -20.0,
    }),
    ("抓取", {
        "left_shoulder_pitch": -62.0, "right_shoulder_pitch": -62.0,
        "left_shoulder_roll": 10.0, "right_shoulder_roll": -10.0,
        "left_elbow_pitch": -38.0, "right_elbow_pitch": -38.0,
        "left_gripper": 52.0, "right_gripper": 52.0,
        "head_pitch": 22.0, "trunk_pitch": 4.0,
    }),
]


# --------------------------------------------------------------------------
# 矩阵工具（行主序，和 `assembly.py` 同一约定；导出给 JS 时再转列主序）
# --------------------------------------------------------------------------
def mat_inv_rigid(m: List[List[float]]) -> List[List[float]]:
    """刚体变换（旋转+平移）的逆：R⁻¹ = Rᵀ，t⁻¹ = −Rᵀt。"""
    rt = [[m[c][r] for c in range(3)] for r in range(3)]
    t = [m[r][3] for r in range(3)]
    ti = [-sum(rt[r][k] * t[k] for k in range(3)) for r in range(3)]
    return [rt[r] + [ti[r]] for r in range(3)] + [[0.0, 0.0, 0.0, 1.0]]


def cm(m: Sequence[Sequence[float]]) -> List[float]:
    """行主序 4×4 → WebGL 列主序 16 元组。"""
    return [round(float(m[r][c]), 6) for c in range(4) for r in range(4)]


def read_limits(urdf: Path) -> Dict[str, Tuple[float, float, float]]:
    """从 URDF 直接读关节限位（rad）→ {关节: (lower, upper, effort)}。

    **不自己编限位**：滑条范围、预设夹紧全走这一份。
    """
    out: Dict[str, Tuple[float, float, float]] = {}
    for j in ET.parse(urdf).getroot().findall("joint"):
        e = j.find("limit")
        if e is None or e.get("lower") is None:
            continue
        out[j.get("name")] = (float(e.get("lower")), float(e.get("upper")),
                              float(e.get("effort") or 0.0))
    return out


# --------------------------------------------------------------------------
# 零件 → link 映射（决定拖关节时它怎么动）
# --------------------------------------------------------------------------
def part_link(name: str, kin: A.Kin, elec_link: Dict[str, str]) -> str:
    """零件名 → 刚性所属 link。

    - `servo__J`  → **父** link：舵机机体被母端笼/抱架夹在父级上，
      只有舵盘带动子级；挂到子级会在弯关节时"舵机飞出笼子"。
    - `cage__J` / `outrigger__J` → 父 link（都建在同一个 `kin.joint_world`）
    - `fork__J`  → 子 link（叉锁在舵盘上，跟着子级转）
    - `elec__<id>` → `placements.json` 里登记的 host link
    - `{link}__{part}` → 名称前缀（LINK_BULK / ADAPTERS / CLUSTER_ARMS 三类同构）
    """
    if name.startswith("servo__"):
        return kin.joints[name[len("servo__"):]]["parent"]
    if name.startswith("cage__") or name.startswith("outrigger__"):
        return kin.joints[name.split("__", 1)[1]]["parent"]
    if name.startswith("fork__"):
        return kin.joints[name[len("fork__"):]]["child"]
    if name.startswith("elec__"):
        key = name[len("elec__"):]
        if key not in elec_link:
            raise KeyError(f"电子件 {key!r} 在 placements.json 里找不到 host link")
        return elec_link[key]
    return name.split("__", 1)[0]


# --------------------------------------------------------------------------
# 几何打包：索引化 + 逐顶点法线（面积加权）
# --------------------------------------------------------------------------
def pack_geometry(name: str, verts: np.ndarray, tris: np.ndarray,
                  vmax: int = 65535) -> Dict[str, Any]:
    """一个零件 → {v:(V,6) float32 [pos|nrm], idx:(3T,) uint16 或 None, 统计}。

    为什么不逐面复制顶点（老做法）：OCC 的 `Shape.tessellate()` **每个面各自一套顶点**
    （`cadquery/occ_impl/shapes.py` 逐 face 追加、不跨面去重），所以在**同一个面内**
    做面积加权平均即可：平面 → 法线完全不变（棱边依旧硬），圆柱/倒角 → 平滑着色。
    顶点数因此从 3T 降到 ≈0.3T，HTML 体积降到约 1/4。
    """
    v = np.asarray(verts, dtype=np.float64)
    t = np.asarray(tris, dtype=np.int64)
    if len(t) == 0 or len(v) == 0:
        raise ValueError("空网格")
    p0, p1, p2 = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    fn = np.cross(p1 - p0, p2 - p0)                 # 未归一化：模长 = 2×面积
    ln = np.linalg.norm(fn, axis=1)
    ln[ln < 1e-12] = 1.0
    unit = fn / ln[:, None]

    acc = np.zeros_like(v)
    np.add.at(acc, t.reshape(-1), np.repeat(fn, 3, axis=0))
    vn = np.linalg.norm(acc, axis=1)
    bad = vn < 1e-12
    if bad.any():                                   # 退化顶点：退回任一面法线
        acc[bad] = unit[0]
        vn = np.linalg.norm(acc, axis=1)
    vnrm = acc / vn[:, None]

    # 质量指标：顶点法线 vs 相邻面法线的最大夹角（平面应 ≈0，圆柱应很小）
    dev = np.degrees(np.arccos(np.clip(np.sum(vnrm[t] * unit[:, None, :], axis=2),
                                       -1.0, 1.0)))
    dev = dev[np.isfinite(dev)]

    out: Dict[str, Any] = {"name": name, "nV": int(len(v)), "nT": int(len(t))}
    if len(v) <= vmax:
        out["v"] = np.concatenate([v, vnrm], axis=1).astype(np.float32)
        out["idx"] = t.astype(np.uint16).reshape(-1)
        out["indexed"] = True
    else:                                           # 保险丝：超大件退回逐面复制
        out["v"] = np.concatenate([v[t].reshape(-1, 3),
                                   np.repeat(unit, 3, axis=0)], axis=1).astype(np.float32)
        out["idx"] = None
        out["indexed"] = False
    out["maxDevDeg"] = float(dev.max()) if dev.size else 0.0
    out["meanDevDeg"] = float(dev.mean()) if dev.size else 0.0
    return out


def ground_geometry(bbox: Sequence[float], margin: float = 40.0
                    ) -> Tuple[np.ndarray, np.ndarray]:
    """垫高处一张薄地平面（2 个三角形）。"""
    z = float(bbox[2])
    x0, y0 = float(bbox[0]) - margin, float(bbox[1]) - margin
    x1, y1 = float(bbox[3]) + margin, float(bbox[4]) + margin
    v = np.array([[x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z]],
                 dtype=np.float64)
    t = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    return v, t


# --------------------------------------------------------------------------
# 配合件（半透明用）：调用 fitcheck.is_joint_mate
# --------------------------------------------------------------------------
def mate_joint_map(names: Sequence[str]) -> Tuple[Dict[str, str], Dict[str, int]]:
    """零件名 → 配合关节名。**判定用 `fitcheck.is_joint_mate`**（不复制它的逻辑）。

    ⚠️ 已知缺口：`fitcheck.is_joint_mate` 的 kinds 白名单是
    {servo×cage, servo×fork, servo×gripper_jaw}，**没有 outrigger**，
    而髋/肩"错轴抱架"（8 件 `outrigger__*`）在几何上就是夹住舵机的母端件。
    这里按同一条定义（同关节 + {servo, outrigger}）补上，两个计数都返回、
    报告里分开写清楚——**不改 `fitcheck.py`**。
    """
    out: Dict[str, str] = {}
    n_fit = n_sup = 0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            if FC.is_joint_mate(a, b):
                ja, _ = FC.joint_kind(a)
                out[a] = out[b] = ja
                n_fit += 1
                continue
            ja, ka = FC.joint_kind(a)
            jb, kb = FC.joint_kind(b)
            if ja and ja == jb and {ka, kb} == {"servo", "outrigger"}:
                out[a] = out[b] = ja
                n_sup += 1
    return out, {"is_joint_mate": n_fit, "outrigger_补充": n_sup}


# --------------------------------------------------------------------------
# 冲突扫描：判定走 fitcheck，本文件只做"档位映射 + 可视化辅助数据"
# --------------------------------------------------------------------------
def _common_bbox(a: cq.Workplane, b: cq.Workplane) -> Optional[List[float]]:
    """两件**重合体**的轴对齐包围盒（mm，零位世界系）——**只用于可视化**。

    ⚠️ 这是热区盒的近似：真实重合体是"管壁啃舵机角"这类奇形，用包围盒画会偏大。
    它**不参与任何判定**——体积/重合率/档位一律走 `fitcheck.overlap_report()`。
    这里重算一次布尔只是为了拿到形状本身（`fitcheck.common_volume()` 把形状丢掉了）。
    """
    op = BRepAlgoAPI_Common(a.val().wrapped, b.val().wrapped)
    op.Build()
    if not op.IsDone():
        return None
    box = Bnd_Box()
    BRepBndLib.Add_s(op.Shape(), box)
    if box.IsVoid():
        return None
    x0, y0, z0, x1, y1, z1 = box.Get()
    if not all(math.isfinite(v) for v in (x0, y0, z0, x1, y1, z1)):
        return None
    if x1 < x0 or y1 < y0 or z1 < z0:
        return None
    return [round(v, 1) for v in (x0, y0, z0, x1, y1, z1)]


def scan_conflicts(items: Sequence[Tuple[str, cq.Workplane]], idx_of: Dict[str, int],
                   heat: bool = True, heat_budget_s: float = HEAT_BUDGET_S
                   ) -> Dict[str, Any]:
    """整机两两求交 → 冲突表（含每件最严重档）+ 重合体包围盒。

    **为什么在 build_cache 里做**：那时装配好的真实体 `items` 就在手上，
    不必为体检再装配一遍；算完随几何缓存落盘，之后每次 `--all` 都是秒级。
    判定本身**一行都没复制**：体积/重合率/判定串全部来自 `FC.overlap_report()`。
    """
    t0 = time.time()
    rows = FC.overlap_report(items, threshold=CONFLICT_MIN_VOL)
    shapes = dict(items)
    counts = {"err": 0, "warn": 0, "dot": 0}
    pairs: List[Dict[str, Any]] = []
    per: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        t = tier_of(r["verdict"])
        counts[t] += 1
        ia, ib = idx_of.get(r["a"]), idx_of.get(r["b"])
        if ia is None or ib is None:
            print(f"  [WARN] 冲突对 {r['a']} × {r['b']} 的零件不在几何里，跳过")
            continue
        for nm, ii in ((r["a"], ia), (r["b"], ib)):
            d = per.setdefault(nm, {"i": ii, "tier": "none", "vol": 0.0, "n": 0,
                                    "verdict": ""})
            d["vol"] += r["vol"]
            d["n"] += 1
            if _TIER_RANK[t] > _TIER_RANK[d["tier"]]:
                d["tier"] = t
                d["verdict"] = r["verdict"]
        pairs.append({"a": r["a"], "b": r["b"], "ai": ia, "bi": ib,
                      "vol": round(r["vol"], 1), "frac": round(r["frac"], 4),
                      "tier": t, "verdict": r["verdict"], "box": None})
    scan_s = time.time() - t0

    # 热区盒：按体积降序算（超预算就截断，先保大错），预算用完记进 JSON
    n_box = 0
    truncated = False
    if heat:
        th0 = time.time()
        for p in sorted(pairs, key=lambda d: -d["vol"]):
            if time.time() - th0 > heat_budget_s:
                truncated = True
                break
            p["box"] = _common_bbox(shapes[p["a"]], shapes[p["b"]])
            n_box += int(p["box"] is not None)
        if truncated:
            print(f"  [WARN] 热区盒计算超过预算 {heat_budget_s:.0f} s，"
                  f"只算了体积最大的 {n_box}/{len(pairs)} 对（其余对无热区盒）")

    parts = [dict(d, name=n) for n, d in per.items()]
    parts.sort(key=lambda d: (-_TIER_RANK[d["tier"]], -d["vol"]))
    return {
        "schema": 1, "builtAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sourceHash": "", "threshold": CONFLICT_MIN_VOL,
        "tiers": CONFLICT_TIERS,
        "counts": dict(counts, pairs=len(pairs), parts=len(parts),
                       totalVol=round(sum(p["vol"] for p in pairs), 1)),
        "pairs": pairs, "parts": parts,
        "scanSec": round(scan_s, 1), "heatSec": round(time.time() - t0 - scan_s, 1),
        "heatBoxes": n_box, "heatBudgetHit": truncated,
    }


def compact_conflicts(conf: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """冲突表 → 塞进 HTML 的紧凑形（数组而非对象，省体积）。

    pairs 项 = [件A下标, 件B下标, 体积mm³, 重合率, 档位下标, (可选)热区盒 6 个数]；
    parts 项 = [零件下标, 最严重档下标, 合计体积mm³, 冲突对数]。
    """
    if not conf:
        return None
    ti = _TIER_INDEX
    return {
        "builtAt": conf["builtAt"], "scanSec": conf["scanSec"],
        "heatBoxes": conf["heatBoxes"], "heatBudgetHit": conf["heatBudgetHit"],
        "counts": conf["counts"], "tiers": conf["tiers"],
        "pairs": [[p["ai"], p["bi"], p["vol"], p["frac"], ti[p["tier"]]]
                  + (p["box"] or []) for p in conf["pairs"]],
        "parts": [[p["i"], ti[p["tier"]], p["vol"], p["n"]] for p in conf["parts"]],
    }


def load_conflicts(cache: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从几何缓存取冲突表；缓存里没有就退回同目录的 `ATRI-conflicts.json`（校验指纹）。"""
    conf = cache.get("conflicts")
    if conf:
        return conf
    if CONFLICT_FILE.exists():
        try:
            d = json.loads(CONFLICT_FILE.read_text(encoding="utf-8"))
            if d.get("sourceHash") == cache.get("sourceHash"):
                print(f"  冲突表取自 {CONFLICT_FILE.name}（几何缓存里没有这一节）")
                return d
            print(f"  [WARN] {CONFLICT_FILE.name} 与几何缓存指纹不符，忽略")
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] {CONFLICT_FILE.name} 读取失败（{type(exc).__name__}: {exc}）")
    print("  [WARN] 没有冲突数据 → 本次不出冲突着色；"
          "跑 `preview.py --all --rebuild` 重建几何时会把冲突表一起算出来")
    return None


# --------------------------------------------------------------------------
# 几何缓存
# --------------------------------------------------------------------------
def geom_fingerprint(tol: float) -> str:
    """几何指纹：只有**影响几何**的文件进哈希（preview.py 里 HTML/JS 的改动不影响）。"""
    h = hashlib.md5()
    for p in (HERE / "skeleton.py", HERE / "assembly.py", HERE / "kit.py",
              HERE / "parts.py", HERE / "standards.py",
              DESIGN / "atri.urdf", DESIGN / "placements.json"):
        if p.exists():
            h.update(p.name.encode("utf-8"))
            h.update(p.read_bytes())
    h.update(f"|v{GEOM_VERSION}|tol={tol:.3f}|zero-pose".encode("utf-8"))
    return h.hexdigest()


def build_cache(tol: float, want_glb: bool = True, heat: bool = True,
                heat_budget_s: float = HEAT_BUDGET_S) -> Dict[str, Any]:
    """**唯一**一次三角化：机械零位装配 → 每零件索引几何 + 运动学 + 配合对。

    ⚠️ 指纹必须**在构建开始时**取一次：构建要 1 分多钟，期间别的线程可能改
    `skeleton.py`（第 11 轮真实发生过：T1 用 `git stash` 做对照实验又弹回来）。
    几何是进程启动时 import 的那份，所以缓存只能按"开始时的指纹"记账；
    若构建结束时指纹变了，说明磁盘上的源已经不是这份几何，**必须显式告警**。
    """
    t0 = time.time()
    fp0 = geom_fingerprint(tol)
    kin = A.Kin(DESIGN / "atri.urdf")                     # 零位（不给 pose_deg）
    placements = json.loads((DESIGN / "placements.json").read_text(encoding="utf-8"))
    elec_link = {str(e["id"]): e["link"] for e in placements["electronics"]}
    items, log = A.build_assembly(kin, placements)
    bad = [l for l in log if not l.get("ok")]
    print(f"  装配 {len(items)} 件（成功 {len(items) - len(bad)}，失败 {len(bad)}）"
          f"· 用时 {time.time() - t0:.1f} s")
    for b in bad:
        print(f"  [ERR] {b['name']}: {b.get('err')}")
    if bad:
        raise SystemExit(f"装配失败 {len(bad)} 件，拒绝出预览")

    print(f"  三角化（tol={tol}，机械零位）…")
    meshes = R.tessellate(items, tol=tol)
    if len(meshes) != len(items):
        print(f"  [WARN] {len(items) - len(meshes)} 件没有三角面（空网格）")

    parts: List[Dict[str, Any]] = []
    packed: List[Dict[str, Any]] = []
    v_float: List[np.ndarray] = []
    v_index: List[np.ndarray] = []
    f_off = i_off = 0
    bbox_all: Optional[List[float]] = None
    for name, verts, tris in meshes:
        pk = pack_geometry(name, verts, tris)
        link = part_link(name, kin, elec_link)
        kind = R.kind_of(name)
        lo = verts.min(axis=0).tolist()
        hi = verts.max(axis=0).tolist()
        if bbox_all is None:
            bbox_all = [lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]]
        else:
            bbox_all = [min(bbox_all[0], lo[0]), min(bbox_all[1], lo[1]),
                        min(bbox_all[2], lo[2]), max(bbox_all[3], hi[0]),
                        max(bbox_all[4], hi[1]), max(bbox_all[5], hi[2])]
        parts.append({"name": name, "link": link, "kind": kind,
                      "vOff": f_off, "vCount": pk["nV"], "mate": "",
                      "iOff": i_off,
                      "iCount": 0 if pk["idx"] is None else int(len(pk["idx"])),
                      "indexed": bool(pk["indexed"]),
                      "aabb": [round(x, 2) for x in (lo + hi)],
                      "degMax": round(pk["maxDevDeg"], 2),
                      "degMean": round(pk["meanDevDeg"], 3)})
        packed.append(pk)
        v_float.append(pk["v"].reshape(-1))
        if pk["idx"] is not None:
            v_index.append(pk["idx"])
            i_off += int(len(pk["idx"]))
        f_off += pk["nV"]

    # 地平面（固定在世界系，不随姿态动）
    gv, gt = ground_geometry(bbox_all)
    gp = pack_geometry("__ground", gv, gt)
    parts.append({"name": "__ground", "link": "", "kind": "ground", "mate": "",
                  "vOff": f_off, "vCount": gp["nV"], "iOff": i_off,
                  "iCount": int(len(gp["idx"])), "indexed": True,
                  "aabb": [round(x, 2) for x in (gv.min(axis=0).tolist()
                                                 + gv.max(axis=0).tolist())],
                  "degMax": 0.0, "degMean": 0.0})
    v_float.append(gp["v"].reshape(-1))
    v_index.append(gp["idx"])
    i_off += int(len(gp["idx"]))
    f_off += gp["nV"]

    names = [p["name"] for p in parts]
    mates, mate_stats = mate_joint_map(names)
    for p in parts:
        p["mate"] = mates.get(p["name"], "")

    # --- 冲突表：判定走 fitcheck.overlap_report（真实体就在手上，顺手算完）---
    conf: Optional[Dict[str, Any]] = None
    idx_of = {p["name"]: i for i, p in enumerate(parts)}
    try:
        print(f"  冲突扫描（两两求交 >{CONFLICT_MIN_VOL:g} mm³"
              f"{'，含热区盒' if heat else ''}）…")
        conf = scan_conflicts(items, idx_of, heat=heat, heat_budget_s=heat_budget_s)
        conf["sourceHash"] = fp0
        c = conf["counts"]
        print(f"  冲突 {c['pairs']} 对 / 合计 {c['totalVol']:.0f} mm³"
              f"（❌ {c['err']} ｜ ⚠️ {c['warn']} ｜ · {c['dot']}）"
              f"· 涉及 {c['parts']} 件 · 热区盒 {conf['heatBoxes']} 个"
              f"· 用时 {conf['scanSec']:.0f}s + {conf['heatSec']:.0f}s")
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] 冲突扫描失败（{type(exc).__name__}: {exc}）"
              "→ 预览仍可出，但**没有分档着色/隔离/热区**")
    if conf:
        try:                       # 另存一份小 JSON：人能直接读，别的脚本也能拿去用
            CONFLICT_FILE.write_text(
                json.dumps(conf, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  已写冲突表 {CONFLICT_FILE.name}"
                  f"（{CONFLICT_FILE.stat().st_size / 1e3:.0f} KB）")
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] 冲突表落盘失败：{type(exc).__name__}: {exc}")

    # --- 运动学（FK 在 JS 里算，这里只导出常量）---
    order: List[str] = []
    queue = [kin.root]
    while queue:
        link = queue.pop(0)
        for child in kin.children[link]:
            order.append(kin.parent_of[child])
            queue.append(child)
    if len(order) != len(kin.joints):
        raise SystemExit(f"关节拓扑序不完整：{len(order)} != {len(kin.joints)}")
    lim = read_limits(DESIGN / "atri.urdf")
    link_names = sorted(kin.world)
    decl = [j.get("name") for j in ET.parse(DESIGN / "atri.urdf").getroot()
            .findall("joint") if j.get("name") in kin.joints]
    if sorted(decl) != sorted(order):
        raise SystemExit("URDF 关节声明序与拓扑序的集合不一致")
    fk_order = [decl.index(jn) for jn in order]

    kinds: Dict[str, Dict[str, Any]] = {}
    for p, pk in zip(parts, packed):
        k = kinds.setdefault(p["kind"], {"kind": p["kind"],
                                         "label": KIND_LABEL[p["kind"]],
                                         "color": list(KIND_COLORS[p["kind"]]),
                                         "tris": 0, "parts": 0})
        k["tris"] += int(len(pk["idx"]) // 3) if pk["idx"] is not None else pk["nV"] // 3
        k["parts"] += 1

    blob = (np.concatenate(v_float).astype(np.float32).tobytes()
            + np.concatenate(v_index).astype(np.uint16).tobytes())

    cache: Dict[str, Any] = {
        "schema": 2, "geomVersion": GEOM_VERSION, "tol": tol,
        "sourceHash": fp0,
        "srcMd5": {p.name: hashlib.md5(p.read_bytes()).hexdigest()[:12]
                   for p in (HERE / "skeleton.py", HERE / "assembly.py",
                             DESIGN / "atri.urdf", DESIGN / "placements.json")
                   if p.exists()},
        "builtAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "bbox": [round(v, 2) for v in bbox_all],
        "links": [{"name": n, "zero": cm(kin.world[n]),
                   "inv0": cm(mat_inv_rigid(kin.world[n]))} for n in link_names],
        "root": link_names.index(kin.root),
        "joints": [{
            "name": jn,
            "parent": link_names.index(kin.joints[jn]["parent"]),
            "child": link_names.index(kin.joints[jn]["child"]),
            "xyz": [round(v, 6) for v in kin.joints[jn]["xyz"]],
            "rpy": [round(v, 9) for v in kin.joints[jn]["rpy"]],
            "axis": [round(v, 9) for v in kin.joints[jn]["axis"]],
            "lo": round(lim[jn][0], 6), "hi": round(lim[jn][1], 6),
            "effort": lim[jn][2],
        } for jn in decl],          # 顺序 = URDF 声明顺序（UI 顺序）
        "fkOrder": fk_order,           # 拓扑序（父先子后）—— FK 必须按它算
        "parts": parts,
        "kinds": sorted(kinds.values(), key=lambda k: -k["tris"]),
        "conflicts": conf,            # 冲突表（含每对档位与热区盒）——没有就是 None
        "vertexCount": int(f_off), "floatCount": int(f_off) * 6,
        "indexCount": int(i_off),
        "vertsB64": base64.b64encode(np.concatenate(v_float).astype(np.float32)
                                     .tobytes()).decode("ascii"),
        "idxB64": base64.b64encode(np.concatenate(v_index).astype(np.uint16)
                                   .tobytes()).decode("ascii"),
        "stats": {
            "triangles": sum((p["iCount"] // 3) if p["indexed"] else (p["vCount"] // 3)
                             for p in parts),
            "vertices": int(f_off), "indexCount": int(i_off),
            "indexedParts": sum(1 for p in parts if p["indexed"]),
            "parts": len(parts),
            "maxDevDeg": max(p["degMax"] for p in parts),
            "mates": mate_stats, "blobBytes": len(blob),
            "conflicts": (None if not conf else
                          dict(conf["counts"], heatBoxes=conf["heatBoxes"],
                               scanSec=conf["scanSec"])),
        },
    }
    st = cache["stats"]
    print(f"  三角面 {st['triangles']:,} · 顶点 {f_off:,}（索引 {i_off:,}）"
          f" · 几何 {len(blob) / 1e6:.2f} MB · 法线最大偏角 {st['maxDevDeg']:.1f}°"
          f" · 配合对 {mate_stats['is_joint_mate']}+{mate_stats['outrigger_补充']}")
    top = sorted(zip(parts, packed), key=lambda x: -x[1]["nT"])[:6]
    for p, pk in top:
        print(f"    {p['name'][:38]:38s} {pk['nT']:6d} 面 {pk['nV']:6d} 顶点"
              f" link={p['link']}")
    if geom_fingerprint(tol) != fp0:
        print("  [WARN] 构建期间几何源文件被改动（指纹 "
              f"{fp0[:8]} → {geom_fingerprint(tol)[:8]}）！"
              "本缓存对应的是**构建开始时**的那份几何，下次运行会自动重建。")
    print(f"  建几何总用时 {time.time() - t0:.1f} s")
    if want_glb:
        glb_mb = export_glb(items, GLB_FILE)
        if glb_mb:
            print(f"  已生成 {GLB_FILE.name}（{glb_mb}，姿态 = 机械零位）")
    return cache


def load_cache(tol: float, rebuild: bool, want_glb: bool = True,
               stale_ok: bool = False, heat: bool = True) -> Tuple[Dict[str, Any], bool]:
    """读缓存；指纹不符或 --rebuild 时重建并落盘。返回 (cache, 是否重建)。

    `--stale-ok`：**跳指纹校验、直接用现有缓存**，只用于"只改 HTML/JS 反复出预览"时
    躲开别人的重 CAD 线程（几何可能与当前源文件不一致，正式出图别用）。
    """
    fp = geom_fingerprint(tol)
    if not rebuild and CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if stale_ok and cache.get("geomVersion") == GEOM_VERSION:
                print(f"  [WARN] --stale-ok：直接用缓存（几何源指纹 "
                      f"{str(cache.get('sourceHash'))[:8]} ≠ 现值 {fp[:8]}，"
                      f"**几何可能与当前源文件不一致**）")
                return cache, False
            if cache.get("sourceHash") == fp and cache.get("geomVersion") == GEOM_VERSION:
                print(f"  复用几何缓存 {CACHE_FILE.name}（{cache['builtAt']} 建，"
                      f"{CACHE_FILE.stat().st_size / 1e6:.2f} MB，"
                      f"指纹 {fp[:8]}）—— **不再重建装配/三角化**")
                return cache, False
            print(f"  缓存指纹不符（缓存 {str(cache.get('sourceHash'))[:8]} ≠ "
                  f"现值 {fp[:8]}）→ 重建")
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] 缓存读取失败（{type(exc).__name__}: {exc}）→ 重建")
    elif rebuild:
        print("  --rebuild：强制重建几何")
    else:
        print("  无缓存 → 首次建几何")
    cache = build_cache(tol, want_glb=want_glb, heat=heat)
    PREVIEW.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")),
                          encoding="utf-8")
    print(f"  已写几何缓存 {CACHE_FILE}（{CACHE_FILE.stat().st_size / 1e6:.2f} MB）")
    return cache, True


# --------------------------------------------------------------------------
# 自包含 HTML（内嵌几何 + 手写 WebGL 查看器，无外部依赖）
# --------------------------------------------------------------------------
_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  html,body{margin:0;height:100%;overflow:hidden;background:#0a2540;
            font:13px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#e8eef7}
  #c{display:block;width:100vw;height:100vh}
  #hud{position:fixed;left:14px;top:12px;pointer-events:none;max-width:52vw}
  #hud b{font-size:15px;letter-spacing:.5px}
  #hud div{opacity:.75;font-size:12px}
  #panel{position:fixed;right:14px;top:12px;width:292px;max-height:calc(100vh - 24px);
         overflow:auto;background:rgba(10,37,64,.86);border:1px solid rgba(255,255,255,.16);
         border-radius:10px;padding:10px 12px;backdrop-filter:blur(6px)}
  #panel h4{margin:10px 0 6px;font-size:12px;opacity:.7;font-weight:600;
            letter-spacing:.4px}
  #panel h4:first-child{margin-top:0}
  #panel label{display:flex;align-items:center;gap:7px;padding:2px 0;cursor:pointer}
  #panel .sw{width:11px;height:11px;border-radius:3px;flex:none}
  #panel .n{margin-left:auto;opacity:.55;font-size:11px}
  #tip{position:fixed;left:14px;bottom:12px;opacity:.6;font-size:12px}
  #panel button{background:rgba(255,255,255,.1);color:#e8eef7;border:1px solid rgba(255,255,255,.2);
                border-radius:6px;padding:5px 6px;cursor:pointer;font-size:12px}
  #panel button:hover{background:rgba(255,255,255,.18)}
  #panel button.on{background:#2f6fd0;border-color:#5b9bff}
  .row{display:flex;gap:6px;flex-wrap:wrap}
  .row button{flex:1 0 40%}
  .jrow{display:grid;grid-template-columns:98px 1fr 42px;align-items:center;gap:5px;padding:1px 0}
  .jrow span.jn{font-size:11px;opacity:.85;overflow:hidden;text-overflow:ellipsis;
                cursor:pointer;white-space:nowrap}
  .jrow.focus span.jn{color:#ffd479;font-weight:600}
  .jrow input[type=range]{width:100%;height:16px;margin:0}
  .jrow span.jv{font-size:11px;text-align:right;opacity:.75;font-variant-numeric:tabular-nums}
  #poseOut{display:none;width:100%;height:52px;margin-top:6px;background:rgba(0,0,0,.35);
           color:#cfe3ff;border:1px solid rgba(255,255,255,.2);border-radius:6px;
           font:11px/1.4 ui-monospace,Menlo,monospace;resize:vertical}
  /* ---- 冲突可视化 ---- */
  #legend{display:flex;flex-direction:column;gap:2px;margin-bottom:4px}
  .lg{display:grid;grid-template-columns:14px 1fr auto;gap:6px;align-items:center;
      font-size:11px;padding:2px 3px;border-radius:5px}
  .lg .sw{width:12px;height:12px;border-radius:3px;flex:none}
  .lg .n{opacity:.6;font-size:10.5px;font-variant-numeric:tabular-nums}
  .lg .rule{grid-column:1/4;font-size:10px;line-height:1.35;opacity:.55;margin:-1px 0 2px 20px}
  #legend .lg.pick{cursor:pointer}
  #legend .lg.pick:hover{background:rgba(255,255,255,.09)}
  #legend .lg.on{background:rgba(47,111,208,.35);box-shadow:inset 0 0 0 1px #5b9bff}
  #selbox{display:none;margin:6px 0 2px;padding:6px 7px;border-radius:7px;
          background:rgba(0,0,0,.30);border:1px solid rgba(255,255,255,.16);font-size:11px}
  #selbox .hd{font-weight:600;line-height:1.4}
  #selbox .sub{opacity:.6;font-size:10px;margin:2px 0 4px}
  .pr{display:grid;grid-template-columns:15px 1fr auto;gap:5px;align-items:center;
      padding:2px 3px;border-radius:5px;cursor:pointer}
  .pr:hover{background:rgba(255,255,255,.12)}
  .pr .num{opacity:.7;font-size:10px;font-variant-numeric:tabular-nums;text-align:right}
  .pr .bg{font-size:11px}
  .pr.sel{background:rgba(47,111,208,.4)}
  #selbox button{margin-top:4px;padding:3px 5px;font-size:11px}
  #confWrap{margin-top:5px}
  #confWrap summary{font-size:11px;opacity:.7;cursor:pointer;outline:none}
  #confList{margin-top:3px;max-height:170px;overflow:auto}
  .heatnote{font-size:10px;opacity:.55;margin-top:5px;line-height:1.4}
  #confMissing{font-size:11px;opacity:.7;padding:4px 0}
</style>
</head>
<body>
<canvas id="c"></canvas>
<div id="hud"><b>__TITLE__</b><div id="sub"></div><div id="pose"></div></div>
<div id="panel">
  <h4>姿势预设</h4>
  <div class="row" id="presets"></div>
  <h4>冲突可视化（机械零位实测）</h4>
  <div id="legend"></div>
  <div id="confMissing" style="display:none"></div>
  <label><input type="checkbox" id="confChk" checked> 按冲突分档着色 + 描边（C）</label>
  <label><input type="checkbox" id="isoChk"> 只看冲突件 + 对手件（X）</label>
  <div class="jrow" style="grid-template-columns:56px 1fr">
    <span class="jn" title="隔离模式的档位门槛">隔离门槛</span>
    <select id="isoSel" style="font-size:11px;background:rgba(0,0,0,.35);color:#e8eef7;
            border:1px solid rgba(255,255,255,.2);border-radius:5px;padding:2px"></select>
  </div>
  <label><input type="checkbox" id="heatChk"> 全部热区盒（近似，V）</label>
  <div id="selbox"></div>
  <details id="confWrap"><summary>冲突清单（按体积，前 12 对）</summary>
    <div id="confList"></div></details>
  <h4>关节（__NJOINT__ DOF · URDF 限位）</h4>
  <div id="sliders"></div>
  <div class="row" style="margin-top:6px">
    <button id="zero">全部归零 (0)</button>
    <button id="copy">复制角度</button>
  </div>
  <textarea id="poseOut" readonly></textarea>
  <h4>显示</h4>
  <label><input type="checkbox" id="mateChk" checked> 配合件半透明（T）</label>
  <label><input type="checkbox" id="groundChk" checked> 地平面</label>
  <div id="kinds"></div>
  <h4>视图</h4>
  <div class="row">
    <button id="reset">重置视角 (R)</button>
    <button id="wire">线框 (W)</button>
    <button id="spin">自动旋转 (空格)</button>
  </div>
</div>
<div id="tip">左键拖拽旋转 · 滚轮缩放 · 右键/Shift 平移 · 拖滑条摆姿态 · <b>点零件</b>=高亮它的冲突对手件 · 点关节名=只看该关节配合件 · Esc 取消选中</div>
<script id="geo" type="application/octet-stream">__B64__</script>
<script id="meta" type="application/json">__META__</script>
<script>
"use strict";
const META=JSON.parse(document.getElementById("meta").textContent);
META.linkIdx={};META.links.forEach(function(l,i){META.linkIdx[l.name]=i;});
function b64bytes(s){const bin=atob(s);const n=bin.length;const u=new Uint8Array(n);
  for(let i=0;i<n;i++)u[i]=bin.charCodeAt(i);return u;}
const BUF=b64bytes(document.getElementById("geo").textContent.trim()).buffer;

const canvas=document.getElementById("c");
const gl=canvas.getContext("webgl",{antialias:true,alpha:false})||canvas.getContext("experimental-webgl");
if(!gl){document.body.innerHTML="<p style='padding:2em'>此浏览器不支持 WebGL，请用 Safari/Chrome/Edge 打开。</p>";}

//<MATHS>
function mMul(a,b){const o=new Array(16);
  for(let i=0;i<4;i++)for(let j=0;j<4;j++){let s=0;
    for(let k=0;k<4;k++)s+=a[k*4+j]*b[i*4+k];o[i*4+j]=s;}return o;}
function mIdent(){const o=new Array(16).fill(0);o[0]=o[5]=o[10]=o[15]=1;return o;}
function mTrans(x,y,z){const o=mIdent();o[12]=x;o[13]=y;o[14]=z;return o;}
function mRpy(r,p,y){const cr=Math.cos(r),sr=Math.sin(r),cp=Math.cos(p),sp=Math.sin(p),
  cy=Math.cos(y),sy=Math.sin(y);
  return [cy*cp, sy*cp, -sp, 0,
          cy*sp*sr-sy*cr, sy*sp*sr+cy*cr, cp*sr, 0,
          cy*sp*cr+sy*sr, sy*sp*cr-cy*sr, cp*cr, 0,
          0,0,0,1];}
function mAxisAngle(ax,th){const n=Math.hypot(ax[0],ax[1],ax[2])||1;
  const x=ax[0]/n,y=ax[1]/n,z=ax[2]/n,c=Math.cos(th),s=Math.sin(th),C=1-c;
  return [x*x*C+c, y*x*C+z*s, z*x*C-y*s, 0,
          x*y*C-z*s, y*y*C+c, z*y*C+x*s, 0,
          x*z*C+y*s, y*z*C-x*s, z*z*C+c, 0,
          0,0,0,1];}
function m3of(m){return [m[0],m[1],m[2], m[4],m[5],m[6], m[8],m[9],m[10]];}
function persp(fov,asp,n,f){const t=1/Math.tan(fov/2),o=new Array(16).fill(0);
  o[0]=t/asp;o[5]=t;o[10]=(f+n)/(n-f);o[11]=-1;o[14]=2*f*n/(n-f);return o;}
function lookAt(e,c,u){
  let z=[e[0]-c[0],e[1]-c[1],e[2]-c[2]];let l=Math.hypot(z[0],z[1],z[2]);z=z.map(function(v){return v/l;});
  let x=[u[1]*z[2]-u[2]*z[1],u[2]*z[0]-u[0]*z[2],u[0]*z[1]-u[1]*z[0]];
  l=Math.hypot(x[0],x[1],x[2])||1;x=x.map(function(v){return v/l;});
  const y=[z[1]*x[2]-z[2]*x[1],z[2]*x[0]-z[0]*x[2],z[0]*x[1]-z[1]*x[0]];
  return [x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,
    -(x[0]*e[0]+x[1]*e[1]+x[2]*e[2]),-(y[0]*e[0]+y[1]*e[1]+y[2]*e[2]),
    -(z[0]*e[0]+z[1]*e[1]+z[2]*e[2]),1];}
//</MATHS>

// ---------- 正运动学（FK）：只算 4×4 矩阵，**不碰几何** ----------
// 与 assembly.py 的 Kin 同源：W[child] = W[parent] · T(xyz) · R(rpy) · R(axis,θ)
//<FK>
const NL=META.links.length, NJ=META.joints.length;
const ANG=new Float64Array(NJ);                 // 关节角（度）—— UI 的唯一真值
const W=new Array(NL), MLINK=new Array(NL);
const JORIGIN=META.joints.map(function(j){
  return mMul(mTrans(j.xyz[0],j.xyz[1],j.xyz[2]), mRpy(j.rpy[0],j.rpy[1],j.rpy[2]));});
function fkSolve(){
  const r=META.root;
  W[r]=META.links[r].zero;
  for(let q=0;q<META.fkOrder.length;q++){
    const k=META.fkOrder[q], j=META.joints[k], th=ANG[k]*Math.PI/180;
    let o=JORIGIN[k];
    if(Math.abs(th)>1e-12) o=mMul(o,mAxisAngle(j.axis,th));
    W[j.child]=mMul(W[j.parent],o);
  }
  for(let i=0;i<NL;i++) MLINK[i]=mMul(W[i],META.links[i].inv0);
}
//</FK>

// ---------- 着色器 ----------
const VS=["attribute vec3 aPos;attribute vec3 aNrm;",
 "uniform mat4 uMVP;uniform mat3 uNrm;",
 "varying vec3 vN;",
 "void main(){vN=uNrm*aNrm;gl_Position=uMVP*vec4(aPos,1.0);}"].join("\n");
const FS=["precision mediump float;varying vec3 vN;",
 "uniform vec3 uColor;uniform float uAlpha;",
 "void main(){vec3 n=normalize(vN);vec3 L=normalize(vec3(0.42,-0.62,0.66));",
 "float d=max(dot(n,L),0.0);",
 "vec3 c=uColor*(0.44+0.14*max(n.z,0.0)+0.58*d);",
 "gl_FragColor=vec4(c,uAlpha);}"].join("\n");
function sh(t,s){const o=gl.createShader(t);gl.shaderSource(o,s);gl.compileShader(o);
  if(!gl.getShaderParameter(o,gl.COMPILE_STATUS))console.error(gl.getShaderInfoLog(o));return o;}
const prog=gl.createProgram();
gl.attachShader(prog,sh(gl.VERTEX_SHADER,VS));
gl.attachShader(prog,sh(gl.FRAGMENT_SHADER,FS));
gl.linkProgram(prog);gl.useProgram(prog);
const aPos=gl.getAttribLocation(prog,"aPos"),aNrm=gl.getAttribLocation(prog,"aNrm"),
      uMVP=gl.getUniformLocation(prog,"uMVP"),uNrm=gl.getUniformLocation(prog,"uNrm"),
      uColor=gl.getUniformLocation(prog,"uColor"),
      uAlpha=gl.getUniformLocation(prog,"uAlpha");

// ---------- 拾取用的小程序：把零件号编码成颜色画 1 个像素，再 readPixels ----------
// 为什么不用射线求交：87 件 / 16 万顶点在 JS 里逐三角形求交要几百毫秒且要维护 BVH；
// 这里复用自己的渲染路径 + scissor 到 1×1，一次点击只多一帧的顶点开销。
const PICK_VS="attribute vec3 aPos;uniform mat4 uMVP;"+
  "void main(){gl_Position=uMVP*vec4(aPos,1.0);}";
const PICK_FS="precision mediump float;uniform vec3 uId;"+
  "void main(){gl_FragColor=vec4(uId,1.0);}";
const pickProg=gl.createProgram();
gl.attachShader(pickProg,sh(gl.VERTEX_SHADER,PICK_VS));
gl.attachShader(pickProg,sh(gl.FRAGMENT_SHADER,PICK_FS));
gl.linkProgram(pickProg);
const pMVP=gl.getUniformLocation(pickProg,"uMVP"),pId=gl.getUniformLocation(pickProg,"uId"),
      pPos=gl.getAttribLocation(pickProg,"aPos");

// ---------- 上传几何（一次性：顶点/法线交错 VBO + 索引 IBO）----------
const F32=new Float32Array(BUF,0,META.floatCount);
const IDX=META.indexCount?new Uint16Array(BUF,META.floatCount*4,META.indexCount):null;
const vbo=gl.createBuffer();
gl.bindBuffer(gl.ARRAY_BUFFER,vbo);
gl.bufferData(gl.ARRAY_BUFFER,F32,gl.STATIC_DRAW);
gl.enableVertexAttribArray(aPos);gl.enableVertexAttribArray(aNrm);
if(IDX){const ibo=gl.createBuffer();gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,ibo);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,IDX,gl.STATIC_DRAW);}

// ---------- 热区盒：一个单位立方体（36 顶点，逐面法线），每个盒子只换模型矩阵 ----------
const CUBE=(function(){
  const out=[];
  [[0,1,2],[1,2,0],[2,0,1]].forEach(function(ax){
    [1,-1].forEach(function(sg){
      const n=[0,0,0];n[ax[0]]=sg;
      const u=[0,0,0],w=[0,0,0];u[ax[1]]=sg;w[ax[2]]=sg;
      function P(su,sw){const p=[0,0,0];
        for(let k=0;k<3;k++)p[k]=0.5*n[k]+0.5*su*u[k]+0.5*sw*w[k];return p;}
      const q=[P(-1,-1),P(1,-1),P(1,1),P(-1,1)];
      [[0,1,2],[0,2,3]].forEach(function(t){
        t.forEach(function(i){out.push(q[i][0],q[i][1],q[i][2],n[0],n[1],n[2]);});});
    });
  });
  return new Float32Array(out);
})();
const cubeBuf=gl.createBuffer();
gl.bindBuffer(gl.ARRAY_BUFFER,cubeBuf);
gl.bufferData(gl.ARRAY_BUFFER,CUBE,gl.STATIC_DRAW);
gl.bindBuffer(gl.ARRAY_BUFFER,vbo);

// ---------- 相机 ----------
const bbox=META.bbox, ctr=[(bbox[0]+bbox[3])/2,(bbox[1]+bbox[4])/2,(bbox[2]+bbox[5])/2];
const radius=Math.max(bbox[3]-bbox[0],bbox[4]-bbox[1],bbox[5]-bbox[2])/2;
const HOME={theta:0.9,phi:1.15,dist:radius*3.4,target:ctr.slice()};
let theta=HOME.theta,phi=HOME.phi,dist=HOME.dist,target=HOME.target.slice();
let spin=false,wire=false,mateAlpha=true,groundOn=true;
const kindOn={},KCOL={};
META.kinds.forEach(function(k){kindOn[k.kind]=true;KCOL[k.kind]=k.color;});
let focus=null;                                  // 聚焦的关节下标（null = 不聚焦）

// ---------- 冲突分档：着色 / 隔离 / 点选 / 热区 ----------
// 档位定义与判定文案来自 Python 侧（唯一判定源 fitcheck.verdict）；JS 只做显示。
const CONF=META.conf||null;
const TIERS=CONF?CONF.tiers:[];
const RANK=TIERS.map(function(t){return t.rank||0;});
const TRGB=TIERS.map(function(t){return t.color?[t.color[0]/255,t.color[1]/255,
  t.color[2]/255]:null;});
const NP=META.parts.length;
META.parts.forEach(function(p,i){p.i=i;});
const PAIRS=CONF?CONF.pairs:[];
const PART_PAIRS=[];for(let i=0;i<NP;i++)PART_PAIRS.push([]);
PAIRS.forEach(function(pr,pi){PART_PAIRS[pr[0]].push(pi);PART_PAIRS[pr[1]].push(pi);});
const PCONF=new Array(NP).fill(null);            // 每件：{t:最严重档, v:合计体积, n:对数}
PAIRS.forEach(function(pr){
  for(let s=0;s<2;s++){const i=pr[s],t=pr[4];
    if(!PCONF[i])PCONF[i]={t:t,v:0,n:0};
    if(RANK[t]>RANK[PCONF[i].t])PCONF[i].t=t;
    PCONF[i].v+=pr[2];PCONF[i].n++;}
});
const N_CONF=PCONF.filter(function(c){return c;}).length;
let confColor=true;                              // 按分档着色
let isolate=false;                               // 只看冲突件+对手件
let isoMin=2;                                    // 隔离门槛（档位 rank：2=⚠️及以上）
let heatAll=false;                               // 全部热区盒
let sel=-1,selPair=-1;                           // 选中的零件 / 选中的"一对"
const partnerSet=new Set();
const VIS=new Array(NP).fill(false);             // 隔离模式下可见（含对手件）
function rebuildVis(){
  for(let i=0;i<NP;i++)VIS[i]=false;
  PAIRS.forEach(function(pr){if(RANK[pr[4]]>=isoMin){VIS[pr[0]]=true;VIS[pr[1]]=true;}});
}
rebuildVis();
function partVisible(i){
  const p=META.parts[i];
  if(!kindOn[p.kind])return false;
  if(p.kind==="ground"&&!groundOn)return false;
  return true;
}
function refreshPartners(){
  partnerSet.clear();
  if(sel<0)return;
  PART_PAIRS[sel].forEach(function(pi){
    const pr=PAIRS[pi];partnerSet.add(pr[0]===sel?pr[1]:pr[0]);});
}
function baseAlpha(i){
  return META.parts[i].mate?__MATE_ALPHA__:1.0;  // 配合面始终半透明（五档第 5 档）
}
function alphaOf(p){
  const i=p.i;
  if(selPair>=0){const pr=PAIRS[selPair];return (i===pr[0]||i===pr[1])?baseAlpha(i):0.05;}
  if(sel>=0)return (i===sel||partnerSet.has(i))?baseAlpha(i):0.05;
  if(focus!==null){return p.mate===META.joints[focus].name?0.92:0.10;}
  if(isolate)return VIS[i]?baseAlpha(i):0.05;
  if(mateAlpha&&p.mate)return __MATE_ALPHA__;
  return 1.0;
}
function colorOf(p){
  if(!confColor||!CONF)return KCOL[p.kind];
  const c=PCONF[p.i];
  const rgb=c?TRGB[c.t]:null;
  return rgb||KCOL[p.kind];                      // 无冲突 → 保留零件本色
}
function tierOf(i){const c=PCONF[i];return c?TIERS[c.t]:null;}
function tierText(i){
  const t=tierOf(i);
  if(!CONF)return "无冲突数据";
  return t?(t.label+"（"+t.rule.split("（")[0]+"）"):"无冲突（与任何零件重合 ≤1 mm³）";
}
const SCR=new Float32Array(16), SCR3=new Float32Array(9);
function partMatrix(p){return (p.link==="")?mIdent():MLINK[META.linkIdx[p.link]];}
function mScaleAbout(c,s){const o=mIdent();o[0]=o[5]=o[10]=s;
  o[12]=c[0]*(1-s);o[13]=c[1]*(1-s);o[14]=c[2]*(1-s);return o;}
// 描边 = 反壳法（放大后只画背面）：≈1.3 mm 等宽，不随零件大小变
function outlineList(){
  const list=[];
  if(wire)return list;
  for(let i=0;i<NP;i++){
    const p=META.parts[i];
    if(!partVisible(i))continue;
    const a=alphaOf(p);
    if(a<0.45)continue;
    const inPair=(selPair>=0)&&(i===PAIRS[selPair][0]||i===PAIRS[selPair][1]);
    if(i===sel||inPair){list.push([i,[1,1,1],1.055]);continue;}
    if(partnerSet.has(i)){list.push([i,[0.42,0.95,1.0],1.045]);continue;}
    const c=confColor?PCONF[i]:null;
    if(c&&RANK[c.t]>=2)list.push([i,[0.04,0.07,0.11],1.0]);   // ⚠️/❌ 加深色描边
  }
  return list;
}
function drawOutlines(pv){
  const list=outlineList();
  if(!list.length)return;
  gl.enable(gl.CULL_FACE);gl.cullFace(gl.FRONT);
  gl.depthMask(true);
  gl.bindBuffer(gl.ARRAY_BUFFER,vbo);
  for(let k=0;k<list.length;k++){
    const p=META.parts[list[k][0]],c=list[k][1],b=p.aabb;
    const diag=Math.hypot(b[3]-b[0],b[4]-b[1],b[5]-b[2])||1;
    const ctr=[(b[0]+b[3])/2,(b[1]+b[4])/2,(b[2]+b[5])/2];
    const M=mMul(partMatrix(p),mScaleAbout(ctr,1+2.6*list[k][2]/diag));
    gl.vertexAttribPointer(aPos,3,gl.FLOAT,false,24,p.vOff*24);
    gl.vertexAttribPointer(aNrm,3,gl.FLOAT,false,24,p.vOff*24+12);
    SCR.set(mMul(pv,M));gl.uniformMatrix4fv(uMVP,false,SCR);
    SCR3.set(m3of(M));gl.uniformMatrix3fv(uNrm,false,SCR3);
    gl.uniform3f(uColor,c[0],c[1],c[2]);gl.uniform1f(uAlpha,1.0);
    if(p.indexed)gl.drawElements(gl.TRIANGLES,p.iCount,gl.UNSIGNED_SHORT,p.iOff*2);
    else gl.drawArrays(gl.TRIANGLES,p.vOff,p.vCount);
  }
  gl.cullFace(gl.BACK);
}
// 热区盒 = 重合体的**轴对齐包围盒**（近似）：零位算好，随"件 A"所在 link 刚性移动
let heatDrawn=0;
function heatList(){
  if(selPair>=0)return PAIRS[selPair].length>=11?[selPair]:[];
  if(!heatAll)return [];
  const out=[];
  for(let k=0;k<PAIRS.length;k++)
    if(PAIRS[k].length>=11&&RANK[PAIRS[k][4]]>=isoMin)out.push(k);
  return out;
}
function drawHeat(pv){
  const list=heatList();
  heatDrawn=list.length;
  if(!list.length)return;
  gl.bindBuffer(gl.ARRAY_BUFFER,cubeBuf);
  gl.disable(gl.CULL_FACE);gl.depthMask(false);
  gl.vertexAttribPointer(aPos,3,gl.FLOAT,false,24,0);
  gl.vertexAttribPointer(aNrm,3,gl.FLOAT,false,24,12);
  gl.uniform3f(uColor,1.0,0.22,0.20);gl.uniform1f(uAlpha,0.30);
  for(let k=0;k<list.length;k++){
    const pr=PAIRS[list[k]],b=pr.slice(5,11);
    const m=mIdent();
    m[0]=Math.max(b[3]-b[0],0.3);m[5]=Math.max(b[4]-b[1],0.3);
    m[10]=Math.max(b[5]-b[2],0.3);
    m[12]=(b[0]+b[3])/2;m[13]=(b[1]+b[4])/2;m[14]=(b[2]+b[5])/2;
    const M=mMul(partMatrix(META.parts[pr[0]]),m);
    SCR.set(mMul(pv,M));gl.uniformMatrix4fv(uMVP,false,SCR);
    SCR3.set(m3of(M));gl.uniformMatrix3fv(uNrm,false,SCR3);
    gl.drawArrays(gl.TRIANGLES,0,36);
  }
  gl.depthMask(true);gl.enable(gl.CULL_FACE);gl.cullFace(gl.BACK);
}
function viewProj(){
  const w=canvas.clientWidth,h=canvas.clientHeight;
  const eye=[target[0]+dist*Math.sin(phi)*Math.cos(theta),
             target[1]+dist*Math.sin(phi)*Math.sin(theta),
             target[2]+dist*Math.cos(phi)];
  return mMul(persp(Math.PI/4,w/h,radius*0.02,radius*40), lookAt(eye,target,[0,0,1]));
}
function draw(){
  const w=canvas.clientWidth,h=canvas.clientHeight;
  if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
  gl.viewport(0,0,w,h);
  gl.clearColor(0.039,0.145,0.251,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
  gl.enable(gl.DEPTH_TEST);gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
  if(wire){gl.disable(gl.CULL_FACE);}else{gl.enable(gl.CULL_FACE);gl.cullFace(gl.BACK);}
  const pv=viewProj();
  fkSolve();                                     // ← 每次重绘只做这一件事（矩阵）
  const mode=wire?gl.LINES:gl.TRIANGLES;
  gl.bindBuffer(gl.ARRAY_BUFFER,vbo);
  if(!wire)drawOutlines(pv);                     // 描边先画（写深度），实体再盖住内部
  for(let pass=0;pass<2;pass++){
    const opaque=(pass===0);
    gl.depthMask(opaque);
    for(let i=0;i<META.parts.length;i++){
      const p=META.parts[i];
      if(!partVisible(i))continue;
      const a=alphaOf(p);
      if((a>=0.999)!==opaque)continue;
      const M=partMatrix(p);
      gl.vertexAttribPointer(aPos,3,gl.FLOAT,false,24,p.vOff*24);
      gl.vertexAttribPointer(aNrm,3,gl.FLOAT,false,24,p.vOff*24+12);
      SCR.set(mMul(pv,M));gl.uniformMatrix4fv(uMVP,false,SCR);
      SCR3.set(m3of(M));gl.uniformMatrix3fv(uNrm,false,SCR3);
      if(wire) gl.uniform3f(uColor,0.62,0.74,0.96);
      else{const c=colorOf(p);gl.uniform3f(uColor,c[0]/255,c[1]/255,c[2]/255);}
      gl.uniform1f(uAlpha,wire?1.0:a);
      if(p.indexed) gl.drawElements(mode,p.iCount,gl.UNSIGNED_SHORT,p.iOff*2);
      else if(!wire) gl.drawArrays(gl.TRIANGLES,p.vOff,p.vCount);
    }
  }
  if(!wire)drawHeat(pv);
  gl.depthMask(true);
}

// ---------- 点选：把零件号编码成颜色，scissor 到 1×1 画一遍再 readPixels ----------
function pickAt(cx,cy){
  const x=Math.round(cx),y=Math.round(canvas.height-Math.round(cy));
  if(x<0||y<0||x>=canvas.width||y>=canvas.height)return -1;
  gl.enable(gl.SCISSOR_TEST);gl.scissor(x,y,1,1);
  gl.clearColor(0,0,0,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
  gl.disable(gl.BLEND);gl.enable(gl.DEPTH_TEST);gl.depthMask(true);
  gl.disable(gl.CULL_FACE);
  const pv=viewProj();
  fkSolve();
  gl.useProgram(pickProg);gl.bindBuffer(gl.ARRAY_BUFFER,vbo);
  for(let i=0;i<NP;i++){
    const p=META.parts[i];
    if(!partVisible(i))continue;
    const id=i+1;
    gl.uniform3f(pId,(id&255)/255,((id>>8)&255)/255,((id>>16)&255)/255);
    gl.vertexAttribPointer(pPos,3,gl.FLOAT,false,24,p.vOff*24);
    if(p.iCount){const M=partMatrix(p);
      SCR.set(mMul(pv,M));gl.uniformMatrix4fv(pMVP,false,SCR);
      gl.drawElements(gl.TRIANGLES,p.iCount,gl.UNSIGNED_SHORT,p.iOff*2);}
  }
  const px=new Uint8Array(4);
  gl.readPixels(x,y,1,1,gl.RGBA,gl.UNSIGNED_BYTE,px);
  gl.disable(gl.SCISSOR_TEST);
  gl.useProgram(prog);gl.enable(gl.BLEND);gl.enable(gl.CULL_FACE);gl.cullFace(gl.BACK);
  gl.clearColor(0.039,0.145,0.251,1);
  const id=px[0]+px[1]*256+px[2]*65536-1;
  return (id>=0&&id<NP)?id:-1;
}
function selectPart(i){
  sel=i;selPair=-1;focus=null;
  jointRow.forEach(function(r){r.classList.remove("focus");});
  refreshPartners();renderSel();request();
}
function selectPair(pi){
  selPair=pi;sel=-1;partnerSet.clear();
  focus=null;jointRow.forEach(function(r){r.classList.remove("focus");});
  renderSel();request();
}
function clearSel(){sel=-1;selPair=-1;partnerSet.clear();renderSel();request();}
let dirty=true;
function request(){dirty=true;}
let halt=false;                                  // 自检跑完就停 RAF（headless 软件渲染很贵）
(function loop(){if(halt)return;if(spin){theta+=0.006;dirty=true;}
  if(dirty){dirty=false;draw();}requestAnimationFrame(loop);})();

// ---------- 键鼠：拖拽旋转 / 平移 / 单击点选 ----------
let drag=null;
canvas.addEventListener("contextmenu",function(e){e.preventDefault();});
canvas.addEventListener("mousedown",function(e){drag={ox:e.clientX,oy:e.clientY,
  x:e.clientX,y:e.clientY,b:e.button,pan:(e.button===2||e.shiftKey),moved:false};});
window.addEventListener("mouseup",function(e){
  if(drag&&!drag.moved&&!drag.pan&&drag.b===0&&e.target===canvas){
    const r=canvas.getBoundingClientRect();
    const hit=pickAt(e.clientX-r.left,e.clientY-r.top);
    if(hit>=0&&META.parts[hit].kind!=="ground")selectPart(hit);else clearSel();
  }
  drag=null;});
window.addEventListener("mousemove",function(e){
  if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;
  if(Math.abs(e.clientX-drag.ox)>3||Math.abs(e.clientY-drag.oy)>3)drag.moved=true;
  if(drag.pan){
    const k=dist*0.0016;
    const right=[-Math.sin(theta),Math.cos(theta),0];
    const up=[-Math.cos(theta)*Math.cos(phi),-Math.sin(theta)*Math.cos(phi),Math.sin(phi)];
    for(let i=0;i<3;i++)target[i]+=(-right[i]*dx+up[i]*dy)*k;
  }else{theta-=dx*0.008;phi=Math.max(0.05,Math.min(Math.PI-0.05,phi-dy*0.008));}
  request();});
canvas.addEventListener("wheel",function(e){e.preventDefault();
  dist*=Math.exp(e.deltaY*0.0011);
  dist=Math.max(radius*0.35,Math.min(radius*30,dist));request();},{passive:false});
function resetView(){theta=HOME.theta;phi=HOME.phi;dist=HOME.dist;target=HOME.target.slice();request();}
window.addEventListener("resize",request);

// ---------- 关节滑条（22 条，范围 = URDF 限位）----------
const PRESETS=META.presets;
const SUB=document.getElementById("sub"), HUD_POSE=document.getElementById("pose");
const rowsEl=document.getElementById("sliders");
const jointRow=[];
function fmtDeg(v){return (Math.round(v*10)/10).toFixed(1).replace(/\.0$/,"")+"°";}
META.joints.forEach(function(j,k){
  const lo=Math.round(j.lo*180/Math.PI), hi=Math.round(j.hi*180/Math.PI);
  const row=document.createElement("div");row.className="jrow";
  const nm=document.createElement("span");nm.className="jn";nm.textContent=j.name;
  nm.title="点击 = 只显示本关节的配合件（"+j.name+"）";
  const rg=document.createElement("input");
  rg.type="range";rg.min=lo;rg.max=hi;rg.step=1;rg.value=0;
  rg.title=j.name+"  "+lo+"° … "+hi+"°（URDF 限位）";
  const val=document.createElement("span");val.className="jv";
  rg.addEventListener("input",function(){ANG[k]=parseFloat(rg.value);val.textContent=fmtDeg(ANG[k]);
    HUD_POSE.textContent="姿态："+poseLabel();request();});
  nm.addEventListener("click",function(){focus=(focus===k)?null:k;
    jointRow.forEach(function(r,i){r.classList.toggle("focus",i===focus);});request();});
  row.appendChild(nm);row.appendChild(rg);row.appendChild(val);
  rowsEl.appendChild(row);
  jointRow.push(row);
  j.row={range:rg,val:val};
});
function setJoint(k,deg){
  const j=META.joints[k];
  const v=Math.max(j.lo*180/Math.PI,Math.min(j.hi*180/Math.PI,deg));
  ANG[k]=v;j.row.range.value=v;j.row.val.textContent=fmtDeg(v);
}
function applyPose(pose){
  META.joints.forEach(function(j,k){setJoint(k,pose[j.name]||0);});
  HUD_POSE.textContent="姿态："+poseLabel();request();
}
function currentPose(){const o={};META.joints.forEach(function(j,k){
  if(Math.abs(ANG[k])>1e-9)o[j.name]=Math.round(ANG[k]*10)/10;});return o;}
function poseLabel(){
  for(let i=0;i<PRESETS.length;i++){const p=PRESETS[i];
    if(META.joints.every(function(j,k){return Math.abs(ANG[k]-(p.pose[j.name]||0))<0.51;}))
      return p.name;}
  return "自定义（"+Object.keys(currentPose()).length+" 个关节非零）";
}
const presEl=document.getElementById("presets");
PRESETS.forEach(function(p,i){
  const b=document.createElement("button");b.textContent=p.name;
  b.title="预设 "+(i+1)+"（快捷键 "+(i+1)+"）";
  b.onclick=function(){applyPose(p.pose);
    Array.prototype.forEach.call(presEl.children,function(c,j){c.classList.toggle("on",j===i);});};
  presEl.appendChild(b);
});
document.getElementById("zero").onclick=function(){applyPose({});
  Array.prototype.forEach.call(presEl.children,function(c,j){c.classList.toggle("on",j===0);});};
document.getElementById("copy").onclick=function(){
  const h="#pose="+META.joints.map(function(j,k){
    return j.name+":"+(Math.round(ANG[k]*10)/10);}).join(",");
  const ta=document.getElementById("poseOut");
  ta.value=location.href.split("#")[0]+h;ta.style.display="block";ta.focus();ta.select();
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(ta.value);}
  history.replaceState(null,"",h);
};

// ---------- 显示开关 ----------
document.getElementById("mateChk").addEventListener("change",function(e){
  mateAlpha=e.target.checked;request();});
document.getElementById("groundChk").addEventListener("change",function(e){
  groundOn=e.target.checked;request();});
document.getElementById("reset").onclick=resetView;
document.getElementById("wire").onclick=function(){wire=!wire;request();};
document.getElementById("spin").onclick=function(){spin=!spin;request();};
const kinds=document.getElementById("kinds");
META.kinds.forEach(function(k){
  const el=document.createElement("label");
  const cb=document.createElement("input");cb.type="checkbox";cb.checked=true;
  const sw=document.createElement("span");sw.className="sw";
  sw.style.background="rgb("+k.color.join(",")+")";
  const tx=document.createElement("span");tx.textContent=k.label;
  const nn=document.createElement("span");nn.className="n";
  nn.textContent=(k.tris/1000).toFixed(0)+"k";
  cb.addEventListener("change",function(){kindOn[k.kind]=cb.checked;request();});
  el.appendChild(cb);el.appendChild(sw);el.appendChild(tx);el.appendChild(nn);
  kinds.appendChild(el);
});

// ---------- 键盘 ----------
window.addEventListener("keydown",function(e){
  const k=e.key.toLowerCase();
  if(k==="r"){resetView();}
  else if(k==="w"){wire=!wire;request();}
  else if(k==="t"){mateAlpha=!mateAlpha;document.getElementById("mateChk").checked=mateAlpha;request();}
  else if(k==="0"){document.getElementById("zero").onclick();}
  else if(k>="1"&&k<="9"&&PRESETS[+k-1]){presEl.children[+k-1].onclick();}
  else if(e.code==="Space"){spin=!spin;request();e.preventDefault();}
});

// ---------- 初始姿态：URL #pose=关节:度,… 或 #preset=名字|序号 ----------
const START=__START_PRESET__;
function applyHash(){
  const h=location.hash||"";
  let m=/preset=([^&]+)/.exec(h);
  if(m){
    const v=decodeURIComponent(m[1]);
    let i=PRESETS.findIndex(function(p){return p.name===v;});
    if(i<0&&/^[0-9]+$/.test(v))i=Math.min(PRESETS.length-1,parseInt(v,10));
    if(i>=0){presEl.children[i].onclick();return true;}
  }
  m=/pose=([^&]+)/.exec(h);
  if(m){
    decodeURIComponent(m[1]).split(",").forEach(function(kv){
      const a=kv.split(":");if(a.length!==2)return;
      const k=META.joints.findIndex(function(j){return j.name===a[0];});
      if(k>=0&&isFinite(parseFloat(a[1])))setJoint(k,parseFloat(a[1]));
    });
    HUD_POSE.textContent="姿态："+poseLabel();request();return true;
  }
  return false;
}
// ---------- 内置自检（URL 带 #selftest=1 时运行；用 headless 浏览器 --dump-dom 抓结果）----------
// 为什么要有它：光"能打开"证明不了滑条/预设/半透明真的生效。这里在**真实 WebGL 上下文**里
// 逐条断言（缓冲区大小、拖动后 FK 矩阵变化、不同预设的像素签名不同、gl.getError()==0）。
let geoUploads=0;
const _bufData=gl.bufferData.bind(gl);
gl.bufferData=function(){geoUploads++;return _bufData.apply(null,arguments);};
let drawCalls=0;
const _drawEl=gl.drawElements.bind(gl), _drawAr=gl.drawArrays.bind(gl);
gl.drawElements=function(){drawCalls++;return _drawEl.apply(null,arguments);};
gl.drawArrays=function(){drawCalls++;return _drawAr.apply(null,arguments);};
function pixSig(){
  const px=new Uint8Array(canvas.width*canvas.height*4);
  gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,px);
  let on=0,sum=0;
  for(let i=0;i<px.length;i+=4*13){
    if(px[i]>16||px[i+1]>48||px[i+2]>80)on++;
    sum+=px[i]+px[i+1]+px[i+2];
  }
  return on+":"+sum;
}
function selftest(){
  const res={ok:true,checks:[],fail:[]};
  function chk(name,cond,extra){
    if(!cond){res.ok=false;res.fail.push(name);}
    res.checks.push(name+"="+(cond?"OK":"FAIL")+(extra===undefined?"":"("+extra+")"));
  }
  chk("webgl",!!gl);
  if(!gl){                       // 没有 WebGL 就把结论直接写在页面上，好让截图看出来
    document.body.insertAdjacentHTML("afterbegin",
      "<pre id='selftestbox' style='position:fixed;left:8px;top:8px;z-index:9;"+
      "background:#fff;color:#900;font:16px/1.4 monospace;padding:10px'>"+
      "SELFTEST FAIL: 无 WebGL 上下文</pre>");
    return;
  }
  chk("parts",META.parts.length>=80,META.parts.length);
  chk("joints22",META.joints.length===22,META.joints.length);
  chk("sliders22",document.querySelectorAll("#sliders input[type=range]").length===22);
  chk("presets>=4",document.querySelectorAll("#presets button").length>=4,
      document.querySelectorAll("#presets button").length);
  chk("uMVP/uNrm",uMVP!==null&&uNrm!==null);
  chk("vboBytes",gl.getBufferParameter(gl.ARRAY_BUFFER,gl.BUFFER_SIZE)>=META.floatCount*4,
      gl.getBufferParameter(gl.ARRAY_BUFFER,gl.BUFFER_SIZE));
  if(IDX)chk("iboBytes",gl.getBufferParameter(gl.ELEMENT_ARRAY_BUFFER,gl.BUFFER_SIZE)
                          ===META.indexCount*2,
             gl.getBufferParameter(gl.ELEMENT_ARRAY_BUFFER,gl.BUFFER_SIZE));
  const uploadsAfterBoot=geoUploads;
  // 逐预设：像素签名用小画布测（软件渲染下大画布一帧要几十秒），最后再恢复原尺寸画一张
  const ow=canvas.style.width, oh=canvas.style.height;
  canvas.style.width="360px";canvas.style.height="270px";
  const sigs={},msig={};
  META.presets.forEach(function(p,i){
    presEl.children[i].onclick();
    fkSolve();
    msig[p.name]=MLINK.map(function(m){return m[12].toFixed(2)+","+m[13].toFixed(2);}).join("|");
    draw();
    sigs[p.name]=pixSig();
  });
  canvas.style.width=ow;canvas.style.height=oh;
  const uniqMat=new Set(Object.keys(msig).map(function(k){return msig[k];}));
  chk("预设FK互不相同",uniqMat.size===META.presets.length,uniqMat.size+"/"+META.presets.length);
  const uniqPix=new Set(Object.keys(sigs).map(function(k){return sigs[k];}));
  chk("预设像素签名互不相同",uniqPix.size===META.presets.length,
      uniqPix.size+"/"+META.presets.length);
  const cover=Object.keys(sigs).map(function(k){return parseInt(sigs[k].split(":")[0],10);});
  const nMini=cover.filter(function(v){return v>60;}).length;
  chk("每个预设都有实体像素",nMini===META.presets.length,
      nMini+"/"+META.presets.length+" 覆盖率 "+cover.join("/"));
  // 单条滑条：拖 head_yaw 只改下游 link 的矩阵
  document.getElementById("zero").onclick();
  fkSolve();
  const kHead=META.joints.findIndex(function(j){return j.name==="head_yaw";});
  const bHead=MLINK[META.linkIdx["head"]].join(",");
  const bPelvis=MLINK[META.linkIdx["pelvis"]].join(",");
  const rg=jointRow[kHead].querySelector("input[type=range]");
  rg.value="45";rg.dispatchEvent(new Event("input"));
  fkSolve();
  chk("滑条改FK(head)",bHead!==MLINK[META.linkIdx["head"]].join(","));
  chk("滑条不动上游(pelvis)",bPelvis===MLINK[META.linkIdx["pelvis"]].join(","));
  rg.value="999";rg.dispatchEvent(new Event("input"));
  chk("滑条越界被夹紧",Math.abs(ANG[kHead]-META.joints[kHead].hi*180/Math.PI)<0.02,
      ANG[kHead]+"° vs 上限 "+META.joints[kHead].hi*180/Math.PI+"°");
  document.getElementById("zero").onclick();fkSolve();
  // 配合件半透明：勾选框真的改 alpha
  const mp=META.parts.filter(function(p){return p.mate;})[0];
  const aOn=(function(){mateAlpha=true;return alphaOf(mp);})();
  const aOff=(function(){mateAlpha=false;return alphaOf(mp);})();
  mateAlpha=true;document.getElementById("mateChk").checked=true;
  chk("配合件半透明生效",aOn<1&&aOff===1,aOn+"→"+aOff);
  const nMate=META.parts.filter(function(p){return p.mate;}).length;
  chk("半透明件数>0",nMate>0,nMate);
  // 拖滑条不重建几何；确实在发起绘制；无 GL 错误
  chk("拖滑条未重传几何",geoUploads===uploadsAfterBoot,geoUploads);
  chk("有绘制调用",drawCalls>0,drawCalls);
  chk("gl.getError==0",gl.getError()===0);
  const box=document.createElement("pre");
  box.id="selftestbox";
  box.style.cssText="position:fixed;left:8px;top:8px;z-index:9;background:#fff;color:#123;"+
    "font:13px/1.5 monospace;padding:10px 12px;border-radius:6px;max-width:640px;white-space:pre-wrap";
  box.textContent="SELFTEST "+(res.ok?"PASS":"FAIL")+"\n"+res.checks.join("\n");
  document.body.appendChild(box);
  const el=document.createElement("div");
  el.id="selftest";el.style.display="none";
  el.textContent="SELFTEST_RESULT "+JSON.stringify(res);
  document.body.appendChild(el);
  document.title="SELFTEST "+(res.ok?"PASS":"FAIL");
  halt=true;                                     // 停掉 RAF，headless 才能尽快 dump
}
if(/selftest=1/.test(location.hash)){selftest();}

SUB.textContent=META.subtitle;
if(!applyHash()){presEl.children[START].onclick();}
request();
</script>
</body>
</html>
"""


def write_html(cache: Dict[str, Any], path: Path, title: str, subtitle: str,
               start_preset: int) -> Dict[str, Any]:
    """把（缓存里的）几何 + 运动学 + 预设打包进一个自包含 HTML。"""
    meta = {
        "schema": cache["schema"], "geomVersion": cache["geomVersion"],
        "tol": cache["tol"], "builtAt": cache["builtAt"], "srcMd5": cache["srcMd5"],
        "bbox": cache["bbox"], "subtitle": subtitle,
        "links": cache["links"], "root": cache["root"],
        "joints": cache["joints"], "fkOrder": cache["fkOrder"],
        "parts": cache["parts"], "kinds": cache["kinds"],
        "vertexCount": cache["vertexCount"], "floatCount": cache["floatCount"],
        "indexCount": cache["indexCount"],
        "stats": cache["stats"],
        "presets": [{"name": n, "pose": p} for n, p in POSE_PRESETS],
    }
    html = (_HTML.replace("__TITLE__", title)
            .replace("__NJOINT__", str(len(cache["joints"])))
            .replace("__MATE_ALPHA__", f"{MATE_ALPHA:.2f}")
            .replace("__START_PRESET__", str(start_preset))
            .replace("__B64__", cache["vertsB64"] + cache["idxB64"])
            .replace("__META__", json.dumps(meta, ensure_ascii=False,
                                            separators=(",", ":"))))
    path.write_text(html, encoding="utf-8")
    return {"html_bytes": path.stat().st_size,
            "geo_bytes": len(cache["vertsB64"]) + len(cache["idxB64"]),
            "triangles": cache["stats"]["triangles"]}


def export_glb(items: Sequence[Tuple[str, cq.Workplane]], path: Path) -> Optional[str]:
    """用 CadQuery 官方导出器出标准 glTF 二进制（需要 vtk）。姿态 = 机械零位。"""
    try:
        asm = cq.Assembly()
        for name, wp in items:
            k = R.kind_of(name)
            c = KIND_COLORS[k]
            asm.add(wp.val(), name=name,
                    color=cq.Color(c[0] / 255, c[1] / 255, c[2] / 255))
        # 注意：必须调 exportGLTF 本体；走 cq.exporters.export(..., exportType="GLTF")
        # 会在 dispatch 上抛 DispatchError（cadquery 2.5.2 的已知路由问题）
        from cadquery.occ_impl.exporters.assembly import exportGLTF
        exportGLTF(asm, str(path), binary=True, tolerance=0.4,
                   angularTolerance=0.4)
        return f"{path.stat().st_size/1e6:.1f} MB"
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] GLB 导出跳过（{type(exc).__name__}: {exc}）")
        print("         装 vtk 后可用：.venv-cad/bin/pip install -i "
              "https://mirrors.aliyun.com/pypi/simple/ vtk")
        return None


# --------------------------------------------------------------------------
# 姿势预设：按 URDF 限位夹紧（不静默改数）
# --------------------------------------------------------------------------
def clamped_presets() -> List[Tuple[str, Dict[str, float]]]:
    lim = read_limits(DESIGN / "atri.urdf")
    out: List[Tuple[str, Dict[str, float]]] = []
    for name, pose in POSE_PRESETS:
        fixed: Dict[str, float] = {}
        for jn, v in pose.items():
            if jn not in lim:
                print(f"  [WARN] 预设「{name}」里的关节 {jn!r} 不在 URDF 里，已忽略")
                continue
            lo, hi = math.degrees(lim[jn][0]), math.degrees(lim[jn][1])
            if v < lo - 1e-6 or v > hi + 1e-6:
                print(f"  [WARN] 预设「{name}」{jn}={v}° 超出 URDF 限位"
                      f"[{lo:.0f},{hi:.0f}]° → 夹到边界")
            fixed[jn] = max(lo, min(hi, v))
        out.append((name, fixed))
    return out


# --------------------------------------------------------------------------
# 自检：静态检查 + JS/Python FK 数值对拍
# --------------------------------------------------------------------------
_FK_HARNESS = r"""// 自动生成（preview.py --check）：JS FK ⟷ Python assembly.Kin 数值对拍
// 用法：node verify_fk.mjs <preview.html> <cache.json> <ref.json>
import {readFileSync} from "node:fs";
const [htmlF, , refF] = process.argv.slice(2);
const html = readFileSync(htmlF, "utf8");
const ref = JSON.parse(readFileSync(refF, "utf8"));
function block(tag){
  const m = new RegExp("//<"+tag+">([\\s\\S]*?)//</"+tag+">").exec(html);
  if(!m) throw new Error("HTML 里找不到 //<"+tag+"> 代码块");
  return m[1];
}
const META = ref.meta;
const src = block("MATHS") + "\n" + block("FK") + "\n";
const api = new Function("META", src + "; return {fkSolve:fkSolve, MLINK:MLINK, ANG:ANG};")(META);
let worst = 0, worstWhere = "";
for(const c of ref.cases){
  for(let k=0;k<META.joints.length;k++) api.ANG[k] = c.ang[k];
  api.fkSolve();
  for(const lk of ref.links){
    const got = api.MLINK[lk.index], want = c.mat[lk.name];
    for(let i=0;i<16;i++){
      const d = Math.abs(got[i]-want[i]);
      if(d>worst){worst=d;worstWhere=c.pose+"/"+lk.name+"/["+i+"]";}
    }
  }
}
console.log("cases="+ref.cases.length+" links="+ref.links.length+
            " maxAbsErr="+worst.toExponential(3)+" mm @"+worstWhere);
if(!(worst < 1e-3)){ console.error("FAIL: JS FK 与 Python Kin 不一致"); process.exit(1); }
console.log("OK");
"""


def _fk_reference(cache: Dict[str, Any]) -> Dict[str, Any]:
    """Python 侧参考矩阵：MLINK = W_q(link) · W_0(link)⁻¹（**与 JS 同一公式**）。"""
    kin0 = A.Kin(DESIGN / "atri.urdf")
    link_names = [l["name"] for l in cache["links"]]

    def mats(pose: Dict[str, float]) -> Dict[str, List[float]]:
        kin = A.Kin(DESIGN / "atri.urdf", pose_deg=pose)
        return {ln: cm(A.mat_mul(kin.world[ln], mat_inv_rigid(kin0.world[ln])))
                for ln in link_names}

    cases = []
    for pname, pose in clamped_presets():
        cases.append({"pose": pname,
                      "ang": [float(pose.get(j["name"], 0.0)) for j in cache["joints"]],
                      "mat": mats(pose)})
    mixed = {j["name"]: math.degrees(j["lo"] + 0.37 * (j["hi"] - j["lo"]))
             for j in cache["joints"]}
    cases.append({"pose": "mixed37",
                  "ang": [mixed[j["name"]] for j in cache["joints"]],
                  "mat": mats(mixed)})
    return {"meta": {"links": cache["links"], "root": cache["root"],
                     "joints": cache["joints"], "fkOrder": cache["fkOrder"]},
            "linkNames": link_names,
            "links": [{"name": n, "index": i} for i, n in enumerate(link_names)],
            "cases": cases}


def run_check(html_path: Path, cache: Dict[str, Any]) -> int:
    """可复现自检：外部依赖 / UI 元素 / 体积 / 配合件 / JS-Python FK 对拍。"""
    fails: List[str] = []
    html = html_path.read_text(encoding="utf-8")
    size_mb = html_path.stat().st_size / 1e6
    ok = size_mb <= 40
    print(f"[1] HTML 体积 {size_mb:.2f} MB（上限 40 MB）→ {'PASS' if ok else 'FAIL'}")
    if not ok:
        fails.append("HTML 体积超 40 MB")

    n_url = len(re.findall(r"https?://", html))
    print(f"[2] 外部 URL 引用（http:// / https://）= {n_url} → "
          f"{'PASS' if n_url == 0 else 'FAIL'}")
    if n_url:
        fails.append(f"外部 URL {n_url} 处")

    need = ['id="sliders"', 'id="presets"', 'id="mateChk"', 'id="kinds"',
            "//<FK>", "//</FK>", "uniform3f", "drawElements", "ANG[k]*Math.PI/180"]
    miss = [s for s in need if s not in html]
    print(f"[3] 关键 UI/引擎片段 {len(need) - len(miss)}/{len(need)} → "
          f"{'PASS' if not miss else 'FAIL ' + str(miss)}")
    if miss:
        fails.append(f"缺少片段 {miss}")

    npreset = len(POSE_PRESETS)
    nj = len(cache["joints"])
    ok = npreset >= 4 and nj == 22
    print(f"[4] 预设 {npreset} 个（要求 ≥4）· 关节滑条 {nj} 条（要求 22）→ "
          f"{'PASS' if ok else 'FAIL'}")
    if not ok:
        fails.append("预设 <4 或滑条 ≠22")

    nmate = len([p for p in cache["parts"] if p["mate"]])
    ms = cache["stats"]["mates"]
    print(f"[5] 配合件半透明：is_joint_mate 命中 {ms['is_joint_mate']} 对"
          f" + outrigger 补充 {ms['outrigger_补充']} 对 → 着色 {nmate} 件 → "
          f"{'PASS' if nmate > 0 else 'FAIL'}")
    if nmate == 0:
        fails.append("没有任何配合件被标成半透明")

    node = None
    for cand in ("node", "/usr/local/bin/node"):
        try:
            subprocess.run([cand, "--version"], capture_output=True, timeout=20,
                           check=True)
            node = cand
            break
        except Exception:  # noqa: BLE001
            continue
    if node is None:
        print("[6] FK 对拍：跳过（找不到 node）")
        fails.append("FK 对拍未跑成（无 node）")
    else:
        ref = _fk_reference(cache)
        (PREVIEW / "_fk_ref.json").write_text(json.dumps(ref, ensure_ascii=False),
                                              encoding="utf-8")
        harness = PREVIEW / "verify_fk.mjs"
        harness.write_text(_FK_HARNESS, encoding="utf-8")
        try:
            r = subprocess.run([node, str(harness), str(html_path),
                                str(CACHE_FILE), str(PREVIEW / "_fk_ref.json")],
                               capture_output=True, text=True, timeout=120)
            print(f"[6] FK 对拍（node，{len(ref['cases'])} 个姿态 × "
                  f"{len(ref['links'])} 个 link）→ 退出码 {r.returncode}")
            for line in (r.stdout or "").strip().splitlines():
                print(f"      {line}")
            if r.returncode != 0:
                print("      " + (r.stderr or "").strip()[:400])
                fails.append("JS FK 与 Python Kin 不一致")
        except Exception as exc:  # noqa: BLE001
            print(f"[6] FK 对拍异常：{type(exc).__name__}: {exc}")
            fails.append("FK 对拍未跑成")

    print("=" * 60)
    if fails:
        print("自检 FAIL：" + "；".join(fails))
        return 1
    print("自检全部 PASS")
    return 0


# --------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    global POSE_PRESETS
    ap = argparse.ArgumentParser(description="生成交互式 3D 预览")
    ap.add_argument("--all", action="store_true", help="整机（默认动作）")
    ap.add_argument("--zero", action="store_true",
                    help="打开时停在机械零位（默认停在展示姿态）")
    ap.add_argument("--part", type=str, default=None, help="只看单个零件")
    ap.add_argument("--tol", type=float, default=1.2, help="网格容差 mm")
    ap.add_argument("--rebuild", action="store_true", help="强制重建几何缓存")
    ap.add_argument("--stale-ok", action="store_true",
                    help="不校验指纹、直接用现有缓存（只改 HTML/JS 时躲开重 CAD 用）")
    ap.add_argument("--no-glb", action="store_true", help="重建时不导出 GLB")
    ap.add_argument("--check", action="store_true",
                    help="只对已有 HTML 做自检（外部依赖/UI/配合件/FK 对拍）")
    args = ap.parse_args(argv)

    PREVIEW.mkdir(parents=True, exist_ok=True)

    if args.check:
        if not HTML_FILE.exists() or not CACHE_FILE.exists():
            print(f"缺 {HTML_FILE.name} 或 {CACHE_FILE.name}，先跑 --all")
            return 1
        print(f"自检 {HTML_FILE}")
        return run_check(HTML_FILE, json.loads(CACHE_FILE.read_text(encoding="utf-8")))

    POSE_PRESETS = clamped_presets()

    if args.part:
        items = [(args.part, sk.build(args.part))]
        name, verts, tris = R.tessellate(items, tol=args.tol)[0]
        pk = pack_geometry(name, verts, tris)
        kind = R.kind_of(name)
        bbl = verts.min(axis=0).tolist() + verts.max(axis=0).tolist()
        cache = {
            "schema": 2, "geomVersion": GEOM_VERSION, "tol": args.tol,
            "builtAt": time.strftime("%Y-%m-%d %H:%M:%S"), "srcMd5": {},
            "bbox": [round(v, 2) for v in bbl],
            "links": [{"name": "part", "zero": cm(A.mat_identity()),
                       "inv0": cm(A.mat_identity())}],
            "root": 0, "joints": [], "fkOrder": [],
            "parts": [{"name": name, "link": "", "kind": kind, "mate": "",
                       "vOff": 0, "vCount": pk["nV"], "iOff": 0,
                       "iCount": int(len(pk["idx"])), "indexed": True,
                       "aabb": [round(v, 2) for v in bbl],
                       "degMax": round(pk["maxDevDeg"], 2), "degMean": 0.0}],
            "kinds": [{"kind": kind, "label": KIND_LABEL[kind],
                       "color": list(KIND_COLORS[kind]),
                       "tris": int(len(pk["idx"]) // 3), "parts": 1}],
            "vertexCount": pk["nV"], "floatCount": pk["nV"] * 6,
            "indexCount": int(len(pk["idx"])),
            "vertsB64": base64.b64encode(pk["v"].tobytes()).decode("ascii"),
            "idxB64": base64.b64encode(pk["idx"].tobytes()).decode("ascii"),
            "stats": {"triangles": int(len(pk["idx"]) // 3), "vertices": pk["nV"],
                      "indexCount": int(len(pk["idx"])), "indexedParts": 1,
                      "parts": 1, "maxDevDeg": round(pk["maxDevDeg"], 2),
                      "mates": {"is_joint_mate": 0, "outrigger_补充": 0},
                      "blobBytes": pk["v"].nbytes + pk["idx"].nbytes},
        }
        info = write_html(cache, HTML_FILE, f"ATRI · {name}", "单件预览", 0)
        print(f"已生成 {HTML_FILE}")
        print(f"  {info['triangles']:,} 三角面 · HTML {info['html_bytes']/1e6:.2f} MB")
        return 0

    t0 = time.time()
    print(f"整机预览（几何缓存 {CACHE_FILE.name}）…")
    cache, _rebuilt = load_cache(args.tol, args.rebuild, want_glb=not args.no_glb,
                                 stale_ok=args.stale_ok)

    bb = cache["bbox"]
    n_parts = len([p for p in cache["parts"] if p["kind"] != "ground"])
    title = "A.T.R.I. 骨架装配预览"
    subtitle = (f"{n_parts} 个零件 · {len(cache['joints'])} DOF · 零位包络 "
                f"{bb[3]-bb[0]:.0f}×{bb[4]-bb[1]:.0f}×{bb[5]-bb[2]:.0f} mm"
                f" · {cache['stats']['triangles']:,} 三角面 · 可拖关节")
    info = write_html(cache, HTML_FILE, title, subtitle, 0 if args.zero else 1)
    print(f"已生成 {HTML_FILE}")
    print(f"  {info['triangles']:,} 三角面 · 几何 {cache['stats']['blobBytes']/1e6:.2f} MB"
          f" · HTML {info['html_bytes']/1e6:.2f} MB（自包含，双击即可用）")
    print(f"总用时 {time.time() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
