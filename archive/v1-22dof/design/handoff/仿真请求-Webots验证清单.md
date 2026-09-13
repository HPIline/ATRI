# 仿真请求 · Webots 验证清单（给队友，2026-09-12 起）

> 本文件对应 `design/handoff/第11轮-多线程施工方案与Prompt.md` 线程表里的 **T5（仿真对接，队友机器）**，
> 交付物是 `docs/process/sim/**`（该目录尚不存在，由你创建），不是仓库线程。
>
> **背景**：本机（Mac）只有 CAD 与纯 Python 软件链，跑不了 Webots；CI 里也只有离线桩测试。
> **9.13 是 deadline，没有实物、只有仿真**，所以这份清单按「**一次跑完、直接能进材料**」写，
> 不是开放式探索：每一节都有精确命令、期望输出、判定阈值和失败后的第一排查点。
>
> **口径纪律**：所有数字必须标出处；**仿真是仿真，实测是实测，两个词不许混用**
> （仓库规矩第 4 条，出自 `docs/process/研发日志-卷1.md` §七）。
> 仿真跑出来的扭矩/位移一律写「仿真值」，不得写成「实测值」。

---

## 〇、先把现状说清楚（你动手前必读，避免白跑）

### 0.1 仓库里现有的仿真资产（已核实到当前 `main`）

| 项 | 真实路径 | 现状 |
|---|---|---|
| 世界文件 | `webots/worlds/atri_22dof.wbt` | 22 电机 / 22 位置传感器 / 23 个 Solid，全部用内置节点，**不引用任何 EXTERNPROTO** |
| 控制器入口 | `webots/controllers/atri_controller/atri_controller.py` | 复用 `atri.sim.run_task_cards`，与无硬件闭环演示**同一条链路** |
| 关节映射 | `webots/controllers/atri_controller/joint_mapping.json` | 22 条同名映射（ATRI 关节名 = Webots 电机名） |
| Nao 参考映射 | `webots/controllers/atri_controller/joint_mapping_nao.json` | 非本世界用；用它绑定 18/22 是预期行为 |
| 批量脚本（Windows） | `webots/tools/run_webots_batch.ps1` | **无人值守就靠这个**，默认 300 s 超时 |
| 批量脚本（Linux） | `webots/tools/run_webots_batch.sh` | 参数名与 ps1 对齐 |
| 世界生成器 | `webots/tools/generate_atri_world.py` | **世界文件不许手改**，改模型后重跑生成器 |
| 离线桩测试 | `webots/tests/`（`webots_api_stub.py` + `test_atri_controller.py`） | 40 项，不需要 Webots，CI 跑的就是这条 |
| 任务卡目录 | `software/atri/task_cards/` | `T-01_face.json` / `T-02_qr.json` / `T-03_carry.json` / `T-04_kick.json` / `T-05_dance.json` |

### 0.2 现有世界**回答不了**这份清单里的 S1/S2（这是最重要的一条）

我逐行读了 `webots/worlds/atri_22dof.wbt`，世界顶部写着：

```
WorldInfo {
  basicTimeStep 32
  gravity 0        # ← 生成器 GRAVITY = 0.0，注释写明「这是运动学联调世界，不是双足平衡」
  ERP 0.6
  CFM 1e-05
```

同时全文件 **没有地面**（无 `Plane` / `Floor` / `Ground`）、
**没有任何 `maxTorque` 字段**、没有 `JointState`、没有 `ContactProperties`。

后果，逐条对应你要做的事：

1. **零重力 + 无地面 → S1「静立」和 S2「站立扭矩」在当前世界里跑不出有意义的数字**。
   零重力下机器人悬浮、不下垂，电机保持力矩 ≈ 0，测出来的峰值会和纸面 1.492 N·m 差一个数量级，
   那种数字**不能进材料**。
2. **`RotationalMotor.maxTorque` 不写 ≠ 无限大，而是 Webots 默认 10 N·m**
   （官方文档：`SFFloat maxTorque 10 # [0, inf)`，`wb_motor_set_available_torque` 可运行时改）。
   10 N·m 是真实 STS3215 堵转 2.94 N·m 的 3.4 倍——**电机权限放宽了 3.4 倍，
   关节当然撑得住，结论不可用**。
3. **手头没有成品「带重力世界」**，需要新增一个派生世界（见 0.3）。
   这一步是本清单里**唯一需要动 `webots/**` 的改动**，请在动手前先确认（见 §五 前提 3）。

### 0.3 S1/S2 需要的「重力世界」怎么来（推荐两条路，任选，不要手改 `.wbt`）

`.wbt` 是生成产物，`webots/README.md` 与 CI（`python webots/tools/generate_atri_world.py` + `git diff --exit-code`）
都要求它和生成器一致，**手改会被 CI 挡下来，也会让后面所有人踩坑**。所以：

- **路 A（推荐，需仓库侧配合一次）**：请仓库主会话给
  `webots/tools/generate_atri_world.py` 加两个环境变量开关，例如
  `ATRI_WORLD_GRAVITY=9.81`、`ATRI_WORLD_MAX_TORQUE=2.94`，并让它支持
  `--out webots/worlds/atri_22dof_gravity.wbt`；同时给控制器加
  `--max-torque`（并读 `ATRI_WEBOTS_MAX_TORQUE`）来调 `setAvailableTorque()`。
  这两个改动都属于 `webots/**`，不在我这次的写权限内，**我没有实施**。
