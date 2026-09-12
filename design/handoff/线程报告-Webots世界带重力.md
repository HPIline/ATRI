# 线程报告：Webots 世界补重力 / 地面 / 扭矩上限（T6，2026-09-12）

> 执行者：DSH 子会话（T6，9.13 演示材料关键路径）
> 任务书：`design/handoff/仿真请求-Webots验证清单.md` §0 / §0.3 + `design/handoff/第11轮-多线程施工方案与Prompt.md` §三 T6
> 目标：给 Webots 世界补上**重力、地面、舵机扭矩上限**，让 S1（静立）/ S2（站立扭矩）能跑，
> 且**默认行为一字不改**（验证 a 是硬门槛）。
>
> ⚠ **本机（Mac）没有装 Webots**，只有 CAD 与纯 Python 链。所以本线程的所有结论都是
> **静态核实 + 离线桩测试**：**生成出来的世界文件没有被 Webots 打开过一次**，
> 凡是需要 Webots 才能确认的事，下面都标了「**未实测**」，请不要当成已验证。

---

## 0. 一句话结论

1. 生成器现在有 4 个**可选**开关（`ATRI_WORLD_GRAVITY` / `ATRI_WORLD_MAX_TORQUE` /
   `ATRI_WORLD_GROUND` / `--out`），全都不给时**产物与已提交的 `webots/worlds/atri_22dof.wbt` 逐字节一致**（验证 a 通过）；
2. 带重力世界能生成，且 `grep` 静态核实三点全过：`gravity -9.81` × 1、`maxTorque 2.94` × **22/22**、地面 `Plane` × 3 处；
3. 控制器加了 `--max-torque` / `ATRI_WEBOTS_MAX_TORQUE`（默认 `None` = 一个字都不改），
   用于运行时对 22 个电机统一 `setAvailableTorque()`，并把实际用的值记进报告 JSON；
4. 离线桩测试 **40/40 全绿**（验证 c），默认路径下报告字段与以前完全一致；
5. **S1/S2 现在只差"队友在真 Webots 里跑一遍"**，命令见 §8。但注意 §9 第 1 条：
   **扭矩反馈没有接进控制器**，S2 仍需清单 §S2 里那份 `torque_probe.py`。

---

## 1. 改动的文件（只动了这 3 个 + 新建本报告）

| # | 路径 | 状态 | 行数增减 | 内容 |
|---|---|---|---|---|
| 1 | `webots/tools/generate_atri_world.py` | 修改 | **+303 / −18** | 4 个可选开关 + 地面节点 + 参数来源注释块；顺手修掉一个本机 Python 3.9 下必崩的写法（§6） |
| 2 | `webots/controllers/atri_controller/atri_controller.py` | 修改 | **+80 / −3** | `--max-torque` / `ATRI_WEBOTS_MAX_TORQUE`，逐电机 `setAvailableTorque()`，报告加 `max_torque_nm` / `torque_limited_joints` |
| 3 | `webots/README.md` | 修改 | **+136 / −1** | 新增「带重力/带地面的校核跑法」一节（生成 / 跑 S1-S2 / 回退 / 踩坑），环境变量表补 `ATRI_WEBOTS_MAX_TORQUE` |
| 4 | `design/handoff/线程报告-Webots世界带重力.md` | **新增** | — | 本文件 |

行数来自 `git diff --numstat`：

```
136	1	webots/README.md
80	3	webots/controllers/atri_controller/atri_controller.py
303	18	webots/tools/generate_atri_world.py
```

**没有改动**（按要求冻结）：`webots/worlds/atri_22dof.wbt`（重跑生成器后逐字节一致，见 §2）、
`webots/tests/**`（桩与测试一行未动，40 项仍全绿）、`software/**`、`design/cad/**`、`ppt/**`、
`task_cards/**`、`design/placements.json`。

**Git**：本线程**没有**执行任何 `git add/commit/push/checkout`；只用了只读的
`git status --porcelain`、`git diff --stat`、`git diff --exit-code`、`git diff --numstat` 做核查。

---

