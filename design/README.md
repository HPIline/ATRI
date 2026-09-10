# A.T.R.I. 设计数据包与仿真链路

本目录把"结构设计"变成**可直接驱动仿真的数据包**，并让硬件设计参数与仿真、
训练共用同一份来源。

> ⚠️ **重要声明**
> 本目录产出的是**设计阶段（design-provisional）**数据：
> - 结构尺寸由关节链几何推导，**不是已加工零件的实测值**
> - 舵机参数为**同级别舵机的典型量级**，不是实测值
> - 仿真为**运动学 + 规则控制器层面**，**不是刚体动力学仿真**
>
> 它验证的是：关节限位可达性、视觉伺服收敛性、舵机非理想特性的影响、
> 以及域随机化下的成功率趋势。
> 它**不**验证双足行走的物理稳定性（那需要 Webots / PyBullet 等刚体引擎）。

---

## 1. 目录结构

```
design/
├── robot_model.json          # L1 单一事实来源：link 尺寸/质量 + 22 关节定义
├── gen_urdf.py               # 纯标准库 URDF 生成器 + 设计约束校验
├── atri.urdf                 # 生成产物，可直接喂给 PyBullet / Webots
├── realistic_sim.py          # 非理想舵机总线 + 带噪声感知 + 域随机化采样
├── run_sim.py                # 仿真运行器（产出 JSON / CSV / SVG）
├── packages/                 # L2 物理与场景数据包
│   ├── servo_spec.json       #   舵机非理想特性
│   ├── domain_random.json    #   域随机化配置
│   ├── perception_sim.json   #   感知噪声与退化档位
│   └── scenario_set.json     #   五项赛题场景集
├── results/                  # 运行产出（CSV）
└── figures/                  # 运行产出（SVG）
```

---

## 2. 快速开始

```bash
cd /path/to/ATRI

# 1) 校验设计并生成 URDF
python3 design/gen_urdf.py --summary --validate --write

# 2) 列出场景
python3 design/run_sim.py --list

# 3) 跑全部场景
python3 design/run_sim.py --all --episodes 10

# 4) 开域随机化
python3 design/run_sim.py --all --episodes 10 --randomize

# 5) 鲁棒性扫描（产出失效边界）
python3 design/run_sim.py --sweep perception --episodes 12

# 6) 测试
cd 软件/atri && python3 -m unittest discover -s tests
```

全部脚本**仅依赖 Python 3.9+ 标准库**，无需 numpy / matplotlib。

---

## 3. 三层数据包

| 层 | 内容 | 文件 |
|---|---|---|
| **L1 几何** | link 尺寸、质量、22 关节（名称/编号/轴向/限位） | `robot_model.json` → `atri.urdf` |
| **L2 物理** | 舵机非理想特性、域随机化、感知噪声、场景 | `packages/*.json` |
| **L3 行为** | 动作库、任务卡（复用 `软件/atri/`） | `action_library/`、`task_cards/` |

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
- 舵机参数为典型值，实际性能可能显著不同。
- 感知噪声为统计模型，未包含真实光照/材质变化。
- 结构为长方体占位几何，未包含外形曲面与打印工艺约束（壁厚、支撑）。
- 夹爪以单自由度铰链近似，实际为平行开合机构。
