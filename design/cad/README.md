# CAD 层：真实零件建模

## 为什么有这一层

之前 `design/` 下的几何是**基元占位**（长方体/圆柱/球/胶囊），
用 Python 手算投影和网格。它能验证运动学与包络，**但永远做不出可制造的零件**：
没有圆角、抽壳、螺钉柱、轴承位、拔模，也没有 STEP。

这一层解决该问题：**接入真正的 CAD 内核（OpenCASCADE）**，
产出实心 B-rep 实体与 STEP/STL。

```
design/
├── robot_model.json      ← 运动学/包络/质量（基元，用于校验与仿真）
├── components.json       ← 外部元件参数（部件库提供）
├── cad/                  ← 本层：真实零件
│   ├── standards.py      ← 标准件参数（舵机/轴承/紧固件/FDM 容差）
│   ├── parts.py          ← 参数化零件建模
│   ├── build.py          ← 构建入口，导出 STEP/STL
│   └── out/
│       ├── step/         ← 可进 SolidWorks / 任何 CAD
│       ├── stl/          ← 可 3D 打印
│       └── report.md     ← 可制造性报告
```

## 安装

CadQuery 需要 OpenCASCADE，**必须装在独立环境**（不要污染主仓库的零依赖约束）：

```bash
cd <repo>
python3 -m venv .venv-cad
.venv-cad/bin/pip install cadquery
```

已验证可用：Python 3.9.6 / macOS arm64 / `cadquery-ocp 7.7.2` / CadQuery 2.5.2。

## 使用

```bash
# 查看标准件参数状态（哪些还是 unknown）
.venv-cad/bin/python design/cad/build.py --standards

# 构建全部零件
.venv-cad/bin/python design/cad/build.py --all

# 构建单个
.venv-cad/bin/python design/cad/build.py --part servo_yoke
```

## 已实现的零件

| 零件 | 说明 | 当前质量(实心) |
|---|---|---|
| `servo_yoke` | 舵机 U 型支架：夹持舵机 + 副轴轴承位 | 17.8 g |
| `horn_adapter` | 25T 舵盘 → 4×M2.5 法兰转接件 | 3.1 g |
| `link_tube` | 两端封头带轴孔的空心承力连杆 | 47.8 g |

> 实心质量按 PLA 1.24 g/cm³ 计，**未计填充率**；实际打印按 30–50% 填充
> 约为该值的 40–60%。

## 设计约定

1. **单位 mm**，Z 轴为回转轴，零件以配合面为基准面。
2. **参数全部来自 `standards.py`**，不硬编码魔数。
3. **`unknown` 状态的参数会拦截构建** —— 宁可构建失败，
   也不要产出一个基于臆测尺寸的零件。
4. 布尔/圆角之后统一走 `sanitize()` 修复几何：
   OCC 偶发自交会让 `isValid()==False`，下游 CAD 导入会报错。
5. **端头直径必须等于管外径**才能与管壁径向重叠——
   否则 `fuse` 无法合并，会留下互不相连的多个实体。

## 质量闭合（重要发现）

用真实 CAD 零件 + 真实元件参数做的整机质量核算：

| 项目 | 质量 |
|---|---|
| 打印结构件（14 关节模块 + 8 连杆 + 2 足 + 4 转接） | 553 g |
| 舵机 22 × STS3215 | 1210 g |
| 电子件 | 351 g |
| 线束 + 紧固件 | 150 g |
| **合计** | **2264 g** |
| 原设计预算 | 1650 g |
| 差 | **+614 g（+37.2%）** |

**结论：原设计质量预算不可达。** 原因是预算制定时没有计入
22 颗舵机（1210 g，占整机 53%）和真实结构件质量。

连带影响：力矩需求按总重等比放大 **×1.37**
（`trunk_roll` 1.29 → 1.78 N·m），STS3215 额定 1.0 N·m
对应的工作余量将变得非常紧张。

**三条出路**（需讨论决定）：
1. 结构减重：连杆壁厚 3→2mm、提高减重窗口比例，目标 −150 g
2. 接受 2.2 kg 级、重算力矩并评估是否换更大舵机
3. 减少自由度或改用更轻的舵机型号

## 与其它层的关系

```
components.json (外部元件参数)
        ↓
cad/standards.py  ──→  cad/parts.py  ──→  STEP / STL
        ↑                                      ↓
robot_model.json (运动学)              SolidWorks 精修 / 3D 打印
        ↓                                      ↓
check_fit.py (配合校验)  ←────────────  实测回填
```

**配合校验（`check_fit.py`）仍然是必要的**：CAD 零件建出来后，
要用它复核整体装配是否仍然满足包络与质量约束。
