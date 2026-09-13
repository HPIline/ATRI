# Webots 仿真（Linux 优先，Windows 实测记录保留）

> **默认世界是 20 DOF v2 运动学联调世界** `worlds/atri_v2.wbt`（无 hip_yaw，控制器 `atri_controller`）。旧 22 DOF 世界备份在 `archive/v1-22dof/webots/worlds/atri_22dof.wbt`，不要当当前证据。CAD 网格导入冒烟见 `design/v2/WEBOTS-STATUS.md`。默认批量脚本跑的是 **零重力关节下发/回读**，不是 G4，不是真机。

本目录是 A.T.R.I. 的 Webots 控制器与仿真世界。控制器复用 `software/atri` 的
`Brain + Cerebellum + TaskCard`，只把 `ServoBus` 换成 Webots 电机，
并用 `robot.step()` 推进仿真时间——**跑的是和无硬件闭环演示完全同一条链路**
（`atri.sim.run_task_cards`），不是另写一份。

## 实测结果

在本机 Webots R2025a 批跑 `atri_v2.wbt`（盒体运动学、重力 0）：

```
Webots 闭环: 5/5 项任务通过
  关节绑定  : 20/20（映射应绑定 20，未绑定 0 个）
  有行程关节: 20/20
  仿真时间  : 12.72 s（397 步，墙钟 0.12 s）
```

“有行程关节”是用位置传感器在每个仿真步回读关节角、取整轮的最大最小差得到的，
即**指令确实下发到了电机、关节链路是通的**，而不是只有 FSM 逻辑跑通。
v2 已去掉 `hip_yaw`。转向用左右髋 roll 反对称占位，不是真实偏航，G4 仍开放。

> 这个闭环验证的是**关节链路与指令下发**（角度限位、传感器回读、行程），不是刚体动力学：
> 世界把 `gravity` 设为 `0`（生成器里有解释），机器人不会倒地，也不做平衡/接触力计算。
> 平衡控制是后续（硬件样机 + IMU）的事。

## 目录结构

```
webots/
├── README.md
├── worlds/
│   └── atri_v2.wbt                        # 自包含 20 DOF 运动学联调世界
├── tools/
│   ├── generate_atri_world.py             # 世界文件生成脚本（从 v2 URDF + profile.py 派生；
│   │                                      #   可选开关 ATRI_WORLD_GRAVITY / _MAX_TORQUE / _GROUND 与 --out，见「带重力/带地面的校核跑法」）
│   ├── run_webots_batch.ps1               # 无人值守批量联调（推荐用这个）
│   └── run_webots_batch.sh                # 同上（Linux）
├── tests/
│   ├── webots_api_stub.py                 # Webots controller 模块的可信替身
│   └── test_atri_controller.py            # 无 Webots 也能跑的控制器端到端测试
└── controllers/
    └── atri_controller/
        ├── atri_controller.py             # 控制器入口
        ├── joint_mapping.json             # ATRI 关节名 -> Webots 电机名（默认同名）
        └── joint_mapping_nao.json         # 内置 Nao 的参考映射（非本世界用）
```

## 快速跑通

1. 安装 Webots（R2023b 或更新，本机实测 R2025a）。Windows 静默安装：
   ```powershell
   .\webots-R2025a_setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-
   ```
2. 克隆仓库并进入：
   ```powershell
   git clone https://github.com/HPIline/ATRI.git
   cd ATRI
   ```

### 方式 A：批量无人值守（推荐）

```powershell
powershell -File webots\tools\run_webots_batch.ps1
```

```bash
bash webots/tools/run_webots_batch.sh
```

脚本会后台起 Webots、等控制器写出报告、再收掉 Webots，最后打印结论并以
`0`（全过）/ `2`（没过）退出，方便接到批处理或 CI 上。

