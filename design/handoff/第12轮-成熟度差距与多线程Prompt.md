# 第 12 轮：成熟度差距与多线程 Prompt（2026-09-13）

> 基线：`main` @ `52b8731`（已快进；含本机 `1cf0a8d` T-01～T-05 补强 + 队友 T-02/T-03 做实 + Python 3.14 统一 + 未测项清单）。
> 赛题：小人形组原文五条 + 双足脱线 + 实物视频 ≤3 分钟。
> 本轮目标：**把「可答辩的软件证据」补齐到能交材料**，不假装已经能过赛场验收。

---

## 0. 一句话判断

**离「软件可复现、材料口径诚实」大约 70%；离「赛题可验收的成熟整机」大约 25%。**

原因不是代码写得少，而是赛题要的是**这台双足机器人在 2.4 m 场地里脱线完成五项任务**。
现在闭合的是：数据集 / 合成图 / Mock 总线 / 零重力运动学世界。
**样机、真机视觉、带重力站立、到位误差、续航，一条都没有。**

权威缺口表：`docs/process/未测项清单.md`。写材料前先搜它。

---

## 1. 现在已经算「软件成熟」的部分

| 层 | 现状 | 证据 |
|---|---|---|
| T-01 识别 | YuNet+SFace+拒识，LFW 困难协议 50 人 98.6% | `design/handoff/T-01-LFW评测报告.md` |
| T-02 路径+解码 | `atri.path.v1` + 三解码器；WeChat 判据条件 6/6；指令 10/10 | `T-02-二维码识别鲁棒性报告.md` |
| T-03 对准/不盲放 | 两步对准、没看见放置区不释放；合成图推荐参数 20/20 | `T-03-搬运-方案与评测报告.md` |
| T-04 踢球逻辑 | 多轮 `lateral_servo`，不收敛也踢但回报 `converged` | `skills/kick.py` + `test_brain.py` |
| T-05 舞蹈门闩 | 关键词白名单；通道已接入却听不清则失败 | `skills/dance.py` |
| 控制骨架 | FSM / 任务卡 / NaN 拦截 / STS3215 假串口 | 主包测试（README 数字 508/556/579 尚未对齐，以当场 `unittest` 为准） |
| CAD 几何 | 包络 407×268×160、零位摆放错误 0、门禁 17 | `assembly.py` / `test_layout.py` |
| 诚实口径 | 未测项清单 + `source` 字段纪律 | `docs/process/未测项清单.md` |

这些够写「我们把赛题五条在离线软件里逐条做实，并且知道哪些数字不能外推」。
**不够写「能过检录、能完成五项任务」。**

---

## 2. 离「可以验收」还差什么（按能否在无样机条件下推进）

### 2.1 ⛔ 没有样机就无解（本轮线程不要假装去测）

| # | 缺口 | 为什么卡验收 |
|---|---|---|
| A1 | 样机未制造 | 赛题要实物展示视频 |
| A2 | 双足连续走 ≥1 m | 现在 5/5 是任务卡流程，不是「走了 1 米不倒」 |
| A4 | STS3215 连续扭矩/温升 | 踝 147.5% 额定，纸面过载 |
| A5 | 整机能否站起来 | 结构 1.38 kg 上限、减重路径未实物验证 |
| B4 | 续航 ≥30 min | 现选 2000 mAh ≈13 min，不得写 30 分钟 |
| C2 | 舵机 sign / zero_pulse | 未装配，标定文件是空的 |

这些只能在材料里写成「设计值 / 待实测」，并给出测法。**不要派线程去「仿真出成功率」。**

### 2.2 ⚠️ 无样机也能推进（本轮主战场）

