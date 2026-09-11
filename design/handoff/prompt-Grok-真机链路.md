# Prompt · Grok 4.6 线程（真机链路）

> 用法：新开会话，把下面 `---` 之间的内容整段粘贴。工作区：`/Users/zhangjingkun/Projects/github/ATRI`。

---

你是 A.T.R.I. 桌面双足机器人项目的**真机链路负责人**。工作区：`/Users/zhangjingkun/Projects/github/ATRI`（DSH 会话，可直接读写文件、跑命令）。

## 第一步：先读这份自包含交接文档

`design/handoff/给Grok-真机链路对接文档.md` —— 里面有完整的仓库地图、硬件事实、协议与寄存器表、已冻结的上位机接口、交付清单、12 条已知坑、红线。**通读后再动手。**

## 你的任务（Phase 1，不依赖实物，现在就做）

1. **`软件/atri/atri/bus_sts3215.py`**：实现 `atri.cerebellum.ServoBus` 的全部语义
   （`set_angle` / `read_angle` / `sync_write`（**必须是真的 SYNC WRITE 一帧**）/ `set_torque_enable`
   / `read_telemetry` / `scan` / `write_limits` / `set_middle`）。
   - 帧头 `0xFF 0xFF`、校验 `~(sum) & 0xFF`、半双工换向、超时重试；
   - **惰性导入串口库**（主包核心必须保持标准库可跑）；
   - 角度↔脉冲一律走 `atri.config` 的 `deg_to_pulse / pulse_to_deg / pulse_limits`，**不许自己再写一套换算**。
2. **`软件/atri/tests/test_bus_sts3215.py`**：用**假串口**（`io.BytesIO` / mock 对象）验证
   —— 帧字节序列、校验和、SYNC WRITE 打包、遥测解包、超时与坏校验重发。**不需要真实硬件**。
3. **协议校核报告** `design/handoff/协议校核-<日期>.md`：把 `design/reference/sts3215/PROTOCOL.md`
   与官方规格书 `design/cad/vendor/feetech/STS3215_7.4V_19kg_spec.pdf` 逐条对照，
   重点核地址 **5/6/9/11/33/40/42/55/56/60/62/63/69**、以及"12V 版是否真有 Present Current"。
   发现不一致**只报告，不改既有结论**。
4. **温升实测模板**：`run_bringup.py --json` 的产物 + 空载点动与分级加载记录表
   （每级负载持续 N 分钟，记录 温度/电流/位置漂移）→ 写到 `design/handoff/`。

## Phase 2（等 STM32F405 开发板到货再做，可先起骨架）

5. `固件/stm32f405/`（结构你定，写进 `固件/README.md`）：UART 半双工舵机总线 + 50 Hz 定时器中断
   （目标角插值 → 一帧 SYNC WRITE）+ IMU（ICM-42688-P）读取 + 看门狗/掉线松轴 + 遥测回传。
6. `design/handoff/上下位机协议.md` + 两端实现（Python 侧 + 固件侧）+ 帧编解码往返单测。
   ⚠️ 动手前先确认**架构 A/B**（见交接文档第 7 节）：建议 Phase 1 走 A（树莓派直连），Phase 2 转 B（固件跑实时环）。

## 红线（违反就返工）

- **只碰这些文件**：`软件/atri/atri/bus_sts3215.py`、`软件/atri/tests/test_bus_sts3215.py`、
  `固件/**`、`design/handoff/上下位机协议.md`、`design/handoff/协议校核-*.md`。
  `atri/config.py` / `cerebellum.py` 已冻结语义，需要新方法就在报告里**提议 patch**，不要直接改。
- **不要碰**：`design/**`、`webots/**`、`ppt/**`、`软件/atri/atri/skills/**`、`task_cards/**`。
- **不要手改生成物**：`design/placements.json`、`design/cad/out/**`。
- 主包核心保持**零第三方依赖**；串口依赖只加在 `软件/atri/requirements.txt` 且惰性导入。
- 中文回复；**报告必须给命令 + 输出**，不要只说"已完成"；找不到就写"未找到"，**禁止编造寄存器地址**。
- 每完成一项先跑测试：`cd 软件/atri && python3 -m unittest discover -s tests`（现有 **186 项必须全绿**）
  以及 `python3 -m compileall -q atri run_bringup.py run_demo.py`。

## 交付验收

见交接文档第 10 节清单。核心三条：假串口单测证明 **sync_write 是一帧**、
`run_bringup.py --bus …--step scan/limits/jog` 三步能在真机跑通并留 JSON 报告、
`config/calibration.json` 有实测的 22 关节 `sign`/`zero_pulse`。

先回报：你打算怎么分步做 Phase 1（3–5 条），以及是否需要我提供额外的寄存器/时序信息。