> 为什么要脚本：`webots --batch` 跑完**不会自己退出**——控制器按
> `--exit-on-done` 退出了，但仿真还在继续，Webots 进程一直挂着，
> 控制台输出也一直不 flush。脚本负责等报告出现后收尾。

### 方式 B：GUI 里看动作

用 Webots 打开 `webots/worlds/atri_v2.wbt` 直接点运行。
世界里的机器人 `controller` 字段已经指向 `atri_controller`，
控制器就在同级 `webots/controllers/` 下，Webots 能自己找到，**不需要手工设 `<extern>`**。

> 世界把 `WorldInfo.gravity` 设为 `0`：这是**运动学联调**世界，验证的是
> 20 个关节角有没有被正确下发与跟随（限位、速度、回读），不是双足平衡，
> 也不是刚体动力学。零重力下机器人不会倒地，关节可以自由摆动，轨迹看得最清楚。
> 平衡控制是后续（硬件样机 + IMU）的事。

## 联调报告

控制器用 `--report`（或环境变量 `ATRI_WEBOTS_REPORT`）写一份机读结论。
本机实测：

```json
{
  "passed": 5, "total": 5,
  "bound_joints": 20, "mapped_joints": 20, "binding_ok": true,
  "expected_joints": 20, "unbound_joints": [],
  "mapping": "joint_mapping.json",
  "basic_time_step_ms": 32, "velocity_rad_s": 2.0,
  "sim_seconds": 14.48, "sim_steps": 452,
  "wall_seconds": 0.247, "simulation_alive": true,
  "moved_joints": 18,
  "joint_travel_deg": {
    "head_yaw": 31.85, "left_shoulder_pitch": 45.22, "right_hip_pitch": 30.21,
    "left_hip_roll": 34.54, "right_hip_roll": 34.49,
    "...": "每个关节一项，共 20 项"
  },
  "tasks": [{"task_id": "T-01", "ok": true, "history": ["STANDBY", "ENTERING", "EXECUTING", "FEEDBACK", "DONE"], "error": null}]
}
```

控制器退出码：`0` = 五项任务全过、仿真全程存活、**映射覆盖 20 个关节且全部绑定**，
**并且至少有一个关节产生了实际行程**；`2` = 上述任一条不满足
（此时任务只是“逻辑上”跑完了，动作并没有真的走完）。

判据分三层，缺一层就会放过一类假阳性：

1. **映射覆盖度**：键集合必须恰好是 20 个 ATRI 关节名。值留空是合法的
   （表示该机型没有这个自由度），但**整条省略**或**键名写错**不合法。
   只比对“绑定数 == 映射非空条目数”查不出这两种错误：映射被截断时两个计数一起变小；
   键名写错（`head_pitchh`）时坏条目同时被计入两个计数，恰好相互抵消。
   两种情况下对应关节整轮都收不到指令，报告里 `mapping_problems` 会列出原因。
2. **绑定完整性**：实际绑定数 == 映射中非空条目数，且 > 0。不是“必须 20/20”——
   `joint_mapping_nao.json` 故意留空 4 个自由度（Nao 没有躯干 2 DOF 与夹爪 2 DOF），
   绑定 16/20 是预期行为，仍然判通过。
3. **实际行程**：至少一个关节的行程 > 1°（报告 `motion_ok`）。绑定完整也可能一步未动——
   `--velocity 0` 在 Webots 里等于电机锁死，任务卡照样会“逻辑上”全过。

## 参数怎么传给控制器

**Webots 没有向控制器透传命令行参数的机制**（`webots --help` 里没有 `--`），
所以批量跑时用环境变量：

