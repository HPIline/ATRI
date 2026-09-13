# 给 Grok 的对接文档：真机链路（总线驱动 + 下位机固件 + bring-up）

> 生成日期：2026-09-11　生成者：设计/装配 agent（本仓库）
> 对象：**新开一个会话的 Grok**（看不到本仓库其他会话的历史，所以这份文档自包含）
> 用途：直接把这篇文章粘贴给新会话，作为它的工作交接与约束。

---

## 0. 一句话任务

**把"A.T.R.I. 从仿真走到真机"的这段链路做出来**：舵机总线驱动 → bring-up（ID/限位/中位标定）
→ 下位机实时环（STM32F405：同步写 + IMU + 看门狗）→ 与上位机（树莓派 Python）的通信协议。
**不做** CAD/结构、不改上层技能与任务流程。

**为什么交给你**：这段是当前**唯一没人认领、又能不依赖实物就推进**的工作面。
硬件（22 只飞特 STS3215 + 3S 电源 + 树莓派 + STM32）尚未到货，但协议与接口都已冻结，
可以先把代码、测试、标定流程全部写完，硬件一到就能当天点动。

---

## 1. 仓库地图与"单一真值来源"

仓库根：`/Users/zhangjingkun/Projects/github/ATRI`

| 路径 | 作用 | 能不能改 |
|---|---|---|
| `software/atri/atri/config.py` | **关节总表 + 角度↔脉冲契约**（22 关节 ID/限位/方向/零偏/分支） | ✅ 可改，但改 ID/限位等于改全机，必须同步固件 |
| `software/atri/atri/cerebellum.py` | 小脑层；`ServoBus` 抽象 + `MockServoBus` + 步态/动作 | ✅ 可扩展，**不要改坏现有 API**（186 项测试在守） |
| `software/atri/atri/bringup.py` | **bring-up 流程**（扫描/限位/中位/点动/标定） | ✅ 这是你的主战场之一 |
| `software/atri/run_bringup.py` | bring-up CLI（`--table/--mock/--bus 模块:类/--step`） | ✅ |
| `software/atri/tests/` | 186 项单测（CI 必绿） | ✅ 只加不改语义 |
| `design/reference/sts3215/PROTOCOL.md` | **飞特协议 + 寄存器表**（双源核验过） | ⚠️ 只读；发现错误在报告里指出，别直接改结论 |
| `design/cad/vendor/feetech/STS3215_7.4V_19kg_spec.pdf` | **飞特官方规格书**（8 页，含外形图） | ⚠️ 只读（官方原始文档） |
| `design/cad/standards.py` | 机械/电气参数（舵机、轴承、紧固件、打印公差） | ❌ **不要改**（另一个 agent 在维护，改动会冲突） |
| `design/`、`webots/`、`ppt/` | 结构设计、装配、仿真、答辩材料 | ❌ 不在你的范围 |
| `任务卡/` `software/atri/task_cards/` | 赛题五项任务定义 | ❌ 不改 |

**生成物不要手改**：`design/placements.json`（由 `design/gen_placements.py` 生成）、
`design/handoff/*.md` 里的自动生成部分、`design/cad/out/**`（全部可重建）。

---

## 2. 硬件事实（全部有出处，可直接采信）

### 2.1 舵机：飞特 STS3215（12V 30kg 版）

| 项 | 值 | 出处 |
|---|---|---|
| 外形 | 45.2 × 24.7 × 35.0 mm（**35 沿输出轴**） | 官方规格书 6-1 |
| 质量 | 55 ± 1 g | 官方 |
| 堵转 / **额定负载** | 30 kg·cm = 2.94 N·m / **10 kg·cm = 0.98 N·m** | 官方 |
| 空载速度 | 0.222 s/60°（45 RPM） | 官方 + 实物标签 |
| 电流 | 静态 30 mA / 空载 180 mA / 额定 900 mA / **堵转 2.7 A** | 官方 |
| 工作电压 | **4–14 V**（3S：9.0–12.6 V 在内） | 官方 |
| 编码器 | 12 bit 磁编码，4096 计数，0.088°/脉冲 | 官方 |
| 协议 | TTL 半双工异步串行，8bit/1stop/无校验；**38400 bps–1 Mbps，出厂默认 1 Mbps** | 官方 |
| ID | 0–253（出厂 1） | 官方 |
| 反馈 | 负载 / 位置 / 速度 / 输入电压 / **工作电流** / 温度 | 官方 |
| 保护 | 过载 >80% 堵转持续 2s；**过流 >2A 持续 2s 关输出**；过热 >70℃ 切扭矩 | 官方 |
| 连接器 | 5264-3P，线长 15 cm，脚序 GND/Vcc/Signal（黑/红/蓝） | 官方（⚠️ 2.0 还是 2.54 间距待实物卡尺确认） |
| 出力轴 | 25T / OD5.9mm，中心螺钉 M3×6 | 官方 |
| **不防水** | — | 官方 |

