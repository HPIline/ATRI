# Webots 仿真（Windows + RTX 4060）

本目录是 A.T.R.I. 的 Webots 控制器与仿真世界。控制器复用 `软件/atri` 的
`Brain + Cerebellum + TaskCard`，只把 `ServoBus` 换成 Webots 电机，
并用 `robot.step()` 推进仿真时间——**跑的是和无硬件闭环演示完全同一条链路**
（`atri.sim.run_task_cards`），不是另写一份。

## 实测结果

在 Windows + RTX 4060 Laptop（Python 3.12.2、Webots R2025a）上实跑 `atri_22dof.wbt`：

```
Webots 闭环: 5/5 项任务通过
  关节绑定  : 22/22（未绑定 0 个）
  有行程关节: 18/22
  仿真时间  : 14.48 s（452 步，墙钟 0.25 s）
```

“有行程关节”是用位置传感器在每个仿真步回读关节角、取整轮的最大最小差得到的，
即**电机真的转了**，而不是只有 FSM 逻辑跑通。没有行程的 4 个是
`left_hip_yaw / left_hip_roll / right_hip_yaw / right_hip_roll`——
当前五项任务卡的动作里根本没有下发过髋侧摆/髋偏航（`Cerebellum` 里只有 `execute_motion("转")`
会用到 `hip_yaw`，而五张任务卡都不会走到那一支），属于运动设计的待补项，不是仿真问题。

## 目录结构