| # | 缺口 | 现在卡在哪 | 本轮能否闭合 |
|---|---|---|---|
| **材料口径** | PPT v4、计划书、README 测试数 437/508/556/579 混用 | 第 6–10 轮 CAD + T-01/02/03 之后数字全漂 | ✅ 能闭合 |
| **T-04 证据** | 踢球没有像 T-02/T-03 那样的评测报告 | 只有单元测试 | ✅ 能闭合（合成图口径） |
| **T-05 证据** | 无 ASR、无音乐节拍、无评测 | Mock 关键词 | ✅ 能闭合一半（离线引擎 + 报告，实机噪声仍未测） |
| **视频** | 仓库内参赛视频未入库；路线 B 有 299 KB mp4（gitignore） | 默认世界 `gravity 0` | ✅ 能出片，必须标注渲染/仿真 |
| **带重力世界** | 生成器开关已有，默认世界仍是零重力 | 队友机器才能跑 S1 静立 | ✅ 本机生成世界+脚本；录屏仍可能要队友 |
| **头部随动** | T-01 识别了姓名，头 2 轴没有跟 bbox | PPT 还在写「头部两轴对准」 | ✅ 能做逻辑层 |
| **CI 人脸/二维码 job** | 推送凭据缺 workflow scope | `docs/process/T-01-CI-job补丁.md` | ⚠️ 有权限才能合 |
| B3 | 树莓派耗时 | 无设备 | ❌ 跳过 |
| B1/B2/B6/B9 | 真相机/真人/真夹爪 | 无硬件 | ❌ 跳过 |

### 2.3 成熟版本还缺的「工程完整性」（不是赛题原文，但是验收官会问）

1. **一个数字只准出现一次**：README 横幅 579、快速上手 556、口径表 508、徽章 437——这本身就不成熟。
2. **PPT 仍是「人脸检测 1/4 步、搬运视觉未做」**，和当前代码相反，答辩会被问穿。
3. **计划书 / 查重 / 承诺书 / 财务报表模板**仍空（后三项只能人工）。
4. **Webots 默认世界不能证明站得住**；带重力世界是可选生成物，没有标准录屏脚本。
5. T-04 允许不收敛也踢，赛场上这是「尽力而为」，材料里不能写成「踢球成功率」。

---

## 3. 本轮线程表（文件所有权互斥）

沿用第 11 轮五条规矩：一个提交者、文件互斥、每线程一份报告、重 CAD 单线、验证命令禁止 `A && B` 假绿。

| # | 线程 | 独占文件 | 交付 | 不要碰 |
|---|---|---|---|---|
| **S1** | T-04 踢球评测（对齐 T-03 证据链） | `software/atri/tools/kick_eval.py`（新建）、`software/atri/tests/test_kick_eval.py`（新建）、`design/handoff/T-04-踢球-方案与评测报告.md`（新建）、`software/atri/config/kick.json`（新建） | 合成图检测 + 闭环收敛报告；数字标明非实机 | `skills/kick.py` 只许加**读取 tuning** 的薄封装，行为默认不变 |
| **S2** | T-05 离线语音做实 | `software/atri/atri/voice/`（可新增 `vosk.py`/`sherpa.py`，惰性导入）、`software/atri/tools/dance_eval.py`（新建）、`design/handoff/T-05-娱乐休闲-方案.md`（新建）、`software/atri/tests/test_voice_offline.py`（新建） | 可选离线 ASR；无模型则 skip；关键词白名单实测 | 禁止云端 API；禁止改 CAD |
| **S3** | 头部视觉随动（T-01 补全 PPT 已承诺的那一截） | `software/atri/atri/skills/face.py`、`software/atri/tests/test_face_skill.py`、`design/handoff/T-01-头部随动.md`（新建） | bbox → head_yaw/pitch 开环映射；无人脸不瞎转 | 不改识别器/人脸库 |
| **S4** | 口径对齐 + PPT 文案（不重生成 pptx 除非工具已通） | `docs/research/项目文档/答辩PPT-逐页文案-v4.md`、`design/handoff/答辩材料口径核对清单.md`、`README.md` **仅测试数字三处**、`docs/contest/参赛计划书.md`（新建骨架） | 一份「现行数字 → PPT 应改成什么」；计划书章节骨架 | **禁止改 pptx 二进制**（留给主会话或已有 `ppt/build_deck.py`）；禁止改 CAD |
| **S5** | 带重力世界生成脚本 + 录屏清单（不跑 GUI） | `docs/process/sim/重力世界录屏脚本.md`（新建）、`webots/tools/record_s1_s2.sh` 或 `.py`（新建，只生成世界+打印命令） | 一键生成 `atri_22dof_gravity.wbt` 到 `docs/process/sim/worlds/`（gitignore 若需要就写进报告让主会话加）；给出队友/本机录屏步骤 | **禁止改默认** `webots/worlds/atri_22dof.wbt`；禁止改生成器默认值 |
| **S6** | 主会话（我） | git / PPT 重生成 / 视频路线 B 是否入库 | 收口、提交、推送 | — |