### 2.2 协议（详见 `design/reference/sts3215/PROTOCOL.md`）

- 帧头 **`0xFF 0xFF`**，帧结构 `[ID][Length][Instruction][Params…][Checksum]`
- 校验和 = **`~(ID + Length + Instruction + Params…) & 0xFF`**（按位取反累加和，不含帧头）
- 关键寄存器地址（**EEPROM**，写入前需先松轴）：

  | 地址 | 名称 | 说明 |
  |---|---|---|
  | 5 | ID | 0–253，总线内唯一 |
  | 6 | Baud Rate | 0=1M, 1=500K, 2=250K, 3=128K, 4=115200, 5=76800, 6=57600, 7=38400 |
  | 9/11 | Min/Max Angle Limit | 限位脉冲（L/H） |
  | 33 | Mode | 0=位置, 1=恒速, 2=PWM, 3=步进 |
  | 40 | Torque Enable | 0=松轴, 1=锁轴 |
  | 42/43 | Goal Position | 目标位置脉冲（2048=中位） |
  | 44/45 | Goal Time | 运动时间 |
  | 46/47 | Goal Speed | 速度 |
  | 55 | Lock | 1=锁 EEPROM |
  | **56/57** | Present Position | 当前位置回读 |
  | 60/61 | Present Load | 负载（含方向） |
  | 62 | Present Voltage | 输入电压 |
  | 63 | Present Temperature | 温度 ℃ |
  | **69/70** | Present Current | 工作电流（L/H） |

- **中位标定**：⚠️ **2026-09-12 订正**——旧文写的"40 号地址写 128"是**错的**：40 号是
  **扭矩使能**（写 128 只是开扭矩，不改零位）。正确做法是写 **31 号位置偏置** ＝
  `当前脉冲 − 2048`（先松轴、写完回读校验）。依据 `design/reference/sts3215/PROTOCOL.md`
  寄存器表（31 = 位置偏置 / 40 = 扭矩使能）。
- 一帧写完多关节要用 **SYNC WRITE**（`0x83`），不要逐个发（见 2.4 时序）。

### 2.3 电气与拓扑（来自结构方，已冻结）

- **数据总线是一条并联总线**：骨盆分线板（PDB）分 4 条**电源**分支
  （左腿 5 / 右腿 5 / 双臂 8 / 躯干+头 4 = 22），但 **DATA 四路并联回驱动板**。
  → 如果你做成 4 个独立串口，上位机软件要整体重写（现在假设单口多 ID）。
- 驱动板：飞特 URT-1 或微雪 Bus Servo Adapter（USB-TTL 半双工）。
- 母线 3S（9.0–12.6 V），逻辑轨 5 V ≥1.5 A（树莓派）。
- **必须做总保险/分支限流**：单只堵转 2.7 A × 22 是灾难工况。
- 控制周期 **20 ms**（50 Hz）——上位机 `config/robot.json` 的
  `cerebellum.control_period_ms = 20`。

### 2.4 时序预算（做同步写之前先算这笔账）

- 1 Mbps 下，一帧 SYNC WRITE 写 22 个关节 ≈ `6 + 22×3 + 1` ≈ **73 字节 ≈ 0.6 ms**；
- 若退化成"逐个写 + 逐个等回包"，每只 ≈ 0.4–0.8 ms（含半双工换向）→ 22 只 ≈ **9–18 ms**，
  20 ms 周期就要爆。**所以 `sync_write` 是硬需求**，不是优化。

---

## 3. 上位机已冻结的接口（你必须与它对齐）

### 3.1 角度 ↔ 脉冲契约（唯一口径，固件必须实现同一套）