## 2. 验证 a（硬门槛）：默认模式与已提交世界**逐字节一致**

### 命令（题面原文）

```bash
python3 webots/tools/generate_atri_world.py && git diff --stat webots/worlds/atri_22dof.wbt
```

### 真实输出（`/tmp/verify_out.txt` 原样，`[a 退出码=0]` 是我加的分隔标记）

```
  模型 v3.0，整机 3.137 kg，包络 372.8×190.0×123.0 mm
已生成 /Users/zhangjingkun/Projects/github/ATRI/webots/worlds/atri_22dof.wbt
关节数 22: trunk_roll, trunk_pitch, head_yaw, head_pitch, left_shoulder_pitch, left_shoulder_roll, left_elbow_pitch, left_gripper, right_shoulder_pitch, right_shoulder_roll, right_elbow_pitch, right_gripper, left_hip_yaw, left_hip_roll, left_hip_pitch, left_knee_pitch, left_ankle_pitch, right_hip_yaw, right_hip_roll, right_hip_pitch, right_knee_pitch, right_ankle_pitch
[a 退出码=0]
```

**`git diff --stat` 输出为空**——即 `关节数 22: …` 那一行与 `[a 退出码=0]` 之间**没有任何内容**，
重跑生成器后 `webots/worlds/atri_22dof.wbt` 与 HEAD 中的版本**逐字节相同，默认行为未被破坏。**

### 补充证据（更强的同一条结论）

```bash
python3 webots/tools/generate_atri_world.py >/dev/null
git diff --exit-code -- webots/worlds/atri_22dof.wbt; echo "git diff --exit-code 退出码=$?"
git status --porcelain
git diff --numstat
```

```
git diff --exit-code 退出码=0（0 = 与 HEAD 逐字节一致）
--- git status --porcelain ---
 M webots/README.md
 M webots/controllers/atri_controller/atri_controller.py
 M webots/tools/generate_atri_world.py
--- git diff --numstat（只看源码改动行数）---
136	1	webots/README.md
80	3	webots/controllers/atri_controller/atri_controller.py
303	18	webots/tools/generate_atri_world.py
```

`git status` 里**没有** `webots/worlds/atri_22dof.wbt`，也没有任何未跟踪的派生世界文件——
默认产物确实原封不动。

---

## 3. 验证 b：带重力世界（生成 + 静态核实三点）

### 命令（题面原文）

```bash
ATRI_WORLD_GRAVITY=-9.81 ATRI_WORLD_MAX_TORQUE=2.94 ATRI_WORLD_GROUND=1 \
  python3 webots/tools/generate_atri_world.py --out /tmp/atri_grav.wbt
grep -c "gravity -9.81" /tmp/atri_grav.wbt     # 期望 ≥1
grep -c "maxTorque 2.94" /tmp/atri_grav.wbt    # 期望 恰好 22
grep -cE "Floor|Plane" /tmp/atri_grav.wbt      # 期望 ≥1
```

### 真实输出

```
  模型 v3.0，整机 3.137 kg，包络 372.8×190.0×123.0 mm
  [生成器] 非默认参数：gravity=-9.81 m/s²，maxTorque=2.94 N·m × 22，地面=有（Plane 4×4 m）
已生成 /tmp/atri_grav.wbt
关节数 22: trunk_roll, trunk_pitch, head_yaw, head_pitch, left_shoulder_pitch, left_shoulder_roll, left_elbow_pitch, left_gripper, right_shoulder_pitch, right_shoulder_roll, right_elbow_pitch, right_gripper, left_hip_yaw, left_hip_roll, left_hip_pitch, left_knee_pitch, left_ankle_pitch, right_hip_yaw, right_hip_roll, right_hip_pitch, right_knee_pitch, right_ankle_pitch
[b 退出码=0]
--- grep -c "gravity -9.81" /tmp/atri_grav.wbt  （期望 ≥1）---
1
--- grep -c "maxTorque 2.94" /tmp/atri_grav.wbt （期望恰好 22）---
22
--- grep -cE "Floor|Plane" /tmp/atri_grav.wbt    （期望 ≥1）---
3
```

