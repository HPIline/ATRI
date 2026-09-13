# A.T.R.I. 设计数据包与仿真链路

> **当前 A 路线（本分支）的机构在 [`design/v2/`](v2/README.md)。** 那是 20 DOF、无 hip_yaw、6061 铝夹层 + 2.4 mm PETG、单电池、单舵机两指夹爪的实装审查设计。本文件其余部分描述的是**旧 22 DOF 设计数据包与仿真链路**——`robot_model.json`、`atri.urdf`、`cad/` 属冻结的现机 22 DOF / 上一代 CAD 线，**不是本分支的机构**。下文的 "22 关节"、"L1 是唯一来源"等表述仅对这条冻结的旧线成立，不要读成 v2。

本目录把"结构设计"变成**可直接驱动仿真的数据包**，并让硬件设计参数与仿真、
训练共用同一份来源。

> ⚠️ **重要声明**
> 本目录产出的是**设计阶段（design-provisional）**数据：
> - 结构尺寸由关节链几何推导，**不是已加工零件的实测值**
> - 舵机参数为**同级别舵机的典型量级**，不是实测值（额定扭矩/速度已按【官方】规格书取，见 v3.1）
> - **v2（2026-09-11）**：身高对齐参考机 373 mm；**link 质量改为真实分布**，URDF 可直接做刚体动力学。
> - **v3（2026-09-11）**：数据口径切到**协作者 CAD 实装测量**（提交 6d4b077）。
>   历史口径：结构件 **1790 g**（虚高值，保留作追溯）、整机 3.437 kg、实装包络 418 × 223 × 129 mm。
> - **v3.1（2026-09-12 口径订正）**：以本轮 `assembly.py --all --no-export` 实测为准 ——
>   **实装包络 407 × 263 × 146 mm**（高×宽×深）；**结构件 1490 g / 81 件（实算）**；
>   **整机 ≈3136 g 为纸面推算，重量方案未定案**。
>   力矩判据改用【官方】额定 **0.98 N·m**（踝 152%；历史『堵转×50% = 1.47』口径下 101%），
>   减重路径 A/B/C 见 `handoff/新架构参数总表.md` §3.1。
> - v3/v3.1 的过期口径与订正过程见 `handoff/过期口径修正记录.md`。
> - 仿真为**运动学 + 规则控制器层面**，**不是刚体动力学仿真**
>
> 它验证的是：关节限位可达性、视觉伺服收敛性、舵机非理想特性的影响、
> 以及域随机化下的成功率趋势。
> 它**不**验证双足行走的物理稳定性（那需要 Webots / PyBullet 等刚体引擎）。

---

## 1. 目录结构

```
design/
├── robot_model.json          # L1 单一事实来源：23 link 几何/质量 + 22 关节定义（v3）
├── placements.json           # ★ 配件位置总表：22 舵机 + 10 电子件 + 23 结构件（宿主/坐标/尺寸/质量）
├── reference/
│   └── tonypi_pro_baseline.json  # 参考机（幻尔 TonyPi Pro）公开参数与可迁移结论
├── gen_v2_baseline.py        # v1→v2 一次性迁移：身高对齐 373 mm + 质量改为真实分布
├── gen_v3_baseline.py        # v2→v3 迁移；`--refresh` = 按最新 CAD 实测量刷新包络/质量（幂等）
├── reference/cad_assembly_measurements.json  # ★ CAD 实装测量的唯一落盘处（包络/零件质量/减重路径）
├── geometry.py               # 几何基元（6 种）+ 惯量 + 三维变换 + 正交投影
├── gen_urdf.py               # 纯标准库 URDF 生成器 + 设计约束校验（支持 link 附加体）
├── gen_spec_sheet.py         # ★ 渲染《新架构参数总表》（人看的视图，禁止手工维护）
├── atri.urdf                 # 生成产物，可直接喂给 PyBullet / Webots
├── gen_drawings.py           # 2D 工程图生成器（纯标准库 SVG）
├── gen_render.py             # 等轴测软件渲染器（纯标准库）
├── renders/                  # 外观渲染产物 ★ 可直接用于宣传材料
│   ├── 01_等轴测外观.svg
│   ├── 02_正视外观.svg
│   ├── 03_侧视外观.svg
│   ├── 04_关节配色图.svg
│   └── 05_等轴测外观-背面.svg
├── drawings/                 # 工程图产物 ★ 可直接用于报名材料
│   ├── preview.html          # ★ 浏览器预览源（四张图切页）
│   ├── 01_关节编号图.svg
│   ├── 02_三视图.svg
│   ├── 04_尺寸链图.svg       # 编号跳过 03：原计划的"爆炸图"未实现
│   └── 05_舵机布局图.svg
├── realistic_sim.py          # 非理想舵机总线 + 带噪声感知 + 域随机化采样
├── run_sim.py                # 仿真运行器（产出 JSON / CSV / SVG）
├── packages/                 # L2 物理与场景数据包
│   ├── servo_spec.json       #   舵机非理想特性
│   ├── domain_random.json    #   域随机化配置
│   ├── perception_sim.json   #   感知噪声与退化档位
│   └── scenario_set.json     #   五项赛题场景集
├── results/                  # 仿真产出（CSV，已 gitignore）
└── figures/                  # 仿真图表（SVG，已 gitignore）
```

