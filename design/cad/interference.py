#!/usr/bin/env python3
"""全机干涉普查：用 OpenCASCADE 布尔求交算**真实干涉体积**，而不是靠肉眼看渲染图。

为什么不用人眼：
    80 个零件在零位下有 3160 个组合，靠旋转缩放逐个看既慢又漏；
    而"有没有撞"是个可以用布尔运算给出**数值**的问题。
    本脚本先按包围盒粗筛，再对候选对做精确求交，输出干涉体积（mm³）。

判定口径：
    > 100 mm³   严重：结构件互穿或舵机被包住，必须改图
    10–100 mm³  轻微：多为倒角/圆角处的擦碰或公差不足，需确认
    < 10 mm³    视为接触（打印件公差 0.2–0.5 mm，这个量级没有工程意义）

用法：
    .venv-cad/bin/python design/cad/interference.py --all
产出：
    out/interference_report.md   干涉表（按体积降序）+ 归类结论
    out/interference.json        机器可读
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cadquery as cq

import assembly as A
import render3d as R

OUT = HERE / "out"

SEVERE_MM3 = 100.0      # 严重干涉阈值
MINOR_MM3 = 10.0        # 轻微干涉阈值（低于此视为接触）

# 组合归类：给报告分组用（键是零件名前缀特征）
GROUP_RULES: List[Tuple[str, str]] = [
    ("servo__", "舵机（占位体）"),
    ("cage__", "关节笼"),
    ("fork__", "连杆叉"),
    ("elec__", "电子件（占位体）"),
]


def group_of(name: str) -> str:
    for prefix, label in GROUP_RULES:
        if name.startswith(prefix):
            return label
    if name.endswith("compact_adapter"):
        return "紧凑转接块"
    if "limb_tube" in name:
        return "连杆管"
    if name.startswith("head"):
        return "头壳"
    if name.startswith("torso"):
        return "躯干框架"
    if name.startswith("pelvis"):
        return "骨盆框架"
    if "foot" in name:
        return "足板"
    if "gripper" in name:
        return "夹爪"
    if "tray" in name or "deck" in name or "pdb" in name:
        return "集成件"
    return "其它"


def bbox_overlap_volume(a: cq.Shape, b: cq.Shape) -> float:
    ba, bb = a.BoundingBox(), b.BoundingBox()
    dx = min(ba.xmax, bb.xmax) - max(ba.xmin, bb.xmin)
    dy = min(ba.ymax, bb.ymax) - max(ba.ymin, bb.ymin)
    dz = min(ba.zmax, bb.zmax) - max(ba.zmin, bb.zmin)
    if dx <= 0 or dy <= 0 or dz <= 0:
        return 0.0
    return dx * dy * dz


def survey(items: Sequence[Tuple[str, cq.Workplane]], min_report: float
           ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    shapes: List[Tuple[str, cq.Shape]] = [(n, w.val()) for n, w in items]
    n = len(shapes)
    pairs: List[Dict[str, Any]] = []
    checked = 0
    for i in range(n):
        ni, si = shapes[i]
        for j in range(i + 1, n):
            nj, sj = shapes[j]
            if bbox_overlap_volume(si, sj) <= 0.0:
                continue
            checked += 1
            try:
                common = si.intersect(sj)
                vol = float(common.Volume()) if common is not None else 0.0
            except Exception:  # noqa: BLE001  OCC 偶发失败，记为待人工确认
                pairs.append({"a": ni, "b": nj, "volume_mm3": None,
                              "group": f"{group_of(ni)} × {group_of(nj)}",
                              "note": "布尔求交失败，需人工确认"})
                continue
            if vol <= min_report:
                continue
            pairs.append({
                "a": ni, "b": nj,
                "group": f"{group_of(ni)} × {group_of(nj)}",
                "volume_mm3": round(vol, 2),
                "severity": ("严重" if vol > SEVERE_MM3 else
                             "轻微" if vol > MINOR_MM3 else "接触"),
            })
    pairs.sort(key=lambda p: -(p["volume_mm3"] or 0))
    stats = {
        "parts": n,
        "bbox_candidates": checked,
        "reported": len(pairs),
        "severe": sum(1 for p in pairs if p["severity"] == "严重"),
        "minor": sum(1 for p in pairs if p["severity"] == "轻微"),
        "touch": sum(1 for p in pairs if p["severity"] == "接触"),
        "failed": sum(1 for p in pairs if p["volume_mm3"] is None),
    }
    return pairs, stats


def suggest(p: Dict[str, Any]) -> str:
    """给出可执行的修改方向（不是泛泛而谈）。"""
    g = p["group"]
    v = p["volume_mm3"]
    if "舵机" in g and ("关节笼" in g or "转接块" in g):
        return "舵机腔净空不足：把腔体加大到 25.2（宽向）/ 46.0（长向），或检查阵列偏移"
    if "舵机" in g and "连杆叉" in g:
        return "叉臂侵入舵机：把臂外移或减小臂宽；检查舵机轴向偏置 6.5 mm 是否用对"
    if "连杆管" in g and ("关节笼" in g or "连杆叉" in g):
        return "插接段干涉：芯棒与管内孔应留单边 0.1；检查插入深度与管长"
    if "电子件" in g:
        return "舱内净空不足：调整电子件高度或托盘位置（注意躯干件整体 +17 mm 的偏移）"
    if "关节笼" in g and "关节笼" in g:
        return "相邻关节笼相碰：髋/肩簇轴线间距仅 19.6 mm，需减小笼体包络或改分件"
    if "骨盆" in g or "躯干" in g:
        return "大件与其它件相碰：检查侧翼/pylon 的伸出量与接口位置"
    if v is not None and v < MINOR_MM3:
        return "接触量级，通常是配合面贴合，可接受"
    return "需人工确认"


def write_report(pairs: List[Dict[str, Any]], stats: Dict[str, Any],
                 path: Path) -> None:
    sev = [p for p in pairs if p["severity"] == "严重"]
    minor = [p for p in pairs if p["severity"] == "轻微"]
    touch = [p for p in pairs if p["severity"] == "接触"]
    fail = [p for p in pairs if p["volume_mm3"] is None]

    def table(rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return "（无）\n"
        out = ["| # | 零件 A | 零件 B | 类别 | 干涉体积 (mm³) | 处理方向 |",
               "|---|---|---|---|---|---|"]
        for k, p in enumerate(rows, 1):
            vol = "求交失败" if p["volume_mm3"] is None else f"{p['volume_mm3']:.1f}"
            out.append(f"| {k} | `{p['a']}` | `{p['b']}` | {p['group']} | "
                       f"**{vol}** | {suggest(p)} |")
        return "\n".join(out) + "\n"

    # 按类别统计
    by_group: Dict[str, int] = {}
    for p in sev + minor:
        by_group[p["group"]] = by_group.get(p["group"], 0) + 1
    group_rows = "\n".join(
        f"| {g} | {c} |" for g, c in
        sorted(by_group.items(), key=lambda kv: -kv[1]))

    md = f"""# 全机干涉普查报告（零位姿态）