并发：S1/S2/S3/S4/S5 可同时开（无重 CAD）。S1 与 S3 都动 `software/atri/tests/` 但不同文件。S1 对 `skills/kick.py` 的改动必须是「读 `config/kick.json`」，与 T-03 的 `tuning.py` 同构，避免和行为测试打架。

---

## 4. 可粘贴 Prompt

### ----- S1 复制开始 -----

你在仓库 `/Users/zhangjingkun/Projects/github/ATRI` 上做 **T-04 踢球评测**，对齐队友已经做完的 T-03 证据链。全部中文。禁止任何 git 操作。

**先读**
- `docs/process/未测项清单.md` B7（实机踢球成功率仍未测，本轮不要宣称闭合它）
- `design/handoff/T-03-搬运-方案与评测报告.md`（报告结构、口径措辞、评测工具风格）
- `software/atri/tools/carry_eval.py`、`software/atri/atri/tuning.py`、`software/atri/config/carry.json`
- `software/atri/atri/skills/kick.py`、`software/atri/atri/perception/opencv.py` 的 `detect_ball`

**要做**
1. 新建 `software/atri/config/kick.json`：只放说明、默认不覆盖代码常数（学 carry.json）。常数经 `tuning.py` 读取，优先级 `任务卡 params > kick.json > 代码默认`。
2. `skills/kick.py` **只加读 tuning 的薄封装**，默认行为（死区 1 cm、最多 5 轮、不收敛也踢、4–40 cm 距离门闩）必须保持，现有 `test_brain.py` 不能红。
3. 新建 `software/atri/tools/kick_eval.py`：合成绿球图 + 真 `detect_ball` + 真 `KickSkill` + 一维几何（可复用 carry 的 yaw 模型，gain 必须在报告里写明是未标定）。输出 markdown 报告到 `design/handoff/T-04-踢球-方案与评测报告.md`。
4. 报告必须分「能写进材料 / 不能外推」两栏；实机成功率写「未测」。
5. 单测 `software/atri/tests/test_kick_eval.py`：无 numpy/cv2 时 skip；有依赖时至少锁「无球失败不下发踢」「死区内 0 次迭代」。

**验收（每条后面 echo exit=$?，禁止 A && B）**
```bash
cd /Users/zhangjingkun/Projects/github/ATRI/software/atri
python3 -m unittest tests.test_brain tests.test_kick_eval -v
echo "exit=$?"
python3 -m unittest discover -s tests 2>/tmp/atri-s1.txt
grep -E "^(Ran |OK|FAILED|ERROR)" /tmp/atri-s1.txt
echo "exit=$?"
```
有 `.venv-face` 再跑评测脚本；没有就在报告里写「未跑评测、缺依赖」，不要装系统包。

写 `design/handoff/线程报告-T04踢球评测.md`，贴真实命令输出。只碰本线程独占文件。

### ----- S1 复制结束 -----

### ----- S2 复制开始 -----

你在仓库 `/Users/zhangjingkun/Projects/github/ATRI` 上做 **T-05 离线语音做实**。全部中文。禁止 git 操作。禁止任何云端 ASR。