---

## 2. 快速开始

```bash
cd /path/to/ATRI

# 0) 看/改模型版本与配件位置
python3 design/gen_v2_baseline.py --check          # 当前版本
python3 design/gen_spec_sheet.py                   # 渲染《新架构参数总表.md》

# 1) 校验设计并生成 URDF
python3 design/gen_urdf.py --summary --validate --write

# 2) 工程图：浏览器打开 HTML 预览（编号/包络/扭矩口径写在页上）
xdg-open design/drawings/preview.html
# 旧 SVG 生成器仍可用于测试： python3 design/gen_drawings.py

# 3) 跑仿真
python3 design/run_sim.py --list
python3 design/run_sim.py --all --episodes 10
python3 design/run_sim.py --all --episodes 10 --randomize
python3 design/run_sim.py --sweep perception --episodes 12

# 4) 测试
cd software/atri && python3 -m unittest discover -s tests
```

全部脚本**仅依赖 Python 3.14+ 标准库**，无需 numpy / matplotlib。

---

## 2.1 外观渲染（软件渲染，无需 GPU / Blender）

`gen_render.py` 是**纯标准库软件渲染器**：自己生成三角网格 → 轴测投影 →
画家算法深度排序 → 背面剔除 → 平面着色，输出 SVG。

```bash
python3 design/gen_render.py                      # 全部 5 张
python3 design/gen_render.py --views iso --png    # 单张 + PNG
python3 design/gen_render.py --pose zero          # 换成零姿态
```

| 文件 | 视角 | 用途 |
|---|---|---|
| `renders/01_等轴测外观.svg` | 3/4 视角 | 封面、宣传页 |
| `renders/02_正视外观.svg` | 正前方 | 展示左右对称构型 |
| `renders/03_侧视外观.svg` | 侧面 | 展示前后轮廓与足长 |
| `renders/04_关节配色图.svg` | 3/4 视角 | **按部位着色**，讲解自由度分布 |
| `renders/05_等轴测外观-背面.svg` | 背面 | 补充视角 |

**渲染特性**：自然站姿（微屈膝、手臂外展）、地面网格、自动取景、平面着色。

**诚实说明**：这是**软件渲染的设计示意图**，不是照片、不是实机、
也不是专业渲染器出图。几何为基元近似，材质为单色平面着色。

---

## 2.2 工程图说明（★ 报名材料直接可用）

| 图号 | 文件 | 内容 | 用途 |
|---|---|---|---|
| ATRI-DWG-001 | `01_关节编号图.svg` | 正视+侧视，22 关节全部编号，**躯干 2 DOF 橙色高亮**，附自由度构成、尺寸合规核验、22 关节明细表 | ⭐ 回答"躯干 2 DOF 在哪" |
| ATRI-DWG-002 | `02_三视图.svg` | 正视/侧视/俯视 + 总体尺寸与官方上限对比 | 材料必交 |
| ATRI-DWG-004 | `04_尺寸链图.svg` | 头部链/左腿链逐级累加，总高校核 + 放置校核 | 证明尺寸自洽 |
| ATRI-DWG-005 | `05_舵机布局图.svg` | 22 路舵机安装位置、按扭矩分档图例、汇总 | 证明"算过怎么装" |