| 环境变量 | 作用 |
|---|---|
| `ATRI_WEBOTS_EXIT_ON_DONE=1` | 任务跑完退出控制器（批量必需，否则挂在保持循环） |
| `ATRI_WEBOTS_REPORT=<路径>` | 联调报告 JSON |
| `ATRI_WEBOTS_LOG=<路径>` | 控制器控制台输出另存一份（Webots 的 `--stdout` 要等它自己退出才 flush） |
| `ATRI_WEBOTS_MAPPING=<路径>` | 关节映射 JSON |
| `ATRI_WEBOTS_VELOCITY=<rad/s>` | 关节最大角速度，默认 2.0 |
| `ATRI_WEBOTS_MAX_TORQUE=<N·m>` | 统一设置各电机的可用扭矩上限，默认**不设**（沿用世界文件 / Webots 默认 10 N·m）。做扭矩校核请给 `2.94`；值非法时控制器**退出码 2**，不会静默放宽 |
| `ATRI_WEBOTS_TASK_CARD_DIR=<路径>` | 任务卡目录 |

直接调试控制器时也可以照常用命令行参数（`--exit-on-done` / `--report` 等），
命令行优先于环境变量。

`joint_mapping_nao.json` 是给 Webots 自带样例世界（`File > Open Sample World`
搜 Nao）用的参考映射，不是本仓库世界的映射：Nao 没有躯干 2 DOF 和夹爪 2 DOF，
用它会绑定 16/20，其余 4 个会列在 `unbound_joints` 里。

## 这一版修了什么

第一版控制器从来没在 Webots 里跑通过；后续审计又发现几条“看起来通过、实际没验到”的坑。
下面每一条都是**实际联调或离线复现时暴露**的：

| # | 问题 | 后果 | 现在 |
|---|---|---|---|
| 1 | 位置传感器没有 `enable()` | Webots 里未使能的 `PositionSensor.getValue()` 返回 **NaN**，`get_pose()` 全废 | 绑定电机后立刻 `enable(basicTimeStep)`，回读还做了 NaN 兜底 |
| 2 | 没设关节角速度 | 电机以最大速度瞬间到位，看不出运动过程 | 绑定后 `setVelocity()`，默认 2.0 rad/s，可用 `--velocity` 调 |
| 3 | 回零后只 `step` 一次 | 第一张任务卡和回零动作叠在一起 | 回零后等 `--settle-s`（默认 0.6 仿真秒）姿态稳定再开始 |
| 4 | `robot.step` 返回值没接 | 仿真结束后仍继续下发角度 | 按基础步长切片推进，返回 -1 立即停止 |
| 5 | 跑完进死循环 | `--batch` 永远不返回，无人值守跑不了 | `--exit-on-done` / `ATRI_WEBOTS_EXIT_ON_DONE=1` |
| 6 | 结果只能靠人眼看日志 | 没法进 CI | `--report` 输出 JSON + 有意义的退出码 |
| 7 | 自己复制了一份 Mock 观测 | 和 `run_demo.py` 两条链路，容易漂 | 复用 `atri.sim.run_task_cards`，注入 `MockPerception` + `MockTTS` |
| 8 | 缺 `controller` 模块时 `sys.exit(0)` | 没在 Webots 里跑却“看起来成功了” | 改成非零码退出并提示离线自检命令 |
| 9 | 只有控制器，没有世界 | 每次要手工拖机器人、手工配映射 | 提供自包含的 `atri_v2.wbt`，打开就跑 |
| 10 | 世界文件 `gravity 0 0 0` | **Webots 里 `WorldInfo.gravity` 是 SFFloat（沿“下”轴的大小），不是 SFVec3f**。写成三个数会让世界解析失败，Webots **静默回退到内置 `empty.wbt`**——机器人根本不存在，电机会绑不上，而且控制台没有任何报错 | 改成 `gravity 0`；并在 `webots/tests` 加了断言钉住它 |
| 11 | 无法证明电机真的动了 | FSM 全绿也可能只是逻辑跑通 | 每个仿真步回读位置传感器，报告给出 `joint_travel_deg` / `moved_joints` |
| 12 | 0 个关节绑定也报“联调通过”（退出码 0） | 世界损坏、映射写错、电机改名都会被宣布成功，最容易被写进答辩材料 | 绑定判据纳入退出码：实际绑定数 == 映射中非空条目数且 > 0，不满足退出码 2、报告 `binding_ok=false` |
| 13 | `WebotsServoBus` 自己覆写 `set_angle`，不设限 | `set_angle(head_yaw, 9999)` 会把 9999° 原样下发给电机，当前没出事只因为“大家都记得走 `Cerebellum.set_pose`” | 改成实现 `ServoBus._write_angle`，限位由基类模板方法统一钳制（离线测试钉住越限请求） |
| 14 | 世界文件不写限位、电机统一 `maxVelocity 2` | Webots 不写 `minStop`/`maxStop` 就是无限位；速度与模型（腿 180 dps、头/臂 240 dps）不一致 | 生成器把 `limit_deg` 写成 `minStop`/`maxStop`、`velocity_dps` 写成逐关节 `maxVelocity`，产物仍由 CI 与生成器比对 |
| 15 | 测试桩瞬间到位、`getMaxVelocity()` 恒 10 | 控制器即使删掉钳制、把目标写到限位外，离线 19 项测试仍全绿 | 桩加限位与速率模型、返回世界文件里真实的 `maxVelocity`；新增断言：所有下发角在 `limit_deg` 内、零绑定必须失败 |
| 16 | 绑定判据只比“绑定数 == 映射非空条目数” | 映射被截断（只写 1 个关节）或 ATRI 侧键名写错（`head_pitchh`）时，两个计数一起变小或把坏条目一起算进去，恰好抵消 —— 21 个关节整轮没收到指令仍报“联调通过” | 先校验映射键集合恰好是 20 个合法关节名，问题列进报告 `mapping_problems` 并计入退出码 |
| 17 | 绑定完整就算通过 | `--velocity 0` 时电机锁死，行程全为 0，任务卡照样“逻辑上”全过、退出码 0 | 至少一个关节行程 > 1° 才算通过（报告 `motion_ok`） |
| 18 | 软钳制读 `atri.config`、世界硬限位读 `design/v2/profile.py`，两份数据没人对账 | 只改一处时：软钳制更宽会让指令被 Webots 硬限位截停而报告按指令角记账；更窄则世界允许的行程永远到不了 | 离线测试逐关节断言两处 `limit_deg` 相等 |

