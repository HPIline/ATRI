# A.T.R.I. 设计→数据包→仿真 全链路 Prompt（下一轮干活用）

> 生成日期：2026-09-10
> 目标：把"设计"变成**可直接跑仿真的数据包**，并让**硬件设计与模型训练相互贴合**
> 前置阅读：`项目文档/三维结构建模Prompt.md`、`项目文档/创新点与硬伤速查.md`
> **本文档是执行指令，下一轮直接照着干。**

---

## 零、读图结论与现状（执行前必读）

### 0.1 已核查的图片资产

| 图 | 内容 | 可用性 |
|---|---|---|
| `ATRI_Project_Presentation.pptx` → image1 | A.T.R.I. LOGO | ⚪ 仅品牌 |
| 同上 → image2 | 人形剪影渲染图（暗调） | ❌ AI 生成，非工程图 |
| 同上 → image3 | 大小脑架构示意图 | ⚪ 概念 |
| 同上 → image4 | 人形剪影渲染图 | ❌ AI 生成，非工程图 |
| `A.T.R.I.-宣传PPT-v2/assets/hardware-exploded.png` | **爆炸/关节布局图** | ⭐ **有参考价值** |
| 同上 → `hero-robot.png` | 机器人渲染图 | ⚪ 造型参考 |
| 同上 → `lab-vision.png` | 实验室场景图 | ⚪ 仅宣传 |

**结论：项目内没有任何工程图纸，但有可借鉴的关节布局范式。**

### 0.2 从 `hardware-exploded.png` 提取的设计范式（建议采纳）

该图展示的布局逻辑与 22 DOF 设计**高度吻合**，建议直接借鉴：

1. **球形关节壳包裹舵机** —— 每个关节用一个球形/圆柱壳包住舵机，形成模块化关节单元
2. **串联双舵机做 2 DOF 关节** —— 肩部 pitch/roll、髋部同理，两舵机轴线垂直串联
3. **模块化连杆** —— 大腿/小腿/上臂/前臂为独立打印件，两端预留关节安装接口
4. **躯干分层** —— 胸腔容纳双板+电池，腰部为独立 2 DOF 模块
5. **独立足底板** —— 矩形足底，面积加大以提升支撑多边形
6. **走线从关节内部穿过** —— 外观整洁，且避免运动中拉扯

> ⚠️ **注意**：该图为 AI 生成，**尺寸完全不可用**，只借鉴拓扑与造型语言。

### 0.3 现有代码接口（数据包必须对齐）

| 接口 | 签名 | 数据包如何对接 |
|---|---|---|
| `ServoBus.set_angle` | `(joint_id: int, deg: float)` | 舵机指令直接喂入 |
| `ServoBus.read_angle` | `(joint_id: int) -> float` | 仿真回读 |
| `SkillContext.perceive` | `(key: str) -> Dict` | 感知数据注入 |
| `PerceptionBackend.detect_face/qr/ball` | `(frame=None) -> PerceptionResult` | 视觉注入 |
| `Cerebellum.play_action` | `(action: Dict, dt_scale)` | 动作库回放 |
| `TaskCard.load` | `(path) -> TaskCard` | 任务卡加载 |

**关键设计原则：数据包必须适配这些**已有**接口，不允许为了仿真而改框架。**

### 0.4 本机环境事实

- Python 3.9.6（系统自带），**无 numpy / 无 matplotlib / 无 trimesh**
- **pip 可联网安装**（已验证可下载 wheel）✅
- 无 Blender / FreeCAD / OpenSCAD
- 核心代码原则：**零第三方依赖**；仿真与分析脚本可单独依赖

---

## 一、总体思路：三层数据包

```
┌─────────────────────────────────────────────┐
│  L1  几何层 (geometry)                       │
│      links.json / joints.json / kinematics   │
│      → 生成 URDF，供 Webots/PyBullet 加载     │
├─────────────────────────────────────────────┤
│  L2  物理层 (physics)                        │
│      inertia.json / collision / servo_spec   │
│      → 质感、质量分布、舵机特性                │
├─────────────────────────────────────────────┤
│  L3  行为层 (behavior)                       │
│      action_library/*.json / task_cards      │
│      → 动作库 + 任务卡，已有格式，直接复用      │
└─────────────────────────────────────────────┘
```

**L3 已经存在**（`action_library/` + `task_cards/`），本轮重点是 **L1 + L2**。

---

## 二、任务 1：定义几何数据包（L1）

### 2.1 新建 `design/robot_model.json`（单一事实来源）

