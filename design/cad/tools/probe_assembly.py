"""装配体探针：把 STEP 里的每个实体按体积/包络列出来，用于识别"谁是谁"。

用途：在厂商整机装配体里定位舵机实例与螺钉实例，
再判断**螺钉穿进了哪个孔**——这是接口语义的最终裁判。

    .venv-cad/bin/python design/cad/tools/probe_assembly.py <step> [--min-volume 100]
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import cadquery as cq


def solids_of(shape):
    if hasattr(shape, "Solids"):
        return list(shape.Solids())
    return []


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = Path(argv[1])
    min_vol = 0.0
    if "--min-volume" in argv:
        min_vol = float(argv[argv.index("--min-volume") + 1])

    shape = cq.importers.importStep(str(path)).val()
    sols = solids_of(shape)
    print(f"# {path.name}: {len(sols)} 个实体")

    rows = []
    for i, s in enumerate(sols):
        bb = s.BoundingBox()
        rows.append({
            "i": i,
            "vol": s.Volume(),
            "dims": (bb.xlen, bb.ylen, bb.zlen),
            "ctr": ((bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2,
                    (bb.zmin + bb.zmax) / 2),
            "bbox": (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax),
        })

    # 按体积分组（同一零件在装配体里会出现多次）
    groups = defaultdict(list)
    for r in rows:
        groups[round(r["vol"], 0)].append(r)

    print(f"\n## 按体积分组（共 {len(groups)} 组）\n")
    print("| 体积 mm³ | 数量 | 包络 (X×Y×Z) | 示例中心 |")
    print("|---|---|---|---|")
    for vol, items in sorted(groups.items(), key=lambda kv: -kv[0]):
        if vol < min_vol:
            continue
        d = items[0]["dims"]
        c = items[0]["ctr"]
        print(f"| {vol:.0f} | {len(items)} | {d[0]:.1f}×{d[1]:.1f}×{d[2]:.1f} | "
              f"({c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f}) |")

    if "--detail" in argv:
        print("\n## 全部实体明细\n")
        print("| # | 体积 | 包络 | 中心 |")
        print("|---|---|---|---|")
        for r in sorted(rows, key=lambda r: -r["vol"]):
            d = r["dims"]
            c = r["ctr"]
            print(f"| {r['i']} | {r['vol']:.1f} | {d[0]:.1f}×{d[1]:.1f}×{d[2]:.1f} | "
                  f"({c[0]:.2f}, {c[1]:.2f}, {c[2]:.2f}) |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