## 世界文件怎么改

`worlds/atri_v2.wbt` 由脚本生成，**不要手改**。
几何/质量来自 `design/v2/out/sim/atri_v2.urdf`，限位来自 `design/v2/profile.py`。
改模型后重跑生成器：

```powershell
python webots/tools/generate_atri_world.py
```

CI 会重新生成一次并 `git diff --exit-code`，保证 `.wbt` 和生成脚本不漂。
生成器另有一条断言：世界里的关节名必须与 `profile.py` **逐一对应**，
所以"世界漏掉/多出关节"这类问题会在生成时就报错。

> 生成器还有一行"可选覆盖"：`ATRI_WORLD_GRAVITY` / `ATRI_WORLD_MAX_TORQUE` /
> `ATRI_WORLD_GROUND` / `--out`，**都不给时行为与以前一字不差**。
> 带重力的校核世界怎么生成、怎么跑，见上面「带重力/带地面的校核跑法」。

> 每个关节的 `minStop`/`maxStop`（弧度）与 `maxVelocity`（rad/s）同样派生自模型：
> 前者来自 `limit_deg`，后者来自 `velocity_dps`（腿 180 dps = 3.1416 rad/s、
> 头/臂 240 dps = 4.1888 rad/s）。世界里不再有"统一 2 rad/s"这种与模型无关的常量。

> 世界里的每个 Solid 质量 = 对应 link 的**真实质量**（含舵机与电子件），
> 与 `design/v2/out/sim/atri_v2.urdf` 同源。