**三点全过**：重力 1 处、`maxTorque 2.94` **恰好 22 处**、地面节点 3 处
（`Plane` 出现 2 次：视觉几何 + `boundingObject`；另有文件头注释里的 "Plane" 1 次）。

### 补充证据：不是"字符串凑够 22"，而是每个电机都有

```python
# /tmp/atri_grav.wbt 逐 RotationalMotor 块核查
RotationalMotor 块数 = 22，其中带 maxTorque 的 = 22
取值分布 = ['2.94']
缺 maxTorque 的电机 = []
gravity 行 = ['#   gravity   = -9.81 m/s²', 'gravity -9.81']
```

### 生成出来的世界文件长什么样（关键片段，原文）

```
#VRML_SIM R2025a utf8

# 本文件由 webots/tools/generate_atri_world.py 生成，请勿手改。
# A.T.R.I. 22 DOF 桌面人形：几何与质量派生自 design/robot_model.json。
# 关节限位与电机速度上限同样来自模型（minStop/maxStop/maxVelocity）。
# 电机名与 controllers/atri_controller/joint_mapping.json 一一对应（默认同名映射）。
#
# ⚠ 本世界用非默认参数生成，只用于**仿真校核**，里面的数字是仿真值不是实测值：
#   gravity   = -9.81 m/s²
#   maxTorque = 2.94 N·m（STS3215 堵转 2.94 N·m）
#   ground    = 有：Plane，4 m × 4 m，z = 0
#   生成命令：见 webots/README.md「带重力/带地面的校核跑法」。

WorldInfo {
  title "A.T.R.I. 22 DOF 桌面人形（带重力校核）"
  basicTimeStep 32
  gravity -9.81
  ERP 0.6
  CFM 1e-05
}
...
Solid {
  name "ground"
  translation 0 0 0
  children [
    Shape {
      appearance Appearance {
        baseColor 0.5 0.5 0.55
      }
      geometry Plane {
        size 4 4
      }
    }
  ]
  boundingObject Plane {
    size 4 4
  }
}
...
        RotationalMotor {
          name "trunk_roll"
          maxVelocity 3.1416
          maxTorque 2.94
        }
```

**地面为什么是 `Plane`、为什么 4 m × 4 m**（也写进了 README）：

- `Floor` / `Ground` 是 Webots 的 **PROTO**，引用必须配 `EXTERNPROTO`，会破坏本世界
  "自包含、不引任何外部 PROTO"这条仓库刻意保留的约束（生成器 docstring 第 3 段就是讲这个的，
  起因是比赛机器的网络访问 GitHub 受限）。`Plane` 是内置几何节点，同时能当视觉几何与 `boundingObject`；
- 尺寸 4 m：机器人高 0.407 m、脚盒 0.11 m，S1 静立与 S3 五张任务卡场景的位移都在 0.5 m 量级，
  4 m 给 ±2 m（≈ 5 倍机高）余量；`Plane` 作接触面在 Webots 里按无限平面处理，
  机器人被推出去也不会掉出世界边界。

### 附带核实的边界行为（都是我实跑的，不是推的）

| 场景 | 命令 | 结果 |
|---|---|---|
| 重力非 0 但**不写** `ATRI_WORLD_GROUND` | `ATRI_WORLD_GRAVITY=-9.81 python3 webots/tools/generate_atri_world.py --out /tmp/atri_auto.wbt` | 退出 0，**自动补上地面**（`Plane` 3 处）并在控制台打印 `重力非 0 → 自动生成地面（…）`；`maxTorque` **字段 0 处**（只有文件头注释里那行"不写该字段"，实测 `grep -cE "maxTorque +[0-9]"` = 0） |
| 重力给**正**值 | `ATRI_WORLD_GRAVITY=9.81 …` | **退出 2**，`gravity 必须 ≤ 0…正值向上，机器人会飞起来`，且**不生成文件** |
| 环境变量写错（逗号） | `ATRI_WORLD_GRAVITY=-9,81 …` | **退出 2**，不悄悄退回零重力 |
| `maxTorque` 给 0 | `ATRI_WORLD_MAX_TORQUE=0 …` | **退出 2**，`maxTorque 必须 > 0…` |
| `--out` 相对路径 | 在 `/tmp/atri_out` 下 `--out rel/atri_rel.wbt` | 落到 cwd（`/private/tmp/atri_out/rel/atri_rel.wbt`），目录自动建 |

