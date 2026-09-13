# A.T.R.I. 软件栈

> **本包已按 ATRI-v2 A 路线改为 20 DOF、无 hip_yaw。** 关节表与限位对齐 [`design/v2/profile.py`](../../design/v2/profile.py)。转向用左右髋 roll 反对称侧倾占位，**不是真实偏航**，G4 仍开放。无硬件 5/5 任务卡与 Webots 运动学联调 **不能当作真机/赛题通过证据**。

这是 A.T.R.I. 双足人形机器人核心控制软件包。基于“大脑—小脑”分层解耦架构开发，上层负责认知与状态机调度，下层负责步态动力学与总线控制。

代码仅依赖 Python 3.14 标准库开发，脱离实体硬件时可通过内置的 Mock 机制直接执行任务卡和步态回放。

## 架构结构

```
run_demo.py                 # 一键闭环演练入口（顺序执行五项任务卡）
run_bringup.py              # 真机 bring-up（扫描 / 限位 / 中位 / 点动；可 Mock）
atri/
  config.py                 # 20 自由度关节命名、限位角与零位定义
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

单元测试覆盖状态机、技能、总线限位、NaN/Inf 拒绝、感知容错与五项任务卡。CadQuery 用例需仓库根 `.venv-cad`。以当场 `python3 -m unittest discover -s tests` 为准。

**技能可调参数**：控制常数不再写死在代码里——优先级是
**任务卡 params > `config/<skill>.json` > 代码默认值**（`atri/tuning.py`）。
随代码发布的 `config/{carry,kick,dance}.json` **只有说明、不含覆盖值**，它们是实物标定回填点；
写错的键/非法值/坏 JSON 只告警不抛异常，告警同时进 stdout 与结果的 `tuning_warnings`；
改完立刻生效（每次调用重读文件）。

**任务评测工具**（`tools/`，产出可复跑的证据；每个工具"测什么、不是什么"写在各自报告里）：

| 工具 | 任务 | 量什么 |
|---|---|---|
| `face_eval.py` / `face_enroll.py` | T-01 | LFW 识别率 / 人脸库录入 |
| `qr_eval.py` | T-02 | 27 场景 × 3 解码器 + 指令回放 |
| `carry_eval.py` | T-03 | 色块检测 + 图像在环闭环 + 参数边界表 |
| `kick_eval.py` | T-04 | 绿球检测 + 图像/几何在环闭环 + 参数边界表 |
| `dance_eval.py` | T-05 | 关键词门闩与匹配注入统计（零依赖） |
| `asr_decode_eval.py` | T-05 | 真引擎真解码（合成语音 + 白噪声扫描；需外部 venv） |

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