世界是**自包含**的：全部使用 Webots 内置节点（`Robot` / `HingeJoint` /
`RotationalMotor` / `PositionSensor` / `Solid` / `Box`），**不引用任何 `EXTERNPROTO`**。
这一点是刻意的——外部 PROTO 要从 GitHub 拉，本机（以及比赛机器）访问 GitHub 受限，
一旦依赖外部 PROTO 世界就可能打不开。

模型是一个 20 DOF 桌面人形（无 hip_yaw），关节名与 `joint_mapping.json` 一一对应：

```
躯干 2  : trunk_pitch, trunk_roll
头部 2  : head_yaw, head_pitch
左臂 4  : left_shoulder_pitch, left_shoulder_roll, left_elbow_pitch, left_gripper
右臂 4  : right_shoulder_pitch, right_shoulder_roll, right_elbow_pitch, right_gripper
左腿 4  : left_hip_roll, left_hip_pitch, left_knee_pitch, left_ankle_pitch
右腿 4  : right_hip_roll, right_hip_pitch, right_knee_pitch, right_ankle_pitch
```

## 带重力/带地面的校核跑法

默认世界是**零重力运动学联调**世界（`gravity 0`、无地面、电机不写 `maxTorque`），
它只回答"20 个关节角有没有被正确下发与跟随"；**回答不了**静立与站立扭矩——
零重力下机器人悬浮不下垂，电机的静力矩 ≈ 0。S1（静立、支撑多边形）与
S2（逐关节站立扭矩）必须换成**带重力 + 带地面 + 显式扭矩上限**的派生世界。

> 派生世界是**生成产物**：写到 `docs/process/sim/` 之类的临时目录或仓库外，
> **不要覆盖 `webots/worlds/atri_v2.wbt`**——CI 会重跑生成器并 `git diff --exit-code` 对账。
>
> **默认模式（不带任何开关）产出的世界仍与仓库里那份逐字节一致**，
> 零重力模式继续用于**纯运动学演示**（20 个关节角下发/回读/行程）。

### 1. 生成带重力世界（仓库根目录执行）

```bash
# 带重力 + 地面 + 舵机扭矩上限（2.94 N·m = STS3215 堵转）
ATRI_WORLD_GRAVITY=-9.81 ATRI_WORLD_MAX_TORQUE=2.94 ATRI_WORLD_GROUND=1 \
  python3 webots/tools/generate_atri_world.py \
  --out docs/process/sim/worlds/atri_v2_gravity.wbt
```

等价的命令行写法（Windows PowerShell 建议用 `--gravity=-9.81` 这种 `=` 形式，
否则 `-9.81` 可能被当成参数名）：

```powershell
python webots\tools\generate_atri_world.py --gravity=-9.81 --max-torque=2.94 --ground `
  --out docs\process\sim\worlds\atri_v2_gravity.wbt
