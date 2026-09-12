#!/usr/bin/env python3
"""极限姿态扫掠自碰撞校核（姿态诱发碰撞 + 逐关节限位建议）。

回答的问题
----------
零位装配"摆放错误 0 对"只说明**静态零位**没有指派错误；它不回答"动起来之后
哪些姿态会撞"。本脚本在关节空间里扫掠，输出**扣除零位基线后的新增干涉体积**，
并据此给出逐关节的保守限位建议。

与其他脚本的分工
----------------
- `assembly.py`     零位装配（权威几何与位姿）
- `audit_assembly.py` 零位体检（轴对齐 / 连通性 / 摆放错误）
- `interference.py` 零位干涉普查（按零件两两布尔求交）
- **本脚本**        关节空间扫掠：同一套零件、同一套判定原语，但姿态可变

口径（与仓库既有产物一致，不得各写一套）
----------------------------------------
1. **几何来源 = 真实零件**：`assembly.build_assembly(Kin(零位), placements)`（只读内存、
   不写盘）。**不用 URDF 的 `<collision>`**——那是实心包络代理块，不是零件：
   实测其两两相交基线为 163 对 / 6 910 468 mm³，是真实基线的 43 倍，且会产出
   `left_foot ↔ head` 88 200 mm³ 这种纯属块状包络假象的"干涉"。
   真实零件两两相交基线实测 **189 对 / 160 339 mm³**，与仓库权威口径逐位一致。
2. **运动学 = `assembly.Kin`**：直接调用权威正解，不另写一套（v1 曾因"预览一套、
   装配一套"导致每个关节差 90°）。
3. **零件 → link 归属 = `preview.py` 第 209–227 行的 `part_link()` 口径**：
   `servo__J`/`cage__J`/`outrigger__J` → 父 link；**`fork__J` → 子 link（叉锁在舵盘上，
   跟着子级转）**；`elec__<id>` → `placements.json` 登记的 host link；
   `{link}__{part}` → 名称前缀。
   ⚠️ `assembly.build_assembly()` 把 `fork__J` 放在 `kin.joint_world(J)`（= 父 link 的
   关节系），**只在零位与"子 link"等价**。零位体检全部在此口径下完成，故无影响；
   但姿态扫掠必须按子 link 归属，否则弯关节时"叉不跟着小腿转"，扫掠结果全错。
   本脚本按子 link 归属，并在 `--selftest` 里与 `preview.part_link()` 逐件比对。
4. **基线扣除**：只在**零位实测相交体积**之上比较。`excess = v(姿态) − v(零位)`，
   按 `excess` 排序。**绝不按绝对体积排序**——否则零位本就存在的 189 对会永远霸榜。
5. **配合面标注**：用 `fitcheck.is_joint_mate(a, b)`（逐字调用，未改该文件）判定
   "同关节锁盘/夹持配合"；另加一列 `same_joint`（同关节号且双方都是关节件），
   因为 `is_joint_mate()` 的集合只有 {servo,cage} / {servo,fork} / {servo,gripper_jaw}，
   **不含 {servo,outrigger} 与 {cage,fork} / {outrigger,fork}**，而运动学上
   {cage|outrigger} 在父、fork 在子，是真正会相对运动的同关节界面。
6. **同 link 的零件对永不检查**：它们刚性同步，相对位姿恒定，不可能"姿态诱发"。
   这不是近似，是恒等式（所以排除它们不影响完备性）。

用法
----
    .venv-cad/bin/python design/cad/sweep_check.py --quick
    .venv-cad/bin/python design/cad/sweep_check.py --full
    .venv-cad/bin/python design/cad/sweep_check.py --quick --lhs 20 --no-figure
    .venv-cad/bin/python design/cad/sweep_check.py --quick --out design/cad/out

产出（默认写到 `design/cad/out/`，gitignored 产物区）
    sweep_report.md    全量报告
    sweep_report.json  机器可读（基线 / 事件 / 限位建议 / 覆盖度 / 溯源指纹）
    sweep_figure.png   答辩用图（零位 vs 危险姿态 + 限位建议 + Top10）

超时
----
`--budget`（秒）是**软预算**：到点即停止采样、按已完成部分出报告，并在报告里
显式写明"未跑完"。SIGALRM 是硬后备（预算 + 180 s），触发也会尽力落盘。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import signal
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import cadquery as cq

import assembly as A
from fitcheck import bbox_of, boxes_overlap, common_volume, is_joint_mate, joint_kind, verdict

DESIGN = REPO / "design"
URDF = DESIGN / "atri.urdf"
PLACEMENTS_JSON = DESIGN / "placements.json"
OUT = HERE / "out"

# 判定阈值（mm³）。1 mm³ = 1 mm × 1 mm × 1 mm 的实体互穿，
# 远小于打印件 0.2–0.5 mm 的公差，故"新增 ≥ 1 mm³"即视为真实新增干涉。
EXCESS_MIN = 1.0     # 报告门限
EXCESS_CLEAR = 10.0  # 限位建议里另给一档"宽松口径"

DEFAULT_TIMEOUT_QUICK = 5400    # 软预算（秒）——实测本机 4 线程可用核下的合理值
DEFAULT_TIMEOUT_FULL = 16200
HARD_BACKSTOP_EXTRA = 180


class BudgetExceeded(Exception):
    """软预算到点（用于优雅收尾，不丢已算出的结果）。"""


_ALARM_S = 0
_ALARM_TIMER = None  # Windows 看门狗（守护线程）；POSIX 下恒为 None


def _install_alarm(seconds: int) -> None:
    """装硬超时后备（预算 + `HARD_BACKSTOP_EXTRA`）。

    POSIX：SIGALRM 在主线程抛 `BudgetExceeded`，会被主流程的 `except` 接住 ⇒ 尽力落盘。
    Windows：没有 `SIGALRM` / `signal.alarm`。退化为守护线程看门狗——线程无法向主线程抛异常，
    只能直接终止进程（`os._exit(3)`，与 POSIX 侧硬超时的退出码一致）。
    语义差别如实写明：这一路**到点必停、但不落盘**；软预算 `--budget` 那条路在 Windows 上
    照常优雅收尾并落盘，所以 Windows 上应以 `--budget` 作为主要停止手段。
    """
    global _ALARM_S, _ALARM_TIMER
    _ALARM_S = int(seconds)

    if hasattr(signal, "SIGALRM"):
        def _handler(signum, frame):  # noqa: ANN001
            raise BudgetExceeded(f"硬超时 {_ALARM_S} 秒到点，主动终止")

        signal.signal(signal.SIGALRM, _handler)
        signal.alarm(max(1, int(seconds)))
        return

    import os
    import threading

    def _watchdog() -> None:
        print(f"\n[FATAL] 硬超时 {_ALARM_S} 秒到点，主动终止"
              "（Windows 看门狗：此路不落盘，请用 --budget 软预算收尾）",
              file=sys.stderr, flush=True)
        os._exit(3)

    _ALARM_TIMER = threading.Timer(max(1, int(seconds)), _watchdog)
    _ALARM_TIMER.daemon = True
    _ALARM_TIMER.start()


def _clear_alarm() -> None:
    global _ALARM_TIMER
    if hasattr(signal, "SIGALRM"):
        signal.alarm(0)
        return
    if _ALARM_TIMER is not None:
        _ALARM_TIMER.cancel()
        _ALARM_TIMER = None


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def md5_of(path: Path) -> str:
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except OSError:
        return "?"


Mat = List[List[float]]


def mat_inv(m: Mat) -> Mat:
    """刚性变换的逆 R⁻¹=Rᵀ, t⁻¹=−Rᵀt（与 preview.mat_inv_rigid 同式）。"""
    rt = [[m[c][r] for c in range(3)] for r in range(3)]
    t = [m[r][3] for r in range(3)]
    ti = [-sum(rt[r][k] * t[k] for k in range(3)) for r in range(3)]
    return [rt[r] + [ti[r]] for r in range(3)] + [[0.0, 0.0, 0.0, 1.0]]


def np_mat(m: Mat) -> np.ndarray:
    return np.asarray(m, dtype=float)


def read_limits(urdf: Path) -> Dict[str, Tuple[float, float]]:
    """URDF 关节限位（弧度）。缺 limit 的关节按 ±π 处理并记录在案。"""
    root = ET.parse(urdf).getroot()
    out: Dict[str, Tuple[float, float]] = {}
    for j in root.findall("joint"):
        if j.get("type") not in ("revolute", "continuous", "prismatic"):
            continue
        name = j.get("name")
        lim = j.find("limit")
        if lim is None or lim.get("lower") is None:
            out[name] = (-math.pi, math.pi)
            continue
        out[name] = (float(lim.get("lower")), float(lim.get("upper")))
    return out


def deg(x: float) -> float:
    return math.degrees(x)


def fmt_deg(x: float) -> str:
    return f"{deg(x):+.1f}°"


# --------------------------------------------------------------------------
# 带关节角的运动学（薄封装：正解仍走 assembly.Kin，不另写一套）
# --------------------------------------------------------------------------
class PoseKin:
    """任意关节角下的整机正解，接口与旧的 sweep_check.PoseKin 兼容。

    pose 用**弧度**（URDF 原生单位）；内部转成度交给 `assembly.Kin`。
    """

    def __init__(self, urdf: Path, pose: Optional[Dict[str, float]] = None):
        self.pose: Dict[str, float] = dict(pose or {})
        pose_deg = {k: deg(v) for k, v in self.pose.items()}
        self._kin = A.Kin(urdf, pose_deg=pose_deg)
        self.world: Dict[str, Mat] = self._kin.world
        self.joints: Dict[str, Dict[str, Any]] = self._kin.joints
        self.parent_of: Dict[str, str] = self._kin.parent_of
        self.children: Dict[str, List[str]] = self._kin.children
        self.root: str = self._kin.root
        self.limits_map: Dict[str, Tuple[float, float]] = read_limits(urdf)
        for j, (lo, hi) in self.limits_map.items():
            if j in self.joints:
                self.joints[j]["lower"] = lo
                self.joints[j]["upper"] = hi

    def limits(self, joint: str) -> Tuple[float, float]:
        return self.limits_map[joint]

    def subtree(self, joint: str) -> Set[str]:
        """关节的孩子侧子树（含孩子 link 本身）。"""
        out: Set[str] = set()
        stack = [self.joints[joint]["child"]]
        while stack:
            lk = stack.pop()
            if lk in out:
                continue
            out.add(lk)
            stack.extend(self.children.get(lk, []))
        return out


# --------------------------------------------------------------------------
# 零件 → link（preview.py 第 209–227 行口径；此处独立实现以便自检比对）
# --------------------------------------------------------------------------
KIN_KINDS = ("servo", "cage", "fork", "outrigger", "gripper_jaw")


def part_link(name: str, kin: PoseKin, elec_link: Dict[str, str]) -> str:
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
    head, sep, _ = name.partition("__")
    if not sep:
        raise ValueError(f"零件名 {name!r} 不含 '__'，无法判定归属 link")
    return head


def part_kind(name: str) -> str:
    """零件种类（复用 fitcheck.joint_kind 的词典，另给结构件兜底）。"""
    _, k = joint_kind(name)
    if k:
        return k
    if name.startswith("elec__"):
        return "elec"
    head, sep, tail = name.partition("__")
    if sep:
        return tail or "bulk"
    return "bulk"


@dataclass
class Part:
    name: str
    link: str
    kind: str
    shape0: cq.Workplane          # 零位世界位姿下的实体（**全部实体**，见 wrap_all_solids）
    shape0_legacy: cq.Workplane   # 仓库既有口径：Workplane.val() 只看第一个实体
    bbox_local: Any               # 零位世界位姿下的 AABB（此后按 link 系平动）
    vol: float
    n_solids: int = 1

    @property
    def truncated(self) -> bool:
        """`val()` 口径是否丢了几何（多实体零件）。"""
        return self.n_solids > 1


def wrap_all_solids(wp: cq.Workplane) -> Tuple[cq.Workplane, int]:
    """把零件的**全部**实体包成一个 Compound 的 Workplane。

    为什么必须做：`fitcheck.common_volume()` 取 `a.val()`，而 CadQuery 的
    `Workplane.val()` 只返回 `objects[0]`。多实体零件（实测全机只有
    `torso_upper__torso_frame`，3 个互不相连实体）因此有 17% 体积
    （21 983 / 130 183 mm³）**对判定链路不可见**。这是仓库既有口径的
    系统性盲区（`interference.py` 同样受影响），本脚本默认修掉它，
    同时用 `shape0_legacy` 保留旧口径以便与权威基线 189 对 / 160 339 mm³ 对账。
    """
    solids = wp.solids().vals()
    if len(solids) <= 1:
        return wp, len(solids)
    return (cq.Workplane("XY").newObject([cq.Compound.makeCompound(solids)]),
            len(solids))


def restack_all_solids(placed: cq.Workplane) -> cq.Workplane:
    """`_place()` 之后重新包一次（否则 val() 又只看到第一个实体）。"""
    solids = placed.solids().vals()
    if len(solids) <= 1:
        return placed
    return cq.Workplane("XY").newObject([cq.Compound.makeCompound(solids)])


def load_parts(kin0: PoseKin) -> Tuple[List[Part], List[Dict[str, Any]]]:
    """零位装配一次，拿到真实零件（只读内存，不写盘）。"""
    placements = json.loads(PLACEMENTS_JSON.read_text(encoding="utf-8"))
    elec_link = {e["id"]: e["link"] for e in placements.get("electronics", [])}
    items, log = A.build_assembly(kin0._kin, placements)
    bad = [l for l in log if not l.get("ok")]
    parts: List[Part] = []
    for name, shape in items:
        link = part_link(name, kin0, elec_link)
        if link not in kin0.world:
            bad.append({"name": name, "ok": False,
                        "err": f"归属 link {link!r} 不在 URDF 里"})
            continue
        complete, n_solids = wrap_all_solids(shape)
        parts.append(Part(name=name, link=link, kind=part_kind(name),
                          shape0=complete, shape0_legacy=shape,
                          bbox_local=bbox_of(complete),
                          vol=float(complete.val().Volume()), n_solids=n_solids))
    return parts, bad


# --------------------------------------------------------------------------
# 事件与结果容器
# --------------------------------------------------------------------------
@dataclass
class Event:
    a: str
    b: str
    vol: float
    base: float
    excess: float
    frac: float
    verdict: str
    mate: bool
    same_joint: bool
    pose: Dict[str, float]
    tag: str                       # 来源：grid:<joint>=<deg> / lhs#n / preset:<名>

    @property
    def key(self) -> Tuple[str, str]:
        return tuple(sorted((self.a, self.b)))  # type: ignore[return-value]

    @property
    def kind(self) -> str:
        """`new` = 零位不干涉（基线 ≤ 1 mm³）而该姿态下才出现 → 真·姿态诱发碰撞；
        `worsen` = 零位本就干涉，该姿态下进一步变大 → 零位几何问题，限位治不了它。

        这个区分是**限位建议的口径基础**：若把 `worsen` 也算进"首撞角"，
        一对零位已干涉 3556 mm³、动 0.5° 只涨 105 mm³ 的既有碰撞会把首撞角
        压到 0.5°，据此收紧限位等于让机器人不能动，而真正该做的是改几何让位。
        """
        return "new" if self.base <= EXCESS_MIN else "worsen"


def classify_events(events: Sequence[Event]) -> Dict[str, bool]:
    """一次姿态检查的判据汇总（多个阈值同时算，供扫描复用）。"""
    return {
        "any": bool(events),
        "new": any(e.kind == "new" for e in events),
        "new10": any(e.kind == "new" and e.vol > EXCESS_CLEAR for e in events),
        "worsen": any(e.kind == "worsen" for e in events),
    }


def same_joint_interface(a: str, b: str) -> bool:
    """同一关节号、双方都是关节件（is_joint_mate 的补充口径，见模块 docstring 5）。"""
    ja, ka = joint_kind(a)
    jb, kb = joint_kind(b)
    if not ja or ja != jb:
        return False
    return ka in KIN_KINDS and kb in KIN_KINDS


def overlap_volume_of_boxes(b1: Any, b2: Any) -> float:
    dx = min(b1.xmax, b2.xmax) - max(b1.xmin, b2.xmin)
    dy = min(b1.ymax, b2.ymax) - max(b1.ymin, b2.ymin)
    dz = min(b1.zmax, b2.zmax) - max(b1.zmin, b2.zmin)
    if dx <= 0 or dy <= 0 or dz <= 0:
        return 0.0
    return dx * dy * dz


def transform_bbox(bbox: Any, m: np.ndarray) -> SimpleNamespace:
    """用刚体矩阵变换 AABB 的 8 个角点 → 新的（保守）AABB。"""
    xs = (bbox.xmin, bbox.xmax)
    ys = (bbox.ymin, bbox.ymax)
    zs = (bbox.zmin, bbox.zmax)
    corners = np.array([[x, y, z, 1.0] for x in xs for y in ys for z in zs])
    pts = corners @ m.T
    p = pts[:, :3]
    lo, hi = p.min(axis=0), p.max(axis=0)
    return SimpleNamespace(xmin=lo[0], xmax=hi[0], xlen=hi[0] - lo[0],
                           ymin=lo[1], ymax=hi[1], ylen=hi[1] - lo[1],
                           zmin=lo[2], zmax=hi[2], zlen=hi[2] - lo[2])


# --------------------------------------------------------------------------
# 扫掠器
# --------------------------------------------------------------------------
class Sweeper:
    def __init__(self, urdf: Path, excess_min: float = EXCESS_MIN):
        self.urdf = urdf
        self.excess_min = excess_min
        t0 = time.time()
        self.kin0 = PoseKin(urdf)
        self.joints: List[str] = list(self.kin0.joints.keys())
        self.parts, self.load_bad = load_parts(self.kin0)
        self.names = [p.name for p in self.parts]
        self.index = {n: i for i, n in enumerate(self.names)}
        self.load_s = time.time() - t0
        # 每个 link 上的零件下标
        self.by_link: Dict[str, List[int]] = defaultdict(list)
        for i, p in enumerate(self.parts):
            self.by_link[p.link].append(i)
        # 不同 link 的零件对（同 link 对恒定，恒等式排除，见 docstring 6）
        self.pairs: List[Tuple[int, int]] = []
        for i in range(len(self.parts)):
            for j in range(i + 1, len(self.parts)):
                if self.parts[i].link != self.parts[j].link:
                    self.pairs.append((i, j))
        self.mate_of: Dict[Tuple[int, int], bool] = {}
        self.same_joint_of: Dict[Tuple[int, int], bool] = {}
        self.link_of_pair: Dict[Tuple[int, int], Tuple[str, str]] = {}
        for i, j in self.pairs:
            a, b = self.names[i], self.names[j]
            self.mate_of[(i, j)] = bool(is_joint_mate(a, b))
            self.same_joint_of[(i, j)] = same_joint_interface(a, b)
            self.link_of_pair[(i, j)] = tuple(sorted((self.parts[i].link,
                                                      self.parts[j].link)))  # type: ignore
        # 单关节扫掠的候选对：跨越 subtree(J) 边界的对（精确，非近似）
        self.joint_pairs: Dict[str, List[Tuple[int, int]]] = {}
        for jn in self.joints:
            sub = self.kin0.subtree(jn)
            self.joint_pairs[jn] = [
                (i, j) for (i, j) in self.pairs
                if (self.parts[i].link in sub) != (self.parts[j].link in sub)
            ]
        self.baseline: Dict[Tuple[int, int], float] = {}
        self.base_bbox_ov: Dict[Tuple[int, int], float] = {}
        self.bool_calls = 0
        self.place_calls = 0
        self.poses_done = 0
        self.pose_seconds: List[float] = []
        self.notes: List[str] = []

    # ---------------- 基线 ----------------
    def zero_baseline(self) -> Tuple[int, float]:
        """零位实测基线（跨 link 对，全部实体口径）。"""
        dead = time.time() + 1800
        for (i, j) in self.pairs:
            if time.time() > dead:
                self.notes.append("基线计算超时，未算完")
                break
            pa, pb = self.parts[i], self.parts[j]
            ov = overlap_volume_of_boxes(pa.bbox_local, pb.bbox_local)
            if ov <= self.excess_min:
                continue
            self.bool_calls += 1
            try:
                v = common_volume(pa.shape0, pb.shape0)
            except Exception as exc:  # noqa: BLE001
                self.notes.append(f"基线布尔失败 {pa.name}↔{pb.name}: {exc}")
                continue
            if v > self.excess_min:
                self.baseline[(i, j)] = v
                self.base_bbox_ov[(i, j)] = ov
        return len(self.baseline), sum(self.baseline.values())

    def authority_bridge(self) -> Dict[str, Any]:
        """与仓库权威口径（`val()` 只看第一个实体）对账。

        只有多实体零件在两种口径下不同，所以：
            旧口径基线 = Σ(不含多实体零件的对) + Σ(含多实体零件的对的旧口径体积)
        这一步只在"含多实体零件"的少数对上重算布尔，成本可忽略。
        """
        flagged = {i for i, p in enumerate(self.parts) if p.truncated}
        legacy_add: Dict[Tuple[int, int], float] = {}
        n_calls = 0
        for (i, j) in self.pairs:
            if i not in flagged and j not in flagged:
                continue
            ov = overlap_volume_of_boxes(self.parts[i].bbox_local,
                                         self.parts[j].bbox_local)
            if ov <= self.excess_min:
                continue
            try:
                n_calls += 1
                v = common_volume(self.parts[i].shape0_legacy,
                                  self.parts[j].shape0_legacy)
            except Exception:  # noqa: BLE001
                continue
            if v > self.excess_min:
                legacy_add[(i, j)] = v
        base_new = sum(v for k, v in self.baseline.items()
                       if k[0] not in flagged and k[1] not in flagged)
        cnt_new = sum(1 for k in self.baseline
                      if k[0] not in flagged and k[1] not in flagged)
        legacy_total = base_new + sum(legacy_add.values())
        legacy_cnt = cnt_new + len(legacy_add)
        return {
            "flagged_parts": [self.parts[i].name for i in sorted(flagged)],
            "flagged_solids": {self.parts[i].name: self.parts[i].n_solids
                               for i in sorted(flagged)},
            "legacy_pairs": legacy_cnt, "legacy_vol": legacy_total,
            "new_pairs": len(self.baseline), "new_vol": sum(self.baseline.values()),
            "bool_calls": n_calls,
            "authority_pairs": 189, "authority_vol": 160339.0,
            "same_link_pairs": 60, "same_link_vol": 63370.0,
        }

    # ---------------- 单姿态检查 ----------------
    def _deltas(self, kin: PoseKin) -> List[np.ndarray]:
        """零件刚体位姿增量：M = world[link](姿态) · world[link](零位)⁻¹。"""
        cache: Dict[str, np.ndarray] = {}
        out: List[np.ndarray] = []
        for p in self.parts:
            d = cache.get(p.link)
            if d is None:
                d = np_mat(A.mat_mul(kin.world[p.link],
                                     mat_inv(self.kin0.world[p.link])))
                cache[p.link] = d
            out.append(d)
        return out

    def check_pose(self, pose: Dict[str, float],
                   pair_ids: Optional[Sequence[Tuple[int, int]]] = None,
                   tag: str = "") -> List[Event]:
        t0 = time.time()
        kin = PoseKin(self.urdf, pose)
        deltas = self._deltas(kin)
        boxes = [transform_bbox(self.parts[i].bbox_local, deltas[i])
                 for i in range(len(self.parts))]
        ids = self.pairs if pair_ids is None else pair_ids
        events: List[Event] = []
        placed: Dict[int, cq.Workplane] = {}
        for (i, j) in ids:
            key = (i, j)
            base = self.baseline.get(key, 0.0)
            ov = overlap_volume_of_boxes(boxes[i], boxes[j])
            # 精确安全剪枝：ov 是真实相交体积的上界 ⇒ ov ≤ base+ε 时 excess 必 ≤ε
            if ov <= base + self.excess_min:
                continue
            for k in (i, j):
                if k not in placed:
                    placed[k] = restack_all_solids(
                        A._place(self.parts[k].shape0, deltas[k].tolist()))
                    self.place_calls += 1
            try:
                self.bool_calls += 1
                v = common_volume(placed[i], placed[j])
            except Exception as exc:  # noqa: BLE001
                self.notes.append(f"布尔失败 {self.names[i]}↔{self.names[j]}: {exc}")
                continue
            excess = v - base
            if excess <= self.excess_min:
                continue
            pa, pb = self.parts[i], self.parts[j]
            smaller = max(min(pa.vol, pb.vol), 1e-9)
            events.append(Event(
                a=pa.name, b=pb.name, vol=v, base=base, excess=excess,
                frac=v / smaller, verdict=verdict(v, v / smaller),
                mate=self.mate_of[key], same_joint=self.same_joint_of[key],
                pose=dict(pose), tag=tag))
        self.poses_done += 1
        self.pose_seconds.append(time.time() - t0)
        return events

    # ---------------- 采样 ----------------
    def grid_poses(self, levels: Sequence[float]) -> List[Tuple[str, Dict[str, float]]]:
        out: List[Tuple[str, Dict[str, float]]] = []
        for jn in self.joints:
            lo, hi = self.kin0.limits(jn)
            for al in levels:
                q = (1 - al) * lo + al * hi
                out.append((f"grid:{jn}={deg(q):+.0f}°", {jn: q}))
        return out

    def lhs_poses(self, n: int, seed: int = 42) -> List[Tuple[str, Dict[str, float]]]:
        rng = np.random.default_rng(seed)
        d = len(self.joints)
        perms = [rng.permutation(n) for _ in range(d)]
        out: List[Tuple[str, Dict[str, float]]] = []
        for i in range(n):
            pose: Dict[str, float] = {}
            for k, jn in enumerate(self.joints):
                lo, hi = self.kin0.limits(jn)
                u = (perms[k][i] + rng.random()) / n
                pose[jn] = lo + u * (hi - lo)
            out.append((f"lhs#{i + 1}", pose))
        return out

    def preset_poses(self) -> List[Tuple[str, Dict[str, float]]]:
        """预览窗口的 5 个预设（口径同 preview.POSE_PRESETS，按 URDF 限位夹紧）。"""
        raw: List[Tuple[str, Dict[str, float]]] = [
            ("预设-空", {}),
            ("预设-展示", dict(A.DISPLAY_POSE_DEG)),
            ("预设-招手", {"right_shoulder_pitch": -88.0, "right_elbow_pitch": -90.0,
                        "right_shoulder_roll": -12.0, "left_shoulder_pitch": -14.0,
                        "left_elbow_pitch": -22.0, "left_shoulder_roll": 6.0,
                        "head_yaw": -14.0, "head_pitch": 4.0, "trunk_roll": -3.0,
                        "right_gripper": 15.0}),
            ("预设-踢球", {"right_hip_pitch": -60.0, "right_knee_pitch": 62.0,
                        "right_ankle_pitch": -24.0, "left_hip_pitch": 3.0,
                        "left_knee_pitch": 3.0, "left_ankle_pitch": -3.0,
                        "trunk_pitch": 6.0, "trunk_roll": 3.0,
                        "left_shoulder_pitch": -30.0, "right_shoulder_pitch": 25.0,
                        "left_elbow_pitch": -32.0, "right_elbow_pitch": -20.0}),
            ("预设-抓取", {"left_shoulder_pitch": -62.0, "right_shoulder_pitch": -62.0,
                        "left_shoulder_roll": 10.0, "right_shoulder_roll": -10.0,
                        "left_elbow_pitch": -38.0, "right_elbow_pitch": -38.0,
                        "left_gripper": 52.0, "right_gripper": 52.0,
                        "head_pitch": 22.0, "trunk_pitch": 4.0}),
        ]
        out = []
        for name, pose_deg in raw:
            pose = {}
            clipped = []
            for jn, v in pose_deg.items():
                lo, hi = self.kin0.limits(jn)
                q = math.radians(v)
                if q < lo:
                    q, _ = lo, clipped.append(jn)
                elif q > hi:
                    q, _ = hi, clipped.append(jn)
                pose[jn] = q
            if clipped:
                self.notes.append(f"{name}: 预设值超出 URDF 限位，已夹紧 {clipped}")
            out.append((name, pose))
        return out


# --------------------------------------------------------------------------
# 逐关节首撞角（单关节扫掠 + 二分细化）
# --------------------------------------------------------------------------
def first_hit_scan(sw: Sweeper, joint: str, direction: int,
                   coarse: int = 12, tol_deg: float = 0.5,
                   deadline: float = float("inf")
                   ) -> Dict[str, Any]:
    """沿单关节某一方向扫到 URDF 限位，找**首次出现姿态诱发碰撞**的角度。

    direction=+1 扫正方向、−1 扫负方向。四个判据同时算（同一次姿态检查里读出）：

    - `new`   ：出现「零位不干涉（基线 ≤ 1 mm³）而该姿态下相交 > 1 mm³」的对
                —— **这是限位建议的依据**；
    - `new10` ：同上但相交 > 10 mm³（宽松口径，用于判断是否只是数值级擦碰）；
    - `worsen`：零位本就干涉的对进一步变大（零位几何问题，限位治不了，仅作信息）；
    - `mate`  ：命中的对全部是 `is_joint_mate` / 同关节界面（配合面贴合加剧）。
    """
    lo, hi = sw.kin0.limits(joint)
    end = hi if direction > 0 else lo
    blank = {"joint": joint, "direction": direction, "limit": end,
             "scanned": True, "hit_any": None, "hit_new": None, "hit_new10": None,
             "hit_worsen": None, "hit_mate": None}
    if abs(end) < 1e-9:
        blank["reason"] = "该方向 URDF 限位为 0，无可扫行程"
        return blank
    ids = sw.joint_pairs[joint]

    def hit_at(q: float) -> Tuple[Dict[str, bool], List[Event]]:
        if time.time() > deadline:
            raise BudgetExceeded("首撞角扫描超出软预算")
        evs = sw.check_pose({joint: q}, pair_ids=ids,
                            tag=f"scan:{joint}={deg(q):+.2f}°")
        c = classify_events(evs)
        c["mate"] = bool(evs) and all(e.mate or e.same_joint for e in evs)
        return c, evs

    # 粗扫全行程（碰撞与角度未必单调，扫完才能说"第一次"）。
    # 角度按幂律向 0 加密 (k/coarse)^1.6：均匀取样在 coarse=12 时首格就有
    # 3.3°（踝）/7.5°（膝），最容易漏掉"一动就撞"的窄带。
    angles = [end * (k / coarse) ** 1.6 for k in range(1, coarse + 1)]
    flags: Dict[str, List[float]] = {k: [] for k in
                                     ("any", "new", "new10", "worsen", "mate")}
    for q in angles:
        c, _ = hit_at(q)
        for k in flags:
            if c.get(k):
                flags[k].append(q)
    if not flags["any"]:
        blank["reason"] = (f"扫到 URDF 限位 {fmt_deg(end)} 全程无新增碰撞"
                           f"（粗扫最密 {deg(angles[0]):.2f}°）")
        blank["scanned_empty"] = True
        blank["coarse"] = coarse
        blank["coarse_first3"] = [deg(x) for x in angles[:3]]
        blank["coarse_hits"] = {k: 0 for k in
                                ("any", "new", "new10", "worsen", "mate")}
        blank["coarse_hit_angles_any"] = []
        return blank

    def refine(target: float, mode: str) -> float:
        """在 target 的前一格到 target 之间二分第一个命中角；a 安全、b 命中。"""
        idx = angles.index(target)
        step = angles[idx] - (angles[idx - 1] if idx > 0 else 0.0)
        a, b = target - step, target
        while abs(deg(b - a)) > tol_deg:
            if time.time() > deadline:
                raise BudgetExceeded("二分细化超出软预算")
            m = 0.5 * (a + b)
            c, _ = hit_at(m)
            if c.get(mode):
                b = m
            else:
                a = m
        return b

    # 只对限位建议真正要用的 `new` / `new10` 做二分细化；
    # `any` / `worsen` / `mate` 只报粗扫首格（分辨率 = 一格，已在报告注明）。
    hit_new = refine(flags["new"][0], "new") if flags["new"] else None
    hit_new10 = refine(flags["new10"][0], "new10") if flags["new10"] else None

    # 代表事件：优先给出"零位不干涉"的那一类（真正的姿态诱发碰撞）
    rep = None
    for probe in (hit_new, hit_new10, flags["any"][0]):
        if probe is None:
            continue
        _, evs = hit_at(probe)
        cand = [e for e in evs if e.kind == "new"] or evs
        if cand:
            rep = max(cand, key=lambda e: e.excess)
            break
    return {
        "joint": joint, "direction": direction, "limit": end, "scanned": True,
        "hit_new": hit_new,
        "hit_new10": hit_new10,
        "hit_any_coarse": flags["any"][0],
        "hit_worsen_coarse": flags["worsen"][0] if flags["worsen"] else None,
        "hit_mate_coarse": flags["mate"][0] if flags["mate"] else None,
        "coarse": coarse, "coarse_first3": [deg(x) for x in angles[:3]],
        "coarse_hits": {k: len(v) for k, v in flags.items()},
        "coarse_hit_angles_any": [deg(x) for x in flags["any"]],
        "worst": ({"a": rep.a, "b": rep.b, "kind": rep.kind, "excess": rep.excess,
                   "vol": rep.vol, "base": rep.base, "mate": rep.mate,
                   "same_joint": rep.same_joint, "verdict": rep.verdict}
                  if rep else None),
    }


def recommend_limit(hit: Optional[float], current: float,
                    margin_deg: float = 2.0, frac: float = 0.10) -> Optional[float]:
    """由首撞角推保守限位：hit − max(margin, frac·|hit|)，向下取整到 1°。

    不收紧（返回 None）当且仅当首撞角不存在（全行程安全）。
    """
    if hit is None:
        return None
    m = max(margin_deg, frac * abs(deg(hit)))
    val = abs(deg(hit)) - m
    if val <= 0:
        return 0.0
    return float(math.floor(val))


# --------------------------------------------------------------------------
# 汇总
# --------------------------------------------------------------------------
def summarize(events: List[Event]) -> Dict[str, Any]:
    by_pair: Dict[Tuple[str, str], List[Event]] = defaultdict(list)
    for e in events:
        by_pair[e.key].append(e)
    records = []
    for key, evs in by_pair.items():
        worst = max(evs, key=lambda e: e.excess)
        records.append({
            "a": key[0], "b": key[1],
            "max_excess": worst.excess, "max_vol": worst.vol,
            "base": worst.base, "frac": worst.frac, "verdict": worst.verdict,
            "mate": worst.mate, "same_joint": worst.same_joint,
            "kind": worst.kind,
            "events": len(evs), "pose": worst.pose, "tag": worst.tag,
        })
    # `new`（零位不干涉、姿态下才撞）优先于 `worsen`：两者各自按新增体积降序
    new = sorted([r for r in records if r["kind"] == "new"],
                 key=lambda r: -r["max_excess"])
    worsen = sorted([r for r in records if r["kind"] == "worsen"],
                    key=lambda r: -r["max_excess"])
    return {"records": new + worsen, "new": new, "worsen": worsen,
            "n_events": len(events), "n_new": len(new), "n_worsen": len(worsen)}


def pose_text(pose: Dict[str, float], top: int = 8) -> str:
    nz = [(j, v) for j, v in pose.items() if abs(deg(v)) >= 0.5]
    nz.sort(key=lambda kv: -abs(kv[1]))
    if not nz:
        return "全零（零位）"
    s = "，".join(f"{j}={deg(v):+.1f}°" for j, v in nz[:top])
    if len(nz) > top:
        s += f"（另 {len(nz) - top} 个关节非零）"
    return s


# --------------------------------------------------------------------------
# 报告
# --------------------------------------------------------------------------
def write_markdown(path: Path, payload: Dict[str, Any]) -> None:
    P = payload
    L: List[str] = []
    add = L.append
    add("# 极限姿态扫掠自碰撞校核（姿态诱发碰撞）")
    add("")
    add(f"> 生成：`design/cad/sweep_check.py` ｜ 模式 `{P['mode']}` ｜ "
        f"耗时 {P['elapsed_s']:.0f} s ｜ 布尔求交 {P['bool_calls']} 次")
    add("")
    add("## 一、口径与溯源")
    add("")
    add("| 项 | 值 |")
    add("|---|---|")
    add(f"| 几何来源 | `assembly.build_assembly()` 真实零件（**非 URDF collision 代理块**）|")
    add(f"| 零件数 | {P['n_parts']}（装配失败 {P['n_load_bad']}）|")
    add(f"| link 数 | {P['n_links']} |")
    add(f"| 关节数 | {P['n_joints']} |")
    add(f"| 参与扫掠的零件对（跨 link）| {P['n_pairs']} |")
    add(f"| 同一 link 内被排除的对 | {P['n_same_link_pairs']}（刚性同步，恒不可能姿态诱发）|")
    add(f"| **零位基线（跨 link，全部实体口径）** | "
        f"**{P['base_pairs']} 对 / {P['base_vol']:.0f} mm³** |")
    B = P.get("authority_bridge") or {}
    if B:
        add(f"| 零位基线（跨 link，仓库 `val()` 口径）| "
            f"{B['legacy_pairs']} 对 / {B['legacy_vol']:.0f} mm³ |")
        add(f"| 同 link 恒定对（不参与扫掠）| 60 对 / 63 370 mm³ |")
        add(f"| **合计 = 权威口径** | **{B['legacy_pairs'] + 60} 对 / "
            f"{B['legacy_vol'] + 63370:.0f} mm³**（权威 189 对 / 160 339 mm³）|")
        add(f"| 全部实体口径多算出的几何 | "
            f"{B['new_pairs'] - B['legacy_pairs']} 对 / "
            f"{B['new_vol'] - B['legacy_vol']:.0f} mm³（"
            f"{'、'.join(B['flagged_parts']) or '无'} 的多实体盲区）|")
    add(f"| 运动学 | `assembly.Kin`（正解唯一实现）|")
    add(f"| 零件→link | `preview.part_link()` 口径（`fork__J` → 子 link）|")
    add(f"| **多实体盲区修正** | 默认把每个零件的**全部实体**包成 Compound；"
        f"全机多实体零件 {len(B.get('flagged_parts', []))} 件"
        f"（{B.get('flagged_solids', {})}）|")
    add("")
    add("溯源指纹（md5）：")
    add("")
    for k, v in P["fingerprints"].items():
        add(f"- `{k}`：`{v}`")
    add("")
    add("## 二、覆盖度")
    add("")
    add("| 项 | 值 |")
    add("|---|---|")
    add(f"| 单关节扫掠档位 | {P['levels']} 档 × {P['n_joints']} 关节 |")
    add(f"| LHS 组合数 | {P['lhs_n']}（种子 {P['seed']}）|")
    add(f"| 预览预设 | {P['n_presets']} |")
    add(f"| 首撞角扫描 | 22 关节 × 2 方向，粗扫 {P['scan_coarse']} 格 + 二分细化 ≤ {P['scan_tol']}° |")
    add(f"| **实际完成姿态数** | **{P['poses_done']}** |")
    add(f"| 跑完? | {'是' if P['completed'] else '**否（软预算到点，见未验证项）**'} |")
    add(f"| 平均单姿态耗时 | {P['pose_avg_s']:.2f} s |")
    add("")
    if P["notes"]:
        add("### 运行时记录")
        add("")
        for n in P["notes"]:
            add(f"- {n}")
        add("")

    add("## 三、姿态诱发的碰撞（按扣基线后的新增体积排序）")
    add("")
    add(f"- 事件总数：{P['n_events']}；涉及零件对：{len(P['records'])}"
        f"（其中**真·姿态诱发 {P['n_new']} 对**，零位既有干涉恶化 {P['n_worsen']} 对）")
    add(f"- 排序口径：`新增 = 该姿态实测相交体积 − 零位实测相交体积`；"
        f"门限 `新增 > {EXCESS_MIN} mm³`")
    add(f"- **分类口径**（这是限位建议的基础）：")
    add(f"  - `new` = 零位基线 ≤ {EXCESS_MIN} mm³（零位不干涉）、该姿态下才相交"
        f" → **真·姿态诱发碰撞**，只能靠限位或改几何解决；")
    add(f"  - `worsen` = 零位已经干涉（这 189 对里的），该姿态下进一步变大"
        f" → 属零位让位不足，**收紧限位治不了它**，只能改几何。")
    add(f"- 配合面列：`mate` = `fitcheck.is_joint_mate()` 逐字判定；"
        f"`same_joint` = 同关节号且双方都是关节件（补充口径，见 docstring 5）")
    add("")
    if not P["records"]:
        add("**未发现任何姿态诱发的新增碰撞**（全部跨 link 对的新增体积 ≤ "
            f"{EXCESS_MIN} mm³）。")
        add("")
    else:
        for title, key in (("3.1 真·姿态诱发碰撞（零位不干涉 → 动起来才撞）", "new"),
                           ("3.2 零位既有干涉在姿态下进一步恶化"
                            "（限位解决不了，需改几何让位）", "worsen")):
            rows = [r for r in P["records"] if r["kind"] == key][:25]
            add(f"### {title}")
            add("")
            if not rows:
                add("（无）")
                add("")
                continue
            add("| # | 件 A | 件 B | 新增 mm³ | 该姿态体积 | 零位基线 | 重合率 | 配合面 | 判定 |")
            add("|---|---|---|---|---|---|---|---|---|")
            for k, r in enumerate(rows, 1):
                flag = ("同关节配合面" if r["mate"] else
                        ("同关节界面(补充)" if r["same_joint"] else "—"))
                add(f"| {k} | `{r['a']}` | `{r['b']}` | **{r['max_excess']:.0f}** | "
                    f"{r['max_vol']:.0f} | {r['base']:.0f} | {r['frac'] * 100:.0f}% | "
                    f"{flag} | {r['verdict']} |")
            add("")
        add("### 3.3 最危险姿态明细（按新增体积 Top 10）")
        add("")
        for k, r in enumerate(P["records"][:10], 1):
            add(f"**{k}. `{r['a']}` ↔ `{r['b']}`** — 新增 {r['max_excess']:.0f} mm³"
                f"（该姿态 {r['max_vol']:.0f}，零位 {r['base']:.0f}，"
                f"{'真·姿态诱发' if r['kind'] == 'new' else '零位既有干涉恶化'}）")
            add("")
            add(f"- 姿态（{r['tag']}）：{pose_text(r['pose'])}")
            add(f"- 配合面：{'是（`is_joint_mate`）' if r['mate'] else ('是（同关节界面，补充口径）' if r['same_joint'] else '否')}")
            add("")

    add("## 四、逐关节限位建议")
    add("")
    add("口径：`首撞角(新碰撞)` = 单关节沿该方向扫掠时**首次出现「零位不干涉"
        f"（基线 ≤ {EXCESS_MIN} mm³）而该姿态下相交 > {EXCESS_MIN} mm³」的对**的角度"
        f"（粗扫按 `(k/n)^1.6` 向 0 加密，再二分细化到 {P['scan_tol']}°）；"
        "`建议限位` = `|首撞角| − max(2°, 10%·|首撞角|)` 向下取整到 1°"
        "（保守余量覆盖装配公差、控制超调与仿真-实物差异）。"
        "`首撞角(>10mm³)` 是更宽松的口径（只在互穿超过 10 mm³ 时才刹车）。"
        "`首撞角(恶化)` 是零位既有干涉首次变大的角度，仅作信息——"\
        "它不该被用来收紧限位。")
    add("")
    add("| 关节 | URDF 限位 | 首撞角(新碰撞) +方向/−方向 | 建议限位 +/− | "
        "首撞角(>10mm³) +/− | 首撞角(恶化) +/− | 代表新碰撞 |")
    add("|---|---|---|---|---|---|---|")
    for row in P["limit_table"]:
        jn = row["joint"]
        lo, hi = row["urdf"]

        def g(key: str, sign: str, unit: str = "°") -> str:
            v = row.get(f"{key}_{sign}")
            if v is None:
                return "—"
            return f"{v:+.1f}{unit}"

        ra = ("保持" if row.get("reco_pos") is None else f"+{row['reco_pos']:.0f}°")
        ra2 = ("保持" if row.get("reco_neg") is None else f"−{row['reco_neg']:.0f}°")
        w = row.get("worst")
        wtxt = "—"
        if w:
            wtxt = (f"`{w['a']}`↔`{w['b']}` {w['excess']:.0f} mm³"
                    f"（{w['kind']}）")
        if row.get("error"):
            add(f"| `{jn}` | {lo:+.0f}° … {hi:+.0f}° | 未完成 | — | — | — | "
                f"{row['error']} |")
            continue
        add(f"| `{jn}` | {lo:+.0f}° … {hi:+.0f}° | "
            f"{g('hit_new', 'pos')} / {g('hit_new', 'neg')} | "
            f"**{ra} / {ra2}** | "
            f"{g('hit_new10', 'pos')} / {g('hit_new10', 'neg')} | "
            f"{g('hit_worsen_coarse', 'pos')} / {g('hit_worsen_coarse', 'neg')} | "
            f"{wtxt} |")
    add("")
    add("（`保持` = 该方向全行程扫掠无「新碰撞」命中，无需收紧。"
        "`首撞角(恶化)` 列的分辨率是一格粗扫，未做二分细化。）")
    add("")
    add("### 4.1 扫掠结果补充：命中间隔与非常数行为")
    add("")
    add("`粗扫命中格数` 是粗扫各判据命中的格数（满格 = 该方向越走越撞；"
        "非满格 = 撞了又恢复，属窄带干涉）。三个判据的顺序是 "
        "any / new / new10 / worsen / mate。")
    add("")
    add("| 关节 | 方向 | 首格角 | 粗扫命中格数(any/new/new10/worsen/mate) | 粗扫命中的任意指令角 |")
    add("|---|---|---|---|---|")
    for row in P["limit_table"]:
        for key, sign in (("pos", "+"), ("neg", "−")):
            d = (row.get("detail") or {}).get(key)
            if not d:
                continue
            ch = d.get("coarse_hits") or {}
            f3 = d.get("coarse_first3") or []
            f3txt = f"{f3[0]:+.2f}°" if f3 else "—"
            add(f"| `{row['joint']}` | {sign} | {f3txt} | "
                f"{ch.get('any', 0)}/{ch.get('new', 0)}/{ch.get('new10', 0)}/"
                f"{ch.get('worsen', 0)}/{ch.get('mate', 0)} | "
                f"{', '.join(f'{x:+.1f}°' for x in (d.get('coarse_hit_angles_any') or [])[:8]) or '—'} |")
    add("")

    add("## 五、未验证项")
    add("")
    for u in P["unverified"]:
        add(f"- {u}")
    add("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


# --------------------------------------------------------------------------
# 图
# --------------------------------------------------------------------------
def _tessellate(shape: cq.Workplane, tol: float) -> Tuple[np.ndarray, np.ndarray]:
    vs, ts = shape.val().tessellate(tol)
    V = np.array([[v.x, v.y, v.z] for v in vs], dtype=float)
    T = np.array(ts, dtype=np.int64)
    return V, T


def _view_basis(azim_deg: float, elev_deg: float) -> np.ndarray:
    a, e = math.radians(azim_deg), math.radians(elev_deg)
    f = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
    right = np.array([-math.sin(a), math.cos(a), 0.0])
    up = np.cross(f, right)
    return np.vstack([right, up, f])          # 行 = 屏幕 x, 屏幕 y, 深度


def _collect_tris(parts: List[Part], meshes: List[Tuple[np.ndarray, np.ndarray]],
                  deltas: List[np.ndarray], RGB: Dict[str, Tuple[float, float, float]],
                  highlight: Set[str], view: np.ndarray, light: np.ndarray
                  ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    tri2d: List[np.ndarray] = []
    cols: List[np.ndarray] = []
    depth: List[np.ndarray] = []
    for p, (V, T), M in zip(parts, meshes, deltas):
        if len(T) == 0:
            continue
        W = V @ M[:3, :3].T + M[:3, 3]
        C = W @ view.T
        v0, v1, v2 = W[T[:, 0]], W[T[:, 1]], W[T[:, 2]]
        nrm = np.cross(v1 - v0, v2 - v0)
        ln = np.linalg.norm(nrm, axis=1)
        ln[ln < 1e-12] = 1.0
        nrm = nrm / ln[:, None]
        shade = 0.30 + 0.70 * np.abs(nrm @ light)
        hl = p.name in highlight
        if hl:
            base = np.array([0.94, 0.13, 0.13])
        else:
            base = np.array(RGB.get(p.kind, (0.62, 0.65, 0.70)))
        tri2d.append(C[T][:, :, :2])
        cols.append(np.clip(shade[:, None] * base[None, :], 0, 1))
        d = C[T][:, :, 2].mean(axis=1)
        # 高亮件加深深度偏置 → 排序后画在最上层，否则会被它前面的件挡掉看不见
        depth.append(d + (1.0e6 if hl else 0.0))
    if not tri2d:
        return np.zeros((0, 3, 2)), np.zeros((0, 4)), np.zeros((0,))
    A2 = np.concatenate(tri2d, axis=0)
    Cc = np.concatenate(cols, axis=0)
    D = np.concatenate(depth, axis=0)
    order = np.argsort(D)                     # 远 → 近
    rgba = np.concatenate([Cc[order], np.ones((len(order), 1))], axis=1)
    return A2[order], rgba, D[order]


def make_figure(path: Path, parts: List[Part],
                meshes: List[Tuple[np.ndarray, np.ndarray]],
                zero_deltas: List[np.ndarray],
                danger_deltas: List[np.ndarray],
                danger_pose: Dict[str, float],
                danger_pairs: List[Dict[str, Any]],
                limit_table: List[Dict[str, Any]],
                coverage: str, tol: float) -> None:
    import matplotlib
    matplotlib.use("Agg")
    # 字体：`Arial Unicode MS` 是本机唯一同时覆盖 ↔ (U+2194) / ³ (U+00B3) 与简体中文的
    # 字体（`Hiragino Sans GB` 缺这两个字形，会渲染成方框）。
    matplotlib.rcParams["font.sans-serif"] = [
        "Arial Unicode MS", "Hiragino Sans GB", "STHeiti", "Songti SC",
        "Apple SD Gothic Neo", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection

    RGB = {
        "servo": (0.20, 0.22, 0.26), "cage": (0.80, 0.62, 0.20),
        "fork": (0.30, 0.62, 0.85), "outrigger": (0.55, 0.45, 0.80),
        "cluster": (0.55, 0.45, 0.80), "adapter": (0.90, 0.45, 0.15),
        "cluster_arm": (0.90, 0.45, 0.15), "elec": (0.25, 0.65, 0.45),
        "bulk": (0.85, 0.87, 0.90),
    }
    for k in ("limb_tube", "limb_fork", "torso_frame", "pelvis_frame", "foot_plate",
              "gripper_jaw", "battery_tray", "cluster_horn_arm", "compact_adapter"):
        RGB.setdefault(k, (0.80, 0.82, 0.86))

    fig = plt.figure(figsize=(17.5, 10.5), dpi=130)
    fig.suptitle("A.T.R.I. 极限姿态扫掠：零位 vs 危险姿态 与 逐关节限位建议",
                 fontsize=19, fontweight="bold", y=0.978)
    fig.text(0.5, 0.944, coverage, ha="center", fontsize=10.5, color="#333")
    fig.text(0.5, 0.918,
             "判定原语 design/cad/fitcheck.py（先包围盒粗筛，再 OCC 真布尔求交）；"
             "几何 = assembly.build_assembly 真实零件；运动学 = assembly.Kin；"
             "基线 = 零位实测相交体积；角度单位 °。",
             ha="center", fontsize=9, color="#666")

    view = _view_basis(azim_deg=58.0, elev_deg=14.0)
    light = np.array([0.35, -0.75, 0.56])
    light = light / np.linalg.norm(light)

    hi_names = {r["a"] for r in danger_pairs[:12]} | {r["b"] for r in danger_pairs[:12]}

    for col, (title, deltas, hl, sub) in enumerate([
        ("(a) 零位（URDF 全 0）", zero_deltas, set(), "零位摆放错误 0 对（已达标）"),
        ("(b) 危险姿态（本报告 Top1）", danger_deltas, hi_names,
         "红色 = 该姿态下新增干涉的零件"),
    ]):
        ax = fig.add_axes([0.020 + col * 0.305, 0.485, 0.29, 0.405])
        T2, C, _ = _collect_tris(parts, meshes, deltas, RGB, hl, view, light)
        ax.add_collection(PolyCollection(T2, facecolors=C, edgecolors="none",
                                         antialiased=False))
        ax.autoscale_view()
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title(title, fontsize=14, fontweight="bold", pad=5)
        ax.text(0.5, -0.035, sub, transform=ax.transAxes, ha="center",
                fontsize=10, color="#555")
        if col == 1:
            ax.text(0.012, 0.012, "姿态：" + pose_text(danger_pose, top=5),
                    transform=ax.transAxes, ha="left", va="bottom",
                    fontsize=8.4, color="#a00", wrap=True,
                    bbox=dict(facecolor="white", edgecolor="#e0a0a0",
                              alpha=0.88, pad=2.5, boxstyle="round,pad=0.35"))

    # (c) Top10 新增碰撞
    ax = fig.add_axes([0.655, 0.485, 0.325, 0.405])
    top = danger_pairs[:10][::-1]
    ax.set_title("(c) 姿态诱发新增碰撞 Top10（已扣零位基线）",
                 fontsize=13.5, fontweight="bold", pad=6)
    if top:
        labels = [f"{r['a'].replace('__', '·')}\n↔ {r['b'].replace('__', '·')}"
                  for r in top]
        vals = [r["max_excess"] for r in top]
        cols = []
        for r in top:
            if r.get("kind") == "worsen":
                cols.append("#7f7f7f")
            elif r["mate"] or r["same_joint"]:
                cols.append("#ff7f0e")
            else:
                cols.append("#d62728")
        ax.barh(range(len(top)), vals, color=cols, height=0.72)
        ax.set_yticks(range(len(top)))
        ax.set_yticklabels(labels, fontsize=7.4)
        ax.set_xlabel("新增相交体积（mm³）", fontsize=10)
        for i, v in enumerate(vals):
            ax.text(v * 1.01, i, f"{v:,.0f}", va="center", fontsize=7.6)
        ax.set_xlim(0, max(vals) * 1.22)
        ax.tick_params(axis="x", labelsize=8.5)
        ax.grid(axis="x", alpha=0.3, linestyle=":")
    else:
        ax.text(0.5, 0.5, "无姿态诱发新增碰撞", ha="center", va="center",
                fontsize=14, transform=ax.transAxes)
        ax.axis("off")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color="#d62728", label="真·姿态诱发（零位不干涉→动才撞）"),
                       Patch(color="#ff7f0e", label="同上，但落在同关节配合面"),
                       Patch(color="#7f7f7f", label="零位既有干涉进一步恶化")],
              fontsize=7.6, loc="lower right", framealpha=0.92)

    # (d) 逐关节限位建议
    ax = fig.add_axes([0.115, 0.135, 0.865, 0.295])
    ax.set_title("(d) 逐关节限位建议：URDF 现值 vs 新碰撞首撞角 vs 建议限位"
                 "（° ，左=负方向 右=正方向）", fontsize=13.5, fontweight="bold", pad=6)
    rows = limit_table
    y = np.arange(len(rows))
    for k, r in enumerate(rows):
        lo, hi = r["urdf"]
        ax.plot([lo, hi], [k, k], color="#bbb", lw=7, solid_capstyle="butt", zorder=1)
        for sign, key in ((1, "pos"), (-1, "neg")):
            rec = r.get(f"reco_{key}")
            if rec is not None:
                ax.plot([0, sign * rec], [k, k], color="#2ca02c", lw=7,
                        solid_capstyle="butt", zorder=2)
            hit = r.get(f"hit_new_{key}")
            if hit is not None:
                ax.plot([hit], [k], marker="v", ms=8, color="#d62728", zorder=3)
            w = r.get(f"hit_worsen_coarse_{key}")
            if w is not None:
                ax.plot([w], [k], marker="x", ms=6, color="#7f7f7f", zorder=3)
    # 图例用显式 proxy artist：不能依赖"首行恰好有该类数据"，否则标记画了却没图例
    from matplotlib.lines import Line2D
    ax.legend(handles=[
        Line2D([], [], color="#bbb", lw=7, label="URDF 限位"),
        Line2D([], [], color="#2ca02c", lw=7, label="建议安全区（实测首撞角 − 余量）"),
        Line2D([], [], color="#d62728", marker="v", ls="none", ms=8,
               label="新碰撞首撞角（零位不干涉→动才撞）"),
        Line2D([], [], color="#7f7f7f", marker="x", ls="none", ms=6,
               label="既有干涉开始恶化（非限位依据）"),
    ], fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.115),
        ncol=4, frameon=False)
    ax.set_yticks(y)
    ax.set_yticklabels([r["joint"] for r in rows], fontsize=7.6,
                       fontfamily="monospace")
    ax.axvline(0, color="#333", lw=0.9)
    ax.grid(axis="x", alpha=0.35, linestyle=":")
    ax.set_xlabel("关节角（°）", fontsize=10.5, labelpad=1)
    ax.set_ylim(-0.8, len(rows) - 0.2)
    ax.tick_params(axis="x", labelsize=9)

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130, facecolor="white")
    plt.close(fig)


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="A.T.R.I. 极限姿态扫掠自碰撞校核（姿态诱发碰撞 + 限位建议）")
    ap.add_argument("--quick", action="store_true",
                    help="快速档：3 档单关节 + 50 组 LHS")
    ap.add_argument("--full", action="store_true",
                    help="完整档：5 档单关节 + 200 组 LHS")
    ap.add_argument("--lhs", type=int, default=None, help="覆盖 LHS 组数")
    ap.add_argument("--seed", type=int, default=42, help="LHS 随机种子")
    ap.add_argument("--budget", type=float, default=None,
                    help="软预算（秒）；到点即按已完成部分出报告")
    ap.add_argument("--out", type=Path, default=OUT, help="产物目录")
    ap.add_argument("--report", type=Path, default=None, help="报告 md 路径")
    ap.add_argument("--no-figure", action="store_true", help="不出 PNG")
    ap.add_argument("--no-scan", action="store_true", help="跳过首撞角扫描")
    ap.add_argument("--scan-coarse", type=int, default=12,
                    help="首撞角粗扫格数（每方向；默认 12）")
    ap.add_argument("--sample-frac", type=float, default=0.55,
                    help="软预算里分给姿态采样的比例（其余给首撞角扫描）")
    ap.add_argument("--fig-tol", type=float, default=0.8, help="图示网格容差 mm")
    ap.add_argument("--figure-only", nargs="?", const="", default=None,
                    help="只重出 PNG：读已有 sweep_report.json（默认在 --out 下），不跑扫掠")
    ap.add_argument("--selftest", action="store_true",
                    help="只做自检：零件→link 映射对拍 preview.part_link()，然后退出")
    args = ap.parse_args(argv)

    mode = "full" if args.full else "quick"
    out_dir: Path = args.out
    report_md = args.report or (out_dir / "sweep_report.md")
    report_json = out_dir / "sweep_report.json"
    figure_png = out_dir / "sweep_figure.png"
    levels_n = 5 if mode == "full" else 3
    lhs_n = args.lhs if args.lhs is not None else (200 if mode == "full" else 50)
    budget = args.budget if args.budget is not None else (
        DEFAULT_TIMEOUT_FULL if mode == "full" else DEFAULT_TIMEOUT_QUICK)
    t0 = time.time()

    print(f"[{mode}] 装配真实零件（assembly.build_assembly，只读内存）…", flush=True)
    sw = Sweeper(URDF)
    print(f"  零件 {len(sw.parts)} 件（装配失败 {len(sw.load_bad)}），"
          f"跨 link 零件对 {len(sw.pairs)}，耗时 {sw.load_s:.1f}s", flush=True)

    # ---- 自检：零件→link 映射与 preview.part_link() 对拍 ----
    if args.selftest:
        try:
            import preview as PV
            pl = json.loads(PLACEMENTS_JSON.read_text(encoding="utf-8"))
            el = {e["id"]: e["link"] for e in pl.get("electronics", [])}
            mismatch = [(p.name, p.link, PV.part_link(p.name, sw.kin0._kin, el))
                        for p in sw.parts if p.link != PV.part_link(p.name, sw.kin0._kin, el)]
            if mismatch:
                print(f"[FAIL] 与 preview.part_link 不一致 {len(mismatch)} 件")
                for m in mismatch:
                    print("   ", m)
                return 2
            print(f"[OK] 零件→link 映射与 preview.part_link() 全一致（{len(sw.parts)} 件）")
        except ImportError as exc:
            print(f"[SKIP] 无法 import preview: {exc}")
        return 0

    # ---- 只重出图：读已有 JSON，不重跑扫掠 ----
    if args.figure_only is not None:
        jp = Path(args.figure_only) if args.figure_only else report_json
        payload = json.loads(jp.read_text(encoding="utf-8"))
        recs = payload.get("records", [])
        ltab = payload.get("limit_table", [])
        print(f"  [figure-only] 读 {jp}：零件对 {len(recs)}，限位行 {len(ltab)}",
              flush=True)
        t_fig = time.time()
        meshes = [_tessellate(p.shape0, args.fig_tol) for p in sw.parts]
        print(f"    三角面 {sum(len(t) for _, t in meshes):,}，"
              f"网格化 {time.time() - t_fig:.1f}s", flush=True)
        zero_deltas = [np.eye(4) for _ in sw.parts]
        if recs:
            danger_pose = {j: math.radians(v) for j, v in recs[0]["pose"].items()}
            danger_deltas = sw._deltas(PoseKin(URDF, danger_pose))
        else:
            danger_pose, danger_deltas = {}, zero_deltas
        make_figure(figure_png, sw.parts, meshes, zero_deltas, danger_deltas,
                    danger_pose, recs[:10], ltab,
                    coverage=(f"模式 {payload.get('mode')}｜完成姿态 "
                              f"{payload.get('poses_done')}/{payload.get('n_plan')}"
                              f"｜零位基线 {payload.get('base_pairs')} 对 / "
                              f"{payload.get('base_vol', 0):.0f} mm³｜"
                              f"真·姿态诱发 {payload.get('n_new')} 对 / "
                              f"既有恶化 {payload.get('n_worsen')} 对"),
                    tol=args.fig_tol)
        print(f"    图：{figure_png}（{time.time() - t_fig:.1f}s）", flush=True)
        return 0

    # ---- 零位基线 ----
    print("  计算零位基线（真实零件、同一判定原语）…", flush=True)
    nb, bv = sw.zero_baseline()
    print(f"  零位基线（跨 link、全部实体口径）：{nb} 对 / {bv:.0f} mm³", flush=True)
    bridge = sw.authority_bridge()
    print(f"  与权威口径对账（val() 只看第一个实体）："
          f"{bridge['legacy_pairs']} 对 / {bridge['legacy_vol']:.0f} mm³"
          f"  ← 权威 189 对 / 160 339 mm³（含同 link 60 对 / 63 370 mm³）", flush=True)

    # ---- 采样 ----
    levels = [i / (levels_n - 1) for i in range(levels_n)]
    grid = sw.grid_poses(levels)
    lhs = sw.lhs_poses(lhs_n, seed=args.seed)
    presets = sw.preset_poses()
    plan = (grid + presets + lhs)
    # `--budget` 只算"基线之后的活儿"：冷启动（装配 + 基线 + 对账）约 90–150 s，
    # 若把它算进预算，小预算下会出现"还没开始采样就超时"的假故障。
    t_work = time.time()
    startup_s = t_work - t0
    _install_alarm(int(budget + HARD_BACKSTOP_EXTRA))
    sample_deadline = t_work + budget * args.sample_frac
    scan_deadline = t_work + budget
    print(f"  冷启动 {startup_s:.0f}s（装配 {sw.load_s:.0f}s + 基线/对账）", flush=True)
    print(f"  计划姿态 {len(plan)} 个（单关节 {len(grid)} + 预设 {len(presets)} + "
          f"LHS {len(lhs)}）；采样软预算 {budget * args.sample_frac:.0f}s，"
          f"首撞角扫描软预算 {budget * (1 - args.sample_frac):.0f}s", flush=True)

    all_events: List[Event] = []
    completed = True
    try:
        for idx, (tag, pose) in enumerate(plan, 1):
            if time.time() > sample_deadline:
                raise BudgetExceeded("采样软预算到点")
            if tag.startswith("grid:"):
                jn = tag[5:].split("=")[0]
                evs = sw.check_pose(pose, pair_ids=sw.joint_pairs[jn], tag=tag)
            elif tag.startswith("预设-"):
                evs = sw.check_pose(pose, tag=tag)
            else:
                evs = sw.check_pose(pose, tag=tag)
            all_events.extend(evs)
            if idx % 10 == 0 or idx == len(plan):
                avg = (sum(sw.pose_seconds) / max(len(sw.pose_seconds), 1))
                print(f"    姿态 {idx}/{len(plan)}  事件 {len(all_events)}  "
                      f"布尔 {sw.bool_calls}  均 {avg:.2f}s/姿态  "
                      f"已用 {time.time() - t0:.0f}s", flush=True)
    except (BudgetExceeded, TimeoutError) as exc:
        completed = False
        sw.notes.append(f"采样软预算中断：{exc}（已完成 {sw.poses_done}/{len(plan)} 姿态）")
        print(f"\n  [预算中断] {exc}  已完成 {sw.poses_done}/{len(plan)}", flush=True)

    print(f"  扫掠结束：完成姿态 {sw.poses_done}，事件 {len(all_events)}，"
          f"布尔 {sw.bool_calls} 次，用时 {time.time() - t0:.0f}s", flush=True)

    # ---- 逐关节首撞角 ----
    limit_table: List[Dict[str, Any]] = []
    if args.no_scan:
        sw.notes.append("已按 --no-scan 跳过首撞角扫描：第四节限位建议不可用")
    else:
        print("  逐关节首撞角扫描（粗扫 + 二分细化）…", flush=True)
        for jn in sw.joints:
            row: Dict[str, Any] = {"joint": jn}
            lo, hi = sw.kin0.limits(jn)
            row["urdf"] = (deg(lo), deg(hi))
            try:
                for key, d in (("pos", +1), ("neg", -1)):
                    r = first_hit_scan(sw, jn, d, coarse=args.scan_coarse,
                                       deadline=scan_deadline)
                    for src, dst in (("hit_new", "hit_new"), ("hit_new10", "hit_new10"),
                                     ("hit_any_coarse", "hit_any_coarse"),
                                     ("hit_worsen_coarse", "hit_worsen_coarse"),
                                     ("hit_mate_coarse", "hit_mate_coarse")):
                        v = r.get(src)
                        row[f"{dst}_{key}"] = None if v is None else deg(v)
                    row[f"reco_{key}"] = recommend_limit(r.get("hit_new"), r["limit"])
                    if r.get("worst") and "worst" not in row:
                        row["worst"] = r["worst"]
                    row.setdefault("detail", {})[key] = {
                        "reason": r.get("reason"),
                        "coarse_hits": r.get("coarse_hits"),
                        "coarse_first3": r.get("coarse_first3"),
                        "coarse_hit_angles_any": r.get("coarse_hit_angles_any"),
                        "limit_deg": deg(r["limit"]),
                    }
            except (BudgetExceeded, TimeoutError) as exc:
                completed = False
                row["error"] = str(exc)
                sw.notes.append(f"{jn} 首撞角扫描未完成：{exc}")
            limit_table.append(row)
            print(f"    {jn:22s} URDF {deg(lo):+6.1f}…{deg(hi):+6.1f}  "
                  f"新碰撞首撞(负/正) "
                  f"{row.get('hit_new_neg')} / {row.get('hit_new_pos')}  建议 "
                  f"{row.get('reco_neg')} / {row.get('reco_pos')}", flush=True)

    # ---- 汇总与落盘 ----
    summary = summarize(all_events)
    elapsed = time.time() - t0
    records = summary["records"]
    pose_avg = (sum(sw.pose_seconds) / max(len(sw.pose_seconds), 1))

    fingerprints = {
        str(p.relative_to(REPO)): md5_of(p) for p in
        (HERE / "skeleton.py", HERE / "assembly.py", HERE / "fitcheck.py",
         HERE / "preview.py", PLACEMENTS_JSON, URDF)
    }

    unverified: List[str] = []
    if not completed:
        unverified.append(
            f"扫掠**未跑完**：完成 {sw.poses_done}/{len(plan)} 个姿态（软预算 "
            f"{budget:.0f}s）。未覆盖的姿态里可能还有更严重的碰撞，"
            f"尤其 LHS 组合姿态。")
    if args.no_scan:
        unverified.append("首撞角扫描被 `--no-scan` 跳过，第四节限位建议不可用。")
    unverified += [
        "**同 link 内的 60 对（63 370 mm³）未扫掠**：它们刚性同步、相对位姿恒定，"
        "恒不可能成为姿态诱发碰撞（恒等式，非近似）。其中 47 对是 `tube × 同关节舵机`"
        "这类同 link 让位不足，属零位问题、应由几何让位解决，不是限位问题。",
        "**多实体零件盲区已在本脚本内修掉，但仓库其余脚本未修**："
        "`torso_upper__torso_frame` 有 3 个互不相连实体，`Workplane.val()` 只返回"
        "第一个（108 199 / 130 183 mm³，**17% 体积不可见**），`interference.py` /"
        "`assembly.py` / `audit_assembly.py` 同样受影响。本脚本用 Compound 包全部实体，"
        "因此本报告基线与权威口径有可对账的差异（见第一节对账行）。",
        "**自碰撞只覆盖刚性零件对**：不考虑线缆、软垫、打印公差（±0.2–0.5 mm）与"
        "装配偏差；建议限位已留 max(2°, 10%) 余量但未做公差堆叠分析。",
        "**舵机与电子件是占位实体**（含舵盘 Φ20×4.0、凸台、花键、副轴），"
        "真实外形有圆角、线缆出口与接插件；占位体偏保守（体积≥实物）。",
        "**未建模机械硬止点与地面**：URDF 限位即为扫掠边界，实际还有舵机内部"
        "限位与足底-地面接触，真机可达角度只会更小。",
        "**单关节首撞角 ≠ 组合安全**：同时驱动多个关节可能在更小角度就撞。"
        "本报告的 LHS/预设姿态是组合侧的抽样，不是完备证明。"
        "首次命中角也未必单调——本脚本记录全行程粗扫命中格数（JSON 的 "
        "`coarse_hit_angles_any`）；若某关节「撞了又安全」，限位建议按首次命中取。",
        "**`首撞角(恶化)` 与 `首撞角(配合面)` 只有粗扫分辨率（一个粗扫格，"
        "近零位处最密约 0.4–7.5° 视关节行程而定）**，未做二分细化；"
        "只有驱动限位建议的「新碰撞首撞角」细化到 0.5°。",
        "**未做动力学**：碰撞判定是纯几何；高速运动下的柔性变形、回弹未考虑。",
        "**`fork__J` 的归属是据 `preview.py` 文档与 `limb_fork` 几何语义判定的**"
        "（叉螺栓锁舵盘→随子级转）。`assembly.build_assembly()` 把 `fork__J` 放在"
        "父级关节系，只在零位与子级等价。本脚本按**子 link** 归属（与预览一致），"
        "若最终认定叉应随父级，则所有含 `fork__*` 的姿态结论需重跑。",
    ]

    payload = {
        "mode": mode, "elapsed_s": elapsed, "completed": completed,
        "startup_s": startup_s, "budget_s": budget,
        "n_parts": len(sw.parts), "n_load_bad": len(sw.load_bad),
        "load_bad": sw.load_bad,
        "n_links": len(sw.kin0.world), "n_joints": len(sw.joints),
        "n_pairs": len(sw.pairs),
        "n_same_link_pairs": len(sw.parts) * (len(sw.parts) - 1) // 2 - len(sw.pairs),
        "base_pairs": nb, "base_vol": bv,
        "authority_bridge": bridge,
        "levels": levels_n, "lhs_n": lhs_n, "seed": args.seed,
        "n_presets": len(presets),
        "scan_coarse": args.scan_coarse, "scan_tol": 0.5,
        "poses_done": sw.poses_done, "n_plan": len(plan),
        "pose_avg_s": pose_avg, "bool_calls": sw.bool_calls,
        "place_calls": sw.place_calls,
        "n_events": summary["n_events"],
        "n_new": summary["n_new"], "n_worsen": summary["n_worsen"],
        "records": [{k: v for k, v in r.items() if k != "pose"} | {
            "pose": {j: deg(x) for j, x in r["pose"].items() if abs(deg(x)) >= 0.5}}
            for r in records],
        "limit_table": limit_table,
        "fingerprints": fingerprints,
        "notes": sw.notes, "unverified": unverified,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                                      default=str), encoding="utf-8")
    write_markdown(report_md, payload)
    print(f"\n  报告：{report_md}\n  JSON：{report_json}", flush=True)

    if not args.no_figure:
        print("  出图（matplotlib，正交投影 + painter 算法）…", flush=True)
        try:
            meshes = []
            t_tes = time.time()
            for p in sw.parts:
                meshes.append(_tessellate(p.shape0, args.fig_tol))
            ntri = int(sum(len(t) for _, t in meshes))
            print(f"    三角面 {ntri:,}（容差 {args.fig_tol} mm，"
                  f"网格化 {time.time() - t_tes:.1f}s）", flush=True)
            zero_deltas = [np.eye(4) for _ in sw.parts]
            # 危险姿态 = 新增体积最大的姿态（优先"真·姿态诱发"，无则退化为恶化）
            if records:
                worst = records[0]
                dkin = PoseKin(URDF, {j: math.radians(v)
                                      for j, v in worst["pose"].items()})
                danger_deltas = sw._deltas(dkin)
                danger_pose = worst["pose"]
            else:
                danger_deltas = zero_deltas
                danger_pose = {}
            make_figure(figure_png, sw.parts, meshes, zero_deltas, danger_deltas,
                        danger_pose, records[:10], limit_table,
                        coverage=(f"模式 {mode}｜完成姿态 {sw.poses_done}/{len(plan)}"
                                  f"｜零位基线 {nb} 对 / {bv:.0f} mm³｜"
                                  f"真·姿态诱发 {summary['n_new']} 对 / "
                                  f"既有恶化 {summary['n_worsen']} 对"),
                        tol=args.fig_tol)
            print(f"    图：{figure_png}", flush=True)
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"    [WARN] 出图失败：{exc}", flush=True)

    print(f"\n完成：姿态 {sw.poses_done}/{len(plan)}，事件 {summary['n_events']} 个，"
          f"真·姿态诱发 {summary['n_new']} 对 / 恶化 {summary['n_worsen']} 对，"
          f"用时 {elapsed:.0f}s", flush=True)
    if records:
        print("Top10 姿态诱发新增碰撞（已扣零位基线）：", flush=True)
        for k, r in enumerate(records[:10], 1):
            flag = "配合面" if (r["mate"] or r["same_joint"]) else "结构"
            print(f"  {k:2d}. [{r['kind']}] {r['a']} ↔ {r['b']}: "
                  f"新增 {r['max_excess']:.0f} mm³ （零位 {r['base']:.0f}）"
                  f"[{flag}] {r['tag']}", flush=True)
    _clear_alarm()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BudgetExceeded as exc:  # 硬超时兜底
        print(f"[FATAL] {exc}", file=sys.stderr)
        raise SystemExit(3)