**这是所有下游产物的唯一来源**：URDF、图纸、仿真都由它生成。

```json
{
  "schema_version": "1.0",
  "name": "ATRI",
  "units": "mm",
  "total": {
    "height_mm": 373.0,
    "width_mm": 187.0,
    "depth_mm": 106.0,
    "mass_kg": 1.65
  },
  "coordinate_frame": {
    "origin": "两脚中心连线中点，位于地面",
    "x_axis": "指向机器人正前方",
    "y_axis": "指向机器人左侧",
    "z_axis": "竖直向上"
  },
  "links": [
    {
      "name": "head",
      "parent": "neck",
      "mass_kg": 0.15,
      "size_mm": [90.0, 80.0, 60.0],
      "geometry": "box",
      "com_offset_mm": [0, 0, 0],
      "mesh": null
    }
  ],
  "joints": [],
  "servo": {}
}
```

**要求**：
- 单位统一 **mm**（URDF 导出时换算为 m）
- 每个 link 必须有：`name` / `mass_kg` / `size_mm` / `geometry`
- 每个 joint 必须有：`name`（**与 `config.py` 完全一致**）/ `type` / `parent` / `child` / `axis` / `origin` / `limit`

### 2.2 连杆尺寸最终确定值

基于总高 373mm 分配（可微调，但必须自洽）：

| link | 尺寸 (mm) | 质量 (kg) | 说明 |
|---|---|---|---|
| `head` | 90 × 80 × 60 | 0.15 | 含摄像头、麦克风 |
| `neck` | 30 × 30 × 20 | 0.03 | 2 DOF 模块 |
| `torso_upper` | 120 × 100 × 70 | 0.35 | 含树莓派+STM32 |
| `torso_lower` | 110 × 95 × 55 | 0.22 | 含电池 |
| `pelvis` | 100 × 90 × 45 | 0.15 | 髋部基座 |
| `thigh_l/r` | 40 × 40 × 75 | 0.08 | |
| `shank_l/r` | 35 × 35 × 75 | 0.06 | |
| `foot_l/r` | 110 × 60 × 23 | 0.07 | 足底加大，增稳 |
| `upper_arm_l/r` | 35 × 35 × 60 | 0.05 | |
| `fore_arm_l/r` | 30 × 30 × 45 | 0.04 | |
| `gripper_l/r` | 40 × 25 × 20 | 0.03 | |

**质量合计校验**：0.15+0.03+0.35+0.22+0.15 + 2×(0.08+0.06+0.07) + 2×(0.05+0.04+0.03) = **1.65 kg** ✅ 与设计值一致

**高度校验**：feet 23 + shank 75 + thigh 75 + pelvis 45 + torso_lower 55 + torso_upper 70 + neck 20 + head 60 = **423mm** ⚠️ 超了

> → 需要压缩。建议：thigh/shank 各 65，torso_lower 45，torso_upper 60，head 50
> 则：23+65+65+45+45+60+20+50 = **373mm** ✅
> **执行时以这个自洽为准，并回写 `design/robot_model.json`。**

### 2.3 关节定义（22 个，名称必须与 `config.py` 一致）

```json
{
  "name": "left_knee_pitch",
  "type": "revolute",
  "parent": "left_thigh",
  "child": "left_shank",
  "axis": [0, 1, 0],
  "origin_xyz": [0, 0, -65.0],
  "limit": {"lower_deg": 0.0, "upper_deg": 90.0, "effort_nm": 2.0, "velocity_dps": 300.0}
}
```

**22 关节的 `limit_deg` 必须逐项对照 `软件/atri/atri/config.py`**（见 `三维结构建模Prompt.md` 第 0.3 节的完整表）。

**关节类型分配**：
- 20 个 `revolute`（head_yaw/pitch, trunk_roll/pitch, 髋膝踝, 肩肘）
- 2 个 `prismatic` 或 `revolute`（左右 gripper，二选一，建议 revolute 模拟夹爪开合）

---

## 三、任务 2：生成 URDF（可直接加载仿真）

### 3.1 写生成器 `design/gen_urdf.py`

**要求**：
- **纯标准库**（不依赖 numpy）
- 输入：`design/robot_model.json`
- 输出：`design/atri.urdf`
- 支持 `--validate` 参数：自检是否符合 `config.py` 限位