```

| 开关 | 环境变量 | 默认 | 语义 |
|---|---|---|---|
| `--gravity` | `ATRI_WORLD_GRAVITY` | `0.0` | `WorldInfo.gravity`（m/s²，**沿 Z 轴的有符号标量**，向下为负）；正值直接报错退出 |
| `--max-torque` | `ATRI_WORLD_MAX_TORQUE` | 不写该字段 | 逐 `RotationalMotor` 的 `maxTorque`（N·m）。**不写 ≠ 无限大，而是 Webots 默认 10 N·m** |
| `--ground` | `ATRI_WORLD_GROUND` | 不生成 | 生成 `Plane` 地面（4 m × 4 m，z = 0）。**重力非 0 时自动强制打开** |
| `--out` | — | `webots/worlds/atri_v2.wbt` | 输出路径 |

三条硬约束（生成器里已经卡住，不用记）：

1. **重力非 0 ⇒ 必须带地面**：没有地面就是自由落体，静立/站立数字全是废的。
   少写 `ATRI_WORLD_GROUND` 不会报错，而是**自动补上地面**并在控制台说明原因；
2. **重力为正 ⇒ 报错退出（2）**：`gravity` 是沿 Z 轴的有符号标量，正值等于让机器人往上飞；
3. **`ATRI_WORLD_GRAVITY=-9,81` 这类笔误 ⇒ 报错退出（2）**：绝不悄悄退回零重力，
   否则跑出来的还是一份"悬浮世界"，而数字看着像真的。

**地面为什么用 `Plane`、为什么取 4 m × 4 m**：`Floor` / `Ground` 都是 Webots 的 **PROTO**，
引用必须配 `EXTERNPROTO`，会破坏本世界"自包含、不引任何外部 PROTO"的约束
（见下文「世界文件怎么改」），所以用内置几何节点 `Plane`（同时兼作 `boundingObject`）。
尺寸取 4 m：机器人高约 0.467 m，静止站立与五张任务卡场景的位移都在 0.5 m 量级，
4 m 给出 ±2 m（≈ 5 倍机高）余量；`Plane` 作接触面在 Webots 里按无限平面处理，
机器人即便被推出去也不会掉出世界边界。

生成后**先自检三条，三条都过**再拿这个世界跑 S1/S2：

```bash
W=docs/process/sim/worlds/atri_v2_gravity.wbt
grep -c "gravity -9.81" $W     # 期望 1
grep -c "maxTorque 2.94" $W    # 期望恰好 20：漏一个，那个关节就还是 Webots 默认 10 N·m
grep -cE "Floor|Plane" $W      # 期望 ≥1（地面）
```

### 2. 跑 S1/S2（都用这一份带重力世界）

控制器侧的扭矩上限用 `--max-torque`（等价环境变量 `ATRI_WEBOTS_MAX_TORQUE`）在**运行时**再设一遍：
与世界文件里的 `maxTorque` 是同一件事的两道保险，报告里的 `max_torque_nm` 会记下本次用的值。

```bash
# Linux / macOS：批量无人值守（调用方 shell 里的环境变量会被继承到 Webots 进程）
ATRI_WEBOTS_MAX_TORQUE=2.94 bash webots/tools/run_webots_batch.sh \
  -World   docs/process/sim/worlds/atri_v2_gravity.wbt \
  -Report  docs/process/sim/s1_report.json \
  -Log     docs/process/sim/s1_console.log \
  -TimeoutSec 600
```

```powershell
# Windows PowerShell
$env:ATRI_WEBOTS_MAX_TORQUE = "2.94"
powershell -File webots\tools\run_webots_batch.ps1 `
  -World  docs\process\sim\worlds\atri_v2_gravity.wbt `
  -Report docs\process\sim\s1_report.json `
  -Log    docs\process\sim\s1_console.log `
  -TimeoutSec 600
```

不用脚本、直接起 Webots 看原始输出：

```bash
ATRI_WEBOTS_MAX_TORQUE=2.94 ATRI_WEBOTS_EXIT_ON_DONE=1 \
ATRI_WEBOTS_REPORT=docs/process/sim/s1_report.json \
ATRI_WEBOTS_LOG=docs/process/sim/s1_console.log \
webots --batch --mode=fast --no-rendering --minimize --stdout --stderr \
  docs/process/sim/worlds/atri_v2_gravity.wbt
