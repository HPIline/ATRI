"""装配体检：穿模（实体相交体积）+ 未衔接（连通分量 / 孤件）。

为什么需要它：
    交互预览里"看起来穿模"是不可复现的主观判断。本脚本把两件事变成数字——
    ① 每对零件的**相交体积**（>阈值为穿模）；
    ② 零件间的**最小距离图**，连通分量 > 1 说明有零件没接上（未衔接）。

用法：
    .venv-cad/bin/python design/cad/audit_assembly.py            # 全机
    .venv-cad/bin/python design/cad/audit_assembly.py --tol 0.5  # 改接触判据
    .venv-cad/bin/python design/cad/audit_assembly.py --iso      # 只看孤件（最快的体检）
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import cadquery as cq
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

import assembly as A


def common_volume(a: cq.Workplane, b: cq.Workplane) -> float:
    """两实体的相交体积（mm³）。"""
    op = BRepAlgoAPI_Common(a.val().wrapped, b.val().wrapped)
    op.Build()
    if not op.IsDone():
        return 0.0
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(op.Shape(), props)
    return abs(props.Mass())


def distance(a: cq.Workplane, b: cq.Workplane) -> float:
    """两实体的最小距离（mm）。"""
    d = BRepExtrema_DistShapeShape(a.val().wrapped, b.val().wrapped)
    d.Perform()
    return d.Value() if d.IsDone() else 1e9


def bbox_of(wp: cq.Workplane):
    return wp.val().BoundingBox()


def boxes_overlap(b1, b2, pad: float = 0.0) -> bool:
    return not (b1.xmax + pad < b2.xmin or b2.xmax + pad < b1.xmin or
                b1.ymax + pad < b2.ymin or b2.ymax + pad < b1.ymin or
                b1.zmax + pad < b2.zmin or b2.zmax + pad < b1.zmin)


def kind_of(name: str) -> str:
    head = name.split("__")[0]
    if head in ("servo",):
        return "servo"
    return name.split("__")[0]


def main(argv: Sequence[str]) -> int:
    tol = 0.6
    if "--tol" in argv:
        tol = float(argv[list(argv).index("--tol") + 1])
    iso_only = "--iso" in argv
    top_n = 25
    if "--top" in argv:
        top_n = int(argv[list(argv).index("--top") + 1])

    kin = A.Kin(A.DESIGN / "atri.urdf")
    placements = json.loads((A.DESIGN / "placements.json").read_text(encoding="utf-8"))
    items, log = A.build_assembly(kin, placements)
    bad = [l for l in log if not l.get("ok")]
    print(f"装配件 {len(items)} 个（失败 {len(bad)}）")
    for b in bad:
        print(f"  [ERR] {b['name']}: {b.get('err')}")

    names = [n for n, _ in items]
    shapes = [w for _, w in items]
    boxes = [bbox_of(w) for w in shapes]

    # ---- ⓪ 关节轴对齐：每个舵机的"沿轴厚度"必须落在该关节的轴上 ----
    #     舵机包络 45.2(长) × 43.1(沿轴含凸台/花键/副轴) × 24.7(宽)；
    #     若沿关节轴方向的尺寸不是 43.1，说明这个关节的舵机转向错了 90°。
    item_map = dict(items)
    mis = []
    for j, sc in A.JOINT_SCHEME.items():
        nm = f"servo__{j}"
        if nm not in item_map:
            continue
        b = item_map[nm].val().BoundingBox()
        dims = (b.xlen, b.ylen, b.zlen)
        w = kin.axis_world(j)
        idx = max(range(3), key=lambda i: abs(w[i]))
        if abs(dims[idx] - 43.1) > 1.0:
            mis.append((j, sc["shaft"], sc["parent"],
                        [round(x, 1) for x in dims]))
    print(f"\n## 关节轴对齐\n\n舵机轴向与关节轴一致："
          f"**{len(A.JOINT_SCHEME) - len(mis)}/{len(A.JOINT_SCHEME)}**")
    for j, sh, pa, dims in mis:
        print(f"  ✗ `{j}` shaft={sh} parent={pa} 包络 {dims}")

    # ---- ① 穿模：包围盒相交 → 精确求交体积 ----
    #     关键指标不是"体积"而是**重合率** = 交集体积 / 较小件自身体积：
    #        几个 mm³  = 让位不足（改尺寸/倒角可解）
    #        >30%      = **摆放错误**（两个零件被指派到同一块空间，改尺寸无解）
    #     这个区分很重要：光看总体积会把"摆放错误"和"配合差"混成一锅。
    vols = [w.val().Volume() for w in shapes]
    inter: List[Tuple[str, str, float, float, float]] = []
    if not iso_only:
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if not boxes_overlap(boxes[i], boxes[j]):
                    continue
                v = common_volume(shapes[i], shapes[j])
                if v > 1.0:
                    smaller = max(min(vols[i], vols[j]), 1e-9)
                    inter.append((names[i], names[j], v, v / smaller, smaller))
    inter.sort(key=lambda t: -t[2])

    def verdict(frac: float, v: float) -> str:
        if frac >= 0.30 or v >= 5000.0:
            return "❌ 摆放错误"
        if frac >= 0.05 or v >= 500.0:
            return "⚠️ 让位不足"
        return "· 局部干涉"

    # ---- ② 未衔接：最小距离图 + 连通分量 ----
    adj: Dict[str, List[str]] = defaultdict(list)
    pairs = 0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if not boxes_overlap(boxes[i], boxes[j], pad=tol + 1.0):
                continue
            pairs += 1
            if distance(shapes[i], shapes[j]) <= tol:
                adj[names[i]].append(names[j])
                adj[names[j]].append(names[i])

    seen, comps = set(), []
    for n in names:
        if n in seen:
            continue
        stack, comp = [n], []
        seen.add(n)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nb in adj[cur]:
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        comps.append(sorted(comp))
    comps.sort(key=len, reverse=True)

    # ---- ③ 孤件：与任何零件的距离都 > tol ----
    iso = []
    for i, n in enumerate(names):
        if not adj[n]:
            iso.append(n)

    # ---- 报告 ----
    print(f"\n## 穿模（相交体积 > 1 mm³，共 {len(inter)} 对）\n")
    if inter:
        n_bad = sum(1 for _, _, v, f, _ in inter if verdict(f, v) == "❌ 摆放错误")
        n_fit = sum(1 for _, _, v, f, _ in inter if verdict(f, v) == "⚠️ 让位不足")
        n_min = len(inter) - n_bad - n_fit
        print(f"**性质判定**：摆放错误 **{n_bad}** 对 ｜ 让位不足 **{n_fit}** 对 ｜ "
              f"局部干涉 {n_min} 对\n")
        print("| # | 件 A | 件 B | 相交 mm³ | 重合率 | 判定 |")
        print("|---|---|---|---|---|---|")
        for k, (a, b, v, f, _sm) in enumerate(inter[:top_n], 1):
            print(f"| {k} | `{a}` | `{b}` | {v:.0f} | {f * 100:.0f}% | {verdict(f, v)} |")
        tot = sum(v for _, _, v, _f, _s in inter)
        print(f"\n合计相交体积 **{tot:.0f} mm³**；"
              f"按零件统计前 8（含各自自身体积占比）：")
        per: Dict[str, float] = defaultdict(float)
        per_own: Dict[str, float] = {}
        for a, b, v, _f, _s in inter:
            per[a] += v
            per[b] += v
        for i, n in enumerate(names):
            per_own[n] = vols[i]
        for n, v in sorted(per.items(), key=lambda kv: -kv[1])[:8]:
            own = per_own.get(n, 1.0)
            print(f"  - `{n}`：{v:.0f} mm³（自身 {own:.0f} mm³，"
                  f"被侵占 {100 * v / max(own, 1e-9):.0f}%）")
        # 体积分布直方图：看"少数大错"还是"大量小差"
        ranges = [(10000.0, 1e9, "≥10 000"),
                  (5000.0, 10000.0, "5 000–10 000"),
                  (1000.0, 5000.0, "1 000–5 000"),
                  (100.0, 1000.0, "100–1 000"),
                  (1.0, 100.0, "<100")]
        print("\n体积分布（用于区分「少数摆错」与「普遍配合差」）：")
        for lo, hi, tag in ranges:
            c = sum(1 for _, _, v, _f, _s in inter if lo <= v < hi)
            print(f"  - {tag:>12s} mm³：{c} 对")
    else:
        print("（无）")

    print(f"\n## 未衔接（接触判据 ≤ {tol} mm）\n")
    print(f"距离计算 {pairs} 对；**连通分量 {len(comps)} 个**")
    for k, c in enumerate(comps[:6], 1):
        head = ", ".join(f"`{x}`" for x in c[:6])
        more = f" …（共 {len(c)} 件）" if len(c) > 6 else ""
        print(f"  {k}. {head}{more}")
    if iso:
        print(f"\n**孤件 {len(iso)} 个**（与所有零件距离 > {tol} mm）：")
        for n in iso:
            b = bbox_of(dict(items)[n])
            print(f"  - `{n}`  包络 {b.xlen:.0f}×{b.ylen:.0f}×{b.zlen:.0f}  "
                  f"中心 ({((b.xmin+b.xmax)/2):.0f}, {((b.ymin+b.ymax)/2):.0f}, "
                  f"{((b.zmin+b.zmax)/2):.0f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
