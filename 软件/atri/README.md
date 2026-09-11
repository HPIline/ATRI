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
  perception/               # 视觉感知接口：MockPerception + OpenCVPerception
  voice/                    # 语音交互接口：Mock 关键词识别 + TTS（macOS say）
  qrgen.py                  # 二维码 JSON 指令生成器
  action_library.py         # 动作库 JSON 校验器
  action_export.py          # 动作库导出工具（Cerebellum -> JSON）
  sim.py                    # 无硬件闭环仿真入口
config/robot.json           # 机器人配置（motion.backend = scripted）
task_cards/*.json           # 五项赛题任务卡
action_library/             # 动作库 JSON 规范 + 示例（Webots 标定导入/导出）
tests/                      # 单元测试
```

> 大脑已支持注入 `perception` 和 `tts`：`Brain(cerebellum, perception=..., tts=...)`。
> `run_demo.py` 默认使用 `MockPerception` + `MockTTS`，技能链无需预填观测即可从感知/语音接口取数。

## 运动控制方案（已弃用 VLA）

运动控制采用 **脚本动作库 + 双足步态生成 + 视觉伺服微调**，全部本地 CPU 可运行：

- 行走：`generate_gait()` 生成双足交替正弦步态关键帧；
- 踢球/抓取/舞蹈：`kick() / grasp() / dance()` 预标定关键帧动作；
- 动作库 JSON：`action_library/` 定义关键帧规范，`Cerebellum.play_action()` 直接回放；
- 视觉对齐：`execute_motion("align", obs)` 根据观测做朝向/姿态微调；
- 部署路径：先在仿真（Webots/PyBullet）中标定动作参数，再移植到 STM32 + IMU 小脑。

## 快速开始

```bash
cd <repo>/软件/atri   # 从仓库根出发

# 1) 编译检查（标准库即可）
python3 -m compileall -q atri run_demo.py && echo "compile OK"

# 2) 跑全部单元测试
python3 -m unittest discover -s tests -v

# 3) 跑无硬件闭环演示（--fast 可跳过 time.sleep，用于 CI/快速自检）
python3 run_demo.py --fast
```

当前测试：316 项全部通过（感知、语音、二维码生成、动作库均含单元测试）。

## 视觉感知（atri/perception）

```python
from atri.perception import MockPerception, OpenCVPerception

# 无硬件开发/测试
p = MockPerception()
print(p.detect_face().to_dict())

# 真机/OpenCV（Windows 或装好 opencv-python 后）
p = OpenCVPerception()
print(p.detect_qr(frame=frame))
```

OpenCV 为可选依赖：`pip install opencv-python`。

## 语音交互（atri/voice）

```python
from atri.voice import MockKeywordRecognizer, MockTTS, VoiceService

svc = VoiceService(recognizer=MockKeywordRecognizer(), tts=MockTTS())
print(svc.respond())  # {'keyword': '跳舞', 'reply': '跳舞'}
```

macOS 可用 `MacOSTTS` 直接调用系统 `say`；Windows 后续接本地 TTS/离线关键词引擎。

## 二维码 JSON 指令生成器

```bash
pip install "qrcode[pil]"   # 可选
python3 -m atri.qrgen --action walk --steps 3 --output qr_walk.png
```

生成内容示例：`{"action":"walk","steps":3}`。

## 动作库 JSON

规范与示例见 `action_library/`。校验与回放：

```python
from atri.action_library import load_action
from atri.cerebellum import Cerebellum

action = load_action("action_library/examples/kick.json", strict=True)
Cerebellum().play_action(action)
```

## 任务卡

任务卡是“一机五任务”的统一入口。示例见 `task_cards/`。新增任务只需新增
`atri/skills/xxx.py` 并在 `Brain` 注册，不改底层。