> 设计取舍：**"重力非 0 却没要地面"是自动补地面而不是报错**——队友少写一个环境变量不至于白跑一轮；
> 而**"重力为正 / 数值写错"是硬报错**——那种情况下生成出来的世界看着正常、数字全是废的，
> 必须在生成阶段就拦住。

---

## 4. 验证 c：离线桩测试（40 项）

### 命令（题面原文）

```bash
python3 -m unittest discover -s webots/tests 2>&1 | tail -3
```

### 真实输出

```
  [WebotsServoBus] 已绑定: right_shoulder_roll -> right_shoulder_roll
  [WebotsServoBus] 已绑定: right_elbow_pitch -> right_elbow_pitch
  [WebotsServoBus] 已绑定: right_gripper -> right_gripper
```

⚠ **`tail -3` 在这里看不到结论行**：`webots/tests` 里有几条用例直接构造 `WebotsServoBus`
（不经 `redirect_stdout`），它的绑定日志走 stdout，而 stdout 被管道接住后是块缓冲，
进程退出时才 flush——于是这些绑定行**排到了 stderr 的汇总行之后**。
同一轮把结果行抓出来是这样（这才是真正的结论）：

```bash
python3 -m unittest discover -s webots/tests 2>&1 | grep -E "^(Ran |OK|FAILED|ERROR)"
```

```
Ran 40 tests in 0.384s
OK
```

**40/40 全绿，退出码 0**（`grep` 管道整体退出码 0）。另外补跑了一次"带着
`ATRI_WEBOTS_MAX_TORQUE=2.94` 的 shell"（模拟队友的批量环境）：

```bash
ATRI_WEBOTS_MAX_TORQUE=2.94 python3 -m unittest discover -s webots/tests 2>&1 | grep -E "^(Ran |OK|FAILED|ERROR)"
# Ran 40 tests in 0.374s
# OK
```

### 控制器新开关的离线行为（自写探针，未落库，脚本在 `/tmp/check_max_torque.py`）

| 场景 | 退出码 | 报告字段 | 说明 |
|---|---|---|---|
| 默认（不给 `--max-torque`） | 0 | `max_torque_nm=null`、`torque_limited_joints=0`、`passed=5/5` | 与改动前一致 |
| `--max-torque 2.94` | 0 | `max_torque_nm=2.94`、`torque_limited_joints=0`、`binding_ok=true` | 桩没有 `setAvailableTorque`，控制器**提示一次后跳过**，不崩 |
| `ATRI_WEBOTS_MAX_TORQUE=2.94` | 0 | `max_torque_nm=2.94` | 环境变量通路 OK |
| `ATRI_WEBOTS_MAX_TORQUE=2,94`（笔误） | **2** | — | `参数错误：环境变量 … 不是合法数字` |
| `--max-torque 0` | **2** | — | `max-torque 必须 > 0…` |

真 Webots 里 `torque_limited_joints` 应当是 **22**；桩里是 0 并且会打印
`电机对象没有 setAvailableTorque()，maxTorque=2.94 N·m 未生效（离线桩？）`——
这是**如实反映"离线没真设上"**，不是静默放过。

---

## 5. 接口一览（新增，全部可选、默认关闭）

### 5.1 世界生成器 `webots/tools/generate_atri_world.py`

