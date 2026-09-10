# A.T.R.I. 软件栈（软件集成版）

面向 A.T.R.I. 桌面自主人形智能的“大脑—小脑”双层软件框架。当前无硬件，因此全部执行
链路以 **Mock 硬件 + 任务卡 + FSM + 技能库 + 脚本动作库/步态生成** 的形式闭环。
核心代码只依赖 Python 标准库，可直接编译、直接运行、直接跑测试。

## 架构

```
run_demo.py                 # 一键演示：顺序执行 5 张任务卡
atri/
  config.py                 # 22 DOF 关节拓扑、限位、零位
  task_card.py              # JSON 任务卡解析与校验
  fsm.py                    # 待机→任务进入→技能执行→结果反馈 状态机
  brain.py                  # 大脑：调度技能、任务上下文、执行结果汇总
  cerebellum.py             # 小脑：步态生成、踢球/抓取/舞蹈动作、脚本运动调度
  skills/                   # 五项赛题技能：face / qr / carry / kick / dance
  sim.py                    # 无硬件闭环仿真入口
config/robot.json           # 机器人配置（motion.backend = scripted）
task_cards/*.json           # 五项赛题任务卡
tests/                      # 单元测试
```

## 运动控制方案（已弃用 VLA）

运动控制采用 **脚本动作库 + 双足步态生成 + 视觉伺服微调**，全部本地 CPU 可运行：

- 行走：`generate_gait()` 生成双足交替正弦步态关键帧；
- 踢球/抓取/舞蹈：`kick() / grasp() / dance()` 预标定关键帧动作；
- 视觉对齐：`execute_motion("align", obs)` 根据观测做朝向/姿态微调；
- 部署路径：先在仿真（Webots/PyBullet）中标定动作参数，再移植到 STM32 + IMU 小脑。

## 快速开始

```bash
cd /Users/hpi/Documents/搞机器人/软件/atri

# 1) 编译检查（标准库即可）
python3 -m compileall -q atri run_demo.py && echo "compile OK"

# 2) 跑全部单元测试
python3 -m unittest discover -s tests -v

# 3) 跑无硬件闭环演示
python3 run_demo.py
```

## 任务卡

任务卡是“一机五任务”的统一入口。示例见 `task_cards/`。新增任务只需新增
`atri/skills/xxx.py` 并在 `Brain` 注册，不改底层。