**URDF 结构**：
```xml
<robot name="ATRI">
  <link name="left_thigh">
    <visual>
      <geometry><box size="0.040 0.040 0.065"/></geometry>
    </visual>
    <collision>
      <geometry><box size="0.040 0.040 0.065"/></geometry>
    </collision>
    <inertial>
      <mass value="0.08"/>
      <inertia ixx="..." ixy="0" ixz="0" iyy="..." iyz="0" izz="..."/>
    </inertial>
  </link>
  <joint name="left_knee_pitch" type="revolute">
    <parent link="left_thigh"/>
    <child link="left_shank"/>
    <axis xyz="0 1 0"/>
    <origin xyz="0 0 -0.065" rpy="0 0 0"/>
    <limit lower="0.0" upper="1.5708" effort="2.0" velocity="5.236"/>
  </joint>
</robot>
```

**关键约束**：
- 单位换算：mm → m（除以 1000），deg → rad
- 关节名与 `config.py` **逐字符一致**
- 限位必须 ≥ `config.py` 的范围
- 惯量矩阵可从 box 尺寸与质量解析计算（`I = m(w²+h²)/12` 等）

### 3.2 校验脚本

`design/gen_urdf.py --validate` 必须检查：
- [ ] 22 个关节齐全，名称与 `config.py` 一一对应
- [ ] URDF 限位 ⊇ `config.py` 限位
- [ ] 总高/宽/厚 ≤ 官方约束（600/300/300 mm）
- [ ] 单侧臂长 ≤ 300mm
- [ ] 质量合计 = 1.65 kg (±5%)
- [ ] 站立姿态质心投影在足底支撑多边形内

---

## 四、任务 3：生成仿真数据包（让硬件贴合模型训练）

> **这是本轮的核心目的**：让硬件设计产出**训练/仿真可直接消费的数据**，而不是只画个图。

### 4.1 数据包目录结构

```
design/
├── robot_model.json           # L1 单一事实来源
├── atri.urdf                  # 仿真加载
├── gen_urdf.py                # 生成器
├── packages/
│   ├── servo_spec.json        # L2 舵机真实特性
│   ├── domain_random.json     # L2 域随机化配置 ★关键
│   ├── perception_sim.json    # 感知仿真参数
│   └── scenario_set.json      # 场景集（五项任务）
└── README.md
```

### 4.2 `servo_spec.json` —— 让仿真"像真舵机"

**这是硬件贴合训练的关键**。当前 `MockServoBus` 是理想舵机（瞬间到位、无限扭矩），仿真与真机差距巨大。必须补充真实特性：

```json
{
  "schema_version": "1.0",
  "model": "Feetech STS3215",
  "protocol": "TTL 半双工串行总线",
  "rated_torque_nm": 2.0,
  "stall_torque_nm": 3.0,
  "no_load_speed_dps": 300.0,
  "deadband_deg": 0.5,
  "backlash_deg": 1.0,
  "position_accuracy_deg": 1.0,
  "control_latency_ms": 8.0,
  "update_rate_hz": 50,
  "voltage_range_v": [9.0, 12.6],
  "current_limit_a": 2.5,
  "temperature_limit_c": 70,
  "notes": "参数为 STS3215 公开规格的典型值；实测后需回填"
}
```

**用途**：
- 仿真时给每个关节加**死区、回程间隙、控制延迟、转速限制**
- 让"仿真能过"的策略在真机上也有机会过
- **材料里可写："仿真中引入了舵机非理想特性（死区 0.5°、回程间隙 1°、控制延迟 8ms），缩小了仿真与实机的差距。"** ← 这是很强的技术论证

### 4.3 `domain_random.json` —— 域随机化配置

**这是"硬件贴合模型训练"的核心**。目的是让策略对真实世界的变化鲁棒：

```json
{
  "schema_version": "1.0",
  "note": "域随机化：训练/仿真时随机扰动这些参数，提升迁移到真机的鲁棒性",
  "mass_kg":        {"nominal": 1.65, "range": [1.55, 1.75]},
  "com_offset_mm":  {"nominal": [0, 0, 0], "range": 15.0},
  "friction":       {"nominal": 0.6, "range": [0.4, 0.9]},
  "motor_strength": {"nominal": 1.0, "range": [0.85, 1.15]},
  "control_latency_ms": {"nominal": 8.0, "range": [4.0, 16.0]},
  "backlash_deg":   {"nominal": 1.0, "range": [0.5, 2.0]},
  "sensor_noise": {
    "imu_gyro_std":  0.01,
    "imu_accel_std": 0.05,
    "camera_pixel_std": 2.0
  },
  "lighting_lux":   {"nominal": 400, "range": [100, 800]},
  "ground_friction": {"nominal": 0.7, "range": [0.5, 0.95]}
}
```

