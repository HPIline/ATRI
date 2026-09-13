"""从生成器与成品 PPTX 导出逐页文案稿（v5）。

为什么要从 PPTX 反读，而不是在 build_deck.py 里再写一遍文案：
**文案稿与成品必须逐字一致**。手抄第二遍，两者迟早会对不上——
这正是 v4 那次「文案改了、pptx 没重生成」的根因。所以这里直接从产出的
PPTX 里按形状位置顺序抽文字，再拼上人工维护的证据与讲稿（EVIDENCE.md）。

用法： ./.venv-ppt/bin/python ppt-gen/export_copy.py
产物： docs/research/项目文档/答辩PPT-逐页文案-v5.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pptx import Presentation

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PPTX = ROOT / "ppt" / "out" / "ATRI-答辩PPT-v7.pptx"
EVIDENCE = HERE / "EVIDENCE.md"
OUT = ROOT / "docs" / "research" / "项目文档" / "答辩PPT-逐页文案-v7.md"


def page_text(slide) -> list[str]:
    """按形状的阅读顺序（上→下、左→右）抽文字，跳过纯装饰。"""
    items = []
    for sh in slide.shapes:
        if sh.has_table:
            rows = []
            for r in sh.table.rows:
                rows.append(" | ".join(c.text.strip() for c in r.cells))
            items.append((sh.top.inches, sh.left.inches, "表格：\n" +
                          "\n".join("| " + r + " |" for r in rows)))
            continue
        if not sh.has_text_frame:
            continue
        t = sh.text_frame.text.strip()
        if not t:
            continue
        items.append((sh.top.inches, sh.left.inches, t))
    items.sort(key=lambda x: (round(x[0], 1), x[1]))
    return [t for _, _, t in items]


def evidence_blocks() -> dict[int, str]:
    """把 EVIDENCE.md 按 '### Pnn' 切开。"""
    if not EVIDENCE.exists():
        return {}
    txt = EVIDENCE.read_text(encoding="utf-8")
    # 连同标题行的页名一起吃掉，否则块首会残留「封面」这类半行标题
    parts = re.split(r"^### P(\d+) · [^\n]*\n", txt, flags=re.M)
    out: dict[int, str] = {}
    for i in range(1, len(parts), 2):
        out[int(parts[i])] = parts[i + 1].strip()
    return out


def main() -> None:
    prs = Presentation(PPTX)
    ev = evidence_blocks()
    lines = [
        "# A.T.R.I. 答辩 PPT · 逐页文案 v7（35 页参赛汇报稿 · ATRI-v2 20 DOF 口径）",
        "",
        "> 本文件由 `ppt-gen/export_copy.py` 从 `ppt/ATRI-答辩PPT-v7.pptx` **反读生成**，",
        "> 与成品逐字一致；讲稿与证据来自 `ppt-gen/EVIDENCE.md`。改文案请改生成器后重跑，",
        "> 不要直接编辑本文件（编辑了会与成品分叉，这正是 v4 出过的问题）。",
        "",
        "## 口径基准（ATRI-v2 / 20 DOF，数字单一来源为 `ppt-gen/facts.py`）",
        "",
        "| 项 | 现行值 | 口径 |",
        "|---|---|---|",
        "| 自由度 | **20**：头 2 · 躯干 2 · 双臂 8 · 双腿 8 | 无髋偏航轴；关节表与固件配置同源 |",
        "| 整机包络 | **466.5 × 188 × 295 mm**（高×宽×深） | CAD 实算；赛题上限 600×300×300 |",
        "| 结构体系 | 6061 铝夹层 + 2.4 mm PETG | 髋与腰前后双侧支承 |",
        "| 装配体 | **1029 件**，几何零相交 | 同源装配快照 + B-rep 干涉求解 |",
        "| 质量账 | **已计 2469 g** / 目标 2300 g | 八类分项累加，采购件按标称质量 |",
        "| 扭矩口径 | 行走 k=1.4 **0.761 N·m（77.6%）**；保持 k=2 **1.086 N·m** | 判据取连续额定 0.98 N·m，不用堵转 2.74/2.94 充当额定 |",
        "| 电源 | 单包 3S 2200 mAh（24.4 Wh）；30 min 需 **10.40 Ah** | 分级方案：板载调试模式 / 扩展坞长航时模式 |",
        "| 测试 | 主包 **699**（skip 46）· 运动学 **41** · 装配链路 **95** | 通用 Linux + CPython 3.14 离线复跑 |",
        "| 成本 | 集采 **≈¥3137** · 零售 **≈¥3961** | 20 台规模约 6.3–7.9 万元 |",
        "| 任务评测 | T-01 LFW 50 人 rank-1 **98.6%**；T-02 主用解码器 100%（判据 6/6）；T-03 推荐参数 **20/20**；T-04 推荐参数 **20/24**；T-05 门闩 **6/6** | 数据集 / 合成图 / 几何在环，各自标注 |",
        "",
        "**答辩三条纪律**：① 数据集与合成图的数字不说成实机指标；"
        "② 技能返回 ok 不等于实物成功率；③ 规划项与实测项分开陈述，用状态标签区分。",
        "",
        "---",
        "",
    ]
    for i, slide in enumerate(prs.slides, 1):
        lines.append(f"## P{i:02d}")
        lines.append("")
        lines.append("**页面文字**（自 PPTX 反读，阅读顺序）")
        lines.append("")
        for t in page_text(slide):
            if "\n" in t:
                lines.append(t)
                lines.append("")
            else:
                lines.append(f"- {t}")
        lines.append("")
        block = ev.get(i)
        if block:
            lines.append("**证据 / 讲稿 / 口径提醒**")
            lines.append("")
            lines.append(block)
            lines.append("")
        lines.append("---")
        lines.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"saved: {OUT}  ({len(lines)} lines, {len(prs.slides._sldIdLst)} pages)")


if __name__ == "__main__":
    main()
