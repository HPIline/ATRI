# A.T.R.I. (Autonomous Tabletop Robotic Intelligence)

> **全称**：AUTONOMOUS TABLETOP ROBOTIC INTELLIGENCE（桌面自主人形智能）  
> **一句话定位**：一台能自己看、自己想、自己走的桌面双足机器人。  
> **项目团队**：何浩睿 · 周柏宇 · 胡晟瑞 · 王旭琪 · 张景昆；**指导教师**：陈妍 · 李璐

[![Python 3.14](https://img.shields.io/badge/Python-3.14%20only-blue.svg)](software/atri/)
[![DOF](https://img.shields.io/badge/DOF-22%20Active-green.svg)](design/atri.urdf)
[![Offline Tasks](https://img.shields.io/badge/Tasks-5%2F5%20Closed--Loop-brightgreen.svg)](software/atri/run_demo.py)
[![Tests](https://img.shields.io/badge/Tests-437%2B40%20Pass-success.svg)](software/atri/tests/)
[![License](https://img.shields.io/badge/License-Pending-lightgrey.svg)](#开源声明与许可证-notice--license)

```
22 DOF (双腿 10 · 双臂 8 · 躯干 2 · 头部 2)  ·  CAD 实装 407 × 268 × 160 mm（高×宽×深）  ·  579 主包测试 + 41 仿真测试 + 17 CAD 门禁  ·  5/5 赛题闭环  ·  Python 3.14
```

A.T.R.I. 面向中国国际大学生创新大赛（人形机器人专项·小人形组）及高校具身智能实验教学场景，直面阻碍双足进课堂与赛场的三大痛点：
1. **设备贵**：动辄数千至万元级套件难以成班普及。本方案全机统一采用 22 只总线舵机，将新增采购预算压至 **2725–3260 元**（全口径 3350–3950 元，扣除实验室已有边缘板与调试件）。
2. **算法散**：碎片化脚本缺乏统一骨架。本方案底座抽离出统一 FSM 调度器与 Skill 契约规范，换场景仅需换一张结构化 JSON 任务卡。
3. **断网瘫**：重度依赖云端大模型导致赛事网络抖动即死锁。本方案单目轻量视觉、离线 TTS 引擎与状态机全板载，实现**全离线 0 次网络出站闭环**。

方案完整闭环赛题规约的五项任务（**流程闭环 ≠ 赛场闭环**；真机摄像头/平衡未测）：
- **人脸识别**（T-01）：赛题原文「识别指定人脸并播报姓名」。真识别通路 = YuNet + SFace + 人脸库 + 显式拒识（LFW 困难协议 50 人 rank-1 98.6%，**不是实机**）。无模型时退回感知/参数兜底，日志必须带 `source`。
- **二维码循迹**（T-02）：识别二维码 JSON（单动作或 `path` 序列）并按指示行走/踩步转体。不是沿黑线巡线。
- **物品搬运**（T-03）：色块目标 + 多轮横向伺服对准（**没对准就不夹**）后 `grasp → walk → release`；
  放置区若接入地标通道则**对准后再释放**（没看见地标 → 停住不释放，不盲放）。
  控制常数全部可标定（`config/carry.json`），闭环边界有可复跑数据（**合成图口径，非实机**），见下方 T-03 小节。
- **体育运动-踢球**（T-04）：绿球色块 + 多轮偏航闭环后侧踢；不收敛也尽力踢，但必须回报 `iterations/converged`。
- **娱乐休闲-舞蹈**（T-05）：离线关键词触发 22 轴短舞 + TTS；可选本地 wav（无播放器标 `audio=unavailable`）。无 ASR 引擎、无节拍同步。

![关节编号与构型图](design/drawings/01_关节编号图.png)

---

## 快速上手 (Quick Start)

核心控制软件位于 `software/atri/`，仅依赖 **Python 3.14 标准库**（零 pip 依赖）。在无硬件连线、无 GPU 环境下，可直接跑通任务卡、技能状态机（FSM）到虚拟舵机总线的完整闭环：

```bash
# 1. 进入软件核心目录
cd software/atri

# 2. 运行主软件栈单元测试（556 项；零依赖环境下人脸/二维码相关 44 项自动跳过）
python3 -m unittest discover -s tests

# 3. 运行赛题五项任务无硬件闭环演练（--fast 跳过动作等待，秒级自检）
python3 run_demo.py --fast

# 4. 运行 Webots 控制器及映射离线自检（切回仓库根目录，40 项全部通过）
cd ../..
python3 -m unittest discover -s webots/tests
```

---

## 人脸识别 T-01（2026-09-12 做实）

T-01 现在是一条**真识别链路**：YuNet 检测 → 5 关键点对齐 → SFace 128 维特征 → 人脸库余弦比对 → 显式拒识。
全离线、CPU、无 GPU。原「Haar 检测 + 参数兜底」路径**保留可用**，真识别通路优先。

```bash
# 一次性环境（仓库根目录）—— 用仓库内自带的 Python 3.14，见 docs/process/工程说明.md §1.1b
./.python/bin/python3 -m venv .venv-face
.venv-face/bin/pip install "opencv-contrib-python==4.11.0.86" numpy pyarrow
#   ⚠ numpy 不要 pin 到 <2：numpy 1.x 没有 3.14 的 wheel

# 拉模型（约 37 MB，带 sha256 校验；模型不入库）
.venv-face/bin/python software/atri/tools/fetch_models.py

# 注册人脸（只写特征向量与姓名，原图不入库）
.venv-face/bin/python software/atri/tools/face_enroll.py \
    --from-dir 本地数据/faces/team --db software/atri/config/face_db.json --append

# 用一张图真跑 T-01（没有摄像头也能验证）
cd software/atri && ../../.venv-face/bin/python run_demo.py --fast \
    --face-image ../../本地数据/faces/e2e/Tony_Blair_0040.jpg \
    --face-db ../../本地数据/faces/demo_face_db.json

# LFW 评测（出成功率 / 混淆矩阵 / EER 曲线）
.venv-face/bin/python software/atri/tools/face_eval.py --hard --compare-haar \
    --report design/handoff/T-01-LFW评测报告.md
```

**LFW 实测**（`design/handoff/T-01-LFW评测报告.md`）：检测 100%；rank-1 5 人 100%、
困难协议（末位选人 + 单张注册 + 随机划分）20 人 99.5% / 50 人 98.6%；
阈值在**不重叠的 20 人身份池**上标定，EER 1.06%。

> ⚠️ 数字来自 **LFW 公开数据集**，**不是实机摄像头实测**；距离档与现场光照未测。
> 人脸库为空时对所有脸只会说「不认识」，这是刻意行为。

> 📌 **T-01 对外口径已按赛题原文落地为「人脸识别」**。退化通路的 `expect_names[0]` 兜底仍保留，
> 但必须打印 `source="params"`，不得写成识别成功率。PPT 成品未改（等团队重生成）。
> 差异归档：`design/handoff/T-01-口径差异清单.md`。

---

## 二维码循迹 T-02（2026-09-12 做实）

赛题原文是「识别二维码并按**指示路径**行走」，而原先的 payload 只能表达**一条指令**。
本次补上路径表达、三解码器对照、多段执行与标称位移。

**路径格式**（旧格式继续可用，现场已印的码不作废）：

```json
{"schema":"atri.path.v1",
 "path":[{"action":"walk","steps":3},{"action":"turn","deg":90},{"action":"walk","steps":2}]}
```

```bash
# 拉二维码模型（约 1 MB，带 sha256 校验；模型不入库）
.venv-face/bin/python software/atri/tools/fetch_models.py --only qr

# 生成一张路径二维码（并打印版本 / 模块数 / 像素尺寸）
.venv-face/bin/python -m atri.qrgen \
    --path '[{"action":"walk","steps":3},{"action":"turn","deg":90}]' -o qr_path.png

# 鲁棒性评测：27 场景 × 3 解码器 + 10 组指令回放
.venv-face/bin/python software/atri/tools/qr_eval.py \
    --report design/handoff/T-02-二维码识别鲁棒性报告.md
```

**实测**（`design/handoff/T-02-二维码识别鲁棒性报告.md`）：

| 解码器 | 判据条件成功率 | 全扫描 | 平均单帧 |
|---|---|---|---|
| `opencv`（自带） | 50.0% | 66.7% | 105.7 ms |
| `aruco`（自带） | 66.7% | 59.3% | 54.0 ms |
| **`wechat`（1 MB 模型）** | **100%** | **88.9%** | **25.9 ms** |

- **主用 `wechat`**：判据条件下 6/6 全过，且**最快**（标准 `QRCodeDetector` 反而最慢）。
- **指令执行正确率 100%（10/10）**（编码 → 真解码 → 真执行，逐段比对）。
- **硬边界是码的像素大小**：<60 px（名义 >1 m）三种全失败；旋转 60°、暗光 ×0.4、噪声 σ=30 都扛得住。
  → 现场该做的是**印大一点 / 走近一点**，不是换算法。

> ⚠️ 畸变是**程序合成**的，不是真实相机拍的；**到位误差（S-02 的 ≤50 mm）未测** ——
> 小脑层没有位移/里程计，路径终点只有标称值（`atri.odometry`，标注 `nominal-uncalibrated`）。

## 物品搬运 T-03（2026-09-13 做实）

队友已把"多轮横向伺服闭环"做进来了（`0f65892` / `1cf0a8d`）。本次补的是它缺的那三件：
**放置区、可标定、可复跑的证据**。

```bash
# 评测（合成图 + 一维几何 + 真检测器/真技能；需要 numpy+opencv）
.venv-face/bin/python software/atri/tools/carry_eval.py \
    --report design/handoff/T-03-搬运-方案与评测报告.md \
    --json design/results/t03_carry_eval.json
```

**三步行为**（`skills/carry.py`）：

1. **对准目标物**：多轮增量偏航闭环；偏差超 `grasp_tolerance_cm` → 判失败、**不下发抓取**；
   没进死区但在容差内 → 允许夹，但必须回报 `aligned=False`（不把"凑合夹"说成"对准了"）。
2. **夹取 + 平移**：`grasp → walk(steps)`（步长名义 2 cm，未标定）。
3. **对准放置区**：通道接入了才做；**地标没看见 → 停住不释放**；通道完全没接入 →
   按任务卡参数释放，但结果里写 `place.status="channel-unavailable"`。

**参数全部可标定**：优先级 `任务卡 params > config/carry.json > 代码默认值`
（`atri/tuning.py`；这份 JSON 随代码发布时**只有说明、没有覆盖值**，有测试盯着）。

**跑出来的数字**（`design/handoff/T-03-搬运-方案与评测报告.md`，**合成图口径**）：

| 项 | 结果 |
|---|---|
| 色块检测（判据条件内） | **23/23 检出**，横向误差 ≤0.05 cm；全扫描 32/33（唯一失败：亮度 ×0.3，HSV 的 V 门限） |
| 遮挡的影响 | 全高挡条挡左侧 20/40/60% → 检出中心**系统性右偏 0.40/0.65/0.95 cm** |
| 端到端闭环（图像在环） | 代码默认 **11/20** → 推荐参数（`max_iters=15, step_gain=1.0`）**20/20** |
| 参数边界 | 12 cm 物距下：默认只纠得动 **3.4 cm**，推荐参数覆盖整个视场 ±6.93 cm |

> ⚠️ **两个数字口径必须一起说**：① 全部来自**程序合成图像 + 一维几何**，不是实机相机；
> ② 现有 Mock 的 `gain=1.5 cm/°` 等价于"物距 86 cm"，比桌面真实物距（8–20 cm，gain 0.14–0.35）**乐观约 7 倍**。
> **实机抓取成功率仍未测**（未测项清单 B6）；实物到手后第一步是量真实 gain 再回填 `config/carry.json`。

## ⚠️ 引用数字之前：先看未测项清单

`docs/process/未测项清单.md` 是全项目**唯一**的"没测过 / 测不了"登记表：

- ⛔ **阻断级**：样机未制造（所有实机指标的根源）、双足行走 ≥1 m、路径到位误差、
  STS3215 真实连续扭矩与温升、减重是否成立
- ⚠️ **重要级**：T-01 实机距离档、T-02 真实相机、树莓派耗时、续航、抓取/踢球成功率……
- ▫️ **背景级**：标称位移系数未标定、舵机零位未标定……
- ❓ **待主办方确认**：上肢躯干是否含头、二维码码制、路径格式……

**任何写进材料的"能做到什么程度"，先在表里搜一遍**；命中 ⛔/⚠️ 的写成"设计值/待实测"，
不要写成结论。表格里每一条都注明了"现在在哪份文档里被写成什么样、为什么没测、怎么才能测"。

---

## 分支与合并状态（2026-09-12 已合入 main）

软件线 `atri-next` 已于 **2026-09-12 合入主线**（`0533f55`，保留主线非几何修正、取其几何），
当前 HEAD 在 **`main`**，与 `origin/main` 同源；远程与本地均**不再保留 `atri-next`**
（合并前快照留在本地分支 `backup/main-pre-merge`，未推送）。**本 README 描述的就是合并后的 main。**

| 项 | 合入后口径 | 说明 |
|---|---|---|
| **整机包络** | **407（高）× 268（宽）× 160（深）mm** | 赛题上限 600×300×300；内部宽门禁 ≤270 mm **只剩 2 mm** |
| **机械零位摆放错误** | **0 对** | 合入后由 19 对清零 |
| **干涉总量** | **186 对 / 151 454 mm³**（让位不足 112 · 局部干涉 74） | 由 189 对 / 160 339 mm³ 经两次修正降下来：`6190ad4`（消全机 Top1）→ 188/156 114；`522cb85`（相机落位对齐头壳口袋 + IMU 归后桥座）→ **186/151 454**。**主会话 17:35 独立复验**；⚠️ 级为主，随几何改动小幅浮动 |
| **结构件质量** | **1383.8 g / 81 件**（CAD 实算；薄壁近似对 3 mm 壁件退化为实心 ⇒ 读作**上限**） | 合入前 1490 g，再减 **−7%** |
| **整机质量** | **≈3029.8 g（纸面推算，重量方案未定案）** | = 结构实算 + 舵机 1210 + 电子电池 316 + 线束 120；URDF 冻结基线 3436.6 g |
| **扭矩（10 个腿部关节超额定）** | 踝 **147.5%**、膝 141.2%、髋 pitch 134.1% / roll 129.4% / yaw 124.7%（占官方连续额定 0.98 N·m） | 腰 `trunk_roll` 41.1%（零姿态）/ 45.1%（最不利），**不超**；权威数字只看 `torque_check` |
| **功率 / 电池** | 平均 **15.97 A**、30 min 需标称 **10.40 Ah**（≈115.5 Wh，整包 ≈1.05 kg）；现选 3S 2000 mAh ≈13 min ⇒ **不得写"30 分钟续航"** | 工作占比 0.35 为工程估值 |
| **测试** | 主包 **508 项 OK**（零依赖环境下人脸 38 项 skip）；Webots 离线桩 **41 项 OK**；CAD 布局门禁 **17 项 OK**（本机实测） | 命令见下节 |

**口径纪律**（细节见 `design/handoff/交接档案-新会话入口.md` 第四节、《答辩材料口径核对清单》）：

1. 包络顺序一律写 **高 × 宽 × 深**，与 `size_cm = [14.6, 26.3, 40.7]` 的深×宽×高顺序不同，引用时别混。
2. `❌ 摆放错误 = 0` **不等于"没有穿模"**——**实测（改前基线 189 对）里只有 5 对**是同关节配合面（`fitcheck.is_joint_mate` 判定），
   其余 184 对是 ⚠️ 级让位不足 / 局部干涉（含 12 对管-舵机族，`right_forearm__limb_tube` 有 80% 自身体积被舵机占掉）。
   `❌ = 0` 的准确含义是"**没有任何一对达到『被指派到同一块空间』的程度**（判据：重合率 ≥30% 或体积 ≥5000 mm³）"。
3. `design/cad/out/report.md` 里印的踝 1.49 N·m / 152% 是 `build_all.py` 自带的**旧简算式**；**权威力矩只认 `hardware_requirements.json` 的 `torque_check`**。
4. `design/robot_model.json` 的 **字段值已是现行值**：`installed_envelope_mm` = 407 × 268 × 160、`overall.mass_kg` = 3.036
   （`mass_budget.total_g` = 3036.4，`sum(links.mass_kg)` = 3.0367）。
   **过期的是散落在该文件里的说明文本**：`installed_envelope_mm.source`（仍称"第 6–10 轮合入后 09:06 重测"）、
   `overall.note`（仍写"实装包络见 installed_envelope_mm（**418 mm 高**）""整机 3.437 kg"）、
   以及 `changelog` 条目（`407 × 263 × 146`、`1490 g`、`3.136 kg` —— 那是 v3.0-refresh 那次变更的**历史记录**，不是现值）。
   ⇒ **字段可引，文本不可引**。

---

## 这是什么 / 不是什么

- **全离线确定性控制栈**：采用“大脑—小脑”双层架构。大脑解析 JSON 任务卡并由有限状态机（FSM）调度；小脑负责参数化步态与动作库回放。感知成败与运动熔断严格绑定。
- **主包零第三方顶层依赖**：核心调度、运动学接口、状态机与单元测试仅依赖 Python 3.14 标准库。仅在接入实体摄像头时可选装 `opencv-python-headless`，生成二维码图像时可选装 `qrcode`。
- **已弃用端到端大模型（无 VLA）**：动作均由几何步态发生器与标定动作库生成，不做不可控的端到端生成式输出。
- **视觉只做轻量几何与检测，不做深度识别**：人脸模块使用 OpenCV Haar 级联检测器截取人脸边界框，**未做高阶人脸特征比对（不能识别人是谁）**；语音交互为离线文本发音（TTS），**不包含声纹识别**；二维码采用标准几何解算。
- **软件与仿真先导，样机未整机组装**：当前处于“设计冻结 + 仿真与脱机软件全绿”状态。实体 STS3215 舵机与骨架零件处于测试备料阶段，尚未开展整机物理在环联调。

---

## 仓库地图

```
ATRI/
├── software/atri/                  # 核心控制软件栈（Python 3.14，主包零第三方依赖）
│   ├── atri/                       # 控制包：config, brain, cerebellum, bus_sts3215, bringup 等
│   ├── task_cards/                 # 五项赛题结构化任务卡 JSON（T-01 ~ T-05）
│   ├── action_library/             # 预标定关键帧动作库（walk, kick, dance, carry 等）
│   ├── tests/                      # 主软件栈单元测试（含 STS3215 假串口与 bring-up）
│   └── run_demo.py                 # 五项任务无硬件快速演练入口
├── webots/                         # 仿真工程（22 DOF 仿真世界、控制器及测试）
│   ├── controllers/atri_controller # 机器人仿真控制器及软硬件关节映射
│   ├── worlds/atri_22dof.wbt       # 22 自由度自包含 Webots 仿真世界
│   └── tests/                      # 40 项关节映射完整率、覆盖度与实际角位移测试
├── design/                         # 机构与运动学模型
│   ├── atri.urdf                   # 22 自由度运动学与动力学描述
│   ├── cad/                        # CadQuery 参数化装配源码（独立 Python 3.9.6 环境）
│   ├── drawings/                   # 关节编号图、三视图、尺寸链图、舵机布局图
│   └── handoff/                    # STS3215 规格书核验、错轴分析、技术参数交接表
├── docs/                           # 工程过程记录、立项调研与参赛材料
│   ├── process/工程说明.md          # 仓库演进说明
│   ├── contest/                    # 省赛操作手册与申报附件
│   └── research/项目文档/           # 项目综述、技术方案、BOM 与可行性核查
├── 固件/                           # 接线与寄存器语义（不是已烧录固件）
├── ppt/                            # 答辩交付物
│   └── ATRI-答辩PPT-v4.pptx        # 24 页答辩演示文稿
└── NOTICE                          # 第三方参考资产（如 SO-ARM100 模型）合规声明
```

---

## 软件架构

软件系统采用双层解耦与防御性调度设计：

```mermaid
graph TD
    TC[JSON 任务卡 Task Card] --> Brain[大脑 Brain: 任务解析与状态机调度]
    Perception[视觉与传感器感知] -->|真实 bool found & 坐标| Brain
    Voice[TTS 语音服务] <--> Brain
    Brain -->|技能调度指令| FSM[任务生命周期 FSM]
    FSM -->|ENTER / EXECUTE / FEEDBACK / DONE| Cerebellum[小脑 Cerebellum]
    Cerebellum -->|参数化步态 / 动作库| Bus[ServoBus 舵机总线]
    Bus -->|拦截 NaN/Inf & 物理限位钳制| Actuators[22 物理/仿真关节]
```

1. **大脑（Cognition & FSM）**：解析标准化 JSON 任务卡，驱动 FSM 生命周期。遵循真实成败契约：感知未找到目标（严格原生布尔 `found` 判定）时立即熔断退出，杜绝虚报成功。
2. **小脑（Motion & Safety）**：管理 22 自由度拓扑，生成参数化步态或回放关键帧动作。
3. **总线防御（Bus Safety）**：`clamp_angle` 与 `deg_to_pulse` 拒绝 `NaN` / `Inf`。Mock / Webots 走 `ServoBus.set_angle` 模板；真机 `Sts3215Bus` 覆盖 `set_angle`，换算仍走 `deg_to_pulse`，不能把非有限值变成满脉冲。

详细模块设计与 API 参见 [software/atri/README.md](software/atri/README.md)。

---

## 设计口径与关键参数

项目中严禁混淆计算阶段与装配阶段的数据，核心量化指标统一规范如下：

| 维度 | 第一层：运动学与 URDF 口径 | 第二层：CAD 现行装配口径 | 说明与工程依据 |
|---|---|---|---|
| **整机尺寸** | 运动学基元 372.8 × 190 × 123 mm | **CAD 实装 407 × 268 × 160 mm**（高×宽×深） | 报名用实装。赛题上限 600×300×300；对上限余 +32 mm，但**对内部 270 mm 布局门禁只剩 2 mm**（肩部外挂错轴件的代价） |
| **结构件质量** | URDF link 质量合计 3436.6 g（历史冻结口径） | **1383.8 g / 81 件（CAD 实算，读作上限）** | 历史链 1790 → 1404 → 1490 → 1390.4 → **1383.8**；薄壁近似对 3 mm 壁件退化为实心，故为上限 |
| **整机总质量** | 历史提交口径 3437 g | **≈3029.8 g（纸面推算，重量方案未定案）** | 结构实算 1383.8 + 舵机 1210 + 电子件与电池 316 + 线束紧固件 120 |
| **腿部关节扭矩需求** | 随质量口径变 | **10 个腿部关节超额定：踝 147.5%、膝 141.2%、髋 pitch 134.1% / roll 129.4% / yaw 124.7%** | 占官方连续额定 0.98 N·m；减重路径 A/B/C 按 0.98 均未达标 |
| **扭矩判断基准** | **0.98 N·m（官方额定负载 10 kg·cm @12V，主判据）** | 1.47 N·m（堵转×50%，仅峰值参考） | 权威数字只看 `hardware_requirements.json` 的 `torque_check`；`out/report.md` 的 1.49 N·m 是旧简算式 |
| **腰部扭矩需求** | — | **`trunk_roll` 41.1%（零姿态）/ 45.1%（最不利），不超额定** | 修正力臂口径后由 187–194% 回落；上半身重力 + 惯性 |
| **电池与续航** | 现选 3S 2000 mAh（约 13 min） | 30 min 需标称 **10.40 Ah（≈115.5 Wh，整包约 1.05 kg）** | 平均电流约 15.97 A（工作占比 0.35 为工程估值）。答辩不要写 30 分钟续航 |
| **错轴量 (Stagger)** | — | **30–35 mm** | 沿舵机输出轴向外平移抽出，解决 19.6 mm 间距下两只 35 mm 舵机机体干涉；8–12 mm 属端面净距，禁止用作错轴量 |
| **BOM 成本** | 新增采购档：**2725–3260 元** | 全口径核算：**3350–3950 元** | 新增档扣除了实验室已有的边缘计算板与 STM32 调试件 |

---

## 运行平台与环境支持

- **基准平台**：基准运行环境为 Linux aarch64 配合 Python 3.14。由于多数嵌入式发行版未自带 Python 3.14，板端推荐源码编译安装。
- **算力选型**：BOM 清单中的树莓派 4B（4GB）仅作为算力基准与成本测算参考物，控制软件面向标准 Linux 接口编写，不绑定树莓派专有生态。
- **语音引擎**：Linux 下依次探测 `piper`、`espeak-ng`、`espeak`、`spd-say`，也可通过环境变量 `ATRI_TTS` 指定引擎；未检测到外部命令时自动降级为安全的 `MockTTS`。
- **CAD 依赖隔离**：CAD 装配基于 CadQuery 2.5.2 与 OpenCASCADE，固定运行在专用的 Python 3.9.6 虚拟环境（`.venv-cad`），与主软件环境完全隔离。

---

## 当前工程状态

| 模块 | 已完成 (Done) | 进行中 / 待真机验证 (WIP) | 规划中未做 (Planned) |
|---|---|---|---|
| **控制软件** | • 5/5 项任务卡快速演练闭环<br>• 主包 + Webots 离线测试<br>• FSM 熔断、NaN 拦截与协作式超时<br>• STS3215 真机总线（假串口可单测） | • 真实摄像头采集帧率与延迟调优<br>• Linux 本地离线 TTS 音色配置<br>• 中位标定：默认写 31，官方一键置中是 40=128 | • STM32 固件接管小脑（`固件/README.md` 为接线与语义，不是已烧录固件） |
| **仿真环境** | • 22 DOF 自包含 Webots 世界与控制器<br>• 40 项映射覆盖度、绑定完整率与实际角行程离线测试通过 | • 步态在环动力学平衡调优 | • CI 无头环境下的自动化 3D 物理交互评测（受限于 Linux CI 无头图形环境） |
| **机械结构** | • 22 DOF URDF 描述文件<br>• 髋肩 30–35 mm 错轴改型（解决对咬干涉）<br>• 基于 `kind` 稳定元件装配 | • 样机 3D 打印件加工与备件装配<br>• 错轴受力件打印强度测试 | • 整体铝合金骨架 CNC 批量加工 |
| **电气硬件** | • 关节动力学推导与选型验证<br>• BOM 成本核算与分级采购清单<br>• 功率缺口已写入交接包（30 min 需 **10.40 Ah**） | • 采购单只 STS3215 12V 舵机实测温升与持续工作力矩<br>• 电池仓扩容或外供方案（现选 3S 2000 mAh 不够 30 min） | • 专用供电管理与电流监测集成板设计 |

---

## 历史改动与工程演进记录

为保留工程演进脉络并供评审复核，本节归纳软件线并入主线过程中的关键变更。该软件线原名 `audit-fixes`、后改名 **`atri-next`**，并已于 **2026-09-12 合入 `main`**（`0533f55`）；下表数字为**各次变更当时的留档**，现行口径以上文口径表为准。

### 1. 审计修复（原 `audit-fixes`，已并入 `atri-next`）

- **纠正技能假成功**：修复感知失败仍盲目上报 ok 的漏洞。未检测到目标时立即熔断后续动作（`software/atri/tests/test_brain.py`）。
- **严格布尔校验**：`found` 字段强制校验原生 `bool` 类型，拒绝 `"False"` 字符串等非布尔真值隐患（`tests/test_perception.py`）。
- **消除动作重复下发**：修正踢球与舞蹈技能中因状态重复调用导致的底层运动指令重复下发（`tests/test_brain.py`）。
- **协作式超时机制**：引入 `abort_event` 标志位，长轨迹在帧边界主动检查退出；归零动作 `home()` 仅在主线程退出后执行一次（`software/atri/tests/test_brain.py` 与 `test_fsm.py`）。
- **总线非数防御**：`clamp_angle` 拦截 `NaN` / `Inf`（`tests/test_cerebellum.py`）。真机路径另在 `deg_to_pulse` 拒绝非有限值，避免 `Sts3215Bus` 把 NaN 写成满脉冲（`tests/test_config.py`、`tests/test_bus_sts3215.py`）。
- **仿真严密三层判据**：Webots 离线测试重构为 22 关节全覆盖、全绑定、真实行程 > 1°，杜绝未绑定也能绿灯的假阳性（`webots/tests/` 40 项通过）。
- **纠正数据口径**：废除以 1.47 N·m 峰值掩盖过载的口径，明确以 0.98 N·m 额定连续扭矩为主判据。额定订正后 30 min 电池需求升到 **11.83 Ah**（不是 4.53 Ah）。

### 2. 已从 origin/main 合入的机械与真机改动 (CAD / Bus)

自分叉点 `c5491d9` 到 `60d8611`：
- **装配判据统一**：`fitcheck.py` + `interference.py`；第 5 轮后 `pair_inspect.py` 把干涉体变回零件坐标系。
- **电子件按 `kind` 落座**，不再靠名称字符串。
- **髋肩错轴 30–35 mm**：`cluster_horn_arm` + `cluster_outrigger` + `backpack_plate`。宽从 223 吃到 **263 mm**。
- **口径订正**：实装包络 **407 × 263 × 146 mm**；结构 **1490 g / 81 件**；整机 3136 g 纸面推算。
- **STS3215 真机总线** `software/atri/atri/bus_sts3215.py`（SYNC WRITE、遥测、假串口测试）+ `固件/README.md`。
- **功率测试**改为「缺口必须被记录」，不许用绿测掩盖 11.83 Ah 超标。

### 3. `atri-next` 收口（已并入 main）

- 分支从 `audit-fixes` 改名为 **`atri-next`**；远程旧名已删，tag `audit-fixes-frozen` 指向改名前的 `13b9ab2`。
- ~~不对 `main` 开合入 PR~~ → **2026-09-12 已合入主线**：`0533f55` 整合 atri-next 第 6–10 轮 CAD 改造（保守合并：几何取其版本、非几何修正保留主线）。合入后 ❌ 摆放错误 19 → **0**、干涉 266 134 → **≈160 300 mm³**。
- 真机 `deg_to_pulse` / `Sts3215Bus.set_angle` 对 NaN/Inf 抛错且不发帧。
- T-01 文案曾改为「人脸检测迎宾」；**2026-09-12 按赛题原文改回「人脸识别」**（真识别通路优先，退化通路保留 `source`）。

### 4. 合入后的口径重测（本次）

- 整机包络重测为 **407（高）× 268（宽）× 160（深）mm**（合入前记录的 263 宽 / 146 深作废）；内部 270 mm 宽度门禁**只剩 2 mm**。
- 结构件实算 **1383.8 g / 81 件**（合入前 1490 g，−7%）；整机纸面推算 **≈3029.8 g**；URDF 冻结口径 3.0367 kg（回灌于 09:06，见 `design/handoff/交接档案-新会话入口.md` §十四）。
- 力矩力臂口径修正：`trunk_roll` 由 187–194% 回落至 **41.1%（零姿态）/ 45.1%（最不利）**，超额定关节由 11 个收敛为 **10 个腿部关节**。
- 测试规模 **432 → 437 → 508 → 579**（主包）+ Webots 离线桩 **41 项** + CAD 布局门禁 17 项。
  **2026-09-13 实测（Python 3.14.7）**：零依赖环境 `Ran 579 tests OK (skipped=44)`；
  装齐可选依赖（numpy 2.5.3 + opencv-contrib 4.11）后 `Ran 579 tests OK`（0 跳过）；Webots 41 项 OK。
  复现：`cd software/atri && ../../.python/bin/python3 -m unittest discover -s tests`（解释器来源见 `.python/VERSION.txt`）。

> 待回灌项：`design/robot_model.json` 的 `installed_envelope_mm` 与 `overall.mass_kg` 两字段仍是过期值，需要一次"包络/质量回灌"提交把它对齐到 `design/cad/out/report.md`。

---

## 开源声明与许可证 (Notice & License)

- **第三方参考模型**：涉及 SO-ARM100 的 10 份参考资产保留上游一致性，遵循 Apache 2.0 许可证，详见根目录 `NOTICE` 及相关目录下的协议文件。
- **选型规格资料**：舵机厂商规格说明 PDF 仅作为内部硬件接口核验使用，不作商业二次发行。
- **主项目许可证**：根目录 **没有 LICENSE**。这不是漏文件：NOTICE 明确不授权 ATRI 自己的代码与文档。第三方 SO-ARM100 资产按 Apache-2.0 保留；飞特规格 PDF 不作二次发行。原创部分在版权人书面同意之前，默认「未授权、保留所有权利」。不要把 NOTICE 读成整库 Apache/MIT。
