# TonyPi 生态对标（T3）

> 生成日期：2026-09-11　执行：第 3 轮 T3（见 `第3轮-资料检索分工与执行.md`）
> 用途：把商用参考机 TonyPi 的**可验证事实**沉淀下来，供答辩材料、研发日志与自身设计对照
> 相关：`TonyPi-Pro-参考构型与零件参数.md`（本文为其第 6 节【待补】项的补充与验证）

---

## 0. 一句话结论

**TonyPi 的关节 ID 映射被独立统计学验证**（镜像对称残差 13.2 vs 错配 163.8），
**动作组格式被完整还原**（`.d6a` 就是 SQLite，表结构已取得），
**117 个动作组**几乎逐项覆盖小人形组五个任务区。

同时得到一个**对参赛合规有直接影响**的结论：**TonyPi 18 DOF 的上肢躯干只有 6（不计头部）
或 8（计头部），都不满足小人形组"上肢躯干 ≥10"**（详见第 7 节）。

---

## 1. 来源清单（全部可追溯）

| # | 来源 | 取到什么 |
|---|---|---|
| 1 | [Hiwonder/TonyPi](https://github.com/Hiwonder/TonyPi)（官方） | 官方 Python SDK、`ActionGroups/` 117 个 `.d6a`、`servo_config.yaml`、`lab_config.yaml` |
| 2 | 同上 `HiwonderSDK/hiwonder/` | `ActionGroupControl.py`（动作组执行）、`Controller.py`（舵机语义）、`ros_robot_controller_sdk.py`（串口协议） |
| 3 | [ist4102/human_code](https://github.com/ist4102/human_code) | `config.py`（云台标定 870/1514）、`BusServoCmd.py`、官方说明书（OLE，正文未取出） |
| 4 | [209371456/tonypi](https://github.com/209371456/tonypi) | `Head_Control.py`（**头部是 PWM 舵机**，决定性证据） |
| 5 | [TommyZihao/openvino_tonypi](https://github.com/TommyZihao/openvino_tonypi) | 本地大模型 Agent 方案，含 `TonyPi-API-*_no_key`（不依赖 ChatGPT key） |
| 6 | [幻尔官方论坛](https://forum.hiwonder.com.cn/t/tonypi-id/599) | 舵机 ID 修改流程、`servo_tool` 用法、**带电插拔会烧 IC** 的官方警告 |

---

## 2. ⭐ 关节 ID 映射的独立验证

### 2.1 待验证的映射（原为孤证）

`TonyPi-Pro-参考构型与零件参数.md` 第 2 节曾从论坛的**上位机截图**读出：

```
右腿 1–5    左腿 9–13
右臂 6–8    左臂 14–16
头部 17–18
```

这是**读图得到的孤证**。本轮用官方动作组数据做了独立检验。

### 2.2 检验方法：镜像对称残差

左右肢体成对关节在同一帧里应满足 `v_右 + v_左 ≈ 2 × 中位 = 1000`（中位为 500）。
对 20 个官方动作组（共 149 个关键帧）计算平均残差：

```
残差 = mean( |v_a + v_b − 1000| )
```

| 配对方案 | 平均残差 |
|---|---|
| **提案配对** `(1,9)(2,10)(3,11)(4,12)(5,13)(6,14)(7,15)(8,16)` | **13.2** ✅ |
| 错配 A（腿错位 + 臂交错） | 163.8 |
| 错配 B（腿对调 + 臂对调） | 122.6 |

**提案配对比错配低一个数量级。**

### 2.3 逐组残差（对称姿态为 0）

| 动作组 | 提案 | 错配A | 动作组 | 提案 | 错配A |
|---|---|---|---|---|---|
| `stand` / `stand_slow` / `squat` | **0.0** | 108.8 | `twist` | 50.6 | 175.7 |
| `squat_up` / `squat_down` / `move_up` | **0.0** | 215–276 | `wave` | 66.3 | 158.0 |
| `chest` | 0.8 | 207.5 | `go_forward` | 34.6 | 124.1 |
| `bow` | 1.6 | 162.1 | `back` | 25.8 | 106.2 |
| `lie_down` / `sit_ups` | 2.1 / 2.9 | 185 / 191 | `turn_left` / `turn_right` | 22.9 / 23.1 | 110 / 118 |

**读法**：**对称姿态残差为 0**（`stand`、`squat`、`move_up` 精确到 0.0）；
残差偏高的恰是**本质上不对称**的动作（`wave` 挥手、`twist` 扭身、`turn_*` 转向）——
这正是应有的模式。**映射成立。**

### 2.4 ✅ 结论

**原映射正确，现在有独立验证，可从"读图推测"升级为"已验证"。**

---

## 3. 动作组格式：`.d6a` 就是 SQLite

### 3.1 执行代码（官方 `ActionGroupControl.py`）

```python
ag = sql.connect(actNum)              # ← .d6a 文件用 sqlite3 打开
cu = ag.cursor()
cu.execute("select * from ActionGroup")
act = cu.fetchone()
for i in range(0, len(act) - 2, 1):
    ctl.set_bus_servo_pulse(i+1, act[2+i], act[1])   # (舵机号, 脉宽, 时长ms)
time.sleep(float(act[1]) / 1000.0)
```

### 3.2 表结构（从 `stand.d6a` 实际读出）

```sql
CREATE TABLE ActionGroup(
  [Index] INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL UNIQUE,
  Time    INT,          -- 本帧持续时间，毫秒
  Servo1  INT, Servo2  INT, ... Servo18 INT   -- 舵机脉宽
)
```

**一次 `stand` 姿态（1 帧）：**

```
Index=1  Time=500ms
Servo1..18 = 500, 390, 500, 600, 500, 575, 800, 725,
             500, 610, 500, 400, 500, 425, 200, 275, 500, 500
```

### 3.3 实测统计（20 个动作组 / 149 帧）

| 项 | 实测 |
|---|---|
| 脉宽范围 | **0 – 1000**，中位 **500**（距中位最大偏移 500） |
| 单帧时长 Δt | **75 – 1500 ms**，中位 **400 ms** |
| 动作组总数 | **117 个** |
| `Servo17/18` 取值 | **恒为 500**（全部样本）→ 不在动作组体系内 |

### 3.4 ⭐ 18 列 ≠ 18 个总线舵机

`Head_Control.py` 给出了决定性证据：

```python
Board.setPWMServoPulse(1, 1800, 200)   # 点头 = PWM 舵机 1
Board.setPWMServoPulse(2, 1200, 200)   # 摇头 = PWM 舵机 2
```

**头部用的是 PWM 舵机（脉宽 1200–1800 µs），不是总线舵机。**
`servo_config.yaml` 的 `servo1: 926 / servo2: 1435` 正是这两个云台舵机的**标定值（µs）**。

→ **TonyPi 的构成是：16 个总线舵机（腿 10 + 臂 6）+ 2 个 PWM 微舵机（头）= 18 DOF。**
动作组表的 18 列是**模板上限**，17/18 列留空（恒 500）。

> 这**印证**了 `TonyPi-Pro-参考构型与零件参数.md` 第 5 节的判断：
> "参考机其实有 11.1 V 总线 + 6 V PWM 两条供电/信号通路"。现在有代码级证据。

---

## 4. 与 ATRI 动作库的逐项对比

ATRI 侧规范：`软件/atri/action_library/schema.json` + `README.md`

| 维度 | **ATRI（JSON）** | **TonyPi（`.d6a` / SQLite）** |
|---|---|---|
| 载体 | JSON 文本 | SQLite 二进制 |
| 帧时长 | `duration_s` 浮点**秒** | `Time` 整数**毫秒** |
| 关节标识 | **语义名**（`right_hip_pitch`） | **列序号** `Servo1..18` |
| 关节值 | **角度（度）** | **脉宽（0–1000，中位 500）** |
| 未列出的关节 | **可省略** | 必须全写（未动写 500） |
| 循环 | `loop` 字段 | 由调用参数 `times` 控制 |
| 可读性 / diff | 高 | 低（二进制） |
| 编辑方式 | 手写 / 脚本 | 图形化上位机拖滑竿 |
| 动作组数量 | 4 个示例 | **117 个** |

### 4.1 三条可执行建议

**①（真实缺口）"未列出的关节"语义未文档化**

`README.md` 只说 `joints` 是"关节名 → 角度（度）"，**没有规定省略的关节怎么办**。
查实现 `cerebellum.py:182 play_action()` → `set_pose()`：

```python
for name, deg in targets.items():     # 只下发列出的关节
    self.bus.set_angle(JOINTS[name]["id"], deg)
```

→ 实际语义是**"保持上一帧的值"**，但**规范里没写**。

对比：TonyPi 18 列全写（未动写 500），**笨重但无歧义**。

**动作**：在 `schema.json` 与 `README.md` 显式写明
`omitted joint = hold last commanded value`，并补一条单元测试锁住该语义。

**② 帧时长建议用整数毫秒**

TonyPi 用 `Time INT`（毫秒）。ATRI 用浮点秒（示例 0.12 s = 120 ms）。
浮点在长时间序列里会累积误差，且与实际控制周期对齐时要取整。
**建议 ATRI 内部统一转 ms 整数**（或在导出到固件时显式取整并做累计误差补偿）。

**③ 帧时长节奏可参考 TonyPi 实测分布**

ATRI `kick.json` 三帧均为 0.12 s。TonyPi 实测分布为 **75–1500 ms，中位 400 ms**，
起步动作（`go_forward_start`）用 **300 → 200 → 75 ms 递减**做加速启动。
**建议按动作类型选节奏，而不是全用 120 ms。**

---

## 5. 117 个动作组 → 小人形组五个任务区

| 小人形组任务区 | TonyPi 对应动作组（节选） | 数量 |
|---|---|---|
| ② 循迹 / 移动 | `go_forward*`、`back*`、`turn_left*`、`turn_right*`、`left_move*`、`right_move*`、`stepping`、`creep_forward` | ~34 |
| ③ 物品搬运 | `grab_left/right`、`grab_squat_*`、`grab_stand_*`、`put_down_object`、`put_up_object`、`seize_right`、`lift_*`、`down_objec` | ~21 |
| ④ 体育运动 | `catch_ball*`（14 个）、`left_kick`、`right_kick`、`left_shot*`、`right_shot*`、**`toulan_0/a/b`（投篮）**、`hurdles`、`climb_stairs*` | ~23 |
| ⑤ 娱乐休闲 | `wave`、`bow`、`twist`、**`wing_chun`（咏春）**、`sit_ups`、`stand_up_front/back`、`lie_down`、`chest`、`squat*`、`move_up` | ~30 |
| ① 人脸识别播报 | 不在动作组体系内 —— 由 `Functions/` 下的视觉例程 + `TTS.py` 完成 | — |

**结论**：商用 373 mm 级平台**已经覆盖小人形组全部任务区**。
这意味着**"我们能做人脸识别/循迹/搬运/踢球/跳舞"本身没有区分度**——
答辩的差异点必须落在架构与合规上（任务卡 / FSM / 二维码 JSON 指令 / 大脑-小脑双层 /
22 DOF 含躯干），而不是技能清单。

---

## 6. 控制架构（可迁移的工程事实）

### 6.1 串口帧协议（`ros_robot_controller_sdk.py`）

```
帧格式：  0xAA 0x55 | Length | Function | ID | Data | Checksum
功能码：  4 = PWM 舵机控制     5 = 总线舵机控制
串口：    /dev/ttyAMA0
波特率：  1 000 000          ← 与 ATRI 选的 STS3215 1 Mbps 一致 ✅
```

总线舵机写位置：

```python
def bus_servo_set_position(self, duration, positions):
    data = [0x01, dur & 0xFF, (dur >> 8) & 0xFF, len(positions)]
    for i in positions:
        data.extend(struct.pack("<BH", i[0], i[1]))   # (id, pulse)
```

回读能力（**对 ATRI 的闭环设计有参考价值**）：

| 方法 | 命令字 | 返回 |
|---|---|---|
| `bus_servo_read_id` | `0x12` | 舵机 ID |
| `bus_servo_read_offset` | `0x22` | 零位偏置 |
| `bus_servo_read_position` | `0x05` | 当前位置（**有符号 short**） |

→ 与 ATRI 的 `ServoBus.read_angle()` 抽象**语义同构**，验证了 ATRI 接口设计的合理性。

### 6.2 官方"避坑提示"（可直接写进 ATRI 装配/调试文档）

> 舵机 ID 复原接线后，**切勿直接运行大幅度动作组**！
> 先微调单关节确认各个 ID 对应的物理位置没有接错，防止机器人开机"自打自"撕裂骨架。

> **铁律**：改 ID 时扩展板上**必须且只能连接 1 个待修改舵机**。
> 所有舵机串在一起点"设置"，会导致整条总线上所有舵机被瞬间批量改写成同一个 ID。

> 带电插拔总线舵机极易产生瞬态高压，导致扩展板或舵机内部 IC 烧毁。

---

## 7. ⚠️ 对参赛合规的直接影响

小人形组要求：**关节 ≥18，每条腿 ≥4，上肢躯干 ≥10**。

按第 3.4 节确认的构成（腿 10 + 臂 6 + 头 2 PWM）：

| 机型 | 臂 | 躯干 | 头 | 上肢躯干（**不计头部**） | 上肢躯干（**计头部**） |
|---|---|---|---|---|---|
| **TonyPi 18 DOF** | 6 | 0 | 2 | **6** ❌ | **8** ❌ |
| TonyPi Pro 20 DOF（+开合手掌） | 8 | 0 | 2 | **8** ❌ | **10** ⚠️ 卡线 |
| **A.T.R.I. 22 DOF** | 8 | **2** | 2 | **10** ✅ | 12 ✅ |

**两条结论**：
1. **TonyPi 18 DOF 无论怎么算都不满足小人形组要求**（这直接影响"买二手 TonyPi 当参赛平台"的可行性）。
2. **A.T.R.I. 是三者中唯一在严格口径下也达标的**（靠那 2 个躯干关节）。
   这正是 `TonyPi-Pro-参考构型与零件参数.md` 说的"这 2 个躯干关节不该删"。

> ⚠️ "上肢躯干"是否含头部，赛题原文未写明。**这一条必须问主办方**（见 U4）。

---

## 8. 不可迁移 / 需注意

| 项 | 说明 |
|---|---|
| 舵机型号 | LX-824HV 是**电位器反馈 + 幻尔私有总线**，与 ATRI 的 STS3215（磁编码）不通用 |
| 动作组数据 | Hiwonder 仓库**未声明开源许可**，其 `.d6a` 与源码**只做对标分析，不引入本仓库** |
| 双通路供电 | 参考机的 PWM 头舵机需要额外 5–6 V 支路；ATRI 全总线归一**更干净，不要退回去** |
| 18 列模板 | 不要把 "18 列" 误读成 "18 个总线舵机"——真实是 16 + 2 PWM |

---

## 9. 复现方法

```bash
# 取下官方动作组与 SDK（只读，不入库）
B=https://raw.githubusercontent.com/Hiwonder/TonyPi/master
curl -sSL -o stand.d6a $B/ActionGroups/stand.d6a
curl -sSL -o ActionGroupControl.py $B/HiwonderSDK/hiwonder/ActionGroupControl.py

# .d6a 是 SQLite，直接用标准库读
python3 -c "
import sqlite3
cu = sqlite3.connect('stand.d6a').cursor()
print([d[0] for d in cu.execute('select * from ActionGroup limit 1').description])
print(cu.execute('select * from ActionGroup').fetchall())
"
```

镜像对称检验脚本见本轮会话记录；核心式：
`residual = mean(|v[a] + v[b] − 1000|)`，对 `(1,9)(2,10)(3,11)(4,12)(5,13)(6,14)(7,15)(8,16)` 求和。

---

## 10. 证据出处

| # | 内容 | 链接 |
|---|---|---|
| 1 | 官方 SDK 与 117 个动作组 | <https://github.com/Hiwonder/TonyPi> |
| 2 | 动作组执行代码（SQLite 证据） | 同上 → `HiwonderSDK/hiwonder/ActionGroupControl.py` |
| 3 | 串口帧协议与回读命令 | 同上 → `HiwonderSDK/hiwonder/ros_robot_controller_sdk.py` |
| 4 | **头部是 PWM 舵机（决定性证据）** | <https://github.com/209371456/tonypi> → `Head_Control.py` |
| 5 | 舵机 ID 修改流程与避坑提示 | <https://forum.hiwonder.com.cn/t/tonypi-id/599> |
| 6 | 本地大模型 Agent（离线方案参考） | <https://github.com/TommyZihao/openvino_tonypi> |
