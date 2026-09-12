# 第 11 轮：多线程施工方案与 Prompt（2026-09-12，面向 9.13 deadline）

> **形势**：9.13 是 deadline，**没有实物、只有仿真**，无采购经费。
> 所以本轮所有线程的验收标准都加一条：**产出必须能直接进参赛材料**（图、数、可交互件、可粘贴文案），
> 不做"为了以后重构"的长期投资。
>
> 基线：`main` @ `0533f55`（`atri-next` 第 6–10 轮已合入）；冻结 tag `v1-print-cad`；
> 实测：装配 86/86、机械零位摆放错误 **0 对**、轴对齐 22/22、包络 **160 × 268 × 407 mm**、
> 干涉总量 160 423 mm³、`test_layout.py` 15 项通过、软件 154+64 项测试绿。

---

## 一、线程表（文件所有权互斥，一人一文件）

| # | 线程 | 建议模型 | 独占文件 | 交付物 | 验收命令/阈值 |
|---|---|---|---|---|---|
| **T1** | 足部重做（垫条+轨距+斜肋，控总质量） | `opencode-go/deepseek-v4-pro` | `design/cad/skeleton.py`、`design/cad/test_layout.py` | 新足底几何 + 三视图 + 报告 | 见 §三 prompt T1 |
| **T2** | 姿态扫掠与关节限位（动态校核） | `opencode-go/kimi-k2.7-code` | `design/cad/sweep_check.py`、`design/handoff/姿态扫掠报告.md` | 姿态碰撞图谱 + 限位建议 + 答辩用图 | 见 §三 prompt T2 |
| **T3** | 交互式预览窗口（关节滑条/预设/半透明配合） | `opencode-go/minimax-m3` 或 `kimi-k2.7-code` | `design/cad/preview.py` | 可交互自包含 HTML + 用法说明 | 见 §三 prompt T3 |
| **T4** | 参赛材料口径核对（只读+清单） | `opencode-go/glm-5.3-flash` | `design/handoff/答辩材料口径核对清单.md` | 逐条核对表（PPT 说法 → 现行实测 → 建议文案） | 见 §三 prompt T4 |
| **T7** | 计划书成文 + PPT 重生成 + 知产/财务数据 | 我（主会话） | `docs/contest/参赛计划书.md`、`ppt/**`（重生成） | 计划书 PDF + 修正后的 pptx/PDF + 两张表的数据 | 见 `docs/contest/提交材料清单.md` |
| **T5** | 仿真对接（队友机器，非本仓库线程） | — | `docs/process/sim/**`（队友） | 仿真报告 + 短视频 | 见 `design/handoff/仿真请求-Webots验证清单.md` |
| **T6** | **Webots 世界补重力/地面/扭矩上限（关键路径）** | `opencode-go/kimi-k2.7-code` 或 `deepseek-v4-pro` | `webots/tools/generate_atri_world.py`、`webots/controllers/atri_controller/atri_controller.py`、`webots/README.md` | 生成器加 `ATRI_WORLD_GRAVITY` / `ATRI_WORLD_MAX_TORQUE` / `--out`；控制器加 `--max-torque`；重生成世界并核实 | 见 §三 prompt T6 |

> ⚠️ **T6 是关键路径**：仿真请求核实出 `webots/worlds/atri_22dof.wbt` 是 **`gravity 0` + 无地面 + 无 `maxTorque` + 无扭矩反馈**，
> 也就是现在这台"仿真验证"其实是无重力运动学演示，**静立扭矩≈0，不能作为站得住/走得了的证据**。
> 而 9.13 的演示材料只能来自仿真——所以"让仿真带重力、带地面、带 2.94 N·m 扭矩上限"必须在录视频之前完成。
> 该线程会动 `webots/**`（原属队友区域）：**只加可选开关、默认行为完全不变**，并需在报告里写明改动点与回退方式。

**重活只有 T1**（要多次重建装配）。T2/T3 各只跑 1–2 次装配；T4 纯文档。
**并发上限**：同一时刻最多 **1 个** 会跑 `assembly.py`/`build_all.py` 的线程 + 任意个纯文档线程。

---

## 二、五条并行规矩（第 10 轮血的教训，必须写进每个 prompt）

