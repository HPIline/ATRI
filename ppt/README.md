# A.T.R.I. 答辩 PPT 生成工程

本目录是答辩 PPT 的**代码化生产流水线**。PPT 不是手工排的，是用 Python 按设计系统生成的——
这样 51 页的版式、配色、字号、状态标签才能完全一致，后续改文案也只改一处。

## 文件

| 文件 | 作用 |
|---|---|
| `design.py` | **设计系统**：画布栅格、8 色配色、字体、页面构件（页眉/判断句标题/导语/状态标签/卡片/大数字卡/关节节点链） |
| `build_sample.py` | 3 页视觉样张（封面 P01 / 一页摘要 P02 / 总体技术架构图 P17） |
| `render.py` | PPTX → PNG 离线渲染器（本机校验用；读真实 pptx 几何 + 真实思源黑体） |
| `export_pdf.applescript` | PowerPoint 导出 PDF（带等待与重试） |
| `build.sh` | 一键流水线：生成 → 导出 PDF → 栅格化 |
| `out/` | 产物：`.pptx` / `.pdf` / `pdf_pNN.png`（PDF 真实渲染）/ `preview/`（自渲染） |

## 用法

```bash
cd '/Users/hpi/Documents/搞机器人'

# 一键：生成 + 导出 PDF + 栅格化
bash ppt/build.sh ppt/build_sample.py "ATRI_答辩PPT-样张"

# 只看自渲染（快，不调用 PowerPoint）
./.venv-ppt/bin/python ppt/render.py "ppt/out/ATRI_答辩PPT-样张.pptx" ppt/out/preview
```

产物在 `ppt/out/`：`ATRI_答辩PPT-样张.pptx` 与同名 `.pdf`。

## 设计系统速查

**画布**：16:9，13.333 × 7.5 in；左右边距 0.833 in；内容宽 11.667 in
**页眉** 0.40 / **标题** 0.78 / **导语** 1.62 / **横线** 2.02 / **正文** 2.24 / **状态条** 6.58 / **页脚** 7.02

**配色（8 个值）**

| 用途 | 变量 | 值 |
|---|---|---|
| 墨蓝 · 章节页底/主标题/大数字 | `INK` | `#0A2540` |
| 结构蓝 · 主色，架构图/连线/表头 | `BLUE` | `#1264A3` |
| 蓝雾 · 卡片底/分区底 | `MIST` / `MIST_2` | `#E8F0F7` / `#DCE9F4` |
| 浅蓝 · 次级线条/网格 | `BLUE_300` | `#9CC0DC` |
| 纸白 · 页面底 | `PAPER` | `#F7F9FB` |
| 石墨 · 正文 | `GRAPHITE` | `#1F2A37` |
| 中性灰 · 次要说明/来源 | `GRAY` | `#6B7A8C` |
| 朱橙 · **唯一强调色**（每页 ≤ 2 处） | `ORANGE` | `#E4572E` |
| 验证绿 · 状态语义色 | `GREEN` | `#2E9E7B` |

**字体**：`Source Han Sans SC Heavy`（标题/大数字/强调）＋ `Source Han Sans SC`（正文）
> 两个是**独立字体家族名**，都装才能同时拿到 Regular 与 Heavy 字重。
> 本机在 `~/Library/Fonts/SourceHanSansSC-{Regular,Heavy}-2.otf`。

**状态标签制度（全片强制）**：`● 已完成`(绿) / `◐ 进行中`(橙) / `○ 规划中`(灰) / `◇ 设计目标`(蓝)
每一处技术声明后都必须挂一个，解决"前面写完成态、后面说没实测"的口径矛盾。

**禁止项**：圆角、阴影、渐变、霓虹辉光、彩虹色图表、无关 stock 图。

## 两个坑（已修，别踩回去）

1. **`px()` 只接受英寸**。`space_before` / `space_after` 拿到的是 pt，必须走 `pt2px()`；
   否则会被放大 72 倍，MIDDLE 锚点的文本直接被推出画布。
2. **思源黑体默认行高 ≈ 1.45 em**（ascender 1160 + descender 320）。`render.py` 里的
   `LINE_FACTOR = 1.45` 必须与 PowerPoint 一致，否则文本框高度会被低估、内容溢出。

## PDF 为什么可以放心拿去放

导出的 PDF 已把字体**子集化内嵌**（`AAAAxx+SourceHanSansSC-*`），
在任何没装思源黑体的机器上打开都不会跑版。现场直接用 PDF 播放，零字体风险；
需要改内容时再用 `.pptx`（那台机器需装思源黑体）。
