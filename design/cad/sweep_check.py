#!/usr/bin/env python3
"""极限姿态扫掠自碰撞校核。

读取 design/atri.urdf 的关节限位，对整机各 link 的碰撞体在大量姿态组合下进行两两干涉检查。
核心判定复用 design/cad/fitcheck.py 的原语（boxes_overlap / common_volume / verdict）。

与 audit_assembly.py 的区别：
- audit 检查零位装配的"摆放错误"与"让位不足"；
- 本脚本检查随关节运动而变化的**姿态诱发碰撞**，用零位体积做基线扣除。

用法：
    .venv-cad/bin/python design/cad/sweep_check.py --quick   # 快速档
    .venv-cad/bin/python design/cad/sweep_check.py --full    # 完整档
    .venv-cad/bin/python design/cad/sweep_check.py --help
"""
from __future__ import annotations

import argparse
import math
import signal
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import cadquery as cq

import assembly as A
from fitcheck import boxes_overlap, common_volume, verdict

DESIGN = REPO / "design"
URDF = DESIGN / "atri.urdf"
REPORT = HERE / "out" / "sweep_report.md"

# --------------------------------------------------------------------------
# 全局超时（快速失败）
# --------------------------------------------------------------------------
TIMEOUT_QUICK = 900   # 15 min
TIMEOUT_FULL = 1800   # 30 min


def set_global_timeout(seconds: int) -> None:
    def _handler(signum, frame):
        raise TimeoutError(f"脚本运行超过 {seconds} 秒，主动终止")
    signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)


# --------------------------------------------------------------------------
# 矩阵工具（与 assembly.py 同源，避免引入 numpy 做 4×4）
# --------------------------------------------------------------------------
Mat = List[List[float]]


def mat_identity() -> Mat:
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def mat_mul(a: Mat, b: Mat) -> Mat:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)]
            for i in range(4)]


def mat_trans(x: float, y: float, z: float) -> Mat:
    m = mat_identity()
    m[0][3], m[1][3], m[2][3] = x, y, z
    return m


