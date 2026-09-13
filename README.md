# A.T.R.I. (Autonomous Tabletop Robotic Intelligence)

> **ATRI-v2 A 路线（当前 main）**：20 DOF 桌面人形重构。**20×Feetech STS3215-C018（12 V，额定 0.98 N·m）**，6061 铝夹层承力 + **2.4 mm PETG 不透明哑光白**外壳，开放骨盆框架，髋/腰双侧支承，**单舵机两指夹爪**（固定指 + 活动指 + 指垫 + 隔柱 + 支承），**单电池**，头部前侧 VL53L1X 预留。
>
> 当前机构与软件入口均为 **20 DOF、无 hip_yaw**，口径以 [`design/v2/`](design/v2/README.md) 与 [`software/atri/`](software/atri/README.md) 为准。转向是髋 roll 占位，**G4 仍开放**。旧 22 DOF 方案整包在 [`archive/v1-22dof/`](archive/v1-22dof/README.md)，不是当前入口。

![ATRI-v2 CAD 光追审查图，非实物照片](design/v2/out/blender/renders/product_iso.png)

![ATRI-v2 无标号爆炸图，CAD 光追，不是实物拆解照片](design/v2/out/render4k/exploded.png)

> 上图：**CAD 路径追踪（Cycles HIP）审查渲染，不是实物照片**。爆炸图是装配分解，不是实物拆解。仓库当前没有任何已制造整机。零件表见 [`exploded-parts.md`](design/v2/out/render4k/exploded-parts.md)。