```python
pulse = zero_pulse + sign × deg × 4096/360        # ≈ 11.378 脉冲/度
deg   = (pulse − zero_pulse) × 360/4096 × sign
```
- `sign ∈ {+1, −1}`：机械装配决定的转向（左右镜像件相反）
- `zero_pulse`：机械零位对应脉冲（出厂 2048，装配标定后修正）
- 实现见 `software/atri/atri/config.py`：`deg_to_pulse / pulse_to_deg / pulse_limits / joint_table`
- **限位寄存器要写成"软件限位外扩 3°"**（`pulse_limits`），保证比软件宽、又比机械硬限位窄。

### 3.2 `ServoBus` 语义（`software/atri/atri/cerebellum.py`）

真机实现**必须**实现：

| 方法 | 语义 |
|---|---|
| `set_angle(id, deg)` | 单关节写目标角（内部换算成脉冲） |
| `read_angle(id)` | 回读角度 |
| `sync_write({id: deg})` | **一个周期内批量写**（默认实现是逐个写，真机必须覆盖） |
| `set_torque_enable(ids, on)` | 松/锁轴（**上电先松轴**，标定后再锁） |
| `read_telemetry(id)` | 返回 `{pos_deg, load_pct, voltage_v, temp_c, current_a, moving}` |
| `scan()` | 扫描在线 ID（bring-up 第一步） |
| `write_limits(id, lo, hi)` | 写 min/max angle 寄存器 |
| `set_middle(id)` | 中位标定（写 **31 号位置偏置** = 当前脉冲 − 2048；⚠️ 旧文「40 号写 128」是错的，40 是扭矩使能） |

### 3.3 bring-up 流程（已写好，用 Mock 跑通）

```bash
cd software/atri
python3 run_bringup.py --table        # 打印 22 关节总表（ID/分支/转向/零偏/脉冲限位）
python3 run_bringup.py --mock         # 用 Mock 总线跑完整流程（自检）
python3 run_bringup.py --bus atri.bus_sts3215:StsBus --port /dev/ttyUSB0 --step scan
```
**流程顺序不能颠倒**：`scan`（确认身份）→ `limits`（写限位）→ `middle`（中位标定，人工摆位）
→ `jog`（单关节 ±10° 点动 + 温升/电流记录）→ 写 `config/calibration.json`。

### 3.4 标定文件（装配后必须回填）

`software/atri/config/calibration.json`：
```json
{"schema_version": "1.0",
 "joints": {"head_yaw": {"sign": -1, "zero_pulse": 2043}}}
```
由 `run_bringup.py --step middle` 生成，程序启动时 `config.load_calibration()` 载入。
**没有它就会出现"两条腿往相反方向走"**——这是现场最贵的错误之一。

---

## 4. 你要交付的东西（按 Phase 划分）

### Phase 1（**不依赖实物也能做完**，优先级最高）

**D1. `software/atri/atri/bus_sts3215.py` —— 真机总线驱动**
- 实现 `ServoBus` 全部语义（3.2 表），可用 `pyserial`（**只允许加在 `software/atri/requirements.txt`**，
  主包 `atri/` 的核心仍保持标准库可跑）。
- 必须实现：`sync_write`（SYNC WRITE 指令）、遥测批量读、`scan`、
  超时重试、半双工换向（URT-1 自动换向的话要注明）、校验和校验失败重发。
- **测试**：`tests/test_bus_sts3215.py` —— 用一个**假串口**（`io.BytesIO` 或 mock 对象）
  验证：帧字节序列、校验和、Sync Write 打包、遥测解包、超时行为。
  不需要真实硬件就能把这些测完。

**D2. 协议文档校核**
- 把 `design/reference/sts3215/PROTOCOL.md` 与官方规格书逐条对照，
  把你发现的**不一致**写成 `design/handoff/协议校核-<日期>.md`（只报告，不要改既有结论）。
- 特别核对：地址 28（保护电流，单位 ×6.5 mA）、34/35/36（过载保护阈值/时间）、
  Present Current 在 12V 版是否真实有效（官方规格书声称支持）。

**D3. bring-up 报告与温升实测记录**
- 用 `run_bringup.py --json` 的产物，做一份**空载点动 + 分级加载**的记录模板：
  每级负载持续 N 分钟，记录 温度/电流/位置漂移，输出 `docs/` 或 `design/handoff/` 下的报告。