| 开关 | 环境变量 | 默认 | 语义 |
|---|---|---|---|
| `--gravity <f>` | `ATRI_WORLD_GRAVITY` | `0.0` | `WorldInfo.gravity`（m/s²，沿 Z 轴**有符号标量**，向下为负）。正数 / nan / inf → 退出 2 |
| `--max-torque <f>` | `ATRI_WORLD_MAX_TORQUE` | 不写该字段 | 逐 `RotationalMotor` 的 `maxTorque`（N·m）。≤0 → 退出 2。**不写 ≠ 无限大，Webots 默认 10 N·m** |
| `--ground` | `ATRI_WORLD_GROUND`（`1/true/on`） | 不生成 | 生成 `Plane` 地面（4 m × 4 m，z = 0）。**重力非 0 时自动强制打开** |
| `--out <path>` | — | `webots/worlds/atri_22dof.wbt` | 输出路径（相对路径按 cwd 解析，父目录自动创建） |

优先级：**命令行 > 环境变量 > 默认值**。非默认组合会在文件头写一段"参数来源"注释
（gravity / maxTorque / ground 各是多少），队友回传世界副本时不用再翻生成命令。

### 5.2 控制器 `webots/controllers/atri_controller/atri_controller.py`

| 参数 | 环境变量 | 默认 | 语义 |
|---|---|---|---|
| `--max-torque <f>` | `ATRI_WEBOTS_MAX_TORQUE` | `None` | 对**每个绑定成功的电机**调 `setAvailableTorque(f)`；非法值退出 2 |

报告 JSON 新增两个字段：`max_torque_nm`（本次用的值，`null` = 没改）、
`torque_limited_joints`（真正设上的电机数）。**旧字段一个没改**，所以
`run_webots_batch.sh/ps1` 的解析逻辑与离线测试都不受影响。

### 5.3 README

`webots/README.md` 新增一节「**带重力/带地面的校核跑法**」（目录结构注释、
环境变量表、注意小节也同步补了）。内容：生成命令（环境变量式 + 命令行式）、
三条自检 `grep`、S1/S2 批量命令（Linux + Windows）、GUI/录屏命令、
三条硬约束、地面尺寸理由、⚠ 控制器发现风险（见 §8.7）、回退方式，
并写明**默认零重力模式仍用于纯运动学演示**。

---

## 6. 顺手修掉的一个"假绿"陷阱（本机必踩）

旧代码最后一行是：

```python
WORLD_PATH.write_text(render_world(), encoding="utf-8", newline="\n")
```

`Path.write_text(newline=...)` **Python 3.10 才支持**，而本机只有系统 Python **3.9.6**
（`.venv-cad` 也是 3.9.6）。实测旧写法在本机是这样：

```
TypeError: write_text() got an unexpected keyword argument 'newline'
[exit=1]
--- git diff --stat webots/worlds/atri_22dof.wbt ---   ← 空
```

**危险点**：题面验证 a 是 `python3 … && git diff --stat …`。生成器以 1 退出后，
`&&` 右边的 `git diff` **根本不会执行**，屏幕上同样是"一片空白"——
和"真的没有差异"长得一模一样，**这就是一次假绿**。

改法（产物字节不变，只是换等价写法）：

```python
with open(opts.out, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(text)
```

队友机器是 Python 3.12，两种写法等价；改完本机才能真正把验证 a 跑出来（见 §2）。

---

## 7. 回退方式（恢复默认行为）

**生成器侧（世界文件）**——什么都不用做，只要不带开关：

```bash
python3 webots/tools/generate_atri_world.py          # = gravity 0、无地面、不写 maxTorque
git diff --stat webots/worlds/atri_22dof.wbt         # 期望：空输出
```

- 派生世界是**生成产物，不在版本库里**：删掉 `/tmp/atri_grav.wbt`、
  `docs/process/sim/worlds/atri_22dof_gravity.wbt` 即可，仓库里的 `.wbt` 不受影响；
- 若曾把派生世界生成到 `webots/worlds/` 下，删掉那个文件即可（它是未跟踪文件）；
- 想彻底卸载本次改动：`git checkout -- webots/tools/generate_atri_world.py webots/controllers/atri_controller/atri_controller.py webots/README.md`
  （**由主会话决定，本线程没执行任何 checkout**）。三个文件都是加开关，删掉后旧行为原样恢复。