1. **一个提交者**：只有主会话做 `git add/commit/push`；线程只写文件，**禁止任何 git 操作**。
2. **文件所有权互斥**：只碰自己名下的文件；要改别人的文件就在报告里写"建议"。
3. **每条线程必写报告**：`design/handoff/线程报告-<线程名>.md`，**附真实命令与输出**（报告即跨线程通信）。
4. **重 CAD 一次只开一条线**：装配构建 1–2 分钟、`build_all` 数分钟；并发会互相抢 CPU，看起来像"卡死"。
5. **慢路由只派短刀任务**：`xbcl` 的 grok 首字节 25–75 秒，只适合"评审/单点判断"，不要用来写整模块。

**另外三条工程纪律（本仓库既有）**：不切干涉包围盒当补丁；不手写错轴量/钟点；不把仿真值当实测值。

**第 6 条（2026-09-12 T6 血案，必须遵守）**：`A && B` 形式的验证命令会**假绿**——
A 若因环境差异静默失败（本例：`Path.write_text(newline=...)` 在 Python 3.9 直接 `TypeError`），
`&&` 右边的 B **根本不执行**，而屏幕同样是"一片空白"，看起来像"没有差异 / 全部通过"。
**规矩**：每条验证都显式 `echo "exit=$?"`；关键判据用 `git diff --exit-code` 这种**自带退出码**的命令；
日志判别用 `grep -E "^(Ran |OK|FAILED|ERROR)"`，不要用 `tail -3`（stdout 块缓冲会把结论行顶掉）。

---

## 三、可粘贴 Prompt（每段独立可用，复制到新会话）

### ----- T1 复制开始 -----

你在仓库 `/Users/zhangjingkun/Projects/github/ATRI` 上做**足部重做**，目标是在 **9.13 deadline 前**拿出一个"站得稳、质量不增加"的足部，并留下能进参赛材料的证据。全部中文。

**必读（先读再动手）**
- `docs/process/骨架重构评估-组会汇报.md` §5「足底支撑面太小」——问题定义与建议改法（垫条、轨距、斜肋、开窗补质量）
- `design/cad/skeleton.py` 的 `foot_plate()` 与踝区相关零件（**注意：其中写明了哪些是承力路径，不许切**）
- `design/cad/test_layout.py`（现有门禁：`test_foot_heel_and_pads` 要求后跟 ≥45 mm、橡胶垫在鞋底之下、不打穿底板；足部质量上限 42 g/只）
- `design/cad/standards.py`（材料与最小壁厚；不要自己编材料参数）

**要做的**
1. 把四只 Φ8×13 圆柱垫改成**前后两条横向垫条**（有效着地面积显著大于现在约 201 mm²），轨距放宽到接近足板宽 60 mm，整体保持**橡胶垫是全机最低点**。
2. 从踝叉臂向垫条**加拉斜肋**把载荷传下去；在**非传力区**开窗，把加肋带来的质量补回来。
3. `test_layout.py` 里补/收紧足部门禁（例如：单脚质量 ≤42 g、支撑多边形面积下限、垫条不得超出足板包络、零位下最低点仍是橡胶垫）。

**验收（必须逐条跑并粘贴真实输出）**
```bash
.venv-cad/bin/python design/cad/tools/build.py --standards          # 冒烟
.venv-cad/bin/python design/cad/assembly.py --all --no-export       # 必须 86/86 成功、『摆放错误』仍为 0 对
.venv-cad/bin/python design/cad/audit_assembly.py --top 8           # 轴对齐必须 22/22
.venv-cad/bin/python design/cad/test_layout.py                      # 全部通过
.venv-cad/bin/python design/cad/tools/render3d.py --part foot_plate # 出三视图（或等价命令，先读 --help）
```
另外报告里必须给：**改前/改后单脚质量、全机结构件总质量**（改后**不得增加**）、着地面积、轨距、后跟长度。

**硬约束**：只改 `design/cad/skeleton.py` 与 `design/cad/test_layout.py`；**禁止 git 操作**、禁止改 `design/placements.json`、禁止改 `software/**`、`ppt/**`、`webots/**`、`design/cad/out/**`（生成物）、禁止 `pip install`。所有命令设超时（≤300 s），重的放后台。
交付 `design/handoff/线程报告-足部重做.md`：改动摘要、验收命令与真实输出、改前后数字对照、承力路径说明、未决项。

### ----- T1 复制结束 -----

### ----- T2 复制开始 -----

你在仓库 `/Users/zhangjingkun/Projects/github/ATRI` 上做**极限姿态扫掠校核**，回答一个问题：**机械零位不穿模（已达标），那么动起来之后哪些姿态会撞？** 全部中文。

