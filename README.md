# 搞机器人（A.T.R.I. 桌面自主人形智能）

本文件夹为 A.T.R.I. 项目的新工作目录。已把散落在各处（deepseek harness 等）的机器人相关材料整理进来，并新建了一套 **零硬件依赖、可直接编译运行** 的软件栈。

## 目录结构

```
搞机器人/
├── ATRI_Project_Presentation-定稿.pptx  # PPT 定稿（预算口径已与 BOM 对齐）
├── ATRI_Project_Presentation.pptx        # 上一版 PPT（备份）
├── 附件3：学生版系统操作手册.docx          # 省赛系统上传操作说明
├── 项目文档/                              # 精选项目文档
│   ├── A.T.R.I.项目综述.md
│   ├── 修改意见.md                        # 上一版评审修改意见（重要）
│   ├── 技术方案.md                        # 技术方案文档版（设计/当前/后续口径）
│   ├── BOM与阶段性指标.md                 # BOM 表 + 量化技术指标
│   ├── 答辩Q&A.md                         # 答辩口径准备
│   └── 大创赛_小机器人组_群聊讨论稿_v1.md/pdf
├── 材料汇总/deepseek-harness/             # 从 deepseek harness/搞机器人 收集来的全部材料
│   ├── A.T.R.I.-宣传PPT-评审遴选版.pptx 等
│   ├── A.T.R.I.桌面自主人形智能-项目企划书*.docx
│   └── A.T.R.I.-宣传PPT-v2/              # HTML 宣传物料
├── .github/workflows/ci.yml               # GitHub Actions CI
└── 软件/atri/                             # 可编译运行的软件集成
```

> 说明：`~/Documents/Codex/搞机器人` 经确认是**其他东西**，不属于本项目，未收集。

## 软件栈（软件/atri）

“大脑—小脑”双层架构 + JSON 任务卡 + FSM + 五项技能 + **脚本动作库/步态生成**（已弃用 VLA）。
核心代码 **仅依赖 Python 3.9+ 标准库**，无硬件、无 GPU 也能跑通全流程。

已新增：
- `atri/perception/`：视觉感知接口 + Mock + OpenCV 实现（人脸/二维码/球）
- `atri/voice/`：离线关键词识别接口 + TTS（Mock / macOS say）
- `atri/qrgen.py`：二维码 JSON 指令生成器
- `action_library/`：动作库 JSON 规范 + 示例 + 校验/回放

```bash
cd '/Users/hpi/Documents/搞机器人/软件/atri'

# 编译检查
python3 -m compileall -q atri run_demo.py && echo "compile OK"

# 单元测试（当前 51 项）
python3 -m unittest discover -s tests -v

# 无硬件闭环演示（顺序执行五项任务卡；--fast 跳过 sleep 用于快速自检）
python3 run_demo.py --fast
```

## 当前状态与后续

- 已完成：材料归集、软件骨架、五项任务卡、FSM、脚本运动控制、视觉/语音接口、二维码生成器、动作库格式、项目文档初版、CI 工作流。
- 待办：承诺书与查重报告、省赛系统上传、Webots 仿真（Windows 4060）、真实视觉/语音联调、硬件样机标定。