**为什么这个重要**：
- 评委问"你们怎么保证仿真结果能迁移到真机"，这个文件就是答案
- 它把"低成本舵机的不确定性"从**劣势**变成了**被显式建模的对象**
- 与主创新点（鲁棒性边界）天然衔接

### 4.4 `perception_sim.json` —— 感知仿真参数

让 Mock 感知**带真实噪声**（当前 Mock 返回固定值，闭环是假的）：

```json
{
  "schema_version": "1.0",
  "camera": {
    "resolution": [640, 480],
    "fov_deg": 70.0,
    "fps": 30,
    "mount_height_mm": 320.0,
    "mount_pitch_deg": -25.0
  },
  "face": {"detect_range_mm": 1500, "min_face_px": 40, "false_positive_rate": 0.02},
  "qr":   {"detect_range_mm": 1000, "min_qr_px": 60, "decode_fail_rate": 0.05},
  "ball": {"diameter_mm": 40.0, "detect_range_mm": 800, "color_tolerance": 0.15},
  "noise": {
    "position_std_mm": 3.0,
    "angle_std_deg": 1.5,
    "dropout_rate": 0.03
  }
}
```

### 4.5 `scenario_set.json` —— 场景集（对齐五项赛题）

```json
{
  "schema_version": "1.0",
  "arena": {"size_mm": [2400, 2400], "zones": 5},
  "scenarios": [
    {
      "id": "S-01-face",
      "task_card": "T-01",
      "initial": {"face_position_mm": [0, 0, 1200], "face_id": "测试员A"},
      "variations": ["光照 100-800lux", "距离 500-1500mm", "5 人以内"],
      "success_criteria": {"name_correct": true, "latency_s": 5.0}
    }
  ]
}
```

---

## 五、任务 4：让数据包"直接能跑"

### 5.1 新建 `design/run_sim.py`

**目标**：一条命令，从数据包跑起仿真，输出结果。

```bash
python3 design/run_sim.py --package design/packages/ --scenario S-01-face
python3 design/run_sim.py --all --randomize --episodes 20
```

**要求**：
- **纯标准库**起步（可选依赖 numpy）
- 复用现有 `atri.brain` / `atri.cerebellum` / `atri.perception`
- **通过 `ServoBus` 注入舵机非理想特性**（继承 `ServoBus` 写一个 `RealisticServoBus`）
- 通过 `PerceptionBackend` 注入带噪声的感知
- 输出：JSON 结果 + CSV 日志 + SVG 图表

### 5.2 新增 `atri/cerebellum.py` 的 `RealisticServoBus`

```python
class RealisticServoBus(ServoBus):
    """带舵机非理想特性的总线：死区、回程间隙、转速限制、控制延迟。

    参数从 design/packages/servo_spec.json 读取。
    这是让仿真贴近真机的关键 —— MockServoBus 假设瞬间到位，不真实。
    """
```

**要求**：
- 死区：目标变化 < `deadband_deg` 时不动
- 回程间隙：换向时叠加 `backlash_deg`
- 转速限制：`no_load_speed_dps` 约束每秒最大角度变化
- 控制延迟：指令延迟 `control_latency_ms` 生效
- **不改变 `ServoBus` 接口**（这是开闭原则的体现）

---

## 六、任务 5：硬件设计贴合训练的具体措施

> 你的要求："让硬件设计的工程尽量贴合模型训练。" 以下是具体做法。

| 措施 | 做法 | 材料里的论证 |
|---|---|---|
| **① 舵机特性入模** | `servo_spec.json` 记录死区/间隙/延迟，仿真中真实模拟 | "仿真引入非理想特性，缩小 sim-to-real gap" |
| **② 域随机化** | `domain_random.json` 随机质量/摩擦/延迟/光照 | "对参数不确定性做域随机化，提升迁移鲁棒性" |
| **③ 感知噪声注入** | `perception_sim.json` 给视觉加噪声与丢帧 | "感知链路按真实相机参数建模" |
| **④ 关节限位对齐** | URDF limit ≡ `config.py` limit | "仿真与固件共用同一份关节约束" |
| **⑤ 控制周期对齐** | 仿真步长 = 20ms = `robot.json` 的 `control_period_ms` | "仿真与实机控制周期一致" |
| **⑥ 动作库共用** | 仿真标定的关键帧直接导出为 `action_library` JSON | "仿真标定结果可直接下发实机" |
| **⑦ 单一下游来源** | 图纸/URDF/仿真全部从 `robot_model.json` 生成 | "设计变更自动同步到仿真与图纸" |