**背景（已核验）**：`design/cad/sweep_check.py` 已存在（读 URDF 限位、做姿态扫掠、复用 `fitcheck.py` 判定、自带全局超时），但**合入第 6–10 轮 CAD 改造后没有复跑过**，可能因接口变化而坏。

**要做的**
1. 先 `--help` 与通读，**修好它**（该文件归你）。允许改的地方：`design/cad/sweep_check.py` 及其自带的报告输出。
2. 跑 `--quick`（3 档单关节 + 50 组 LHS），如时间允许再 `--full`。**必须放后台或设超时**。
3. 产出：
   - 姿态诱发的碰撞清单（按"零位体积基线扣除"后的**新增**体积排序），标注哪些是**配合面**（用 `fitcheck.is_joint_mate` 判定，注意：该函数在 `fitcheck.py` 里**已定义但当前无人调用**——你可以调用它，但**不要改 `fitcheck.py`**）；
   - **逐关节限位建议**（把会导致碰撞的角度区间列出来，给出保守余量），格式能直接抄进 URDF/`config.py` 讨论；
   - **一张答辩用图**：至少一页（PNG），显示"零位 vs 危险姿态"的对照或碰撞热区。
4. 写 `design/handoff/姿态扫掠报告.md`：命令、真实输出摘要、结论、限位建议表、未验证项。

**硬约束**：只改 `design/cad/sweep_check.py` + 新建 `design/handoff/姿态扫掠报告.md`（+ `design/cad/out/` 下的报告/图片产物）；**禁止 git 操作**、禁止改 `skeleton.py`/`assembly.py`/`fitcheck.py`/`test_layout.py`、禁止改 `software/**`、`ppt/**`、`webots/**`、禁止 `pip install`。所有命令设超时。

### ----- T2 复制结束 -----

### ----- T3 复制开始 -----

你在仓库 `/Users/zhangjingkun/Projects/github/ATRI` 上做**交互式 3D 预览窗口**，目标：答辩时能当场拖关节、自由转视角，且**不依赖任何外部库/网络**。全部中文。

**背景（已核验）**
- `design/cad/preview.py` 已能生成**自包含 WebGL HTML**：`.venv-cad/bin/python design/cad/preview.py --all` → `design/cad/out/preview/ATRI-preview.html`（17.2 MB，158 778 三角面，几何内嵌，**双击即用**，鼠标轨道+滚轮缩放已可用）+ `ATRI-assembly.glb`。
- 它默认渲染**展示姿态**（`A.DISPLAY_POSE_DEG`），`--zero` 看机械零位。**目前没有关节滑条**。

**要做的（按性价比，先做能进答辩的）**
1. **关节滑条**：22 个关节各一条，范围取 URDF 限位（不要自己编限位），拖动即时重算 FK 并更新网格变换（只更新 4×4 矩阵，不要重新三角化）。
2. **姿势预设**：零位 / 展示姿态 / 招手 / 踢球 / 抓取——至少 4 个，按钮切换；预设值写在一处常量表里，便于以后改。
3. **配合件半透明**：调用 `fitcheck.is_joint_mate`（该函数已定义但**当前无人调用**）把同一关节的叉/爪/笼与该关节舵机渲染成半透明——这是第 10 轮做了一半的功能，你把它接到预览里；**不要改 `fitcheck.py`**。
4. **一键生成说明**：在 `design/cad/README.md` 里补 5–10 行"怎么生成、怎么打开、怎么截图"（该文件归你）。
5. 注意性能：滑条拖动时不得卡顿（不得每次重建几何）；文件体积不要暴涨（>40 MB 就要说明原因）。

**验收**：重新生成 HTML；确认**无外部 URL 依赖**（除 SVG 命名空间等无害引用）、双击可开、滑条/预设/半透明均生效（给出你实际验证方式，例如用 `node`/`grep` 静态检查 + 人工打开截图）。报告写 `design/handoff/线程报告-预览窗口.md`。

**硬约束**：只改 `design/cad/preview.py` 与 `design/cad/README.md`（+ `out/` 产物）；**禁止 git 操作**、禁止改 `skeleton.py`/`assembly.py`/`fitcheck.py`、禁止引入 npm/pip 依赖、禁止访问网络、禁止改 `software/**`、`ppt/**`、`webots/**`。

### ----- T3 复制结束 -----