**控制器侧**：不传 `--max-torque`、不设 `ATRI_WEBOTS_MAX_TORQUE` 时，控制器**一个电机都不碰**
`setAvailableTorque`（报告里 `max_torque_nm: null`、`torque_limited_joints: 0`），
其余行为、报告字段、退出码判据全部与改动前一致。

**注意**：派生世界文件里的 `maxTorque 2.94` 是**写进文件**的——一旦用了带 `--max-torque` 生成的世界，
那次跑出来的电机权限就是 2.94 N·m；要回到"Webots 默认 10 N·m"必须重新生成不带 `--max-torque` 的世界
（或在 GUI 里逐个改）。这是**故意的**：扭矩校核场景就该被文件钉死。

---

## 8. 队友机器上跑 S1 / S2 的完整命令（Windows 为主）

> 前提：仓库在 `C:\Users\<你>\ATRI`，`webots`（R2023b+，实测 R2025a）在 PATH 或
> `C:\Program Files\Webots\...`；Python 与 Webots 设置里的 `Python command` 是同一个。

### 8.0 前置：确认基线没坏（S0，约 1 分钟）

```powershell
cd C:\Users\<你>\ATRI
python -m unittest discover -s webots\tests -v          # 期望 40 项全过
python webots\tools\generate_atri_world.py
git diff --exit-code -- webots\worlds\atri_22dof.wbt    # 期望：退出码 0（无差异）
```

### 8.1 生成带重力世界

> ⚠ **先读 §8.7 的控制器发现风险**：直接生成到 `docs\process\sim\worlds\` 更符合清单 §3.1 的
> 目录约定，但 Webots 可能找不到控制器。**最稳的是下面第 2 条**（生成到 `webots\worlds\` 下跑，
> 回传用的副本再复制到 `docs\process\sim\worlds\`）。

```powershell
# 1) 建目录（清单 §3.1 要求的回传目录）
mkdir docs\process\sim\worlds -Force

# 2) 最稳：生成到 webots\worlds\ 下（project 不变，控制器一定找得到）
python webots\tools\generate_atri_world.py --gravity=-9.81 --max-torque=2.94 --ground `
  --out webots\worlds\atri_22dof_gravity.wbt
copy webots\worlds\atri_22dof_gravity.wbt docs\process\sim\worlds\atri_22dof_gravity.wbt

# 2b) 或者：按清单口径直接生成到 docs\process\sim\worlds\（配合 §8.7 的办法 2）
python webots\tools\generate_atri_world.py --gravity=-9.81 --max-torque=2.94 --ground `
  --out docs\process\sim\worlds\atri_22dof_gravity.wbt
```

等价的**环境变量**写法（本题面要求的形式；Linux/macOS 下直接照抄）：

```bash
ATRI_WORLD_GRAVITY=-9.81 ATRI_WORLD_MAX_TORQUE=2.94 ATRI_WORLD_GROUND=1 \
  python3 webots/tools/generate_atri_world.py --out docs/process/sim/worlds/atri_22dof_gravity.wbt
```

```powershell
$env:ATRI_WORLD_GRAVITY = "-9.81"; $env:ATRI_WORLD_MAX_TORQUE = "2.94"; $env:ATRI_WORLD_GROUND = "1"
python webots\tools\generate_atri_world.py --out docs\process\sim\worlds\atri_22dof_gravity.wbt
```

### 8.2 三条自检（不过就别往下跑）

```powershell
$W = "webots\worlds\atri_22dof_gravity.wbt"     # 或 docs\process\sim\worlds\…
(Select-String -Path $W -Pattern "gravity -9.81").Count    # 期望 1
(Select-String -Path $W -Pattern "maxTorque 2.94").Count   # 期望 22
(Select-String -Path $W -Pattern "Floor|Plane").Count      # 期望 ≥1
```

```bash
# Linux/macOS 同款
grep -c "gravity -9.81" $W; grep -c "maxTorque 2.94" $W; grep -cE "Floor|Plane" $W
```

### 8.3 S1 · 静立（批量 + GUI）

```powershell
# S1-a：静立（把任务卡目录指向一个空目录，控制器回零后不再动作）
$env:ATRI_WEBOTS_MAX_TORQUE = "2.94"
$env:ATRI_WEBOTS_TASK_CARD_DIR = "docs\process\sim\empty_cards"   # 先 mkdir
$env:ATRI_WEBOTS_EXIT_ON_DONE = "1"
$env:ATRI_WEBOTS_REPORT = "docs\process\sim\s1_report.json"
$env:ATRI_WEBOTS_LOG    = "docs\process\sim\s1_console.log"
webots --batch --mode=fast --no-rendering --minimize --stdout --stderr `
  webots\worlds\atri_22dof_gravity.wbt

# S1-b：带界面看 10 秒静立（截图/录像用）
webots --mode=realtime webots\worlds\atri_22dof_gravity.wbt
```