- 这份数据直接喂给"买 1 只舵机实测连续扭矩与温升"的开环验证。

### Phase 2（需要一块 STM32F405 开发板，仍不需要整机）

**D4. 下位机固件骨架（建议路径 `固件/stm32f405/`，你先定结构，写进 `固件/README.md`）**
- 串口（UART）半双工收发的舵机总线驱动（同 D1 的协议）+ SYNC WRITE
- 50 Hz 定时器中断：目标角插值（梯形/正弦）+ 一帧同步写
- IMU（ICM-42688-P，SPI/I²C）读取与姿态解算（哪怕先只做互补滤波）
- 看门狗 + 掉线保护（上位机心跳丢失 → 松轴站住）+ 急停输入
- 遥测回传（22 关节温度/电流/电压 + IMU），周期 ≥10 Hz
- **验收**：不接舵机时用串口助手能看到 50 Hz 稳定同步帧；接 1 只舵机能跟随正弦目标。

**D5. 上位机 ↔ 下位机通信协议（`design/handoff/上下位机协议.md`）**
- 建议：定长二进制帧（帧头 + 类型 + 长度 + 载荷 + CRC16），类型至少覆盖：
  ① 高层指令（走/停/踢/抓/姿势号）② 关节目标流（标定/遥测模式）③ 遥测上报
  ④ 心跳/看门狗 ⑤ 急停 ⑥ 参数读写（PID/限幅）
- **两端都要实现**：Python 侧（可以作为 `ServoBus` 的另一种实现，或独立的 `LowerLink`）
  与固件侧；并写一份 `tests/` 里的帧编解码往返测试。
- ⚠️ 需要先定架构（见第 7 节 A/B），默认按 Phase 2 = B（固件跑实时环）。

---

## 5. 纪律与红线（违反会直接返工）

1. **测试必须绿**：`cd software/atri && python3 -m unittest discover -s tests`（现在 **186 项**）；
   CI 还跑 `python3 -m compileall -q atri run_demo.py` 与 `python3 run_demo.py --fast`。
2. **主包核心保持标准库可跑**：`atri/` 里不要 `import serial` 到顶层；
   真机依赖放进独立模块 + `requirements.txt`，用惰性导入或 try/except。
3. **不要改** `design/cad/standards.py`、`design/**`、`webots/**`、`ppt/**`、
   `software/atri/atri/skills/**`、`task_cards/**`（各有归属）。
4. **不要手改生成物**：`design/placements.json`、`design/cad/out/**`。
5. **中文注释/文档**；参数不要写死，一律从 `config.py` 的关节表取。
6. 改完任何东西，先跑测试再报告；报告里给**命令 + 输出**，不要只说"已完成"。
7. 找不到就写"未找到"，**不要编造寄存器地址或波形**；不确定的标注置信度。

---

## 6. 已知坑（踩过的，别重踩）

| # | 坑 | 说明 |
|---|---|---|
| 1 | 帧头 / 校验 | `0xFF 0xFF` + `~sum & 0xFF`（**不含帧头**）。写错一位全总线不响应 |
| 2 | 半双工换向 | 单线半双工：发完必须让出总线才能收；URT-1 自动换向，自己写板子要注意 DE/RE 时序 |
| 3 | 逐个写会超时 | 22 关节 × 往返 ≈ 9–18 ms > 20 ms 周期 → **必须 SYNC WRITE** |
| 4 | 中位不是"零点" | 出厂 2048 只是电气中位；**机械零位要标定**并写进 `calibration.json` |
| 5 | 方向符号 | 左右镜像件 `sign` 必然相反；不回填就是"腿反着走" |
| 6 | 上电就锁轴 | 上电应先 `torque_enable=False`（松轴），标定/装配完成再锁，否则装配时舵机会顶人 |
| 7 | 过流保护会咬人 | 官方：>2 A 持续 2 s 关输出；调试加载时会被保护打断，**重发位置指令才解除** |
| 8 | 3S 满电 12.6 V | 在舵机 4–14 V 内 ✅，但**逻辑轨与舵机轨要分开**，别让舵机电流穿过树莓派 |
| 9 | 不防水、不防尘 | 桌面环境即可，别在粉尘/液体旁调试 |
| 10 | 连接器间距未定 | 5264-3P 的 2.0 还是 2.54 需实物卡尺；**先别批量压线** |
| 11 | 端口会变 | 树莓派上 USB 掉线会重新枚举（`ttyUSB0`→`ttyUSB1`），驱动要按 USB 序列号或 udev 规则绑定 |
| 12 | 温升才是真瓶颈 | 官方额定 0.98 N·m（不是堵转 2.94）；连续工况必须实测温度，别按堵转算 |