**图的读法**：SVG 是矢量图，浏览器直接打开。转 PNG：`rsvg-convert` 或 `inkscape`；macOS 上才用 `qlmanage -t -s 2000`。

> **关于图号**：编号 **跳过 03**——原计划第 3 张为爆炸图，未实现；`gen_drawings.DRAWINGS` 里没有 03，
> 现有 4 张编号为 01 / 02 / 04 / 05。

**关于这些图的诚实说明**：
- 它们是**由设计模型正交投影生成的示意图**，不是 CAD 出图，也不是渲染图
- 外形为设计基元（圆角壳 / 关节球壳 / 胶囊连杆 / 足底板），用于表达构型与包络
- 所有尺寸为**设计值**，实物制造前须按采购件复测

### 2.2 几何基元

`geometry.py` 支持 6 种基元，全部可纯数学生成与投影：

| 基元 | 用途 | URDF 导出方式 |
|---|---|---|
| `box` | 夹爪等方块件 | `<box>` |
| `rounded_box` | 外壳、机身 | `<box>`（去圆角，保守） |
| `cylinder` | 舵机本体、关节轴 | `<cylinder>` |
| `sphere` | 关节 | `<sphere>` |
| `capsule` | 连杆（两端圆头） | `<cylinder>`（长度含球头） |
| `sphere_shell` | 球形关节壳 | `<sphere>`（外球半径） |

**关键设计**：`visual` 用真实基元，`collision` 用**等效包围盒**——这是标准工程做法，
碰撞检测更快更稳，且不影响外观表达。

**`origin_mm`（几何偏移）**：关节坐标系在转轴处，而零件实体通常不在轴上——
例如大腿要从髋关节一直延伸到膝关节。`origin_mm` 表达这个偏移，等价于 URDF 的
`<visual><origin>`，并同时作用于 URDF、AABB 与渲染。有了它，23 个 link 的实体
首尾相接，不会出现悬空段（有回归测试 `test_segments_connect_without_gaps` 守护）。


---

## 3. 三层数据包

| 层 | 内容 | 文件 |
|---|---|---|
| **L1 几何** | link 基元几何、质量、22 关节（名称/编号/轴向/限位） | `robot_model.json` → `atri.urdf` + `drawings/` |
| **L2 物理** | 舵机非理想特性、域随机化、感知噪声、场景 | `packages/*.json` |
| **L3 行为** | 动作库、任务卡（复用 `software/atri/`） | `action_library/`、`task_cards/` |

**关键原则：L1 是唯一来源。** URDF、图纸、仿真都从它生成，改一处即全局同步。

---

## 4. 硬件设计如何贴合仿真与训练

这是本目录的核心目的。七条具体措施：

| # | 措施 | 实现位置 | 作用 |
|---|---|---|---|
| 1 | **舵机特性入模** | `RealisticServoBus` | 死区 / 回程间隙 / 转速限制 / 控制延迟 / 扭矩饱和 |
| 2 | **域随机化** | `domain_random.json` | 随机扰动质量、摩擦、延迟、光照等 |
| 3 | **感知噪声注入** | `NoisyPerception` | 位置噪声 + 随机丢帧，闭环数据才有意义 |
| 4 | **关节限位对齐** | `gen_urdf.py --validate` | URDF 限位与固件 `config.py` 逐项一致 |
| 5 | **控制周期对齐** | `robot.json` 的 `control_period_ms` = 20ms | 仿真步长与实机一致 |
| 6 | **动作库共用** | 复用 `action_library/` 格式 | 仿真标定的关键帧可直接下发实机 |
| 7 | **单一下游来源** | `robot_model.json` | 设计变更自动同步到仿真与图纸 |

### 4.1 为什么"非理想舵机"很重要

`MockServoBus` 假设舵机**瞬间到位、扭矩无限**，用它跑出的"闭环收敛"没有参考价值。
`RealisticServoBus` 实测行为示例：

```
理想模式：  目标 30.0° → 实际 30.000°（一步到位）
非理想模式：目标 30.0° → 每步最多转 6.0°（300°/s × 0.02s）
            重复下发 30 次，29 次被死区拒绝
            指令先进入延迟队列，8ms 后才生效
```