> ⚠ **S1 不要拿退出码判定**：任务卡目录为空时是 `passed=0 / total=0`，
> 控制器与 `run_webots_batch.ps1` 都会判"未通过"并以 **2** 退出（`total > 0` 是它的通过条件之一）。
> 这是预期的，**只看 `s1_report.json` 与 `s1_console.log`**：`simulation_alive: true`、
> `bound_joints: 22`、`max_torque_nm: 2.94` 就说明 S1 跑起来了。

### 8.4 S2 · 站立扭矩（**这一条还需要清单 §S2 的 `torque_probe.py`**）

本次改动**没有**把扭矩反馈（`enableTorqueFeedback` / `getTorqueFeedback`）接进 `atri_controller`，
原因：S2 的工况是"下发零位站姿 → 保持 10 仿真秒 → 记录每关节峰值"，与控制器现在跑的
"回零 → 连跑 5 张任务卡"不是同一个工况，硬塞进去会污染 S3 的回归结论。所以 S2 走清单 §S2 的路子：

1. 用 `docs/process/sim/torque_probe.py`（清单 §S2 已给出全文，照抄即可）；
2. 把带重力世界的 `Robot.controller` 字段指到它（或在世界副本同目录放 `controllers/torque_probe/`）；
3. **扭矩上限已经由世界文件钉死**：本线程生成的世界里 22 个电机全部写了 `maxTorque 2.94`，
   所以那份探针**即使不调 `setAvailableTorque()`，读数也已经是 2.94 N·m 截断的**——
   这正是清单 §S2 最担心的"默认 10 N·m 让结论作废"那个坑，现在从世界侧堵死了；
4. 跑之前把这段写进报告：世界路径 + `gravity=-9.81` + `basicTimeStep=32` + `maxTorque=2.94`（×22）。

### 8.5 环境变量速查（S1/S2 都会用到）

| 变量 | S1/S2 建议值 | 说明 |
|---|---|---|
| `ATRI_WEBOTS_MAX_TORQUE` | `2.94` | 运行时给 22 个电机设可用扭矩上限（与世界里的 `maxTorque` 同值，两道保险） |
| `ATRI_WEBOTS_EXIT_ON_DONE` | `1` | 批量必需，否则控制器挂在保持循环里 |
| `ATRI_WEBOTS_REPORT` | `docs\process\sim\s1_report.json` | 机读结论 |
| `ATRI_WEBOTS_LOG` | `docs\process\sim\s1_console.log` | 控制台全文（Webots 的 `--stdout` 要等它退出才 flush） |
| `ATRI_WEBOTS_TASK_CARD_DIR` | 空目录（仅 S1 静立） | 指向空目录 = 只回零、不跑任务 |

### 8.6 世界文件里实际会出现的三个值（回传报告照抄这行）

```
gravity -9.81      basicTimeStep 32      maxTorque 2.94（22/22 个电机）
```

### 8.7 ⚠ 控制器发现风险（**本机没 Webots，未实测，请先确认**）

