#!/usr/bin/env python3
"""成对解剖：把干涉体反变换回**零件自己的局部坐标系**，直接给出可用的切口盒。

**为什么需要它**：`audit_assembly.py` 只告诉你"A 与 B 相交 3582 mm³（重合率 34%）"，
但修的时候要回答的是另一个问题——"在 A 的建模坐标系里，该切掉哪一块？"。
过去靠肉眼估，切口不是切穿了承力筋就是留了 0.3 mm 残料。

原理（关键事实，见 assembly.py `_place`）：
    零件都是先在**自己的局部坐标系**里建模（`skeleton.py` 的 `sk.build(...)`），
    再用 `_place(shape, M)` 刚体变换到世界。M 的取法有三种：
      - 关节类零件 `servo__/cage__/fork__/outrigger__ <jname>` → `kin.joint_world(jname)`
      - link 类零件 `<link>__limb_tube/gripper_jaw/cluster_horn_arm` → `kin.world[link]`
      - 绝对定位件（电子件、背板等）→ 单位矩阵（局部系 = 世界系）
    所以"世界坐标系里的干涉体"乘上 `M_A⁻¹`，就是 **A 局部坐标系里的干涉体**，
    取其轴对齐包围盒即可直接写成一个切口盒（AABB 略保守，但方向绝不错）。

用法：
    .venv-cad/bin/python design/cad/pair_inspect.py --errors        # 全部 ❌ 摆放错误
    .venv-cad/bin/python design/cad/pair_inspect.py --top 8          # 相交体积前 8 对
    .venv-cad/bin/python design/cad/pair_inspect.py \
        --pair "fork__left_elbow_pitch|servo__left_gripper"          # 指定一对
    .venv-cad/bin/python design/cad/pair_inspect.py --errors --pad 1.5 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import cadquery as cq  # noqa: E402
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common  # noqa: E402
from OCP.gp import gp_Trsf  # noqa: E402

import assembly as A  # noqa: E402
from fitcheck import bbox_of, boxes_overlap, verdict  # noqa: E402
from kit import apply_trsf  # noqa: E402

# 以关节名为后缀、用 `kin.joint_world()` 定位的零件族
JOINT_KINDS = ("servo", "cage", "fork", "outrigger")


def inv_rigid(m: A.Mat) -> A.Mat:
    """刚体变换的逆：R^T 与 -R^T·t（比通用求逆稳，且这些矩阵恒为正交阵）。"""
    r = [[m[i][j] for j in range(3)] for i in range(3)]
    t = [m[i][3] for i in range(3)]
    rt = [[r[j][i] for j in range(3)] for i in range(3)]
    tt = [-sum(rt[i][k] * t[k] for k in range(3)) for i in range(3)]
    return [[rt[0][0], rt[0][1], rt[0][2], tt[0]],
            [rt[1][0], rt[1][1], rt[1][2], tt[1]],
            [rt[2][0], rt[2][1], rt[2][2], tt[2]],
            [0.0, 0.0, 0.0, 1.0]]


def trsf_of(m: A.Mat) -> gp_Trsf:
    r = A.rot3(m)
    tr = gp_Trsf()
    tr.SetValues(r[0][0], r[0][1], r[0][2], m[0][3],
                 r[1][0], r[1][1], r[1][2], m[1][3],
                 r[2][0], r[2][1], r[2][2], m[2][3])
    return tr


def frame_of(name: str, kin: A.Kin) -> Tuple[Optional[A.Mat], str]:
    """零件名 → (定位矩阵, 说明)。返回 None 表示"绝对定位/未识别"（局部系=世界系）。

    命名约定（见 assembly.py 的 add(...) 调用点）有两族，**必须先判 link 族**：
      - `<link>__<part>`（limb_tube / gripper_jaw / cluster_horn_arm / foot_plate …）
        → `_place(..., kin.world[link])`，link 是 `__` **前**那一截
      - `<kind>__<joint>`（servo / cage / fork / outrigger）
        → `_place(..., kin.joint_world(joint))`，joint 是 `__` 后那一截
      - 其余（elec__*、backpack_plate 等）绝对定位，局部系 = 世界系
    """
    head, _, tail = name.partition("__")
    if head in kin.world:
        return kin.world[head], f"world[{head}]"
    if head in JOINT_KINDS and tail in kin.joints:
        return kin.joint_world(tail), f"joint_world({tail})"
    if tail and tail in kin.world:  # 兜底：历史命名的反序写法
        return kin.world[tail], f"world[{tail}]"
    return None, "绝对定位（局部系 = 世界系）"


def box_of_bbox(bb: Any, pad: float) -> Dict[str, Any]:
    """轴对齐包围盒 → `kit.box(l, w, h, at=(cx, cy, z_bottom))` 参数（at 的 z 是**底面**）。"""
    l = (bb.xmax - bb.xmin) + 2 * pad
    w = (bb.ymax - bb.ymin) + 2 * pad
    h = (bb.zmax - bb.zmin) + 2 * pad
    return {"l": round(l, 2), "w": round(w, 2), "h": round(h, 2), "pad": pad,
            "at": (round((bb.xmin + bb.xmax) / 2.0, 2),
                   round((bb.ymin + bb.ymax) / 2.0, 2),
                   round(bb.zmin - pad, 2)),
            "expr": (f"box({l:.2f}, {w:.2f}, {h:.2f}, at="
                     f"({(bb.xmin + bb.xmax) / 2.0:.2f}, "
                     f"{(bb.ymin + bb.ymax) / 2.0:.2f}, "
                     f"{bb.zmin - pad:.2f}))")}


def common_shape(a: cq.Workplane, b: cq.Workplane):
    op = BRepAlgoAPI_Common(a.val().wrapped, b.val().wrapped)
    op.Build()
    return op.Shape() if op.IsDone() else None


def inspect(pair: Tuple[str, str], shapes: Dict[str, cq.Workplane],
            kin: A.Kin, pad: float) -> Dict[str, Any]:
    na, nb = pair
    sa, sb = shapes[na], shapes[nb]
    ma, why_a = frame_of(na, kin)
    mb, why_b = frame_of(nb, kin)
    common = common_shape(sa, sb)

    out: Dict[str, Any] = {"a": na, "b": nb, "a_frame": why_a, "b_frame": why_b,
                           "bbox_a": _bb(bbox_of(sa)), "bbox_b": _bb(bbox_of(sb))}
    if common is None or common.IsNull():
        out["note"] = "无公共体（可能仅面/边接触）"
        return out

    ia = _local_box(common, ma, pad)
    ib = _local_box(common, mb, pad)
    out["cut_in_a"] = ia
    out["cut_in_b"] = ib
    return out


def _bb(bb: Any) -> List[float]:
    return [round(bb.xmin, 2), round(bb.ymin, 2), round(bb.zmin, 2),
            round(bb.xmax, 2), round(bb.ymax, 2), round(bb.zmax, 2)]


def _local_box(common: Any, m: Optional[A.Mat], pad: float) -> Dict[str, Any]:
    """把世界系的公共体搬到局部系，取 AABB 并换算成 `kit.box` 参数。"""
    wp = _wrap(common)
    if m is not None:
        wp = apply_trsf(wp, trsf_of(inv_rigid(m)))
    return box_of_bbox(wp.val().BoundingBox(), pad)


def _wrap(topo: Any) -> cq.Workplane:
    """把裸 TopoDS_Shape 包成 Workplane（便于统一取 BoundingBox / 变换）。"""
    return cq.Workplane("XY").newObject([cq.Shape.cast(topo)])


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="成对解剖：输出可直接使用的局部切口盒")
    ap.add_argument("--pair", action="append", default=[],
                    help='指定一对，形如 "fork__left_elbow_pitch|servo__left_gripper"（可重复）')
    ap.add_argument("--errors", action="store_true", help="自动取全部 ❌ 摆放错误 对")
    ap.add_argument("--top", type=int, default=0, help="自动取相交体积前 N 对")
    ap.add_argument("--pad", type=float, default=1.0, help="切口盒四周外扩余量 mm（默认 1.0）")
    ap.add_argument("--json", action="store_true", help="同时输出 JSON 到 out/pair_inspect.json")
    args = ap.parse_args(argv)

    kin = A.Kin(A.DESIGN / "atri.urdf")
    placements = json.loads((A.DESIGN / "placements.json").read_text(encoding="utf-8"))
    items, log = A.build_assembly(kin, placements)
    bad = [l for l in log if not l.get("ok")]
    print(f"装配件 {len(items)} 个（失败 {len(bad)}）")
    for b in bad[:5]:
        print(f"  [ERR] {b['name']}: {b.get('err')}")

    shapes = dict(items)
    pairs: List[Tuple[str, str]] = []
    for spec in args.pair:
        a, _, b = spec.partition("|")
        if a not in shapes or b not in shapes:
            miss = [n for n in (a, b) if n not in shapes]
            print(f"[ERR] 零件名不存在：{miss}")
            for m in miss:  # 帮忙找近似名
                near = [n for n in shapes if m.split("__")[-1][:6] in n][:6]
                if near:
                    print(f"      近似：{near}")
            return 2
        pairs.append((a, b))

    if args.errors or args.top:
        names = [n for n, _ in items]
        boxes = [bbox_of(w) for _, w in items]
        vols = [w.val().Volume() for w in shapes.values()]
        found: List[Tuple[float, str, str, str]] = []
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if not boxes_overlap(boxes[i], boxes[j]):
                    continue
                com = common_shape(items[i][1], items[j][1])
                if com is None or com.IsNull():
                    continue
                from fitcheck import common_volume
                v = common_volume(items[i][1], items[j][1])
                if v <= 1.0:
                    continue
                frac = v / max(min(vols[i], vols[j]), 1e-9)
                found.append((v, names[i], names[j], verdict(v, frac)))
        found.sort(key=lambda t: -t[0])
        sel = [t for t in found if t[3].startswith("❌")] if args.errors else found[:args.top]
        pairs += [(a, b) for _, a, b, _ in sel]
        print(f"自动选对：{len(sel)} 对"
              f"（{'全部摆放错误' if args.errors else f'前 {args.top} 大'}）\n")

    seen = set()
    results: List[Dict[str, Any]] = []
    for pr in pairs:
        key = tuple(sorted(pr))
        if key in seen:
            continue
        seen.add(key)
        res = inspect(pr, shapes, kin, args.pad)
        results.append(res)
        _print_pair(res)
    if args.json:
        p = A.OUT / "pair_inspect.json"
        p.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 {p}")
    return 0


def _print_pair(r: Dict[str, Any]) -> None:
    print("=" * 78)
    print(f"A = {r['a']}   ←  {r['a_frame']}")
    print(f"B = {r['b']}   ←  {r['b_frame']}")
    print(f"  世界包围盒 A: {r['bbox_a']}")
    print(f"  世界包围盒 B: {r['bbox_b']}")
    if "note" in r:
        print(f"  {r['note']}")
        return
    for tag, key in (("A", "cut_in_a"), ("B", "cut_in_b")):
        c = r[key]
        print(f"  ▶ 在 {tag} 的局部坐标系里切掉（四周外扩 {c['pad']:.2f} mm）：")
        print(f"      {c['expr']}")
        print(f"      尺寸 {c['l']} × {c['w']} × {c['h']} mm，"
              f"中心 (x,y)=({c['at'][0]}, {c['at'][1]})，底面 z={c['at'][2]}")


if __name__ == "__main__":
    raise SystemExit(main())