**这七条本身就是可以写进材料的工程方法。** 尤其 ①④⑤⑥，直接回应"仿真能不能信"这个必问题。

---

## 七、任务 6：跑通并出数据

### 7.1 最小闭环

```bash
# 1. 生成模型
python3 design/gen_urdf.py --input design/robot_model.json --output design/atri.urdf --validate

# 2. 校验 URDF（用现有测试框架）
python3 -m unittest discover -s tests -v

# 3. 跑仿真
python3 design/run_sim.py --all --episodes 10

# 4. 出图表
python3 design/plot_results.py --input design/results/ --output design/figures/
```

### 7.2 必须产出的数据

| 数据 | 形式 | 证明什么 |
|---|---|---|
| 关节限位校核表 | Markdown 表 | 22 关节行程都够 |
| 质心与支撑多边形 | SVG 图 | 站立稳定 |
| 五项任务仿真成功率 | 柱状图 | 系统能跑 |
| **域随机化下的鲁棒性** | 成功率-扰动曲线 | ⭐ 核心创新证据 |
| 舵机非理想特性影响 | 有无对比曲线 | sim-to-real 论证 |

---

## 八、执行顺序与依赖

```
任务1 (robot_model.json)  ← 关键路径起点
    ↓
任务2 (gen_urdf.py → atri.urdf)  ──→ 可独立验证
    ↓
任务3 (packages: servo/domain/perception/scenario)
    ↓
任务4 (RealisticServoBus + run_sim.py)
    ↓
任务6 (跑数据 + 出图)
    ↑
任务5 (贴合措施贯穿 3-4，不是独立任务)
```

**并行建议**：
- SolidWorks 建模（人工）与任务 1—4（软件）**可并行**，但**以 `robot_model.json` 为共同基准**
- CAD 出来后回填 `mesh` 字段，替换 box 占位几何

---

## 九、约束与红线

1. **禁止编造数据**。所有结果来自真实运行，注明命令与日期。
2. **核心代码零第三方依赖**（`atri/` 包内）。`design/` 脚本可选用 numpy。
3. **关节名与限位以 `config.py` 为准**，不得自创。
4. **不改 `brain.py` / `fsm.py` / `task_card.py` 核心逻辑**；通过子类/注入扩展。
5. **单位纪律**：数据包用 mm，URDF 用 m，角度内部用 deg、导出用 rad。**转换处必须写注释。**
6. **禁止 force push**；改动前 `git pull --rebase origin main`。
7. CAD 大文件（>50MB）不入库，放网盘 + 仓库内放说明。
8. **每个产物必须可复现**：给出确切命令。

---

## 十、交付清单

**设计层**
- [ ] `design/robot_model.json`（L1 单一事实来源，尺寸自洽）
- [ ] `design/gen_urdf.py`（纯标准库，带 `--validate`）
- [ ] `design/atri.urdf`（22 关节，限位对齐 `config.py`）

**数据包层**
- [ ] `design/packages/servo_spec.json`（舵机真实特性）⭐
- [ ] `design/packages/domain_random.json`（域随机化）⭐
- [ ] `design/packages/perception_sim.json`（感知噪声）
- [ ] `design/packages/scenario_set.json`（五项任务场景）

**仿真层**
- [ ] `atri/cerebellum.py` 新增 `RealisticServoBus`
- [ ] `design/run_sim.py`（一条命令跑起）
- [ ] `design/plot_results.py`（SVG 出图，纯标准库）
- [ ] `design/results/`（真实运行数据）

**文档层**
- [ ] `design/README.md`（数据包说明 + 复现命令）
- [ ] 关节限位校核表
- [ ] 质心/支撑多边形图
- [ ] sim-to-real 论证段（供材料引用）

**CAD 层（人工，可并行）**
- [ ] 总装三视图 + **22 关节编号图**（最高优先级）
- [ ] 回填 `mesh` 字段

---

## 十一、时间不足时的优先级

1. **`robot_model.json` + `gen_urdf.py` + `atri.urdf`** ← 这是"能跑仿真"的最小集
2. **`servo_spec.json` + `domain_random.json`** ← 这两个是"贴合训练"的核心论证
3. **`RealisticServoBus` + `run_sim.py`** ← 让仿真真的不一样
4. **22 关节编号图**（人工 CAD）← 评委必问
5. 其余

---

## 十二、一句话记住

> **本轮的目标不是"画出机器人"，而是让"设计"变成一份能直接喂给仿真、且仿真结果对真机有参考价值的数据包。**
> 能做到这一点，"仿真先行"才是真的，而不是一句口号。
