# 答辩 PPT 生成工程（ppt-gen/）

这是答辩 PPT 的**代码化生产流水线**。演示文稿不是手工排的，是按设计系统用 Python
生成的——这样 35 页的版式、配色、字号、状态标签才能完全一致，改文案也只改一处。

现行版本是 **v7（35 页，参赛汇报体）**，口径为仓库 **ATRI-v2 A 路线（20 DOF，无 hip_yaw）**。

## 文件

| 文件 | 作用 |
|---|---|
| `design.py` | **设计系统**：画布栅格、配色、字体、页面构件（页眉 / 判断句标题 / 导语 / 状态标签条 / 卡片 / 大数字卡 / 图片 object-fit） |
| `facts.py` | **数字单一来源**：自由度、包络、质量账、扭矩、电源、成本、五项任务评测值、验收准则、研发路线、素材路径 |
| `figures.py` | **数据图形构件**：扭矩条形图、包络区间条、质量堆叠条、百分比对照、刻度尺（全部矢量自绘，不引 matplotlib） |
| `diagrams.py` | **技术图构件**：20 DOF 关节拓扑图、FSM 状态转移图、流程条、章节页 |
| `build_deck.py` | 35 页答辩稿（数字只从 `facts.py` 读） |
| `prepare_v2_assets.py` | 把仓库 `design/v2/out/` 的 CAD 光追渲染图加工成可摆放素材（**按底色差自动裁掉空底**、压平底色、缩放并转 JPEG） |
| `textmetrics.py` | 文本框真实排版范围测量（与 `render.py` 同一套字距与行高口径） |
| `check_layout.py` | 版面体检：按**真实排版高度**扫描越界与压盖 |
| `render.py` | PPTX → PNG 离线渲染器（含图片与裁切支持），本机目检用 |
| `export_copy.py` | 从成品 PPTX **反读**生成逐页文案稿，保证文案与成品逐字一致 |
| `animate.py` | 转场（fade 700 ms），直接写 DrawingML |

## 用法

```bash
cd <repo>   # 仓库根目录

# 0. 素材：把 .upstream/renders/（仓库 design/v2/out/ 的渲染图）加工进 assets/v2/
./.venv-ppt/bin/python ppt-gen/prepare_v2_assets.py

# 1. 生成 PPTX
./.venv-ppt/bin/python ppt-gen/build_deck.py            # 默认产物名 ATRI-答辩PPT-v7

# 2. 版面体检（必须 0 页有问题）
./.venv-ppt/bin/python ppt-gen/check_layout.py "ppt/out/ATRI-答辩PPT-v7.pptx"

# 3. 逐页目检（输出 ppt/out/preview-v7/pNN.png）
./.venv-ppt/bin/python ppt-gen/render.py "ppt/out/ATRI-答辩PPT-v7.pptx" ppt/out/preview-v7

# 4. 导出逐页文案稿（与成品逐字一致）
./.venv-ppt/bin/python ppt-gen/export_copy.py

# 5. 交付：把成品放到 ppt/ 下
cp "ppt/out/ATRI-答辩PPT-v7.pptx" "ppt/ATRI-答辩PPT-v7.pptx"
```

环境：`./.venv-ppt`（python-pptx 1.0.2 + Pillow + cairosvg + numpy + pymupdf）。
CAD 与 Webots 无关，本流水线不进 CAD 环境，避免与 OCCT 抢 CPU。

## 设计系统速查

**画布**：16:9，13.3333 × 7.5 in；左右边距 0.8333 in；内容宽 11.6667 in
**基线**：页眉 0.40 / 标题 0.78 / 导语 1.62 / 横线 2.02 / 正文 2.24 / 状态条 6.58 / 页脚 7.02

**配色**

| 用途 | 变量 | 值 |
|---|---|---|
| 墨蓝 · 章节页底 / 主标题 / 大数字 | `INK` | `#0A2540` |
| 结构蓝 · 主色，架构图 / 连线 / 表头 | `BLUE` | `#1264A3` |
| 蓝雾 · 卡片底 / 分区底 | `MIST` / `MIST_2` | `#E8F0F7` / `#DCE9F4` |
| 浅蓝 · 次级线条 / 网格 | `BLUE_300` | `#9CC0DC` |
| 纸白 · 页面底 | `PAPER` | `#F7F9FB` |
| 石墨 · 正文 | `GRAPHITE` | `#1F2A37` |
| 中性灰 · 次要说明 | `GRAY` | `#6B7A8C` |
| 朱橙 · 唯一强调色 | `ORANGE` | `#E4572E` |
| 验证绿 · 状态语义色 | `GREEN` | `#2E9E7B` |
| 图版页底（= ATRI-v2 渲染图底色） | `DARK` | `#323A42` |