### ----- T4 复制开始 -----

你在仓库 `/Users/zhangjingkun/Projects/github/ATRI` 上做**参赛材料口径核对**：把 PPT/文档里每一处数字与**当前实测**逐条对照，输出一张可直接照着改的清单。全部中文。**你只写一个新文件**：`design/handoff/答辩材料口径核对清单.md`。

**当前权威口径（实测，2026-09-12，`main` @ `0533f55`）**
- 包络 **160 × 268 × 407 mm**（宽内部门禁 ≤270，**只剩 2 mm 余量**；赛题上限 600 × 300 × 300）
- 机械零位**摆放错误 0 对**；`test_layout.py` **15 项**门禁；关节轴对齐 22/22
- 结构件 **1490 g / 81 件**（CAD 实算，`design/cad/out/report.md`）；整机 **≈3136 g 纸面推算，重量方案未定案**
- 扭矩判据：官方额定 **0.98 N·m @12V**（堵转 2.94）——踝 **152%**、`trunk_roll` **194%**
- 功率：平均电流 **18.92 A**，30 min 需标称 **11.83 Ah / ≈131 Wh（整包≈1.19 kg）**；现有 3S 2000 mAh 只能撑 **约 13 分钟** ⇒ **答辩材料里不得写"30 分钟续航"**
- 软件测试：`software/atri` 154 项（含总线 64 项）实测绿；CAD 侧 `test_layout.py` 15 项绿
- 目录已改名：`软件/` → `software/`；文档在 `docs/process`、`docs/research/项目文档`、`docs/contest`

**要做的**
1. 读（**只读，不许改**）`docs/research/项目文档/答辩PPT-逐页文案-v4.md`、`ppt/**`、`README.md`、`docs/research/项目文档/技术方案.md`、`docs/process/研发日志-卷1.md`。
2. 输出表格：`文件:行 → 现在的说法 → 现行实测 → 判定（✅一致/⚠️过期/❌错误）→ 建议文案（可直接替换的一整句）`。
3. 重点排查：418×223×129、1790 g、3437 g、3.437 kg、1.47 N·m 判据、"30 分钟续航"、"官网不可达"、"副轴 3.0 / 纵深 11.0 / 底部 38×15"、`软件/atri` 旧路径、`design/cad/measure_servo.py` 旧路径（已迁 `tools/`）。
4. 末尾给"**答辩口头问答预案**"：把 3–5 个最可能被问到的数字（扭矩超标、续航、为什么没实物、宽度余量）写成 2–3 句的诚实回答，**不许粉饰**。

**硬约束**：只写 `design/handoff/答辩材料口径核对清单.md`；**禁止 git 操作**、禁止改任何既有文件（包括 PPT 与文档）、禁止跑 CAD、禁止 `pip install`。

### ----- T4 复制结束 -----

### ----- T6 复制开始（关键路径）-----

你在仓库 `/Users/zhangjingkun/Projects/github/ATRI` 上，给 **Webots 仿真世界补上重力、地面与舵机扭矩上限**。这是 9.13 演示材料的**关键路径**：现在的世界跑不了站立/行走验证。全部中文。

**先读（必须，别猜）**
- `design/handoff/仿真请求-Webots验证清单.md` §0 与 §0.3（已核实的事实与要求加的开关名/语义，全在里面）
- `webots/tools/generate_atri_world.py`（世界生成器，现 `GRAVITY = 0.0`）
- `webots/controllers/atri_controller/atri_controller.py` 与 `webots/README.md`
- `webots/tests/webots_api_stub.py`、`webots/tests/test_atri_controller.py`（离线桩测试，改完必须仍绿）

**已核实的事实（直接采信）**
1. `webots/worlds/atri_22dof.wbt` 现在是 `gravity 0`、**全文件没有地面**、电机**没有 `maxTorque` 字段**、
   没有扭矩反馈 ⇒ 零重力下静立扭矩 ≈ 0，**S1/S2 场景跑不了**。
2. Webots 的 `RotationalMotor.maxTorque` **默认 10 N·m**；不显式设 2.94，等于把舵机权限放宽 3.4 倍，结论作废。
3. 扭矩反馈 API 是 `Motor.enableTorqueFeedback(samplingPeriod)` / `getTorqueFeedback()`；
   请求文档里已附一份可用的 `torque_probe.py` 草案。

