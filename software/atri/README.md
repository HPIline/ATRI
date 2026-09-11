# A.T.R.I. 软件栈

这是 A.T.R.I. 双足人形机器人核心控制软件包。基于“大脑—小脑”分层解耦架构开发，上层负责认知与状态机调度，下层负责步态动力学与总线控制。

代码仅依赖 Python 3.14 标准库开发，脱离实体硬件时可通过内置的 Mock 机制直接执行任务卡和步态回放。

## 架构结构

```
run_demo.py                 # 一键闭环演练入口（顺序执行五项任务卡）
run_bringup.py              # 真机 bring-up（扫描 / 限位 / 中位 / 点动；可 Mock）
atri/
  config.py                 # 22 自由度关节命名、限位角与零位定义
  task_card.py              # JSON 任务卡解析、校验与参数绑定
  fsm.py                    # 任务生命周期有限状态机（待机/进入/执行/反馈/终止）
  brain.py                  # 大脑调度核心：技能注册、上下文管理、感知与语音装配
  cerebellum.py             # 小脑控制核心：参数化双足步态生成、动作库回放、安全限位钳制
  bus_sts3215.py            # STS3215 真机总线（SYNC WRITE；角度换算走 config.deg_to_pulse）
  bringup.py                # 真机 bring-up 流程（不含串口；总线由 --bus 注入）
  skills/                   # 赛题技能实现（face / qr / carry / kick / dance）
  perception/               # 视觉感知接口（MockPerception / OpenCVPerception）
  voice/                    # 语音交互接口（Mock / Linux 探测 / macOS say）
  qrgen.py                  # 二维码离线指令图生成器
  action_library.py         # 关键帧动作库校验工具
  action_export.py          # 动作序列导出工具
  sim.py                    # 纯软件闭环仿真入口
config/robot.json           # 机器人拓扑配置与小脑后端设置
task_cards/*.json           # 五项赛题结构化任务卡定义
action_library/             # 预先标定的关键帧动作库文件
tests/                      # 软件单元测试套件
```

## 快速上手

从仓库根目录进入软件子工程：

```bash
cd software/atri

# 1) 语法与字节码编译检查
python3 -m compileall -q atri run_demo.py && echo "compile OK"

# 2) 执行完整单元测试套件
python3 -m unittest discover -s tests

# 3) 执行五项任务无硬件快速自检演练
python3 run_demo.py --fast
```

当前单元测试套件包含 **427** 项测试（以 `python3 -m unittest discover -s tests` 当场输出为准），覆盖状态机流转、技能成败、总线限位、NaN/Inf 拒绝、感知容错及任务卡解析。

## 视觉感知模块

感知接口定义位于 `atri/perception/`。支持脱机测试与实体摄像头部署平滑切换：

```python
from atri.perception import MockPerception, OpenCVPerception

# 1) 脱机开发与模拟自检
p = MockPerception()
print(p.detect_face().to_dict())

# 2) 接入真实摄像头（需安装 opencv-python-headless）
p = OpenCVPerception()
print(p.detect_qr(frame=frame))
```

在无图形界面的嵌入式设备上，请安装无头版本：`pip install opencv-python-headless`。

## 语音交互模块

语音接口位于 `atri/voice/`。负责离线关键词捕获与文本语音播报（TTS）：

```python
from atri.voice import MockKeywordRecognizer, MockTTS, VoiceService

svc = VoiceService(recognizer=MockKeywordRecognizer(), tts=MockTTS())
print(svc.respond())
```

- **Linux 环境**：模块依次自动检测系统可用的 `piper`、`espeak-ng`、`espeak`、`spd-say` 引擎，或通过环境变量 `ATRI_TTS` 显式指定。若系统未安装任何语音包，自动降级为安全的 `MockTTS`。
- **macOS 环境**：可直接接入系统原生 `say` 命令。

## 二维码离线指令生成

可使用内置命令行工具生成内嵌标准化任务动作的二维码图片：

```bash
pip install "qrcode[pil]"   # 图像渲染可选依赖
python3 -m atri.qrgen --action walk --steps 3 --output qr_walk.png
```