- **路 B（临时自救，不落库）**：复制一份 `.wbt` 到仓库外（例如 `%USERPROFILE%\atri_sim\`），
  在副本上手工改三处：`gravity 0` → `gravity 9.81`、
  `basicTimeStep 32` 视稳定性可降到 `8`（可选）、每个 `RotationalMotor` 加 `maxTorque 2.94`；
  再在副本世界同级放一份 `Floor`（`Plane` 或 1000×1000 的 `Box`，`size 2 2 0.01` 即可）。
  **副本产物只写进 `docs/process/sim/`，不要覆盖仓库里的 `.wbt`。**
  注意机器人的初始高度：现有世界是 `translation 0 0 0.1942`（= `robot_model.json` 的
  `base_pose_mm` z=194.2 mm），落到地面后脚垫底面在 z=0 附近，**不要自己改这个数字**。

> 无论走路 A 还是路 B，请在报告里写清用的是哪条路、世界文件路径、以及
> `gravity` / `basicTimeStep` / `maxTorque` 三个值，否则数字无法复现。

### 0.4 两条已知偏差（**必须在报告里原样复述**，不是让你去修）

**偏差 1：URDF 的 link 质量仍是历史口径，没有回灌当前 CAD 实算。**
- `design/atri.urdf` 的 23 个 link 质量合计 **3436.6 g**（我实测求和：23 个 `<mass>`，
  含结构 1790 g 历史口径），`README.md` 与 `design/handoff/骨架重构评估-组会汇报.md` §三也写明
  「URDF 仍为历史 1790 g（待回灌）」。
- CAD 现行口径是 **结构 1490 g / 81 件（实算）、整机 ≈3136 g（纸面推算，重量方案未定案）**。
- **但要注意一个已核实的分叉**：`webots/worlds/atri_22dof.wbt` 里的 23 个质量
  **合计 3136.6 g，与 `design/robot_model.json` 逐项相等**（生成器 v2 起从模型派生）。
  也就是说：**世界文件是新的、URDF 是旧的**，两者对不上。
  → 所以 `design/atri.urdf` **不能**直接当 Webots 的动力学基准；
  如果你要拿 URDF 导入 Webots 或做对比，请把这条写进报告的「与预期差异」。
- 结论：**仿真里任何质量/惯量/重力负载数字，都与 CAD 口径存在系统性偏差，
  只能当保守侧参考，不能宣称等于当前设计。**

**偏差 2：额定扭矩口径已订正，旧口径的「合格」结论作废。**
- 主判据 = **官方连续额定 0.98 N·m @12V**（`design/handoff/hardware_requirements.json`
  的 `torque_criterion.primary = "continuous_rated"`）。
- 其余两档只能当参考：**峰值 1.47 N·m**（= 堵转 ×50%，仅瞬时上限）、**堵转 2.94 N·m**。
- **如果你的仿真按旧口径 1.47 N·m 判「合格」，结论不可用**：
  CAD 侧纸面需求是踝 `left/right_ankle_pitch` **1.492 N·m（占额定 152%）**、
  `trunk_roll` **1.899 N·m（占额定 194%）**，两者**在额定和峰值两档都已超**
  （`hardware_requirements.json`：`joints_exceeding_peak = [left_ankle_pitch, right_ankle_pitch, trunk_roll]`）。

**设计侧扭矩需求表（判阈值的唯一依据，来自 `design/handoff/hardware_requirements.json`，
`required_torque_nm`，已含 1.8 安全系数）：**

| 关节 | 纸面需求 (N·m) | 占额定 0.98 | 占峰值 1.47 | 主要工况 |
|---|---|---|---|---|
| `left/right_ankle_pitch` | **1.492** | **152%** ❌ | **101%** ❌ | 单腿支撑 |
| `trunk_roll` | **1.899** | **194%** ❌ | **129%** ❌ | 上半身重力 |
| `left/right_knee_pitch` | 1.427 | 146% ❌ | 97% | 单腿支撑 |
| `left/right_hip_pitch` | 1.355 | 138% ❌ | 92% | 单腿支撑 |
| `left/right_hip_roll` | 1.308 | 133% ❌ | 89% | 单腿支撑 |
| `left/right_hip_yaw` | 1.260 | 129% ❌ | 86% | 单腿支撑 |
| `trunk_pitch` | 0.838 | 86% ✅ | 57% ✅ | 重力 |
| `left/right_shoulder_pitch` 等臂/头 11 项 | 0.250 | 26% ✅ | 17% ✅ | 工程下限 |

> 供参考的 CAD 侧结论（不是仿真值，别混写）：机械零位摆放错误 **0 对**、关节轴对齐 **22/22**、
> 实装包络 **160 × 268 × 407 mm**（`design/handoff/第11轮-多线程施工方案与Prompt.md` 引的
> `assembly.py --all --no-export` + `audit_assembly.py` 实测）、`design/cad/test_layout.py` **15 项门禁通过**。
> ⚠️ 干涉总量有两组数：`193 677 mm³`（`docs/process/研发日志-卷1.md` §一）与
> **`160 423 mm³`**（第 11 轮 prompt 里的更新值）——**本文件以 160 423 mm³ 为准**，
> 两处差异原因未见留档，**（待确认）**。

### 0.5 足部几何：S1 要回答的问题从哪来

新足底的四只垫是 **Φ8 × 13 mm 圆柱垫**，落在 **122 × 60 mm** 的板上；几何定义在
`design/cad/skeleton.py::foot_plate()`（`pad_h = 13.0`、`inset = 9.0`、
四垫中心在 `(x_rear+9, ±20)` 与 `(x_front−9, ±20)`，`cyl(8.0, ...)`）。

**⚠️ 两个足部坐标原点不是同一个，换算前先看清：**
CAD 的 `foot_plate()` 局部系里垫中心确实是 **x = −39 / +65 mm**；
但 `design/robot_model.json` 给 `left/right_foot` 的几何是
`rounded_box 110 × 60 × 19.6 @ origin_mm [18, 0, 0]`（**踝轴在盒子中间**），
`atri.urdf` 与 `atri_22dof.wbt` 用的都是这一份。
本清单里凡是标「推导值」的支撑面数字**全部来自 robot_model.json 的盒子**，
不是 CAD 的 122 mm 足板——两者不要混用。

由这份几何直推的数值（**推导值，不是实测**，公式与代入过程见下面括注）：

- 垫中心 x = **−39 / +65 mm**（CAD `foot_plate()` 局部系；踝轴为 x=0，后跟 48 mm、前掌 74 mm），
  垫外缘 **−43 … +69 mm**（= 垫中心 ± 半径 4 mm），**前后跨距 112 mm**。
- 盒子口径（= URDF/世界实际用的）：脚盒外缘 x = **−37 … +73 mm**（= 18 ± 55 mm），
  **前后跨距 110 mm**。两个口径差 2 mm，判「前后余量」时请注明用的哪一个。
- 垫外缘 y = **±24 mm**（= 垫心 ±20 ± 4），单脚**横向跨距 48 mm**。
  （注：`骨架重构评估-组会汇报.md` §五 写的是「横向跨距只有 40 mm」，那是**垫心距**口径，
  两个数都对，别当成矛盾——报告里请写清用的是哪个口径。）
- 髋 yaw 在 y = **±45 mm**（`design/atri.urdf` 的 `left/right_hip_yaw` origin；也等于门禁
  `test_layout.py::test_hip_yaw_stance_not_narrowed` 的 `HIP_YAW_Y_MIN_MM = 45.0`）。
  → 双脚支撑多边形的 y 方向范围 **±69 mm**（外缘到外缘 138 mm），x 方向 **112 mm**。
- 门禁 `test_layout.py::test_foot_heel_and_pads` 要求：后跟 `xmin ≤ −45 mm`、
  足宽 58–62 mm、垫 `zmin ∈ [−18.5, −15.5] mm`（必须是全机最低点）、单脚打印质量 ≤ 42 g。

**注意**：`webots/worlds/atri_22dof.wbt` 里左右脚的碰撞体是**一个盒子**
（`left/right_ankle_pitch_link` → `boundingObject Box { size 0.11 0.06 0.0196 }`），
**不是四个圆柱垫**。所以 S1 的「侧向能偏多少才翻」在当前世界里只能给出**盒子底面的近似值**；
想要真足底几何，需要给世界加四根 `Cylinder`（同样是 0.3 节说的仓库侧改动）。

---

## 一、一句话任务

**请在 Windows + RTX 4060 的 Webots 里，按下面 S1→S5 的顺序跑一遍 A.T.R.I. 的 22 DOF 模型：
S1 静立 10 s 量支撑多边形与质心投影余量、S2 站立时逐关节扭矩峰值（对照 0.98 / 1.47 / 2.94 N·m）、
S3 回归 `software/atri/task_cards/` 那 5 张任务卡、S4 复核 CAD 已标出的极限姿态自碰撞，
S5 录一段答辩用短视频；把结果写成 `docs/process/sim/仿真报告-20260913.md`（表格 + 原始日志 + 截图），
在 2026-09-13 中午前回传，报告里每一个数字都要标「仿真值 / 设计值 / 推导值」。
如果 S1/S2 需要的重力世界一时批不下来，就先交 S3（唯一不依赖新世界的场景），
并在报告里写明 S1/S2 卡在哪一步——不要用零重力世界的数字充数。**

---

## 二、执行清单（可直接复制粘贴）

> 所有命令都在仓库根目录执行（例：`cd C:\Users\<你>\ATRI`）。
> `webots` 若不在 PATH，ps1 脚本会自动找
> `C:\Program Files\Webots\msys64\mingw64\bin\webots.exe`，找不到就 `-Webots` 指定。

### S0（前置，5 分钟）：在动手前先把环境和基线钉死

```powershell
# 1) 版本与机器信息（要贴进报告）
webots --version
webots --sysinfo
python --version