### 4.2 为什么"域随机化"很重要

它把"低成本舵机的不确定性"从**劣势**变成**被显式建模的对象**，
并且是回答"仿真结果能不能信"的主要依据。

---

## 5. 产出数据说明

| 产出 | 路径 | 含义 |
|---|---|---|
| 设计摘要 | stdout | 22 关节清单、包络尺寸、质量合计、臂长/腿长 |
| URDF | `design/atri.urdf` | 23 link + 22 joint，含 visual/collision/inertial |
| 仿真 CSV | `results/sim_*.csv` | 每 episode 的收敛轮次、末误差、丢帧率 |
| 成功率图 | `figures/success_rate_*.svg` | 各场景成功率 |
| 收敛曲线 | `figures/convergence_*.svg` | 视觉伺服误差随迭代下降 |
| 鲁棒性曲线 | `figures/sweep_*.svg` | 感知退化档位下的成功率 |

### 5.1 已验证的仿真结果示例

**视觉伺服收敛**（nominal 档，固定种子 20260910）：

```
偏移  5.0cm → 4 轮收敛，末误差 0.382cm   误差序列: 5.00 → 2.42 → 1.45 → 0.38
偏移 12.0cm → 6 轮收敛，末误差 0.476cm   误差序列: 12.00 → 7.92 → 4.20 → 1.76 → 1.48 → 0.48
偏移 20.0cm → 7 轮收敛，末误差 0.355cm   误差序列: 20.00 → 15.92 → 12.16 → 7.82 → 4.50 → 1.99 → 0.35
```

**鲁棒性边界**（12 episode / 档位，开启域随机化）：

| 感知档位 | 成功率 | 说明 |
|---|---|---|
| ideal | 12/12 | 上界参考，非真实条件 |
| nominal | 12/12 | 默认仿真条件 |
| harsh | 9/12 | 弱光 + 高噪声 |
| adversarial | 4/12 | 用于定位失效边界 |

> 这组数据说明：**闭环在什么条件下开始失效是可测量的**。
> 主动给出失效边界，比宣称一个高成功率更有说服力。

---

## 6. 与真实仿真的衔接

本目录的 `atri.urdf` 可直接加载到刚体仿真引擎：

```python
# PyBullet（可选依赖）
import pybullet as p, pybullet_data
p.connect(p.GUI)
p.setAdditionalSearchPath(pybullet_data.getDataPath())
p.setGravity(0, 0, -9.81)
robot = p.loadURDF("design/atri.urdf", useFixedBase=False)
```

**Webots**：把 URDF 转成 PROTO，或直接参考 URDF 的关节名与限位配置
`webots/controllers/atri_controller/joint_mapping.json`（关节名已与之完全一致）。

> 加入刚体引擎后，本目录的 `domain_random.json` 与 `servo_spec.json`
> 仍可复用为仿真参数，形成"运动学验证 → 刚体动力学验证"的递进链路。

---

## 7. 复现与诚实性约定

1. **所有结果可复现**：固定随机种子（默认 `20260910`），命令写在上面。
2. **不编造实测数据**：本目录一切数据均为设计/仿真结果，标注 `design-provisional`。
3. **参数标注来源**：`servo_spec.json` 明确写 `provisional-typical`，
   并列出"已建模效应"与"未建模效应"。
4. **实物到手后回填**：舵机外形、安装孔、实测死区/间隙/延迟需复测替换。

---

## 8. 已知限制

- 未做刚体动力学，因此**不能**据此断言双足行走稳定性。
- 工程图为**投影示意图**，非 CAD 出图，也非渲染图；尺寸为设计值。
- 结构为基元几何（长方体/圆柱/球/胶囊/球壳），未包含真实圆角曲面、
  壁厚、拔模与支撑等工艺细节。
- 零件级拆分（零件编号 / BOM / 打印参数）尚未完成，属下一阶段工作。
- 极限姿态下的干涉校核尚未实现。
- 夹爪以单自由度铰链近似，实际为平行开合机构。
- 舵机参数为典型值，实际性能可能显著不同；实物到手后须复测回填。
- 感知噪声为统计模型，未包含真实光照与材质变化。