**先读**
- 赛题原文：「娱乐休闲：如舞蹈、音乐播放、语音交互等。」三条是举例，做实语音触发 + 舞蹈即可。
- `software/atri/atri/skills/dance.py`、`software/atri/atri/voice/`
- `docs/process/未测项清单.md` B8（样机噪声下识别率仍未测）

**要做**
1. 给 `voice/` 增加可选离线后端（优先 vosk 小模型或仓库已有风格的惰性导入）。**核心包零第三方**：没装引擎时 `detect_speech` / recognizer 不可用，测试 skip，主包 unittest 全绿。
2. 技能层保持：通道未接入 → `source=params` 兜底；通道已接入且关键词不在白名单 → TTS「我没听清」并失败。
3. 新建 `software/atri/tools/dance_eval.py`：对一组 wav（可合成正弦+可跳过）或关键词注入，统计命中/拒识。
4. 报告 `design/handoff/T-05-娱乐休闲-方案.md`：写清「无 ASR 时仍是 Mock」「有引擎时离线关键词命中率（本机，非赛场噪声）」。
5. 测试 `software/atri/tests/test_voice_offline.py`。

**不要做**：节拍同步假装已标定；改 CAD；改 T-01/02/03。

**验收**
```bash
cd /Users/zhangjingkun/Projects/github/ATRI/software/atri
python3 -m unittest tests.test_brain tests.test_voice_offline -v
echo "exit=$?"
python3 -m unittest discover -s tests 2>/tmp/atri-s2.txt
grep -E "^(Ran |OK|FAILED|ERROR)" /tmp/atri-s2.txt
echo "exit=$?"
```
写 `design/handoff/线程报告-T05语音.md`。

### ----- S2 复制结束 -----

### ----- S3 复制开始 -----

你在仓库 `/Users/zhangjingkun/Projects/github/ATRI` 上补 **T-01 头部随动**。答辩 PPT 写过「头部两轴对准人脸目标框」，代码里识别完只 TTS，头不转。全部中文。禁止 git。

**先读**
- `software/atri/atri/skills/face.py`
- `software/atri/tests/test_face_skill.py`
- `software/atri/atri/cerebellum.py` 的 `set_pose`
- 关节限位：`head_yaw ±90`、`head_pitch ±45`（`config.py`）

**要做**
1. 真识别通路在检出 bbox 后，把框中心映射到 `head_yaw` / `head_pitch`（像素偏差 → 角度，增益写进任务卡可覆写，默认保守）。
2. 无人脸 / 拒识：**回中或保持**，不要对着噪声转。
3. 退化通路若只有姓名没有 bbox，不瞎转，结果里 `gaze="skipped"`。
4. 测试：有 bbox 则 `set_pose` 被调用；无人脸不调用转头（可用假 cerebellum 计数）。
5. 短报告 `design/handoff/T-01-头部随动.md`：公式、限位、未标定（像素当量）。

**不要改** 识别器、FaceDB、LFW 数字、PPT。

**验收**
```bash
cd /Users/zhangjingkun/Projects/github/ATRI/software/atri
python3 -m unittest tests.test_face_skill tests.test_brain.TestFaceExpectations -v
echo "exit=$?"
```
写 `design/handoff/线程报告-T01头部随动.md`。

### ----- S3 复制结束 -----

### ----- S4 复制开始 -----

你在仓库 `/Users/zhangjingkun/Projects/github/ATRI` 上做 **口径对齐与计划书骨架**。全部中文。禁止 git。禁止改 `ppt/*.pptx`。禁止改 `design/cad/**`、`software/atri/atri/**`。

**先读**
- `docs/process/未测项清单.md`（引用任何能力前先搜）
- `design/handoff/答辩材料口径核对清单.md`
- `docs/research/项目文档/答辩PPT-逐页文案-v4.md` P11–P15
- `README.md`（测试数字 437 / 508 / 556 / 579 混用）
- `docs/contest/提交材料清单.md`