# 2) 拉最新 main 并确认提交号
git fetch --all
git log --oneline -3            # 期望看到 0533f55（第 6–10 轮 CAD 已合入）

# 3) 不需要 Webots 的离线回归（40 项，先确认软件链没坏）
python -m unittest discover -s webots\tests -v

# 4) 世界文件与生成器是否同步（CI 同款检查）
python webots\tools\generate_atri_world.py
git diff --exit-code -- webots\worlds\atri_22dof.wbt
```

- **期望输出**：`webots --version` 给出 **R2023b 或更新**（仓库在 R2025a 上实测过）；
  第 3 步 40 项全过；第 4 步 `git diff` 为空（退出码 0）。
- **判定阈值**：第 3 步有任何 fail、或第 4 步产生 diff → **停下来先修环境**，
  不要带着脏世界跑 S1–S4。
- **失败先查**：Python 版本要和 Webots 设置里的 `Python command` 一致
  （`webots/README.md`「注意」：命令行是 3.12，Webots 里也要指同一个）；
  第 4 步有 diff 时**先 `git checkout -- webots/worlds/atri_22dof.wbt` 还原**再排查。

---

### S1 · 静立：支撑多边形与质心投影（**必须先有 0.3 节的带重力世界**）

**目的**：回答两个问题——(a) 双足站立 10 s 时质心投影是否落在支撑多边形内、余量多少；
(b) **侧向能偏多少才翻**（CAD 侧已判定「四只孤立 Φ8 垫 + 轨距偏窄 = 踩高跷」，
这是替代实物做侧翻验证的唯一途径）。

**命令（两段式：先无渲染跑数，再开 GUI 看动作）**

```powershell
# S1-a 无人值守跑数（世界换成 0.3 节产出的带重力世界）
powershell -File webots\tools\run_webots_batch.ps1 `
  -World  <带重力世界.wbt 的绝对路径> `
  -Report docs\process\sim\s1_report.json `
  -Log    docs\process\sim\s1_console.log `
  -TimeoutSec 600