```

看 GUI / 录屏（**不要**用 `--mode=fast` 录，会跑成加速看不清）：

```bash
webots --mode=realtime docs/process/sim/worlds/atri_v2_gravity.wbt
```

> ⚠ **派生世界放在 `webots/worlds/` 之外时，Webots 可能找不到控制器**
> （**本机没装 Webots，这一条没实测**，请先按下面办法之一确认）。
> 原因：Webots 是在"世界文件所在 project 的 `controllers/` 目录"里找 `atri_controller`
> 的；世界一旦放在 `docs/process/sim/worlds/`，project 就变成 `docs/process/sim/`，
> 那里并没有 `controllers/atri_controller`——控制器起不来时**表现是报告 JSON 一直不出现**
> （`run_webots_batch` 会超时退出 2 并打印日志尾部）。两个稳妥办法，任选：
>
> 1. **把世界放到 `webots/worlds/` 下再跑**（project 不变，控制器一定找得到）：
>    `python3 webots/tools/generate_atri_world.py --gravity=-9.81 --max-torque=2.94 --ground --out webots/worlds/atri_v2_gravity.wbt`
>    ——这个派生文件**不要提交**（生成产物）；要回传的副本再复制到 `docs/process/sim/worlds/`。
> 2. **保持 `docs/process/sim/worlds/` 不动**，把 `webots/controllers/atri_controller/`
>    整个复制成 `docs/process/sim/controllers/atri_controller/`，Webots 就会在派生 project 里找到它。

### 3. 回退（恢复默认行为）

不生成派生世界即可，仓库里的默认世界**不受任何影响**：

```bash
python3 webots/tools/generate_atri_world.py     # 不带开关 = gravity 0、无地面、不写 maxTorque
git diff --stat webots/worlds/atri_v2.wbt    # 期望：空输出（逐字节一致）
```

控制器侧同理：不传 `--max-torque`、不设 `ATRI_WEBOTS_MAX_TORQUE` 时**一个电机都不碰**
（报告里 `max_torque_nm: null`、`torque_limited_joints: 0`，其余字段与以前完全一致）。

## 没有 Webots 也能验（CI 用的就是这条）

`tests/webots_api_stub.py` 顶替 Webots 的 `controller` 模块，
并把真实 Webots 的几个坑一起复刻了（未使能的传感器返回 NaN、
`getDevice()` 对不存在的设备返回 `None`、`robot.step()` 仿真结束返回 -1、
电机按 `velocity`/`maxVelocity` 限速趋近目标且被关节限位截停），
所以离线测出来的结论对真机是有意义的：

```powershell
python -m unittest discover -s webots/tests -v
```

离线桩覆盖：20 关节全绑定、传感器全部使能、速度已设置、所有下发角落在
`limit_deg` 内（越限请求被钳制）、零绑定/缺电机/映射截断/键名写错必须判失败而
Nao 留空仍判通过、`--velocity 0`（零行程）必须判失败、软钳制与世界硬限位逐关节一致、
桩的限速与限位语义、仿真提前结束时干净退出、`--report` 字段正确、
环境变量能配好批量运行，以及世界文件的结构断言
（`gravity` 必须是单个数字、逐关节 `minStop`/`maxStop` 与 `maxVelocity` 必须与模型一致）。

## 注意

- Webots 的 Python 解释器版本要与你的命令行 Python 一致（Webots 设置里有
  `Python command` 选项）。本机命令行是 Python 3.12。
- 控制器通过 `sys.path` 指向 `software/atri`，不需要 `pip install`。
- 执行任务时控制器用 `robot.step()` 推进仿真，不要在 `Cerebellum` 里再调用
  `time.sleep`；`Cerebellum` 已支持注入 `sleeper`。
- 若某些电机名不存在，控制器会跳过并在控制台提示，不会崩，
  最终在 `--report` 的 `unbound_joints` 里列出来；同时因为绑定数小于映射中
  非空条目数，这次联调判**未通过**（退出码 2）。
- 关节限位在 `ServoBus.set_angle`（模板方法）里统一钳制，`WebotsServoBus` 只实现
  `_write_angle` 下发；世界里另有 `minStop`/`maxStop` 硬限位，两层都来自
  `design/v2/profile.py` 与 v2 URDF。
- 做扭矩校核时，**世界文件的 `maxTorque` 与控制器 `--max-torque` 都要设成 2.94**
  （STS3215 堵转）：前者决定 Webots 里的物理上限，后者是运行时再设一遍并记进报告。
  只做纯运动学演示时两者都不用管，默认行为不变。