[![DOF](https://img.shields.io/badge/DOF-v2%20%E6%9C%BA%E6%9E%84-20%20Active-green.svg)](design/v2/out/sim/atri_v2.urdf)
[![Servos](https://img.shields.io/badge/Servos-20%C3%97STS3215--C018%2012V-blue.svg)](design/v2/out/ATRI-v2-BOM.md)
[![Structure](https://img.shields.io/badge/Structure-6061%20Al%20%2B%202.4mm%20PETG-lightgrey.svg)](design/v2/MANUFACTURING-NOTES.md)
[![Software](https://img.shields.io/badge/Software-v2%2020%20DOF-green.svg)](software/atri/README.md)
[![Gates](https://img.shields.io/badge/G0%E2%80%93G4-OPEN-red.svg)](design/v2/out/gates.json)
[![Mass](https://img.shields.io/badge/Mass-2469g%20%3E%202450g%20hard%20limit-red.svg)](design/v2/out/%E8%B4%A8%E9%87%8F%E8%B4%A6.md)
[![License](https://img.shields.io/badge/License-Pending-lightgrey.svg)](#开源声明与许可证-notice--license)

```
20 DOF v2 机构（头 2 · 躯干 2 · 腿 4+4 · 臂 4+4，无 hip_yaw）  ·  20×C018 12V  ·  零位 CAD 外包络 466.5 × 188 × 295 mm  ·  已计质量 ≈2469 g（超 2450 g 硬顶，未计齐）  ·  软件 20 DOF  ·  Python 3.14
```

---

## 当前方案是什么 / 不是什么

**是：**

- **A 路线（铝 + PETG）实装审查设计。** 承力件为 6061 铝夹层（激光平板 + 标准角铝/铝管 + 局部转接），外壳为 2.4 mm 不透明哑光白 PETG/TPU。
- **20 DOF、无 hip_yaw 的新机构。** 骨盆改为开放框架、局部角铝转接与外部壳体夹持；髋侧摆与腰侧摆均改为**前后双侧支承**（后角铝 + 自由后盘 + 轴端保持件）。骨盆输出转接件已重画以避开中框碰撞。
- **单舵机两指夹爪。** 每只手一只 C018，固定指 + 活动指 + 指垫 + 隔柱 + 支承；没有双手舵机方案。
- **单电池方案。** 仅一只 Gens Ace GEA223S25T3GT（3S 2200 mAh）按实际包络进入主装配；第二包与扩展托盘已移除。想加第二包是**受门禁的提案**，不在主装配里，见 [`POWER-EXPANSION.md`](design/v2/POWER-EXPANSION.md)。
- **传感器预留。** VL53L1X 作为头部前侧 20×24×1.6 mm 夹扣/胶粘预留包络进入主装配，**未虚构厂商安装孔**。

**不是：**

- **不是已打样整机。** CAD 审查、加工文件、光追图同源输出，但**没有已制造实物**。CAD 审查 ≠ 打样 ≠ 赛题验证。
- **不是制造放行版。** `design_mass_closed: false`、`physical_mass_verified: false`，G0–G4 全部开放。
- **不是真机闭环，也不是 G4。** 仓库里的 5/5 Mock / Webots 运动学联调属于 **20 DOF 软件流程**，**不能当作 v2 硬件的赛事通过证据**。

---

## 当前状态与门禁

| 维度 | 现状 | 说明 |
|---|---|---|
| **阶段** | CAD 审查（design-provisional） | 同源 STEP/STL/3MF/DXF/URDF/WebGL，见[可下载产物](#可下载与审查产物) |
| **零件数** | 装配快照当前 **1030** 件 | `assembly-snapshot.json` 同源导出 **1030** 件，已去掉第二块电池。**这不是放行数字。** |
| **质量账** | 已计 **≈2469 g**，设计目标 2300 g，硬顶 2450 g | **超硬顶**；未计线束、相机、总线板、降压板、IMU、音频等，**不得填 0**。见 [`质量账.md`](design/v2/out/%E8%B4%A8%E9%87%8F%E8%B4%A6.md) |
| **门禁 G0–G4** | **全部 OPEN** | G0 购物车、G1 温升、G2 单腿质量、G3 赛方定义、G4 无 hip_yaw 转向误差。见 [`gates.json`](design/v2/out/gates.json) |
| **软件对齐** | 20 DOF 拓扑已迁；T1–T5 可在 Mock/Webots 运动学联调 | 转向是髋 roll 占位，**G4 未关闭**。无硬件 5/5 ≠ 真机通过。见 [`T1-T5-HARDWARE-ALIGNMENT.md`](design/v2/T1-T5-HARDWARE-ALIGNMENT.md) |
| **验证边界** | 几何/装配审查，非强度/热/续航 | CAD 有效网格、零位无相交**不等于**强度、走线或量产合格 |

> **口径纪律**：`release_ready` 为 `false`。任何"已打样 / 已通过验证 / 5/5 真机闭环 / 30 分钟续航"的表述都不成立，不要写进材料。

---

## 关键链接

| 主题 | 文件 |
|---|---|
| **A 路线工程入口** | [`design/v2/README.md`](design/v2/README.md) |
| 打样工艺与放行条件 | [`design/v2/MANUFACTURING-NOTES.md`](design/v2/MANUFACTURING-NOTES.md) |
| 髋/腰双侧支承集成 | [`design/v2/DUAL-SUPPORT-INTEGRATION.md`](design/v2/DUAL-SUPPORT-INTEGRATION.md) |
| T1–T5 软硬件对齐 | [`design/v2/T1-T5-HARDWARE-ALIGNMENT.md`](design/v2/T1-T5-HARDWARE-ALIGNMENT.md) |
| 结构理论初筛 | [`design/v2/STRUCTURAL-VALIDATION-PLAN.md`](design/v2/STRUCTURAL-VALIDATION-PLAN.md) |
| 电源扩展（提案，非主装配） | [`design/v2/POWER-EXPANSION.md`](design/v2/POWER-EXPANSION.md) |
| BOM | [`design/v2/out/ATRI-v2-BOM.md`](design/v2/out/ATRI-v2-BOM.md) |
| 质量账 | [`design/v2/out/质量账.md`](design/v2/out/%E8%B4%A8%E9%87%8F%E8%B4%A6.md) |
| 当前工程核验 / 门禁 | [`ATRI-v2-工程验证.md`](design/v2/out/ATRI-v2-%E5%B7%A5%E7%A8%8B%E9%AA%8C%E8%AF%81.md) · [`gates.json`](design/v2/out/gates.json) |
| 制造清单 | [`design/v2/out/铝件-加工清单.md`](design/v2/out/%E9%93%9D%E4%BB%B6-%E5%8A%A0%E5%B7%A5%E6%B8%85%E5%8D%95.md) · [`PETG-打印清单.md`](design/v2/out/PETG-%E6%89%93%E5%8D%B0%E6%B8%85%E5%8D%95.md) |

---

## 自由度构成（20 DOF，无 hip_yaw）

| 部位 | DOF | 关节 |
|---|---|---|
| 头部 | 2 | `head_yaw`, `head_pitch` |
| 躯干 | 2 | `trunk_roll`, `trunk_pitch` |
| 左腿 | 4 | `left_hip_roll`, `left_hip_pitch`, `left_knee_pitch`, `left_ankle_pitch` |
| 右腿 | 4 | `right_hip_roll`, `right_hip_pitch`, `right_knee_pitch`, `right_ankle_pitch` |
| 左臂 | 4 | `left_shoulder_pitch`, `left_shoulder_roll`, `left_elbow_pitch`, `left_gripper` |
| 右臂 | 4 | `right_shoulder_pitch`, `right_shoulder_roll`, `right_elbow_pitch`, `right_gripper` |

- **`left_hip_yaw` / `right_hip_yaw` 已移除**，本机构不恢复 yaw；无 hip_yaw 的转向误差属 G4 未关闭项。
- 关节名以 [`design/v2/out/sim/atri_v2.urdf`](design/v2/out/sim/atri_v2.urdf)（20 revolute）为准。

---

## 设计口径与关键参数

| 维度 | 当前口径 | 说明与出处 |
|---|---|---|
| **自由度** | 20 DOF，无 hip_yaw | 头 2 · 躯干 2 · 腿 4+4 · 臂 4+4 |
| **舵机** | 20× Feetech STS3215-C018，12 V，**连续额定 0.98 N·m** | 不以堵转 2.94 N·m 当额定；详细来源与真实性见 [`design/v2/README.md`](design/v2/README.md) |
| **结构** | 6061 铝夹层（激光平板 + 标准角铝/铝管）+ 2.4 mm PETG 不透明哑光白外壳 | 承力路径含髋/腰双侧支承 |
| **零位 CAD 外包络** | **466.5（高）× 188（宽）× 295（深）mm** | `assembly-snapshot.json` bbox（实际几何，非旧示意盒）。解析骨架包络见 `profile.py:envelope_mm()` = 466.5 × 185 × 128 mm。比赛包络量法待 G3 书面确认 |
| **骨架尺寸（mm）** | 足 120×70，小腿 78，大腿 78，hip_stack_z 32，hip_width 80，shoulder_width 150，上臂 58，前臂 60 | [`design/v2/profile.py`](design/v2/profile.py)；站高取 `standing_height_mm()` = 466.5 mm |
| **质量** | 已计 **≈2469 g**（铝 283 件 + PETG 8 + TPU 6 + 紧固件 444 + 隔柱 14 + 20 舵机 + 单电池 + Pi 4B） | 设计目标 **2300 g**、硬顶 **2450 g**，**超硬顶**；未知项未计入。见 [`mass-ledger.json`](design/v2/out/mass-ledger.json) |
| **扭矩口径** | walk k=1.4：0.761 N·m（利用率 77.6%）；hold k=2：1.086 N·m，**超额定** | 额定 0.98 N·m；hold 场景踝仍超额定 |
| **电池** | **仅一只** Gens Ace GEA223S25T3GT（3S 2200 mAh，107×33×22 mm，169 g） | 第二包与扩展托盘已移除；扩容为受门禁提案 |
| **预算** | close 估算 ≈¥3137、retail ≈¥3961 | **均非已锁购物车**；G0 要求 close ≤ ¥3000 且 12V SKU 截图，当前**不通过** |

---

## 仓库地图（当前 main）

```
ATRI/
├── design/v2/                      # ★ 当前机构（20 DOF）
│   ├── profile.py                  #   尺寸、限位、采购件接口
│   └── out/                        #   同源审查产物
├── software/atri/                  # 20 DOF 控制软件
├── webots/worlds/atri_v2.wbt       # 默认 20 DOF 运动学联调世界
├── archive/v1-22dof/               # 旧 22 DOF 整包备份
├── docs/                           # 工程记录与参赛材料
├── 固件/                           # 接线说明（不是已烧录固件）
├── ppt/                            # 答辩交付物
└── NOTICE                          # 第三方参考资产合规声明
```

---

## 可下载与审查产物

- [完整 STEP 压缩包](design/v2/out/packages/ATRI-v2-review.step.gz)（解压为未简化的装配 STEP）
- [完整打样审查包](design/v2/out/packages/ATRI-v2-manufacturing-review.zip)（DXF、3MF、STL 与逐件清单）
- [URDF 与完整网格包](design/v2/out/packages/ATRI-v2-simulation-review.zip)
- [Blender 可见装配场景](design/v2/out/blender/ATRI-v2-assembly-review.blend)
- [文件 SHA256](design/v2/out/packages/checksums.json)
- 逐件装配身份 / 材料 / 加工文件：`design/v2/out/manufacturing/manifest.json`

**出图状态**：`design/v2/out/blender/renders/` 为 GPU 光追 CAD 审查图（含 `product_iso.png`、`service_exploded.png` 等）。`design/v2/out/render4k/` 为 4K 展示图：整机前/后、腰-手-传感器细节、**无标号爆炸图**（不提交带编号版）。

> 此处所有文件均为**未放行审查版**。原始 STEP 超过 GitHub 单文件限制，故以无损 gzip 保存；压缩包经解压哈希/CRC 检查。

---

## 复现命令

所有命令在此工作树根目录执行。CadQuery 必须使用本仓库 `.venv-cad`（Python 3.12）。

```bash
PYTHONPATH=design python3 -m unittest software.atri.tests.test_v2_rebuild -q
PYTHONPATH=design .venv-cad/bin/python -m unittest discover -s software/atri/tests -p 'test_v2_*.py' -q
PYTHONPATH=design python3 -m v2.generate
PYTHONPATH=design .venv-cad/bin/python -m v2.cad_audit
blender --background --python design/v2/blender_build.py -- --out design/v2/out --samples 64
```

生成器严格从同一次 `cad_export.build_items()` 导出；缺件或无效实体会报错，不静默替换、跳过或合并丢件。

---

## 快速上手（20 DOF 软件）

核心控制软件在 `software/atri/`，仅依赖 Python 3.14 标准库。无硬件时可跑任务卡 → FSM → 虚拟总线：

```bash
cd software/atri
python3 -m unittest discover -s tests
python3 run_demo.py --fast
cd ../..
python3 -m unittest discover -s webots/tests
bash webots/tools/run_webots_batch.sh
```

CadQuery 用例需要仓库根 `.venv-cad`（Python 3.12）。默认 Webots 世界是 `webots/worlds/atri_v2.wbt`（20 电机、重力 0），这是运动学联调，**不是 G4，不是真机**。

---

## 旧方案备份

22 DOF 打印件方案（CAD、URDF、旧世界、旧方案正文）整包在 [`archive/v1-22dof/`](archive/v1-22dof/README.md)。当前文档与数字不以那一包为准。

---

## 开源声明与许可证 (Notice & License)

- **第三方参考模型**：SO-ARM100 的 10 份参考资产遵循 Apache 2.0，详见根目录 `NOTICE`。备份树里的路径是 `archive/v1-22dof/design/cad/vendor/`。
- **选型规格资料**：舵机厂商规格 PDF 仅作内部核验，不作二次发行。
- **主项目许可证**：根目录 **没有 LICENSE**。NOTICE 不授权 ATRI 自己的代码与文档。原创部分在版权人书面同意之前，默认「未授权、保留所有权利」。