# S1-b 带界面看 10 秒静立（可选，用于截图）
webots --mode=realtime webots\worlds\atri_22dof_gravity.wbt
```

同时在控制器侧需要「站 10 s 不动」而不是跑任务卡。最快做法是在带重力世界副本里把
`ATRI_WEBOTS_TASK_CARD_DIR` 指向一个空目录（控制器会 0/0 跑完并退出，**但退出码不是 0**，
所以别拿退出码判定 S1，只看报告 JSON 和日志）：

```powershell
$env:ATRI_WEBOTS_TASK_CARD_DIR = "docs\process\sim\empty_cards"   # 先建这个空目录
$env:ATRI_WEBOTS_EXIT_ON_DONE  = "1"
$env:ATRI_WEBOTS_REPORT        = "docs\process\sim\s1_report.json"
$env:ATRI_WEBOTS_LOG           = "docs\process\sim\s1_console.log"
webots --batch --mode=fast --no-rendering --minimize --stdout --stderr <带重力世界.wbt>
```

**要记录的 6 个数（每个都写清是仿真值还是推导值）**

| # | 量 | 怎么取 |
|---|---|---|
| 1 | 站立 10 s 内**是否翻倒** | 目视 + `Robot` 根节点姿态；报告写「10 s 内倾倒 / 未倾倒」 |
| 2 | **质心投影 (x, y)** | 控制器侧取各 Solid 世界位姿后按质量加权；或 GUI 里 `Robot > Show Center of Mass` 截图 |
| 3 | **支撑多边形顶点** | 四个垫中心的实际世界坐标（或盒子底面的四角） |
| 4 | **投影到边界的最小余量 (mm)** | 前/后/左/右四个方向分别给 |
| 5 | **侧向极限偏移 (mm)** | 逐步给 `trunk_roll` 或整体质心加偏置，直到翻倒；记为「侧向 ±XX mm 翻倒」 |
| 6 | 关节实际回读角 | 报告 `joint_travel_deg`（证明真的站住了，不是逻辑跑通） |

**判定阈值（两个口径都要，别只给一个）**

- 参考值 A（**设计值**，来自 `hardware_requirements.json` 与 URDF 质量分布）：
  零位质心高度 ≈ **186 mm**（骨盆世界 z=194.2 + 质心相对骨盆 −8.0 mm，23 link 质量加权求和），
  质心相对踝轴 x ≈ **+1.2 mm**。
- 参考值 B（**推导值**，见 0.5 节几何）：静止站立时质心到支撑边界的余量应为

  | 口径 | 后 | 前 | 侧（单侧） | 说明 |
  |---|---|---|---|---|
  | CAD 四只 Φ8 垫（设计几何） | ≈43 mm | ≈68 mm | ≈69 mm | 垫外缘 x −43…+69、y ±24，髋 y=±45 |
  | URDF/世界脚盒 110×60（仿真实际用的） | ≈38 mm | ≈72 mm | ≈75 mm | 盒外缘 x −37…+73、y ±30（=±45±30） |

  以你实测为准，并**注明用的是四垫还是盒子口径**（两者差 2–6 mm，别混着报）。
- 通过判据：**10 s 不翻倒** 且 **质心投影在支撑多边形内**；
  并给出「侧向再偏多少毫米翻倒」这个数——**这才是 CAD 侧要的答案**（越大越好，无硬阈值，
  但必须给数，且注明是四垫口径还是盒子口径）。

**失败先查什么（按顺序）**

1. 机器人是否在 z=0 悬浮或直接穿地 → `translation 0 0 0.1942` 是否被改；
2. 是否脚垫不是最低点 → 那是世界用了盒子脚（见 0.5 节），在报告里注明；
3. `basicTimeStep 32` 太大导致接触抖动/穿透 → 降到 8 再试一次，报告里注明用了哪个；
4. 电机 `maxTorque` 是否为默认 10 → 未降到 2.94 时站立会「过于轻松」，数字不可用。

---

### S2 · 逐关节扭矩峰值（**与 S1 同一个带重力世界**）

**目的**：拿到站立工况下**每个关节的扭矩峰值**，与 **0.98 N·m 连续额定 / 1.47 N·m 峰值 /
2.94 N·m 堵转**三档对照。**重点看** `left_ankle_pitch`、`right_ankle_pitch`、`trunk_roll`、
`left_hip_pitch`、`right_hip_pitch`（这 5 个纸面需求最紧），膝与髋 yaw/roll 作补充。

**命令**：与 S1 同一世界、同一批环境变量。**但当前控制器不读扭矩**——
`atri_controller.py` 只调 `getPositionSensor().getValue()`，
全 `webots/` 目录内**没有任何扭矩相关代码**（我 grep 过：`maxTorque` / `force` / 扭矩 均 0 命中）。
所以要么按 0.3 节路 A 让仓库侧加开关，要么用下面这段**独立的最小控制器/脚本**取扭矩反馈
（**不改仓库的控制器**，放在 `docs/process/sim/` 下）：

```python
# docs/process/sim/torque_probe.py —— 静止站立工况下逐关节扭矩峰值
# 放在 docs/process/sim/ 下，把带重力世界副本的 Robot.controller 指到它（或写绝对路径）。
# 只做三件事：下发一次零位站姿 -> 保持 10 仿真秒 -> 记录峰值扭矩。
from controller import Robot
import json
import math

VELOCITY = 2.0          # rad/s，与 atri_controller.py 的 DEFAULT_VELOCITY 一致
HOLD_SIM_S = 10.0       # 站立观察时长（仿真秒）

# 机械零位站姿（design/atri.urdf 的零位；肘部 rest 不是 0，见 software/atri/atri/config.py::rest_pose）
REST_DEG = {"left_elbow_pitch": -10.0, "right_elbow_pitch": -10.0}

# 全部 22 个关节都下发目标角（漏掉的那个会在重力下瘫掉，但扭矩记成 0，看着像"很轻松"）
ALL_JOINTS = [
    "head_yaw", "head_pitch", "trunk_pitch", "trunk_roll",
    "left_shoulder_pitch", "left_shoulder_roll", "left_elbow_pitch", "left_gripper",
    "right_shoulder_pitch", "right_shoulder_roll", "right_elbow_pitch", "right_gripper",
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee_pitch", "left_ankle_pitch",
    "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee_pitch", "right_ankle_pitch",
]

robot = Robot()
dt = int(robot.getBasicTimeStep())

motors, sensors = {}, {}
for name in ALL_JOINTS:
    m = robot.getDevice(name)
    if m is None:
        print(f"[torque_probe] 找不到电机 {name}"); continue
    m.setVelocity(VELOCITY)                       # 不设速度会瞬间到位，看不出过程
    m.enableTorqueFeedback(dt)                    # ★ Webots Python API
    s = m.getPositionSensor()
    if s is not None:
        s.enable(dt)                              # 未 enable 的 PositionSensor 返回 NaN
    motors[name] = m
    sensors[name] = s
    print(f"[torque_probe] 已绑定 + 扭矩反馈: {name}")

# 下发零位站姿
for name, m in motors.items():
    m.setPosition(math.radians(REST_DEG.get(name, 0.0)))

peak_abs, lo, hi = {n: 0.0 for n in motors}, {n: 0.0 for n in motors}, {n: 0.0 for n in motors}
steps = 0
while robot.step(dt) != -1:
    steps += 1
    for name, m in motors.items():
        t = m.getTorqueFeedback()
        if t != t:          # 过滤 NaN
            continue
        peak_abs[name] = max(peak_abs[name], abs(t))
        lo[name] = min(lo[name], t)
        hi[name] = max(hi[name], t)
    if steps * dt >= HOLD_SIM_S * 1000:
        break