def mat_rpy(r: float, p: float, yw: float) -> Mat:
    """URDF 固定轴 XYZ 外旋（R = Rz·Ry·Rx）。"""
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(yw), math.sin(yw)
    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, 0.0],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, 0.0],
        [-sp, cp * sr, cp * cr, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def mat_axis_angle(axis: Sequence[float], theta: float) -> Mat:
    """绕任意单位轴的旋转矩阵（Rodrigues）。"""
    x, y, z = axis
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    x, y, z = x / n, y / n, z / n
    c, s = math.cos(theta), math.sin(theta)
    C = 1.0 - c
    return [
        [x * x * C + c, x * y * C - z * s, x * z * C + y * s, 0.0],
        [y * x * C + z * s, y * y * C + c, y * z * C - x * s, 0.0],
        [z * x * C - y * s, z * y * C + x * s, z * z * C + c, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def mat_inv(m: Mat) -> Mat:
    """刚性变换的逆（R^T | -R^T t）。"""
    r = [row[:3] for row in m[:3]]
    t = [m[0][3], m[1][3], m[2][3]]
    rt = [[r[j][i] for j in range(3)] for i in range(3)]
    nt = [-sum(rt[i][j] * t[j] for j in range(3)) for i in range(3)]
    return [
        [rt[0][0], rt[0][1], rt[0][2], nt[0]],
        [rt[1][0], rt[1][1], rt[1][2], nt[1]],
        [rt[2][0], rt[2][1], rt[2][2], nt[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def apply_mat(m: Mat, v: Sequence[float]) -> Tuple[float, float, float]:
    x, y, z = v
    return (m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
            m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
            m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3])


# --------------------------------------------------------------------------
# 带关节角的正运动学
# --------------------------------------------------------------------------
class PoseKin:
    """与 assembly.Kin 接口兼容，但支持任意关节角。"""

    def __init__(self, urdf: Path, pose: Optional[Dict[str, float]] = None):
        self.pose: Dict[str, float] = dict(pose or {})
        root = ET.parse(urdf).getroot()
        self.joints: Dict[str, Dict[str, Any]] = {}
        self.parent_of: Dict[str, str] = {}
        self.children: Dict[str, List[str]] = {}
        links = [l.get("name") for l in root.findall("link")]
        for l in links:
            self.children[l] = []
        for j in root.findall("joint"):
            name = j.get("name")
            parent = j.find("parent").get("link")
            child = j.find("child").get("link")
            o = j.find("origin")
            xyz = [float(v) * 1000.0
                   for v in (o.get("xyz") or "0 0 0").split()]
            rpy = [float(v) for v in (o.get("rpy") or "0 0 0").split()]
            ax = j.find("axis")
            axis = [float(v) for v in (ax.get("xyz") if ax is not None
                                       else "0 0 1").split()]
            lim = j.find("limit")
            lower = float(lim.get("lower")) if lim is not None else -math.pi
            upper = float(lim.get("upper")) if lim is not None else math.pi
            self.joints[name] = {"parent": parent, "child": child,
                                 "xyz": xyz, "rpy": rpy, "axis": axis,
                                 "lower": lower, "upper": upper}
            self.parent_of[child] = name
            self.children[parent].append(child)
        self.root = [l for l in links if l not in self.parent_of][0]
        self.world: Dict[str, Mat] = {}
        self._fk(self.root, mat_identity())

    def _fk(self, link: str, m: Mat) -> None:
        self.world[link] = m
        for child in self.children[link]:
            j = self.joints[self.parent_of[child]]
            theta = self.pose.get(self.parent_of[child], 0.0)
            child_m = mat_mul(
                m,
                mat_mul(
                    mat_trans(*j["xyz"]),
                    mat_mul(mat_rpy(*j["rpy"]),
                            mat_axis_angle(j["axis"], theta))
                )
            )
            self._fk(child, child_m)

    def limits(self, joint: str) -> Tuple[float, float]:
        return self.joints[joint]["lower"], self.joints[joint]["upper"]


# --------------------------------------------------------------------------
# 从 URDF 构建各 link 的碰撞体
# --------------------------------------------------------------------------
def build_link_collision_shapes(urdf: Path) -> Dict[str, cq.Workplane]:
    """把每个 link 下所有 <collision> 几何体合并成一个零件（link 局部坐标）。"""
    root = ET.parse(urdf).getroot()
    shapes: Dict[str, cq.Workplane] = {}
    for link in root.findall("link"):
        name = link.get("name")
        parts: List[cq.Workplane] = []
        for col in link.findall("collision"):
            o = col.find("origin")
            xyz = [float(v) * 1000.0
                   for v in (o.get("xyz") or "0 0 0").split()]
            rpy = [float(v) for v in (o.get("rpy") or "0 0 0").split()]
            geom = col.find("geometry")
            box = geom.find("box")
            if box is not None:
                sx, sy, sz = [float(v) * 1000.0 for v in box.get("size").split()]
                part = cq.Workplane("XY").box(sx, sy, sz)
                # cq.box 默认中心在原点，需按 URDF origin 平移/旋转
                part = part.translate((xyz[0], xyz[1], xyz[2]))
                if any(v != 0.0 for v in rpy):
                    part = part.rotate((0, 0, 0),
                                       (1, 0, 0), math.degrees(rpy[0]))
                    part = part.rotate((0, 0, 0),
                                       (0, 1, 0), math.degrees(rpy[1]))
                    part = part.rotate((0, 0, 0),
                                       (0, 0, 1), math.degrees(rpy[2]))
                parts.append(part)
        if parts:
            comp = cq.Compound.makeCompound([p.val() for p in parts])
            shapes[name] = cq.Workplane("XY").newObject([comp])
        else:
            shapes[name] = cq.Workplane("XY")
    return shapes


def place_shape(shape: cq.Workplane, m: Mat) -> cq.Workplane:
    """用 4×4 齐次矩阵放置形状（复用 assembly._place）。"""
    return A._place(shape, m)


def bbox_of(shape: cq.Workplane) -> Any:
    return shape.val().BoundingBox()


def transform_bbox(bbox: Any, m: Mat) -> Any:
    """用 m 变换轴对齐包围盒，返回新的轴对齐包围盒。"""
    corners = [
        (bbox.xmin, bbox.ymin, bbox.zmin),
        (bbox.xmin, bbox.ymin, bbox.zmax),
        (bbox.xmin, bbox.ymax, bbox.zmin),
        (bbox.xmin, bbox.ymax, bbox.zmax),
        (bbox.xmax, bbox.ymin, bbox.zmin),
        (bbox.xmax, bbox.ymin, bbox.zmax),
        (bbox.xmax, bbox.ymax, bbox.zmin),
        (bbox.xmax, bbox.ymax, bbox.zmax),
    ]
    pts = [apply_mat(m, c) for c in corners]
    xs, ys, zs = zip(*pts)
    return SimpleNamespace(
        xmin=min(xs), xmax=max(xs), xlen=max(xs) - min(xs),
        ymin=min(ys), ymax=max(ys), ylen=max(ys) - min(ys),
        zmin=min(zs), zmax=max(zs), zlen=max(zs) - min(zs),
    )


# --------------------------------------------------------------------------
# 白名单
# --------------------------------------------------------------------------
WHITELIST_REASONS = {
    "same_link": "同一 URDF link 内的多个 collision 几何体已被合并为单个刚体零件，"
                 "不存在自身碰撞问题。",
    "adjacent_link": "URDF 中直接相连的 link 在关节处属于同一运动链的连续环节，"
                     "其碰撞体在关节轴承/叉架处允许接触；本脚本直接白名单，"
                     "聚焦非相邻 link 之间的意外自碰撞。",
    "foot_ground": "足底与地面的接触在运动允许范围内（本模型未建地面，保留规则）。",
    "limit_surface": "机械限位面为设计硬止点，允许贴合甚至微压（本模型未单独建限位面）。",
}


def adjacent_links(kin: PoseKin) -> Set[Tuple[str, str]]:
    """返回 URDF 中直接相邻的 link 对（parent-child）。"""
    out = set()
    for j, info in kin.joints.items():
        pair = tuple(sorted((info["parent"], info["child"])))
        out.add(pair)
    return out


# --------------------------------------------------------------------------
# 姿态采样
# --------------------------------------------------------------------------
def nominal_pose(joints: Sequence[str]) -> Dict[str, float]:
    return {j: 0.0 for j in joints}


def grid_samples(joints: Sequence[str], kin: PoseKin,
                 levels: Sequence[float]) -> List[Dict[str, float]]:
    """单关节扫掠：每次只动一个关节，其余保持在名义零位。"""
    out = []
    for j in joints:
        lo, hi = kin.limits(j)
        for alpha in levels:
            q = (1 - alpha) * lo + alpha * hi
            pose = nominal_pose(joints)
            pose[j] = q
            out.append(pose)
    return out


def lhs_samples(joints: Sequence[str], kin: PoseKin, n: int,
                seed: int = 42) -> List[Dict[str, float]]:
    """拉丁超立方采样：在完整关节空间内均匀分层。"""
    rng = np.random.default_rng(seed)
    d = len(joints)
    perms = [rng.permutation(n) for _ in range(d)]
    poses = []
    for i in range(n):
        pose = {}
        for k, j in enumerate(joints):
            lo, hi = kin.limits(j)
            u = (perms[k][i] + rng.random()) / n
            pose[j] = lo + u * (hi - lo)
        poses.append(pose)
    return poses


# --------------------------------------------------------------------------
# 单姿态碰撞检查
# --------------------------------------------------------------------------
@dataclass
class CollisionEvent:
    a: str
    b: str
    vol: float
    frac: float
    pose: Dict[str, float]
    verdict: str


def check_pose(link_names: List[str], link_shapes: Dict[str, cq.Workplane],
               link_bboxes0: Dict[str, Any], link_vols: Dict[str, float],
               kin: PoseKin, baseline: Dict[Tuple[str, str], float],
               whitelist_cache: Dict[Tuple[str, str], Optional[str]],
               pose: Dict[str, float],
               progress: Optional[str] = None) -> List[CollisionEvent]:
    """对一个姿态做包围盒预筛 + 精确布尔干涉检查。"""
    if progress:
        print(progress, end="\r", file=sys.stderr)

    # 1. 先计算每个 link 在新姿态下的包围盒（只转 8 个角点）
    bboxes: Dict[str, Any] = {}
    for name in link_names:
        bboxes[name] = transform_bbox(link_bboxes0[name], kin.world[name])

    events: List[CollisionEvent] = []
    n = len(link_names)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = link_names[i], link_names[j]
            key = tuple(sorted((a, b)))
            if whitelist_cache.get(key):
                continue
            if not boxes_overlap(bboxes[a], bboxes[b]):
                continue
            # 2. 仅对包围盒相交的对做布尔
            try:
                sa = place_shape(link_shapes[a], kin.world[a])
                sb = place_shape(link_shapes[b], kin.world[b])
                v = common_volume(sa, sb)
            except Exception as exc:  # noqa: BLE001
                print(f"\n[WARN] 布尔失败 {a} ↔ {b}: {exc}", file=sys.stderr)
                continue
            base = baseline.get(key, 0.0)
            if v <= max(base, 1.0):
                continue
            smaller = max(min(link_vols[a], link_vols[b]), 1e-9)
            frac = v / smaller
            events.append(CollisionEvent(
                a=a, b=b, vol=v, frac=frac, pose=dict(pose),
                verdict=verdict(v, frac),
            ))
    return events


# --------------------------------------------------------------------------
# 基线（名义零位）碰撞体积
# --------------------------------------------------------------------------
def compute_baseline(link_names: List[str], link_shapes: Dict[str, cq.Workplane],
                     kin0: PoseKin) -> Tuple[Dict[Tuple[str, str], float],
                                              Dict[Tuple[str, str], Optional[str]]]:
    """在名义零位下记录所有非白名单 link 对的相交体积，作为基线。

    白名单：
    - 相邻 link（URDF 直接 parent-child）在关节处允许接触，不计入姿态诱发碰撞。
    """
    baseline: Dict[Tuple[str, str], float] = {}
    whitelist_cache: Dict[Tuple[str, str], Optional[str]] = {}
    adj = adjacent_links(kin0)

    for i in range(len(link_names)):
        for j in range(i + 1, len(link_names)):
            key = tuple(sorted((link_names[i], link_names[j])))
            if key in adj:
                whitelist_cache[key] = "adjacent_link"
            else:
                whitelist_cache[key] = None

    for i in range(len(link_names)):
        for j in range(i + 1, len(link_names)):
            a, b = link_names[i], link_names[j]
            key = tuple(sorted((a, b)))
            if whitelist_cache[key]:
                continue
            sa = link_shapes[a]
            sb = link_shapes[b]
            if not boxes_overlap(bbox_of(sa), bbox_of(sb)):
                continue
            try:
                v = common_volume(sa, sb)
            except Exception:  # noqa: BLE001
                v = 0.0
            if v > 1.0:
                baseline[key] = v
    return baseline, whitelist_cache


# --------------------------------------------------------------------------
# 汇总与建议
# --------------------------------------------------------------------------
def summarize(events: List[CollisionEvent], kin: PoseKin) -> Dict[str, Any]:
    by_pair: Dict[Tuple[str, str], List[CollisionEvent]] = defaultdict(list)
    for ev in events:
        by_pair[tuple(sorted((ev.a, ev.b)))].append(ev)

    records = []
    for pair, evs in by_pair.items():
        worst = max(evs, key=lambda e: e.vol - 1.0)
        records.append({
            "pair": pair,
            "max_vol": max(e.vol for e in evs),
            "max_excess": max(e.vol - 1.0 for e in evs),
            "worst": worst,
            "count": len(evs),
        })
    records.sort(key=lambda r: -r["max_excess"])

    # 统计哪些关节在事故姿态中处于极限附近
    joint_counts: Dict[str, int] = defaultdict(int)
    for ev in events:
        for j, v in ev.pose.items():
            lo, hi = kin.limits(j)
            span = hi - lo
            if span <= 0:
                continue
            if abs(v - lo) < 0.10 * span or abs(v - hi) < 0.10 * span:
                joint_counts[j] += 1
    risky_joints = sorted(joint_counts.items(), key=lambda kv: -kv[1])

    return {"records": records, "risky_joints": risky_joints}


def format_pose(pose: Dict[str, float], kin: PoseKin) -> str:
    parts = []
    for j in sorted(pose):
        v = pose[j]
        lo, hi = kin.limits(j)
        span = hi - lo
        edge = ""
        if span > 0:
            if abs(v - lo) < 0.05 * span:
                edge = " (min)"
            elif abs(v - hi) < 0.05 * span:
                edge = " (max)"
        parts.append(f"{j}={math.degrees(v):.1f}°{edge}")
    return "<br>".join(parts)


# --------------------------------------------------------------------------
# 报告输出
# --------------------------------------------------------------------------
def write_report(summary: Dict[str, Any], link_names: List[str],
                 baseline: Dict[Tuple[str, str], float],
                 samples: List[Dict[str, float]], mode: str,
                 elapsed: float, report_path: Path) -> str:
    records = summary["records"]
    risky_joints = summary["risky_joints"]
    kin = PoseKin(URDF)

    lines = [
        "# 极限姿态扫掠自碰撞校核报告",
        "",
        f"- 运行模式：`{mode}`",
        f"- URDF link 数：{len(link_names)}",
        f"- 采样姿态数：{len(samples)}（含单关节扫掠 + LHS）",
        f"- 运行耗时：{elapsed:.1f} 秒",
        "",
        "## 方法",
        "",
        "1. 读取 `design/atri.urdf`，解析 22 个旋转关节的限位。",
        "2. 把每个 link 下所有 `<collision>` 几何体合并成该 link 的碰撞体（局部坐标）。",
        "3. 用带关节角的正运动学 `PoseKin` 计算各 link 的世界位姿。",
        "4. 先用轴对齐包围盒预筛选，仅对包围盒相交且不在白名单内的 link 对调用",
        "   `fitcheck.common_volume` 做精确布尔求交。",
        "5. 用名义零位的相交体积作为基线，只报告**姿态诱发增量**（> 1 mm³）的事件。",
        "",
        "### 白名单规则",
        "",
    ]
    for key, reason in WHITELIST_REASONS.items():
        lines.append(f"- `{key}`：{reason}")
    lines.append("")

    lines.append("## 基线（名义零位）统计")
    lines.append("")
    lines.append(f"- link 对总数：{len(link_names) * (len(link_names) - 1) // 2}")
    lines.append(f"- 基线相交体积 > 1 mm³ 的对数：{len(baseline)}")
    if baseline:
        total = sum(baseline.values())
        lines.append(f"- 基线总体积：{total:.0f} mm³")
    lines.append("")

    lines.append("## 姿态诱发的高危碰撞")
    lines.append("")
    if not records:
        lines.append("未发现显著的姿态诱发碰撞（增量 ≤ 1 mm³）。")
    else:
        lines.append("| 排名 | 件 A | 件 B | 事件数 | 最大侵入 mm³ | 姿态诱发增量 | 判定 |")
        lines.append("|---|---|---|---|---|---|---|")
        for k, r in enumerate(records[:25], 1):
            a, b = r["pair"]
            lines.append(
                f"| {k} | `{a}` | `{b}` | {r['count']} | "
                f"{r['max_vol']:.0f} | {r['max_excess']:.0f} | "
                f"{r['worst'].verdict} |"
            )
        lines.append("")
        lines.append("### 触发姿态与最大侵入事件详情")
        lines.append("")
        for k, r in enumerate(records[:15], 1):
            a, b = r["pair"]
            ev = r["worst"]
            lines.append(f"#### {k}. `{a}` ↔ `{b}`")
            lines.append("")
            lines.append(f"- 最大侵入体积：**{r['max_vol']:.0f} mm³**")
            lines.append(f"- 姿态诱发增量：**{r['max_excess']:.0f} mm³**")
            lines.append(f"- 重合率（相对较小件）：**{ev.frac * 100:.1f}%**")
            lines.append(f"- 判定：{ev.verdict}")
            lines.append("- 触发姿态（各关节角度）：")
            lines.append("")
            lines.append(format_pose(ev.pose, kin))
            lines.append("")

    lines.append("## 关节行程建议")
    lines.append("")
    if risky_joints:
        lines.append("以下关节在碰撞姿态中频繁处于极限附近，建议优先限制其行程或增加速度/力矩保护：")
        lines.append("")
        lines.append("| 关节 | 触发次数 | 当前 URDF 限位 | 建议 |")
        lines.append("|---|---|---|---|")
        for j, c in risky_joints[:20]:
            lo, hi = kin.limits(j)
            lines.append(
                f"| `{j}` | {c} | "
                f"{math.degrees(lo):.1f}° ~ {math.degrees(hi):.1f}° | "
                f"缩限至 80% 以内或增加该关节附近碰撞监测 |"
            )
        lines.append("")
        combo: Dict[Tuple[str, str], int] = defaultdict(int)
        for ev in [r["worst"] for r in records[:15]]:
            near = []
            for j, v in ev.pose.items():
                lo, hi = kin.limits(j)
                span = hi - lo
                if span > 0 and (abs(v - lo) < 0.10 * span or abs(v - hi) < 0.10 * span):
                    near.append(j)
            for i in range(len(near)):
                for j2 in range(i + 1, len(near)):
                    combo[tuple(sorted((near[i], near[j2])))]+=1
        if combo:
            lines.append("### 需同时关注的关节组合")
            lines.append("")
            lines.append("| 关节 A | 关节 B | 同发次数 |")
            lines.append("|---|---|---|")
            for (ja, jb), c in sorted(combo.items(), key=lambda kv: -kv[1])[:15]:
                lines.append(f"| `{ja}` | `{jb}` | {c} |")
            lines.append("")
    else:
        lines.append("未发现需要缩限的关节组合。")
    lines.append("")

    lines.append("## 采样说明")
    lines.append("")
    lines.append(f"- 单关节扫掠档位数：{'5' if mode == 'full' else '3'}（含两端极限）")
    lines.append(f"- 拉丁超立方组合数：{'200' if mode == 'full' else '50'}")
    lines.append("- 随机种子：42（可复现）")
    lines.append("")

    text = "\n".join(lines)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text, encoding="utf-8")
    return text


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="A.T.R.I. 极限姿态扫掠自碰撞校核")
    ap.add_argument("--quick", action="store_true", help="快速档：3 档单关节 + 50 组 LHS")
    ap.add_argument("--full", action="store_true", help="完整档：5 档单关节 + 200 组 LHS")
    ap.add_argument("--seed", type=int, default=42, help="LHS 随机种子")
    ap.add_argument("--report", type=Path, default=REPORT, help="报告输出路径")
    args = ap.parse_args(argv)

    mode = "full" if args.full else "quick"
    set_global_timeout(TIMEOUT_FULL if mode == "full" else TIMEOUT_QUICK)

    import time
    t0 = time.time()

    print(f"[{mode}] 加载 URDF 与构建 link 碰撞体...", flush=True)
    kin0 = PoseKin(URDF)
    joints = list(kin0.joints.keys())
    link_shapes = build_link_collision_shapes(URDF)
    link_names = sorted(link_shapes.keys())
    link_bboxes0 = {n: bbox_of(s) for n, s in link_shapes.items()}
    link_vols = {n: s.val().Volume() for n, s in link_shapes.items()}
    print(f"  link 碰撞体 {len(link_names)} 个，关节 {len(joints)} 个", flush=True)

    print("  计算名义零位基线...", flush=True)
    baseline, whitelist_cache = compute_baseline(link_names, link_shapes, kin0)
    print(f"  基线相交对 {len(baseline)} 个", flush=True)

    if mode == "full":
        levels = [0.0, 0.25, 0.5, 0.75, 1.0]
        lhs_n = 200
    else:
        levels = [0.0, 0.5, 1.0]
        lhs_n = 50

    grid = grid_samples(joints, kin0, levels)
    lhs = lhs_samples(joints, kin0, lhs_n, seed=args.seed)
    samples = grid + lhs
    print(f"  生成姿态 {len(samples)} 个（单关节 {len(grid)} + LHS {len(lhs)}）", flush=True)

    print("  开始扫掠...", flush=True)
    all_events: List[CollisionEvent] = []
    for idx, pose in enumerate(samples, 1):
        kin = PoseKin(URDF, pose)
        evs = check_pose(
            link_names, link_shapes, link_bboxes0, link_vols,
            kin, baseline, whitelist_cache, pose,
            progress=f"    姿态 {idx}/{len(samples)}，已发现 {len(all_events)} 个事件"
        )
        all_events.extend(evs)
    print(f"\n  扫掠完成，共 {len(all_events)} 个姿态诱发碰撞事件", flush=True)

    summary = summarize(all_events, kin0)
    elapsed = time.time() - t0

    report_text = write_report(summary, link_names, baseline, samples, mode,
                               elapsed, args.report)

    print(f"\n报告已写入 {args.report}", flush=True)
    print(f"耗时 {elapsed:.1f} 秒", flush=True)
    print(f"姿态诱发碰撞事件 {len(all_events)} 个", flush=True)
    print(f"涉及 link 对 {len(summary['records'])} 个", flush=True)
    if summary["risky_joints"]:
        print("高危关节（触发次数）：", flush=True)
        for j, c in summary["risky_joints"][:10]:
            print(f"  {j}: {c}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