---

## 7. 需要先定的一个架构选择（请与人类确认后再动手 D5）

| 方案 | 谁跑实时环 | 优点 | 缺点 |
|---|---|---|---|
| **A. 树莓派直连舵机** | 树莓派（Python） | 最快见效；bring-up/标定/温升测试全部够用；不用固件 | Python 抖动大（20 ms 周期不保证）；掉线保护弱 |
| **B. STM32 跑实时环**（设计文档原意） | STM32F405 | 实时性/看门狗/IMU 闭环稳；与设计文档一致 | 要写固件、要定上下位机协议；Python 侧小脑要退化为"指令下发 + 仿真回放" |

**建议路径**：**Phase 1 按 A**（先把总线驱动与 bring-up 做完，硬件一到就能点动/标定/测温），
**Phase 2 转 B**（固件接管实时环，Python 只发高层指令）。
这样"软件等硬件"这段路不会白等，也不会一次性押上大重构。

---

## 8. 最小验证路径（从零到能动）

```bash
# 0) 环境（树莓派或开发机）
cd software/atri && python3 -m unittest discover -s tests      # 186 项应全绿（不需硬件）

# 1) 无硬件：跑通 bring-up 流程与驱动单测
python3 run_bringup.py --mock
python3 -m unittest tests.test_bus_sts3215 -v               # D1 完成后

# 2) 有 USB-TTL + 1 只舵机（约 90 元，可先买 1 只）
python3 run_bringup.py --bus atri.bus_sts3215:StsBus --port /dev/ttyUSB0 --step scan
python3 run_bringup.py --bus atri.bus_sts3215:StsBus --port /dev/ttyUSB0 --step limits
python3 run_bringup.py --bus atri.bus_sts3215:StsBus --port /dev/ttyUSB0 --step jog --joint head_yaw

# 3) 有 STM32 开发板：固件 50 Hz 同步帧 + 单关节正弦跟随
```

---

## 9. 参考文件（精确路径）

| 需要什么 | 去哪看 |
|---|---|
| 协议与寄存器表 | `design/reference/sts3215/PROTOCOL.md` |
| 官方规格书（8 页，含外形图） | `design/cad/vendor/feetech/STS3215_7.4V_19kg_spec.pdf` |
| 舵机 3D 模型（B-rep，可量接口） | `design/cad/vendor/so-arm100/STS3215_03a.step` |
| 接口/CAD 现状与体检 | `design/handoff/装配一致性修正记录.md`、`design/cad/audit_assembly.py` |
| 关节表与契约实现 | `software/atri/atri/config.py`（`joint_table()`、`pulse_limits()`） |
| bring-up 流程 | `software/atri/atri/bringup.py`、`software/atri/run_bringup.py` |
| 上层架构（大脑/小脑/技能） | `software/atri/README.md`、`software/atri/atri/brain.py` |
| 赛题要求与合规口径 | `design/handoff/第3轮-T6-小人形组合规核对.md` |

---

## 10. 交付验收清单（照这个自检）

- [ ] `python3 -m unittest discover -s tests` 全绿，且**新增**了你自己的测试
- [ ] `atri/bus_sts3215.py` 在**没有硬件**时能被导入（惰性导入串口库），并有用假串口的单测
- [ ] `sync_write` 有单测证明是**一帧**写出（不是循环调 `set_angle`）
- [ ] 遥测解包有单测（负载/电压/温度/电流/位置）
- [ ] `run_bringup.py --bus …--step scan/limits/jog` 三步在真机上跑通，并留下 JSON 报告
- [ ] `config/calibration.json` 有实测的 `sign` / `zero_pulse`（22 个关节齐全）
- [ ] 协议校核报告：至少核对地址 5/6/9/11/33/40/42/55/56/60/62/63/69 与官方一致
- [ ] 报告里给出**命令与输出**，不要只说"已完成"