Webots 是在"**世界文件所在 project 的 `controllers/` 目录**"里找 `atri_controller` 的
（`webots/README.md` 里"不需要手工设 `<extern>`"就是靠这个机制）。世界一旦放到
`docs\process\sim\worlds\`，project 就变成 `docs\process\sim\`，那里**没有** `controllers\atri_controller`
——控制器可能起不来，**表现是报告 JSON 一直不出现**（`run_webots_batch` 会超时退出 2 并打印日志尾部，
`webots` 控制台里应当是找不到控制器的报错）。两个稳妥办法，任选：

1. **把世界放在 `webots\worlds\` 下再跑**（§8.1 第 2 条；project 不变，控制器一定找得到），
   回传用的副本再复制到 `docs\process\sim\worlds\`；这个派生文件**不要提交**（生成产物）；
2. **保持 `docs\process\sim\worlds\`**，把 `webots\controllers\atri_controller\` 整个复制成
   `docs\process\sim\controllers\atri_controller\`，Webots 就会在派生 project 里找到它。

两条都试一下只要 1 分钟，**别在这个坑上耗**：先看 `webots` 控制台有没有
`A.T.R.I. Webots 控制器启动` 这行——有就说明控制器起来了。

---

## 9. 本次**没做**的事（诚实清单，别误读）

1. **扭矩反馈没接进控制器**：`enableTorqueFeedback` / `getTorqueFeedback` 一行都没写。
   S2 仍需要清单 §S2 的 `docs/process/sim/torque_probe.py`。本线程只保证"扭矩上限是真的"，
   不保证"有扭矩读数"。
2. **没有在 Webots 里打开过世界**：本机没装 Webots。重力/接触/地面的**物理行为**
   （会不会穿地、接触抖动多大、`basicTimeStep 32` 够不够）**全部未实测**。
   如果站着抖/穿透，清单 §S1「失败先查」第 3 条给的处置是**把 `basicTimeStep` 降到 8**——
   本次**没有**加这个开关（超出 T6 任务书的 4 个开关），请在派生世界副本上手工改那一行，
   并在报告里注明用了哪个值。
3. **世界仍是"盒子脚"**：`left/right_ankle_pitch_link` 的碰撞体还是一个 `Box 0.11 0.06 0.0196`，
   不是新足底的四只 Φ8 垫。所以 S1 的"侧向能偏多少才翻"只能给**盒子口径**的近似值
   （清单 §0.5 已说明）。
4. **`design/atri.urdf` 质量仍是旧口径**（3436.6 g），世界是 3136.6 g；
   §0.4 偏差 1 请在仿真报告里**原样复述**。
5. **额定扭矩口径**：主判据是连续额定 **0.98 N·m**（占额定 152%/194% 的踝与 `trunk_roll`），
   峰值 1.47 只作瞬时参考，堵转 2.94 是物理上限；§0.4 偏差 2 同样要复述。
6. **`ATRI_WORLD_*` 只影响生成器，不影响已在跑的世界**：改开关后必须重新生成并**用新文件**跑，
   `webots` 不会热加载。

---

## 10. 口径声明

- 本报告里的**真实输出**：§2 / §3 / §4 的命令与输出，全部是本机 2026-09-12 实跑，
  原始文件在 `/tmp/verify_out.txt` 与 `/tmp/verify_extra.txt`（本机临时文件，未入库）；
- 本报告里的**静态核实值**：`gravity -9.81`、`maxTorque 2.94` × 22、`Plane` 4 m × 4 m、
  `RotationalMotor` 块数 22 —— 都是**对生成产物文本的 grep / 正则统计**，不是 Webots 的运行时读数；
- 本报告里的**设计值**：STS3215 堵转 2.94 N·m、连续额定 0.98 N·m、峰值 1.47 N·m
  （来自 `design/handoff/hardware_requirements.json` 与 `STS3215-官方规格书核验.md`）；
  Webots `RotationalMotor.maxTorque` 默认 10 N·m 来自 Webots 官方文档；
- **本报告不含任何"实测值"**：本机没有真机、没有 Webots，仿真也还没跑过。
  等队友回传 `docs/process/sim/` 后，那些数字才是**仿真值**，且**不得写成实测值**（仓库规矩第 4 条）。