**要做**
1. 在本机跑一次 `python3 -m unittest discover -s software/atri/tests` 与 `python3 -m unittest discover -s webots/tests`，把 **Ran N** 写进清单，作为唯一现行测试数。
2. 更新 `答辩材料口径核对清单.md`：P11 人脸、P12 二维码、P13 搬运、P14 踢球、P15 舞蹈 —— 每条「PPT 旧句 → 现行事实 → 建议讲者一句」。T-01 称识别；T-02/T-03 数字必须带「合成图/LFW，非实机」。
3. 直接改 `答辩PPT-逐页文案-v4.md` 对应页（这是文案源，不是 pptx）。
4. `README.md` 只改测试数字相关行，改成第 1 步跑出来的数，三处对齐。
5. 新建 `docs/contest/参赛计划书.md` 骨架：项目概述 / 技术方案 / 创新点 / 可行性 / 成本 / 团队 / 路线图 / **未测项诚实声明**。正文用现行口径填能填的，空的标 TODO。不要编造续航、抓取成功率、行走 1 m。

写 `design/handoff/线程报告-口径与计划书.md`。

**验收**：清单里每一条 PPT 旧句都有建议新句；README 不再同时出现两个不同的主包测试数。

### ----- S4 复制结束 -----

### ----- S5 复制开始 -----

你在仓库 `/Users/zhangjingkun/Projects/github/ATRI` 上做 **带重力 Webots 世界的可复现生成与录屏清单**。全部中文。禁止 git。

**硬约束**
- **禁止修改** `webots/worlds/atri_22dof.wbt`（默认必须保持 gravity 0，CI 钉死）。
- **禁止修改** `webots/tools/generate_atri_world.py` 的默认值。
- 只新增脚本和文档。

**先读**
- `webots/README.md`「带重力/带地面的校核跑法」
- `design/handoff/仿真请求-Webots验证清单.md` S1/S2
- `docs/contest/提交材料清单.md` §二（视频 ≤100 MB，3 分钟）

**要做**
1. 新建 `webots/tools/make_gravity_world.py`（或 sh）：调用现有生成器
   `python3 webots/tools/generate_atri_world.py --gravity=-9.81 --max-torque=2.94 --ground --out docs/process/sim/worlds/atri_22dof_gravity.wbt`
   生成后 `grep` 确认 `gravity -9.81`、有地面、有 maxTorque。
2. 文档 `docs/process/sim/重力世界录屏脚本.md`：S1 静立 10 s、S2 扭矩探针、T-05 舞蹈 各怎么启动 Webots、怎么录、怎么压到 720p/≤100 MB。写明：**本机可能无 Webots GUI**，命令给队友用。
3. 若目录 `docs/process/sim/worlds/` 应 gitignore，在报告里建议主会话加规则，你自己不要改 `.gitignore` 除非它已在你的独占范围——本线程 **不要改 .gitignore**，只在报告里写建议。
4. 跑生成器（允许失败：若无 robot 模型依赖，把报错贴进报告）。

写 `design/handoff/线程报告-重力世界录屏.md`。

### ----- S5 复制结束 -----

---

## 5. 主会话收口清单（S6，不要派给子线程）

1. 收五份线程报告，冲突只可能出现在 README 测试数字（S4）——以 S4 当场跑数为准。
2. 若 `ppt/build_deck.py` 还能跑，按 S4 文案重生成 pptx；跑不了就保持 pptx 不动、用更新后的文案。
3. 路线 B 视频已在 `design/cad/out/video/ATRI-pose-demo.mp4`（gitignore）。参赛要交的话由用户从 Downloads 拷附件，**不要把 mp4 强行入库**。
4. 查重 / 承诺书 / 平台上传：继续走人工。
5. 不要派线程去测 A1–A5。

---

## 6. 给用户看的优先级（如果只能开 3 条）

1. **S4 口径 + 计划书** —— 明天交材料最疼的是 PPT 和计划书还在说旧故事。
2. **S1 T-04 评测** —— 五项里唯一还没有「做实报告」的软件任务。
3. **S5 重力世界脚本** —— 视频仍是提交清单里唯一吃紧项。

S2/S3 是加分，不挡提交。