**要做的（只加开关，不改默认行为）**
1. `generate_atri_world.py`：支持**可选覆盖**——`ATRI_WORLD_GRAVITY`（默认保持现在的 0.0）、
   `ATRI_WORLD_MAX_TORQUE`（默认不写字段，保持现状）、`ATRI_WORLD_GROUND`（默认不生成地面）、
   `--out <path>`（默认仍是原来的输出路径）。**重力非 0 时必须同时生成地面**（否则机器人自由落体），
   地面用 Webots 的 `Floor`（或 `Plane`）节点，尺寸足够大并在 README 里写明。
2. `atri_controller.py`：加 `--max-torque`（默认 None = 不改），用于在运行时对 22 个电机统一设上限。
3. `webots/README.md`：加一节"**带重力/带地面的校核跑法**"，给出可直接复制的命令
   （含环境变量与 `--out` 指向 `docs/process/sim/` 之类的临时目录），并写清"默认零重力模式仍用于纯运动学演示"。
4. **验证（必须逐条跑并粘贴真实输出）**
   ```bash
   # a) 默认模式必须与已提交的世界完全一致（证明没有破坏现有行为）
   python3 webots/tools/generate_atri_world.py && git diff --stat webots/worlds/atri_22dof.wbt
   #    → 期望：无差异（空输出）
   # b) 带重力模式生成到临时路径，并静态核实三个关键点
   ATRI_WORLD_GRAVITY=-9.81 ATRI_WORLD_MAX_TORQUE=2.94 ATRI_WORLD_GROUND=1 \
     python3 webots/tools/generate_atri_world.py --out /tmp/atri_grav.wbt
   grep -c "gravity -9.81" /tmp/atri_grav.wbt; grep -c "maxTorque 2.94" /tmp/atri_grav.wbt; grep -cE "Floor|Plane" /tmp/atri_grav.wbt
   #    → 期望：gravity ≥1 处、maxTorque 恰好 22 处、地面 ≥1 处
   # c) 离线桩测试仍绿
   python3 -m unittest discover -s webots/tests 2>&1 | tail -3
   ```
5. 报告 `design/handoff/线程报告-Webots世界带重力.md`：改动点、上述命令的真实输出、**回退方式**（如何恢复默认行为）、
   以及"队友机器上该怎么跑 S1/S2 的完整命令"。

**硬约束**：只改 `webots/tools/generate_atri_world.py`、`webots/controllers/atri_controller/atri_controller.py`、`webots/README.md`
（+ 新建报告文件）；**禁止 git 操作**；禁止改 `software/**`、`design/cad/**`、`ppt/**`、`task_cards/**`；
禁止 `pip install`、禁止访问网络；所有命令设超时（≤120 s）；**默认行为必须保持不变**（验证 a 是硬门槛）。

### ----- T6 复制结束 -----

---

## 四、依赖与排期（9.12 → 9.13）

```
D0 今天：T1 开工（唯一重 CAD）｜T2、T4 并行（轻）｜T3 与 T1 错开跑（避免同时构建装配）
D0 晚：  T1 验收 → 主会话复验+提交；T2 出限位建议 → 同步给队友（进仿真请求）
D1 上午：T3 出可交互预览 → 主会话提交；T4 清单 → 主会话按清单改 PPT 文案（红线区由人工确认）
D1 下午：队友仿真报告回传 → 把仿真数字写进材料；最后一次统一 push
```

**交付优先级（时间不够就从下往上砍）**：① 仿真报告/视频（队友）② 口径核对清单（T4）③ 交互式预览（T3）④ 姿态限位（T2）⑤ 足部重做（T1）。

> 说明：足部重做排最后**不是**因为它不重要，而是它最容易在 deadline 前把"已经干净的零位（❌=0）"重新弄脏——
> 它必须**单独占一条重 CAD 线**并留足复验时间。

---

## 五、主会话的复验清单（每条线程交付后必跑）

```bash
.venv-cad/bin/python design/cad/assembly.py --all --no-export   # 86/86 + 摆放错误 0
.venv-cad/bin/python design/cad/audit_assembly.py --top 8        # 轴对齐 22/22、看有无新增大对
.venv-cad/bin/python design/cad/test_layout.py                   # 15 项
.venv-cad/bin/python design/cad/pair_inspect.py --errors         # 必须为空
cd software/atri && .venv/bin/python -m unittest tests.test_bus_sts3215 tests.test_bringup tests.test_cerebellum tests.test_config tests.test_handoff
```
数字有任何一项变差 → **不进提交**，先查因。