```
webots/
├── README.md
├── worlds/
│   └── atri_22dof.wbt                     # 自包含 22 DOF 世界（可直接打开就跑）
├── tools/
│   ├── generate_atri_world.py             # 世界文件生成脚本（改模型改这里）
│   └── run_webots_batch.ps1               # 无人值守批量联调（推荐用这个）
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

脚本会后台起 Webots、等控制器写出报告、再收掉 Webots，最后打印结论并以
`0`（全过）/ `2`（没过）退出，方便接到批处理或 CI 上。

> 为什么要脚本：`webots --batch` 跑完**不会自己退出**——控制器按
> `--exit-on-done` 退出了，但仿真还在继续，Webots 进程一直挂着，
> 控制台输出也一直不 flush。脚本负责等报告出现后收尾。

### 方式 B：GUI 里看动作

用 Webots 打开 `webots/worlds/atri_22dof.wbt` 直接点运行。
世界里的机器人 `controller` 字段已经指向 `atri_controller`，
控制器就在同级 `webots/controllers/` 下，Webots 能自己找到，**不需要手工设 `<extern>`**。

> 世界把 `WorldInfo.gravity` 设为 `0`：这是**运动学联调**世界，验证的是
> 22 个关节角有没有被正确下发与跟随，不是双足平衡。零重力下机器人不会倒地，
> 关节可以自由摆动，轨迹看得最清楚。平衡控制是后续（硬件样机 + IMU）的事。

## 联调报告

控制器用 `--report`（或环境变量 `ATRI_WEBOTS_REPORT`）写一份机读结论。
本机实测：

```json
{
  "passed": 5, "total": 5,
  "bound_joints": 22, "expected_joints": 22, "unbound_joints": [],
  "mapping": "joint_mapping.json",
  "basic_time_step_ms": 32, "velocity_rad_s": 2.0,
  "sim_seconds": 14.48, "sim_steps": 452,
  "wall_seconds": 0.247, "simulation_alive": true,
  "moved_joints": 18,
  "joint_travel_deg": {
    "head_yaw": 31.85, "left_shoulder_pitch": 45.22, "right_hip_pitch": 30.21,
    "left_hip_yaw": 0.0, "left_hip_roll": 0.0,
    "...": "每个关节一项，共 22 项"
  },
  "tasks": [{"task_id": "T-01", "ok": true, "history": ["STANDBY", "ENTERING", "EXECUTING", "FEEDBACK", "DONE"], "error": null}]
}
```

控制器退出码：`0` = 五项任务全过且仿真全程存活；`2` = 有任务失败，或仿真提前结束
（仿真提前结束时任务只是“逻辑上”跑完了，动作并没有真的走完，不算通过）。

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
| `ATRI_WEBOTS_TASK_CARD_DIR=<路径>` | 任务卡目录 |

直接调试控制器时也可以照常用命令行参数（`--exit-on-done` / `--report` 等），
命令行优先于环境变量。

`joint_mapping_nao.json` 是给 Webots 自带样例世界（`File > Open Sample World`
搜 Nao）用的参考映射，不是本仓库世界的映射：Nao 没有躯干 2 DOF 和夹爪 2 DOF，
用它会绑定 18/22，其余 4 个会列在 `unbound_joints` 里。

## 这一版修了什么

第一版控制器从来没在 Webots 里跑通过。下面每一条都是**实际联调时暴露**的：

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
| 9 | 只有控制器，没有世界 | 每次要手工拖机器人、手工配映射 | 提供自包含的 `atri_22dof.wbt`，打开就跑 |
| 10 | 世界文件 `gravity 0 0 0` | **Webots 里 `WorldInfo.gravity` 是 SFFloat（沿“下”轴的大小），不是 SFVec3f**。写成三个数会让世界解析失败，Webots **静默回退到内置 `empty.wbt`**——机器人根本不存在，22 个电机一个都绑不上，而且控制台没有任何报错 | 改成 `gravity 0`；并在 `webots/tests` 加了断言钉住它 |
| 11 | 无法证明电机真的动了 | FSM 全绿也可能只是逻辑跑通 | 每个仿真步回读位置传感器，报告给出 `joint_travel_deg` / `moved_joints` |

## 世界文件怎么改

`worlds/atri_22dof.wbt` 由脚本生成，**不要手改**，改 `tools/generate_atri_world.py` 后重新生成：

```powershell
python webots/tools/generate_atri_world.py
```

CI 会重新生成一次并 `git diff --exit-code`，保证 `.wbt` 和生成脚本不漂。

世界是**自包含**的：全部使用 Webots 内置节点（`Robot` / `HingeJoint` /
`RotationalMotor` / `PositionSensor` / `Solid` / `Box`），**不引用任何 `EXTERNPROTO`**。
这一点是刻意的——外部 PROTO 要从 GitHub 拉，本机（以及比赛机器）访问 GitHub 受限，
一旦依赖外部 PROTO 世界就可能打不开。

模型是一个 22 DOF 桌面人形，关节名与 `joint_mapping.json` 一一对应：

```
躯干 2  : trunk_pitch, trunk_roll
头部 2  : head_yaw, head_pitch
左臂 4  : left_shoulder_pitch, left_shoulder_roll, left_elbow_pitch, left_gripper
右臂 4  : right_shoulder_pitch, right_shoulder_roll, right_elbow_pitch, right_gripper
左腿 5  : left_hip_yaw, left_hip_roll, left_hip_pitch, left_knee_pitch, left_ankle_pitch
右腿 5  : right_hip_yaw, right_hip_roll, right_hip_pitch, right_knee_pitch, right_ankle_pitch
```

## 没有 Webots 也能验（CI 用的就是这条）

`tests/webots_api_stub.py` 顶替 Webots 的 `controller` 模块，
并把真实 Webots 的几个坑一起复刻了（未使能的传感器返回 NaN、
`getDevice()` 对不存在的设备返回 `None`、`robot.step()` 仿真结束返回 -1），
所以离线测出来的结论对真机是有意义的：

```powershell
python -m unittest discover -s webots/tests -v
```

共 19 项，覆盖：22 关节全绑定、传感器全部使能、速度已设置、关节真的动了、
Nao 映射只绑 18 个、映射指向不存在的电机时跳过不崩、仿真提前结束时干净退出、
`--report` 字段正确、环境变量能配好批量运行，以及世界文件的结构断言
（含 `gravity` 必须是单个数字那条——离线唯一能挡住第 10 条坑的地方）。

## 注意

- Webots 的 Python 解释器版本要与你的命令行 Python 一致（Webots 设置里有
  `Python command` 选项）。本机命令行是 Python 3.12。
- 控制器通过 `sys.path` 指向 `软件/atri`，不需要 `pip install`。
- 执行任务时控制器用 `robot.step()` 推进仿真，不要在 `Cerebellum` 里再调用
  `time.sleep`；`Cerebellum` 已支持注入 `sleeper`。
- 若某些电机名不存在，控制器会跳过并在控制台提示，不会崩，
  最终在 `--report` 的 `unbound_joints` 里列出来。
