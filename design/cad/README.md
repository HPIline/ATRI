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
├── components.json       ← 外部元件参数（部件库提供；电子件必须带稳定 kind）
├── placements.json       ← 22 舵机 + 10 电子件 + 结构件落座（由 gen_placements.py 生成）
├── cad/                  ← 本层：真实零件与整机装配
│   ├── standards.py      ← 标准件参数（舵机/轴承/紧固件/FDM 容差）
│   ├── kit.py            ← 接口标准 + servo_frame()（舵机姿态唯一真值）
│   ├── skeleton.py       ← 15 种骨架零件（笼/叉/管/框架/托盘…）
│   ├── assembly.py       ← 整机装配；按 kind 落座电子件，失败即报错
│   ├── fitcheck.py       ← 干涉判定原语（装配/体检/钟点求解共用）
│   ├── audit_assembly.py ← 穿模 / 连通性 / 关节轴对齐
│   ├── build.sh          ← 一键：零件 → 装配 → 体检 → 预览
│   └── out/              ← STEP/STL/报告（gitignore，可复现）
```

## 安装

CadQuery 需要 OpenCASCADE，**必须装在独立环境**（不要污染主仓库的零依赖约束）：

```bash
cd <repo>

# ① 先检查是否已存在 —— 环境约 830 MB，重建代价高（要重下 165 MB 的 OCP wheel）
if .venv-cad/bin/python -c "import cadquery, OCP" 2>/dev/null; then
  echo "已就绪：$(.venv-cad/bin/python -c 'import cadquery; print(cadquery.__version__)')"
else
  # ② 只有确认不存在/不可用时才重建
  python3 -m venv .venv-cad
  .venv-cad/bin/pip install -r design/cad/requirements.txt
fi
```

已验证可用：Python 3.9.6 / macOS arm64 / `cadquery-ocp 7.7.2` / CadQuery 2.5.2 / `ezdxf 1.4.2`。

> ⚠️ **环境必须建在仓库内（`.venv-cad/`），禁止建在 `/tmp`。**
> macOS 重启会清空 `/tmp`，系统还会清理 3 天未访问的临时文件。
> 2026-09-11 凌晨曾把环境建在 `/tmp/cadvenv`，当天下午的新会话找不到它，
> 误判为「协作者机器上的环境没有 clone 过来」，白下 859 MB。
>
> 另注：`.venv-cad/` 已在 `.gitignore` 中，**git 里看不到它**。
> 判断环境是否存在**必须查文件系统**（`ls .venv-cad/bin/python`），不能只看 `git status`。

## 使用

```bash
# 查看标准件参数状态（哪些还是 unknown / provisional）
.venv-cad/bin/python design/cad/build.py --standards

# 推荐：零件 → 装配 → 体检（改参数反复跑用 --fast）
bash design/cad/build.sh --fast

# 只要零件
.venv-cad/bin/python design/cad/build_all.py --all
```

## 现行零件（`skeleton.py`，不是早期的 `parts.py` 三件套）

15 种 / 72 件，质量按 PETG 1.27 g/cm³ + 外壁/填充估算。权威表每次构建写在 `design/cad/out/report.md`。

| 模块 | 件数 | 作用 |
|---|---|---|
| `joint_cage` / `joint_cage_yaw` | 13 + 3 | 夹住舵机 + 副轴第二支点 + Ø34 插接 |
| `limb_fork` / `limb_tube` / `compact_adapter` | 12 + 8 + 8 | 舵盘侧叉子、Φ40 连杆、短轴距转接 |
| `torso_frame` / `pelvis_frame` / `head_shell` / `foot_plate` | 1+1+1+2 | 定制大件 |
| 托盘 / 夹爪 / 线夹等 | 其余 | 电池仓、电控托盘、夹爪、线夹 |

**现行 CAD 质量口径（装配一致性修正后）**：结构 **1404 g**、整机 **3050 g**、踝关节 1.49 N·m（占堵转×50% 判据 102%）。过程记录见 `design/handoff/装配一致性修正记录.md`。

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
> ⚠️ **本章为 v1 历史核算（475 mm 机身）。**
> v3 提交口径：实装包络 418 mm、结构 1790 g、整机 3437 g（`新架构参数总表.md`）。
> **装配一致性修正后的现行 CAD 实算**：结构 1404 g、整机 3050 g（`装配一致性修正记录.md` §4.4 / `out/report.md`）。
> URDF 尚未回灌现行数——改重量方案时一并重算。下表保留用于追溯。

| 打印结构件（14 关节模块 + 8 连杆 + 2 足 + 4 转接） | 553 g（v1，475 mm） |
| 舵机 22 × STS3215 | 1210 g |
| 电子件 | 351 g |
| 线束 + 紧固件 | 150 g |
| **合计（v1）** | **2264 g** |
| **v3 口径（当前）** | **3437 g**（结构 **1790**〔CAD 实装实算〕+ 舵机 1210 + 电子件与电池 316 + 线束紧固件 120） |

**v1 结论（已由 v2 取代）：原设计质量预算不可达。** 原因是预算制定时没有计入
22 颗舵机（1210 g，占整机 56%）和真实结构件质量。

**v3 结论**：按 CAD 实装质量，腿部关节需求 **1.629 N·m**，占「堵转 × 50% = 1.47 N·m」判据的 **111%（超标）**。
必须执行减重路径（A 拓扑 900–1100 g / B 买金属件 550–700 g / C 减自由度）——见 `design/handoff/新架构参数总表.md` §3.1。

> **待办**：`parts.py` 的连杆长度目前用默认值（v2 已改为大腿 62.8 mm），
> 臂段 47.1/39.3 mm 尚未按实例传入；恢复 CAD 阶段时应改为**从 `robot_model.json` 派生**。

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