---

## 六、第 11 轮补充：减重与材料强度结论（2026-09-12 晚，来自 `减重与材料强度整合方案.md`）

**质量口径已更新**（`build_all.py --all` 重跑，09:06）：结构件 **1390.4 g / 81 件**（对比上一版 1490 g，**−7%**）、
整机 **≈3036 g**、踝 **1.49 N·m = 额定 152%**。
⚠️ `design/atri.urdf` 的 link 质量**仍是旧口径**（sum = 3436.6 g），所以 `trunk_roll` 的 1.899 N·m **尚未重算**。

**质量模型的一个坑（影响所有引用）**：`kit.printed_mass()` 的薄壁近似是
`V_壳 = 表面积 × 壁厚`，对本仓库这种 3 mm 壁件会**退化成实心质量**（壳体积 ≥ 总体积），
即填充率参数完全不起作用（我核过 `joint_cage`：体积 17 378 mm³ → 22.07 g = 实心值）。
⇒ **1390 g 应读作上限**（薄壁区本来就接近实心，厚实区的填充折扣没体现）。
**T1 附带一项 10 分钟任务**：拿一个件进切片器标定，给出现值与实心值的比值，写进报告。

**三个杠杆（9.13 前只有 L2/L3 来得及）**

| 杠杆 | 可省质量 | 代价 | 9.13 前 |
|---|---|---|---|
| L1 材料替换（决策表 4 类 36 件→6061） | **245 g**（整机金属化则 830 g） | +300 元、省 20 h 打印、4 条接口前提未闭环 | ❌ 无经费/无实物 |
| L2 拓扑开窗（腹板/减重孔） | **100–150 g**（保守）／150–220（进取） | 0 元、半天；扭转刚度 −15~25%（推断） | ✅ **唯一来得及** |
| L3 减件合并 + 紧固件 | **68–115 g** | 省装配工时 | ✅（左右 mirror 已做完，收益 0 g，要诚实写 0） |

**L2 + L3 在 9.13 内的现实值 ≈ 150–220 g。**

**扭矩：只减结构确实无解（比例法）**
- 踝 ∝ 整机质量：每减 100 g 结构 = **−5.0 pt**；结构 1390→900 g（要挖 490 g）踝只从 152% 走到 **127%**。
  反解：踝进额定需整机 ≤2000 g，而**舵机 1210 + 电子电池 316 = 1526 g 已占 76%**，结构只剩 354 g 额度（要砍 74.5%）。
- 腰：`trunk_roll` 进额定需下游质量 ≤405 g（现 1634 g，缺口 1229 g），而**上半身结构总共只有 525.5 g**——全删也只到 131%。

**⇒ 本轮必须把"降额运行"写进控制策略（可直接抄）**：
默认限流 **1.3 A**（踝允许占空比 48%）｜峰值 **≤2.0 A 且 ≤2 s**（官方过流保护）｜
**禁止把单腿支撑当静止保持姿态**（≤3 s 过渡）｜禁止长时"躯干倾斜 + 双臂外伸"组合。
限流同时是**续航杠杆**：13 min 有机会翻倍到 25–30 min（推断）。

**单项性价比最高**：电池（165 g）从躯干下移到骨盆 → `trunk_roll` **−0.192 N·m（−20 pt）**、踝 −0.081 N·m。
这是摆位改动（`design/gen_placements.py`），但会动到"零位 ❌=0"的现状 ⇒ **若做，单独占一条线 + 全量复验**，不要塞进 T1。

**本轮新发现、需另行处理的缺陷**
1. `torso_frame` 与 `foot_plate` 各由 **3 个互不相连的实体**组成（`build_all` 几何列 ❌，非单一可打印体）——
   `foot_plate` 并入 **T1** 顺手修；`torso_frame` 单独记一条。
2. `tools/diagnose_mass.py` 的 `breakdown_torso` 仍用旧特征 `tl=96/tw=86`（现值 108/104），只能当量级参考。
3. `trunk_roll` 的 1.899 N·m **系数语义不自洽**（1.688×9.81×0.137×1.8 = 4.08，而表值 1.899 = 重力矩 1.055×1.8）→ **待复核**；
   现有敏感度分析走比例法，不受影响。
4. `standards.py` 里**没有** PETG / 6061-T6 的许用应力与安全系数 ⇒ 材料强度结论一律标"需查手册"，**不得编造**。