payload = {
    "sim_seconds": steps * dt / 1000.0,
    "velocity_rad_s": VELOCITY,
    "note": "峰值扭矩为 |τ| 最大值；lo/hi 是带符号的最小/最大值，用于判断加载方向",
    "peak_abs_torque_nm": {k: round(v, 4) for k, v in peak_abs.items()},
    "min_torque_nm": {k: round(v, 4) for k, v in lo.items()},
    "max_torque_nm": {k: round(v, 4) for k, v in hi.items()},
    "final_joint_deg": {k: round(math.degrees(s.getValue()), 2)
                        for k, s in sensors.items() if s is not None},
}
with open("docs/process/sim/s2_torque_peak.json", "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2)
print(json.dumps(payload, ensure_ascii=False, indent=2))
```

> **必须在世界副本里把每个 `RotationalMotor` 的 `maxTorque` 设成 2.94**
> （或按 0.3 节路 A 用 `setAvailableTorque(2.94)`），否则电机可用扭矩是默认 **10 N·m**，
> 峰值扭矩看起来「要多少有多少」，结论直接作废。这一条是本场景最容易踩的坑，
> 请在报告里显式写出你设的值。
>
> **`final_joint_deg` 是关键的自检字段**：它应该接近 0（肘 ≈−10）。
> 如果它明显偏离（腿软下去、关节被压到限位），说明 2.94 N·m 撑不住这个站姿——
> **那本身就是 S2 要的结论**，照实写，不要偷偷把 `maxTorque` 调大再跑一遍。

**期望输出**：`docs/process/sim/s2_torque_peak.json`，形如

```json
{ "sim_seconds": 10.0, "velocity_rad_s": 2.0,
  "peak_abs_torque_nm": { "left_ankle_pitch": 0.xx, "right_ankle_pitch": 0.xx,
                          "trunk_roll": 0.xx, "left_hip_pitch": 0.xx, "...": 0.0 },
  "min_torque_nm": { "...": 0.0 }, "max_torque_nm": { "...": 0.0 },
  "final_joint_deg": { "left_ankle_pitch": 0.xx, "left_elbow_pitch": -10.xx, "...": 0.0 } }
```

**判定阈值**（三级，三档都要给，别只给一个「合格」）

| 档 | 阈值 | 含义 |
|---|---|---|
| 连续额定 | **0.98 N·m** | **主判据**；超过即「超额定」，站不久（温升） |
| 峰值 | **1.47 N·m** | 堵转 ×50%，仅瞬时上限；超过即「连瞬时都超」 |
| 堵转 | **2.94 N·m** | 物理上限，超过说明该姿态下电机根本保持不住 |

对照 S2 数字与 §0.4 的设计值表，逐关节给出「仿真 / 设计值」比值。
**预期方向**：由于世界质量（3136.6 g）比 URDF（3436.6 g）轻约 9%，且世界用简化碰撞体，
仿真峰值**大概率低于**纸面 1.492 / 1.899 N·m——**这是预期的，不是好消息**，
报告要写成「仿真偏保守，不能据此宣布合格」，并把两个数并排列出。

**失败先查什么**

1. `getTorqueFeedback()` 全是 0 → `enableTorqueFeedback(dt)` 没调、或调在了 `robot.step()` 之后；
2. 数字大得离谱（>10 N·m）→ `maxTorque` 没设，还是默认 10；
3. 名字对不上 → 电机名以 `joint_mapping.json` 的 22 个键为准（与 `robot_model.json` 的关节名逐一对应）；
4. 想要「髋/踝单独承重」的极限值 → 那是 S4 的活，S2 只报**双足静止站立**工况，别混。

---

### S3 · 任务回归：跑 CI 里那套 5 张任务卡（**不需要新世界，先跑这个**）

**目的**：确认第 6–10 轮 CAD 改动与 T-03 软件改动**没有破坏任务流程**。
这是唯一一条在**现有零重力世界**里就能跑、且结论可用的场景。

**命令（直接复用仓库脚本，一行）**

```powershell
powershell -File webots\tools\run_webots_batch.ps1 `
  -World  webots\worlds\atri_22dof.wbt `
  -Report docs\process\sim\s3_report.json `
  -Log    docs\process\sim\s3_console.log `
  -TimeoutSec 300
```

（脚本内部就是 `webots --batch --mode=fast --no-rendering --minimize --stdout --stderr <world>`，
并设好 `ATRI_WEBOTS_EXIT_ON_DONE / _REPORT / _LOG` 三个环境变量。
**Webots 没有向控制器透传命令行参数的机制**，别想着在 `webots ...` 后面加 `--` 传参。）

想跑 GUI 看动作：`webots webots\worlds\atri_22dof.wbt`，世界的 `controller` 字段已指向
`atri_controller`，Webots 自己会找到，**不需要手工设 `<extern>`**。

**期望输出**（`docs/process/sim/s3_report.json`，字段名以控制器实际写出的为准）

```json
{ "passed": 5, "total": 5,
  "bound_joints": 22, "mapped_joints": 22, "binding_ok": true, "motion_ok": true,
  "expected_joints": 22, "unbound_joints": [],
  "mapping": "joint_mapping.json",
  "basic_time_step_ms": 32, "velocity_rad_s": 2.0,
  "sim_seconds": 14.48, "sim_steps": 452, "wall_seconds": 0.247,
  "simulation_alive": true, "moved_joints": 18,
  "joint_travel_deg": { "head_yaw": 31.85, "...": "每个关节一项，共 22 项" },
  "tasks": [{"task_id": "T-01", "ok": true,
             "history": ["STANDBY","ENTERING","EXECUTING","FEEDBACK","DONE"], "error": null}] }
```

**判定阈值**

- **5/5 通过**（`passed == total == 5`，逐张卡 `T-01`…`T-05` 全 `ok: true`）；
- **绑定 22/22**（`bound_joints == mapped_joints == 22`，`binding_ok: true`）；
- **至少 1 个关节行程 > 1°**（`motion_ok: true`，报告 `moved_joints`）；
- **仿真全程存活**（`simulation_alive: true`）；
- 脚本退出码 **0**（2 = 未通过，3 = 找不到 webots 或世界文件）。
- 已知可接受项：`left/right_hip_yaw`、`left/right_hip_roll` 四个关节行程为 **0**
  （现有 5 张任务卡不会走到用它们的动作支，`webots/README.md` 已记录为运动设计待补项）。
  报告里把这 4 个单独列出来，别当成回归失败。

**失败先查什么**

1. **一个关节都没绑定** → 世界文件被改坏（最典型：`gravity` 写成了三个数 `0 0 0`，
   Webots 会**静默回退到内置 `empty.wbt`**，机器人根本不存在且控制台无报错）；
   用 `git diff -- webots/worlds/atri_22dof.wbt` 确认；
2. `unbound_joints` 非空 → 电机改名/映射写错；`mapping_problems` 会给出原因；
3. 报告压根没出现（脚本超时 300 s） → 看 `-Log` 尾部 40 行（脚本会自动打），
   常见原因是 Python 解释器不对或 `software/atri` 路径没带上；
4. `motion_ok: false` → `ATRI_WEBOTS_VELOCITY=0` 会让电机锁死，任务卡照样「逻辑上」全过。

---

### S4 · 极限姿态：复核 CAD 已标出的自碰撞

> ## 🛑 2026-09-12 14:20 **重大更正：下面这 4 组姿态来自已废弃的旧报告，请不要再去复核它们**
>
> 本节原来引用的 `design/cad/out/sweep_report.md` 是**旧版 `sweep_check.py`** 的产物，
> 该脚本有 **4 个致命缺陷**（2026-09-12 T2 线程实测定位，见 `design/handoff/姿态扫掠报告.md` §二）：
> 1. 零位基线**从未用 FK 摆到世界位姿**；
> 2. 排序按**绝对体积**而不是"扣基线后的新增"；
> 3. **几何来源是 URDF `<collision>` 的实心包络代理块，不是真实零件 ⇒ 基线虚高 43×**；
> 4. 缺全部交付物。
>
> ⇒ 下面表里那些 **65 000 / 30 000 mm³ 级的"❌ 摆放错误"是代理块造成的假象**，
> 例如 `right_forearm ↔ torso_upper` 66 519 mm³ ——用真实零件重算根本不存在。
> **请不要按它去 Webots 里复现**，那是白跑。
>
> **✅ 真实的 S4 目标（新报告实测，双原语复核过）只有一条**：
> `trunk_roll` 在**它自己的 URDF 限位 ±10°** 处，`servo__right_gripper ↔ servo__right_hip_pitch`
> 新增互穿 **7 644.4 mm³**（零位 0 mm³；`−10°` 侧对称族 3 787 mm³）。
> **请在 Webots 里做的就这一件事**：把 `trunk_roll` 摆到 **+10°** 与 **−10°**，
> 可视化确认"右侧/左侧夹爪舵机是否真的插进同侧髋 pitch 舵机"，并截图。
> 另外 **19/22 个关节的首撞角尚未测出**（扫描进程被超时终止），
> 所以**不要**把 S4 当"全机极限姿态复核"，它现在只是一个单点确认。
> 完整依据与建议限位见 `design/handoff/姿态扫掠报告.md` §六。

**目的**：CAD 侧用**同一份 `design/atri.urdf`** 做过极限姿态扫掠，已经报出高危自碰撞
（`design/cad/out/sweep_report.md`，运行模式 `quick`，116 个采样姿态，耗时 75.3 s）。
现在要在 Webots 里**用可视化确认**这些结论、并留下能进材料的图/视频。
**不要做开放式探索**——直接复现下面这 4 个已知姿态即可。

**判定阈值（先知道结论，再去验证）**：CAD 侧排名前 4 的高危对与触发姿态
（角度全部取自 `design/cad/out/sweep_report.md`，逐字抄录）：

| 排名 | 碰撞对 | 最大侵入 | 判定 | 关键角度（摘） |
|---|---|---|---|---|
| 1 | `right_forearm` ↔ `torso_upper` | 66 519 mm³ | ❌ 摆放错误 | `right_shoulder_roll=87.0(max)`、`left_shoulder_roll=57.2`、`left_knee_pitch=80.5`、`right_hip_pitch=36.3` |
| 2 | `left_forearm` ↔ `torso_upper` | 65 630 mm³ | ❌ 摆放错误 | `left_shoulder_roll=-86.4(min)`、`left_knee_pitch=89.8(max)`、`right_hip_pitch=28.1` |
| 3 | `pelvis` ↔ `right_forearm` | 38 221 mm³ | ❌ 摆放错误 | `left_elbow_pitch=-83.9`、`right_elbow_pitch=-46.4`、`left_hip_yaw=-35.0`、`trunk_roll=9.8(max)` |
| 4 | `left_shank` ↔ `right_foot` | 30 670 mm³ | ❌ 摆放错误 | `left_knee_pitch=2.8(min)`、`right_hip_roll=17.8`、`right_hip_yaw=-1.8`、`left_ankle_pitch=-28.5` |

（第 5–21 名与每个姿态的 22 个关节完整角度见 `design/cad/out/sweep_report.md`，
请整份拷进 `docs/process/sim/` 一起回传。）

**命令**：用能改关节角的方式把这 4 组姿态逐组摆出来。三种做法按成本排序：

1. **GUI 手摆（最快，够用）**：`webots webots\worlds\atri_22dof.wbt`，
   打开 `Scene Tree` 里对应的 `HingeJoint > jointParameters > position`（或电机 `position`），
   按表格角度填，然后截图/录像。**零重力世界里机器人不会倒**，正适合看姿态。
2. **写一个小控制器**：复用 `atri.cerebellum.Cerebellum.set_pose()`（它按名下发、
   自动按 `limit_deg` 钳制、未知关节名抛 `ValueError`），把 4 组姿态写成 JSON 循环下发。
   入口参考 `webots/controllers/atri_controller/atri_controller.py` 的 `WebotsServoBus`。
   **放在 `docs/process/sim/`，不要改仓库控制器。**
3. **跑 CAD 侧全量扫掠**（不需要 Webots，但会占 CPU 1–2 分钟以上）：
   `.venv-cad/bin/python design/cad/sweep_check.py --quick` —— 本机在跑别的重活，
   **请等主会话确认空闲后再跑**，不要在队友的 Windows 机上跑这个（那是 CAD 环境）。

**要判的三件事**

| 项 | 怎么判 | 注意 |
|---|---|---|
| **自碰撞** | 4 组姿态里是否出现 CAD 报告的那几对件互相穿模 | 配合面（关节笼包舵机、连杆叉穿舵机轮廓）**是允许的**，别把它们算成碰撞；`fitcheck.is_joint_mate` 已把这类白名单化 |
| **穿地** | 关节最低点是否低于地面 | **零重力世界没有地面**，这一项只能在 0.3 节的带重力世界里做；两个世界的结论要分开写 |
| **关节超限** | 指令角是否被限位截停 | 限位以 `design/robot_model.json` 的 `limit_deg` 为准（22 项，例：`left_ankle_pitch [-40,40]`、`trunk_roll [-10,10]`、`left_elbow_pitch [-120,0]`、`left_knee_pitch [0,90]`）；世界里另有 `minStop/maxStop` 硬限位，**两处同源**。注意 `motor.setPosition()` 受 `minPosition/maxPosition` **软限位**约束，而当前世界**没写这两个字段**，默认关闭——所以「没被截停」不等于「没超限」，要拿命令角自己去比 `limit_deg` |

**失败先查什么**：世界被手改坏（`git diff`）、姿态值抄错（对照 `sweep_report.md` 原文）、
GUI 里改的是 `position` 而不是 `jointParameters` 的限位。

---

### S5 ·（可选）答辩用短视频

**目的**：一段能直接剪进答辩材料的短片。**S3 的动作 + S1/S2 的静立**各录一段就够。

| 项 | 建议值 | 说明 |
|---|---|---|
| 机位 1（主） | 等轴测，约 `(0.45, -0.45, 0.35)` 看向 `(0, 0, 0.19)` | 能同时看到脸、手、脚与地面 |
| 机位 2 | 正侧视（沿 ±Y 看 XZ 面） | **侧翻/重心**这类结论必须用侧视，正视看不出来 |
| 机位 3 | 足部特写 | 拍四只 Φ8 垫与地面接触，配合 S1 的侧向极限 |
| 时长 | 单段 **20–30 s**，总 3 段以内 | 答辩时间紧，宁短勿长 |
| 分辨率/帧率 | **1920×1080 @ 30 fps** | RTX 4060 足够；别开 4K，剪辑和邮件都吃不消 |
| 模式 | `--mode=realtime`（**不要** `--mode=fast`） | `--mode=fast` 会跑成加速，录出来的动作快得看不清；GUI 里也可以直接点工具栏录制按钮 |
| 命名 | `docs/process/sim/video/S3_任务回归_20260913.mp4` 等 | 文件名带场景号与日期 |

**判定**：能看清「22 个关节在动」+「任务卡依次执行」+「足部着地」三件事即可；
**录制时不要裁掉锁盘配合面**——那是真实装配关系，不是穿模。

---

## 三、回报格式

### 3.1 落盘位置（**新建目录**，当前仓库里没有 `docs/process/sim/`）

```
docs/process/sim/
├── 仿真报告-20260913.md          # ★ 主报告，格式见 3.2
├── s1_report.json                # S1 的控制器报告（原始）
├── s1_console.log                # S1 控制台全文
├── s2_torque_peak.json           # S2 扭矩峰值（原始）
├── s3_report.json / s3_console.log
├── sweep_report.md               # 从 design/cad/out/ 拷来，供对照
├── video/                        # S5 短片
├── shots/                        # 截图（每个场景≥2 张，文件名带场景号）
└── worlds/                       # 你实际用的世界副本（含 gravity/maxTorque 改动处截图）
```

报告文件名用**当天日期**（例：`仿真报告-20260913.md`）。报告里每个数字后面用括号标出处，例如
`1.42 N·m（仿真值，s2_torque_peak.json，10 s 静止站立，maxTorque=2.94）`。

### 3.2 主报告骨架（直接抄这个结构）

```markdown
# A.T.R.I. Webots 仿真报告 · 20260913

## 0. 运行环境（必填）
| 项 | 值 |
|---|---|
| 机器 | <CPU / GPU / 内存>（`webots --sysinfo` 原文粘贴） |
| Webots 版本 | <R20xx，`webots --version` 原文> |
| Python | <`python --version`>，Webots 设置里的 Python command：<路径> |
| 仓库提交 | <`git log --oneline -1`> |
| 世界文件 | <路径> + gravity=<值> + basicTimeStep=<值> + 各电机 maxTorque=<值> |
| 每个场景耗时 | <墙钟秒数 + 仿真秒数> |

## 1. 总表（场景 / 命令 / 关键数字 / 判定 / 与预期差异）
| 场景 | 命令（原文） | 关键数字 | 判定 | 与预期差异 |
|---|---|---|---|---|
| S1 静立 | `powershell -File webots\tools\run_webots_batch.ps1 -World ...` | 质心投影(x,y)=…；余量 后/前/侧=…mm；侧向极限=±…mm | 通过/不通过 | 与 §0.5 推导值比，差在哪 |
| S2 扭矩 | `python docs\process\sim\torque_probe.py` | 踝 L/R=…；trunk_roll=…；hip_pitch L/R=…（N·m） | 相对 0.98/1.47/2.94 三档逐项 | 与 1.492/1.899 设计值比，偏低多少、为什么 |
| S3 任务回归 | `powershell -File webots\tools\run_webots_batch.ps1` | 5/5；绑定 22/22；行程关节 18/22；仿真 14.48 s | 通过/不通过 | 与 2026-09 基线是否一致 |
| S4 极限姿态 | <命令> | 4 组姿态的碰撞对与最大侵入 | 复现/未复现 | 与 sweep_report.md 的差 |
| S5 短片 | <录制方式> | <时长/分辨率/文件> | 可用/不可用 | — |

## 2. 逐场景详情
（每个场景：目的 / 实际命令 / 原始输出粘贴 / 截图引用 / 判定 / 异常与排查过程）

## 3. 口径声明（★ 不许省）
- 本报告中的 **仿真值**：<逐条列出，例：S1 质心投影、S2 全部扭矩峰值、S3 行程角>
- 本报告中的 **设计值/纸面值**：<例：1.492 N·m、1.899 N·m、3136 g、1490 g/81 件、407×263×146 mm>
- 本报告中的 **推导值**：<例：支撑多边形 112×138 mm、质心高 186 mm>
- **本次仿真未覆盖**：<见 §四清单>

## 4. 已知偏差复述
（把本清单 §0.4 两条偏差原样抄一遍，并说明它们如何影响本次结论）

## 5. 待确认项
（把本清单 §五 的条目按你的实际情况逐条回答）
```

### 3.3 三条硬要求

1. **数字必须标来源**：写 `1.42 N·m（仿真值，s2_torque_peak.json）`，
   不要写「实测 1.42 N·m」。仓库规矩第 4 条：**仿真是仿真，实测是实测，两个词不许混用**。
2. **仿真值 / 设计值 分两张表或两列**，不要混在一格里。凡是从
   `design/robot_model.json`、`hardware_requirements.json`、`README.md`、`sweep_report.md`
   拿来的数，一律标「设计值」。
3. **原始日志与截图必须同目录回传**。只有结论没有原始输出的报告，
   在仓库里会被当成「不可复现」（规矩第 1 条：参数必须有出处）。

---

## 四、已知偏差与不可回答的问题

### 4.1 两条已知偏差（会直接改变结论，必须在报告里复述）

**偏差 1 · URDF 质量未回灌 CAD 实算。**
`design/atri.urdf` 的 23 个 link 质量合计 **3436.6 g**（历史口径，结构 1790 g），
CAD 现行是 **结构 1490 g / 81 件（实算）、整机 ≈3136 g（纸面推算，未定案）**。
世界文件 `atri_22dof.wbt` 的质量**已经**是 3136.6 g（从 `robot_model.json` 派生），
但 URDF 还是旧的——**两份模型质量不一致**。
影响：惯量与重力负载**偏保守**（URDF 重约 9%），
所以任何基于 URDF 的仿真都会**高估**扭矩需求、**低估**稳定性；
反过来，任何基于当前世界质量的仿真会**低估**扭矩需求。
**两条路都得在报告里写明用的是哪一份质量。**

**偏差 2 · 额定扭矩口径已订正为 0.98 N·m @12V（堵转 2.94 N·m）。**
旧口径「堵转 ×50% = 1.47 N·m」**只能当瞬时峰值参考**。
按旧口径判「合格」的结论**不可用**。主判据表见 §0.4。

### 4.2 Webots **不能**回答什么（写进报告的「未覆盖」一节，别让评审误读）

1. **真机电流与温升**。Webots 不做电机热模型；本项目连「额定 0.98 N·m」本身都是
   **12V 变体推断值，待买 1 只 STS3215 实测**（`design/handoff/STS3215-官方规格书核验.md` §4.1）。
   仿真最多告诉你「需要多大扭矩」，**永远不能告诉你「舵机扛不扛得住温升」**。
2. **PETG 的蠕变与层间强度**。打印件的长期变形、层间剥离、螺钉座压溃，
   都是材料与工艺问题；Webots 的刚体 + `boundingObject` 里没有这一层。
   （零件质量按 PETG 1.27 g/cm³ + 外壁/填充估算，见 `design/cad/out/report.md`。）
3. **1 Mbps 总线时序**。22 只 STS3215 共用一条并联总线，SYNC WRITE 的帧长、
   20 ms 控制周期的余量、丢包与重试，这些必须在真机（或假串口单测）上验，
   见 `software/atri/atri/bus_sts3215.py` 与 `design/handoff/给Grok-真机链路对接文档.md`。
4. **打印件装配公差**。配合公差 0.2–0.5 mm 量级；`interference.py` 已明确
   「<10 mm³ 的干涉没有工程意义」。仿真里看到的微穿模**不代表装不上**，
   反之仿真里没碰撞**也不代表装得上**。
5. **电池实际续航**。现选 3S 2000 mAh，按订正后的平均电流约 18.92 A
   **只能支撑约 13 分钟**；30 min 需要标称 11.83 Ah / 整包约 1.19 kg
   （`骨架重构评估-组会汇报.md` §三）。**答辩材料里不要写「30 分钟续航」**，
   仿真也给不出续航。
6. （补充）**真实平衡控制**。现有世界是**零重力运动学联调**世界，
   连带重力版本也只是刚体静力学；真正的步态平衡要等硬件样机 + IMU。

### 4.3 顺带说清：这些数字**不是**仿真值

包装络 **407 × 263 × 146 mm**、结构 **1490 g / 81 件**、整机 **≈3136 g**、
零位摆放错误 **0 对**、轴对齐 **22/22**、门禁 **15 项**、干涉 **160 423 mm³**、
踝 **1.492 N·m**、`trunk_roll` **1.899 N·m** —— 全部是 **CAD 侧设计/实算值**，
不是仿真值，也不是实测值。报告里引用时请保留这个前缀。

---

## 五、需要你确认的前提（**动手前先回一句**）

请逐条回答（不确定就写「不确定」，别猜）。**下面 1、2、4、5、6 条我无法从这台 Mac 核实，全部标（待确认）；3、7 条需要你拍板。**

1. **Webots 版本**：R2025a？还是别的？仓库在 **R2025a** 上实测通过，最低要求 R2023b
   （`webots/README.md` / `docs/process/工程说明.md` §3）。**你机器上的实际版本（待确认）**——
   `webots --version` 与 `webots --sysinfo` 的原文各贴一份。
2. **world 文件是否需要更新到当前 CAD（待确认）**：
   我核实的结果是——`webots/worlds/atri_22dof.wbt` 的**质量已与 `design/robot_model.json`
   逐项相等（3136.6 g）**，但**几何仍是 `geometry.py` 的基元**（脚是一个盒子，不是四只 Φ8 垫），
   而 CAD 侧第 6–10 轮改的是**零件形状**（U 形骨盆、头壳封顶、足底四垫、背挂外移）。
   也就是说：**质量新、几何粗**（这是我从文件读出来的，不是从谁的转述）。请确认：
   (a) 你能接受用「基元几何 + 新质量」跑 S1–S4，还是需要仓库先把 CAD 实装几何导进世界？
   (b) 若需要，请说明你机器上是否有 CadQuery/OCCT 环境来接手转换（**Mac 这台不跑 CAD**）。
3. **S1/S2 的带重力世界**：能不能按 §0.3 路 A 让仓库侧加
   `ATRI_WORLD_GRAVITY` / `ATRI_WORLD_MAX_TORQUE` / `--out` 三个开关？
   还是你走路 B 自己派生副本？**这一条不确认，S1/S2 就别开跑**——
   零重力世界的数字会被误读成「站得住」。
4. **跑一次要多久**：
   我这边只有一条基线可引：**5/5 任务卡在 452 步内跑完、仿真 14.48 s、墙钟 0.247 s**
   （`webots/README.md` 实测，零重力 + `--mode=fast`）。
   S1/S2 带重力 + 接触 + 10 仿真秒的墙钟时间**未知（待确认）**——
   请你实测一次后把「仿真秒 : 墙钟秒」的比值告诉我，我们据此排 deadline 前的迭代次数。
5. **GPU / headless 限制（待确认）**：
   (a) RTX 4060 Laptop 上 GUI 与 `--mode=realtime` 录屏是否流畅？
   (b) 你是否有能长期无人值守跑批的环境（`--batch --no-rendering`）？
   (c) 有没有 Windows 上 `webots.exe` 不在 PATH 的情况（脚本会退回
   `C:\Program Files\Webots\...`，仍找不到需 `-Webots` 指定）？
6. **Python 版本（待确认）**：命令行 Python 与 Webots 设置里的 `Python command` 是否同一个？
   （`webots/README.md`「注意」：不一致会导致控制器起不来。）
7. **能投入的机时**：9.13 之前你能给这台机器多少小时？
   如果只有 1–2 小时，**优先顺序是 S3 → S1 → S2 → S4 → S5**；
   S3 不需要新世界，S1/S2 依赖第 3 条确认。

---

## 附：本次核实过的路径与名字（照抄，别改大小写）

```
webots/worlds/atri_22dof.wbt
webots/tools/generate_atri_world.py
webots/tools/run_webots_batch.ps1        # Windows，参数：-World -Report -Log -Webots -Mapping -TimeoutSec
webots/tools/run_webots_batch.sh
webots/controllers/atri_controller/atri_controller.py
webots/controllers/atri_controller/joint_mapping.json
webots/controllers/atri_controller/joint_mapping_nao.json
webots/tests/test_atri_controller.py
webots/tests/webots_api_stub.py
software/atri/task_cards/T-01_face.json  … T-05_dance.json
software/atri/atri/sim.py                # run_task_cards 在这
software/atri/run_demo.py
design/robot_model.json                  # L1 单一事实来源（23 link / 22 关节，v3）
design/atri.urdf                         # 仍是历史质量口径
design/cad/test_layout.py                # 15 项布局门禁
design/cad/skeleton.py                   # foot_plate() 四垫几何在这
design/cad/out/sweep_report.md           # 极限姿态自碰撞（S4 的对照）
design/cad/out/report.md                 # 零件质量表
design/handoff/hardware_requirements.json  # 逐关节扭矩需求（S2 的对照）
design/handoff/骨架重构评估-组会汇报.md
design/handoff/第11轮-多线程施工方案与Prompt.md   # 本文件对应的 T5
docs/process/工程说明.md                  # §3 Webots 环境
docs/process/研发日志-卷1.md              # §七 六条规矩
.github/workflows/ci.yml                 # CI 跑什么
```
