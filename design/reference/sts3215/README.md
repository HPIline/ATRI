# STS3215 参考资料（第三方，已核验来源）

> 用途：飞特官网 `feetech.cn` / `feetechrc.com` 在国内网络下**不可达**，
> 本项目需要 STS3215 的机械接口与通信协议数据。此目录存放**可追溯的第三方来源**，
> 作为 `design/cad/standards.py` 的证据基础。
> 核验结论见 `design/handoff/STS3215-机械接口核验.md`。

---

## 文件清单

| 文件 | 内容 | 来源 | 许可 |
|---|---|---|---|
| `STS3215_03a.step` | STS3215 真实三维模型（单实体，B-rep） | [TheRobotStudio/SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100) `STEP/SO100/STS3215_03a.step` @ `d04fa975` (2025-04-28) | Apache-2.0 |
| `STS3215-12V-包装标签.jpg` | 12V 版实物照片，**含官方规格标签** | [commanderfun/STS3215](https://github.com/commanderfun/STS3215) `photos/STS3215-12V.jpg` | MIT |
| `Servo-Stand-实物.jpg` | 3D 打印舵机座与舵机的装配实物照 | 同上 `photos/servo-stand-00.jpg` | MIT |
| `STS3215_Register_Reference.md` | 寄存器地址表（EEPROM/RAM，含单位与默认值） | 同上 `REGISTER_REFERENCE.md` | MIT |
| `STS3215_Reference.pdf` | 同上内容的 PDF 版（ReportLab 生成） | 同上 | MIT |

**为什么信这两个来源**：
- **SO-ARM100**（★7426）是 LeRobot 生态的标准开源机械臂，**整机就用 STS3215**，
  全球大量用户按它的 STEP/STL 打印支架并实装 —— 接口几何经过实物验证。
  ⚠️ 但它是**社区建模**，不是飞特官方图纸；与官方图纸的差异需实物复测。
- **commanderfun/STS3215** 提供的是**实物照片**（含官方包装标签），
  属一手证据，可用来交叉核对模型的标称尺寸。

---

## 从这些资料直接得到的事实

### 官方包装标签（实物照片，`STS3215-12V-包装标签.jpg`）

```
STS3215 SPECIFICATION
● TORQUE:  30kg.cm / 417.35oz.in (12V)
● SPEED:   0.222sec/60degree (12V)
● SIZE:    A: 45.22mm  B: 24.7mm  C: 35mm
● Command signal: Digital Packet
● Code:    ST-3215-C018
```

| 项 | 标签值 | 本项目 `standards.py` 原值 | 判定 |
|---|---|---|---|
| 尺寸 | 45.22 × 24.7 × 35 mm | `body_mm = [45.2, 24.7, 35.0]` | ✅ 一致 |
| 堵转扭矩 | 30 kg·cm = **2.94 N·m** @12V | `stall_torque_nm = 3.0` | ✅ 一致 |
| 速度 | **0.222 s/60°** @12V | `speed_s_per_60deg = 0.18` | ❌ **偏乐观 19%**，需修正 |

> ⚠️ 注意：**标签上没有任何"安装耳"尺寸**，实物照片中机身也是**光板长方体**。

### 几何实测（`design/cad/tools/measure_servo.py` 可复现）

| 项 | 实测值 |
|---|---|
| 包络 | 45.419 × 24.819 × 39.619 mm |
| 实体体积 | 36 216.9 mm³ |

见核验报告。

---

## 再分发注意

两个来源均为宽松许可（Apache-2.0 / MIT），保留此出处说明即可再分发。
**本目录文件不得作为"官方图纸"引用** —— 报告中一律标注为
【第三方模型】或【实物照片】，不得标【官方图纸】。