> 生成：`design/cad/interference.py`（OpenCASCADE 布尔求交）。
> 判定口径：**> 100 mm³ 严重 / 10–100 mm³ 轻微 / < 10 mm³ 视为接触**。
> 打印件配合公差为 0.2–0.5 mm，低于 10 mm³ 的"干涉"没有工程意义。

## 一、汇总

| 项 | 值 |
|---|---|
| 零件数 | {stats['parts']} |
| 包围盒粗筛出的候选对 | {stats['bbox_candidates']} |
| **严重干涉（>100 mm³）** | **{stats['severe']}** |
| 轻微干涉（10–100 mm³） | {stats['minor']} |
| 接触量级（<10 mm³） | {stats['touch']} |
| 布尔求交失败（需人工确认） | {stats['failed']} |

### 按类别分布（严重 + 轻微）

| 类别组合 | 对数 |
|---|---|
{group_rows if group_rows else "| （无） | 0 |"}

## 二、严重干涉（必须改图）

{table(sev)}

## 三、轻微干涉（需确认，多数为倒角/公差问题）

{table(minor)}

## 四、接触量级（可接受，仅计数）

{len(touch)} 对，体积均 < {MINOR_MM3:.0f} mm³，属配合面贴合或打印公差范围，逐条列出无意义。

## 五、求交失败（OCC 未返回结果）

{table(fail)}

## 六、口径说明

1. 干涉是**零位姿态**下的静态结果；关节运动包络（踝 ±40°、膝 0–90°、髋 ±60°）
   需要扫掠检查，本脚本不做——见"下一步"。
2. 舵机与电子件用的是**占位长方体**（真实外形有圆角、线缆出口、接插件），
   所以"舵机 × 结构件"的轻微干涉要按占位体的保守性打折看；
   但"严重"级别的互穿在占位体上就已经成立，真实件只会更糟。
3. 本报告不替代 SolidWorks 的干涉检查：SolidWorks 会在**装配约束**下检查，
   能抓到本脚本看不到的"运动过程中相碰"。
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="全机干涉普查")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--min", type=float, default=MINOR_MM3,
                    help="低于该体积不列入报告（默认 10 mm³）")
    args = ap.parse_args(argv)

    kin = A.Kin(A.DESIGN / "atri.urdf")
    placements = json.loads(
        (A.DESIGN / "placements.json").read_text(encoding="utf-8"))
    items, log = A.build_assembly(kin, placements)
    bad = [l for l in log if not l.get("ok")]
    print(f"装配件 {len(items)} 个" + (f"（{len(bad)} 个失败）" if bad else ""))
    print("开始布尔求交（先包围盒粗筛，再精确求交）…")

    pairs, stats = survey(items, min_report=args.min)
    write_report(pairs, stats, OUT / "interference_report.md")
    json.dump({"stats": stats, "pairs": pairs},
              (OUT / "interference.json").open("w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"  严重 {stats['severe']} / 轻微 {stats['minor']} / "
          f"接触 {stats['touch']} / 求交失败 {stats['failed']}")
    for p in pairs[:10]:
        v = "失败" if p["volume_mm3"] is None else f"{p['volume_mm3']:.1f} mm³"
        print(f"  [{p['severity']}] {p['a']} × {p['b']}: {v}")
    print(f"\n报告: {OUT / 'interference_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