**字体**：`Source Han Sans SC Heavy`（标题 / 大数字 / 强调）＋ `Source Han Sans SC`（正文）。
本机在 `~/Library/Fonts/SourceHanSansSC-{Regular,Heavy}-2.otf`。

**状态标签制度（全片强制）**：`● 已完成`(绿) / `◐ 进行中`(橙) / `○ 规划中`(灰) / `◇ 设计目标`(蓝)。

**禁止项**：圆角、阴影、渐变、霓虹辉光、彩虹色图表、AI 生图；标题下不加装饰色条。

## 文案纪律（v7 相对 v6 的最大变化）

v6 是「工程自白体」：封面就写扭矩缺口与样机未制造，正文夹着内部备注（「对外表述要求：
不得表述为已满足 30 分钟续航」）、待办（「待确认：尺寸是否以报名申报值为准」）、
占位框（「待补图……渲染完成后替换此占位框」）、命令行与 Git 提交号。这些属于研发过程
材料，不该出现在答辩屏幕上。

v7 改为**面向评审的创新竞赛叙事**，在生成器文件头以写作规范固定下来：

1. 不出现命令行、仓库路径、提交号、内部备注、待办事项、占位说明与免责声明；
2. 技术声明一律附**方法口径**（CAD 实算 / 公开数据集 / 合成图基准 / 离线测试 / 设计校核），
   评委能追问来源，但不暴露工程台账；
3. 缺陷改写成**边界与对策**：扭矩超限写成「载荷峰值识别 + 减载机制 + 台架验证计划」，
   续航缺口写成「功率预算 + 续航分级方案」；
4. 状态用统一标签表达，不用文字自曝。

## 图片素材

素材来自仓库 `design/v2/out/`（Blender Cycles HIP 光追审查渲染），底色约 `#323A42`。
`prepare_v2_assets.py` 先按「与底色的差值 > 16」求包围盒**自动裁掉四周空底**——渲染图是
16:9 大画布、机体只占中间一小块，不裁的话贴进竖版画框只剩一小截机体加一大片空底；
随后压到 `design.DARK` 上并缩放到版面需要的最长边，输出 JPEG：

| 素材 | 用途 |
|---|---|
| `hero_front.jpg` | 封面右侧整机正视图（4K 缩到 2600 px） |
| `product_iso.jpg` | 第 13 页整机等轴测图版 |
| `product_front.jpg` | 第 7 页包络页配图 |
| `exploded.jpg` | 第 14 页爆炸图版（4K 无标号版） |
| `detail_pelvis.jpg` | 第 8 页髋腰双侧支承细节 |
| `detail_waist.jpg` / `detail_gripper.jpg` / `service_exploded.jpg` / `product_rear.jpg` | 备用素材 |

**对齐约定**：因为素材已经裁到机体包围盒，各页面一律用 `picture_fit`（不裁切），
图版页的底色铺满整版、与渲染图底色同色，所以看不到接缝；浅色页用白底细描边图框，
**竖版图配竖版画框**（4:3 画框配 0.55 长宽比的图会留下大片白边），图注区高度按行数预留。

## 版本演进

| 项 | v5（33 页） | v6（35 页） | **v7（现行，35 页）** |
|---|---|---|---|
| 机构口径 | 22 DOF（打印件方案） | 22 DOF | **20 DOF，无 hip_yaw；6061 铝夹层 + 2.4 mm PETG** |
| 文体 | 短句标语体 | 学术汇报体（含工程自白） | **参赛汇报体：定位 → 构型 → 软件 → 任务 → 验证路线** |
| 自曝内容 | 页脚注 | 独立成章（未测项 27 条） | **全部移除，改为边界分析与对策** |
| 图片 | 自绘矢量为主 | 4 张旧 CAD 渲染 | **ATRI-v2 光追渲染 9 张（含 4K 整机与爆炸图）** |
| 文案一致性 | `export_copy.py` 反读 | 同 v5 | 同 v5（`docs/research/项目文档/答辩PPT-逐页文案-v7.md`） |

## 三个坑（已修，别踩回去）

1. **`px()` 只接受英寸**。`space_before` / `space_after` 拿到的是 pt，必须走 `pt2px()`。
2. **思源黑体默认行高 ≈ 1.45 em**。`textmetrics.py` 的 `LINE_FACTOR = 1.45` 必须与
   PowerPoint 一致，否则文本框高度会被低估、内容溢出。
3. **PPTX 的文本框不裁剪溢出文字**。版面体检必须按真实排版高度算
   （`check_layout.py` 走 `textmetrics.text_extent`），拿 `shape.height` 判越界会漏掉真实溢出。
