# ATRI-v2 Webots 导入状态（A 路线）

**这是一次 URDF 导入 / 运动学冒烟测试，不是 G4，不是 5/5 任务卡验证，不是真机测试。**

This is an import/kinematics smoke test, **NOT G4**, **NOT 5/5 contest-task verification**, **NOT a physical robot test**. T1–T5 were not run. The 22-DOF `webots/worlds/atri_22dof.wbt` controller and `software/atri` were not modified.

生成器：`design/v2/webots_v2_import.py`（自写 URDF→WBT，未安装 `urdf2webots`）。  
参考：本仓库 `webots/tools/generate_atri_world.py`（嵌套 HingeJoint、`dampingConstant`、`gravity` 为 SFFloat、禁止 EXTERNPROTO）以及 cyberbotics/urdf2webots 的 `endPoint.translation = joint origin`、`anchor = origin`、Mesh+scale 约定。

## Webots 是否真正启动

**是。** 本机 `/usr/bin/webots` → Webots R2025a。两次 `--batch` 均写出报告后退出。

命令（第二次，`castShadows FALSE` 之后）：

```
webots --mode=fast --no-rendering --batch --stdout --stderr --minimize design/v2/out/webots/worlds/atri_v2.wbt
```

| 项 | 结果 |
| --- | --- |
| 进程 | `/usr/bin/webots` pid 74376（第一次 73542） |
| 退出 | `returncode=0`；Supervisor `simulationQuit`；报告出现后 watchdog 回收 |
| 控制器 | `INFO: atri_v2_import_check: Starting controller: python3 -u atri_v2_import_check.py` 然后 `Terminating.` |
| 报告 | `design/v2/out/webots/import-report.json`，`"ok": true`，`"failures": []` |

世界 / 控制器：

- `design/v2/out/webots/worlds/atri_v2.wbt`
- `design/v2/out/webots/controllers/atri_v2_import_check/atri_v2_import_check.py`
- 快照 URDF/网格：`design/v2/out/webots/atri_v2.urdf`、`design/v2/out/webots/meshes/`（21 个 link STL，约 85 MB）。CAD 导出会 `rmtree out/sim/`，所以导入不用那份热路径。

## 关节数 / hip_yaw

从 **当前** `atri_v2.urdf` 复核（不要凭记忆）：

- `robot name="atri_v2"`
- 注释：mm→m、deg→rad；质量是目标质量分摊，不是 CAD/实测
- 根 link `pelvis`，`root_xyz_mm="0.0 0.0 232.0"` → 世界 `translation 0 0 0.232`
- **20 revolute**（Webots 里 20 个 `HingeJoint` / 20 个 `RotationalMotor` / 20 个 `PositionSensor`）
- **`hip_yaw` 不存在**（URDF 无名、电机无名、传感器无名）
- 夹爪：`left_gripper` → 子 link `left_grip`；`right_gripper` → `right_grip`
- VL53L1X **不是** URDF joint/link

电机名（与 URDF joint 名一致）：

`trunk_roll`, `trunk_pitch`, `head_yaw`, `head_pitch`, `left_shoulder_pitch`, `left_shoulder_roll`, `left_elbow_pitch`, `left_gripper`, `right_shoulder_pitch`, `right_shoulder_roll`, `right_elbow_pitch`, `right_gripper`, `left_hip_roll`, `left_hip_pitch`, `left_knee_pitch`, `left_ankle_pitch`, `right_hip_roll`, `right_hip_pitch`, `right_knee_pitch`, `right_ankle_pitch`

相对 22 DOF 世界：少一对 `left_hip_yaw` / `right_hip_yaw`。这是 A 路线 20 舵机，不是漏导入。

## 轴向 / 零位

20 个关节的 `HingeJointParameters.axis` 与 URDF `<axis xyz>` 一致；`endPoint Solid.translation` 与 URDF `<origin xyz>` 一致（零位，容差 1e-5）。锚点 `anchor` 同步写成同一 origin。

例：

- `trunk_roll` axis `(1,0,0)` xyz `(0,0,0.018)`
- `head_yaw` axis `(0,0,1)` xyz `(0,0,0.087)`
- `right_shoulder_pitch` axis `(0,-1,0)` xyz `(0,-0.075,0.045)`（URDF 右侧肩 pitch 轴带负号，原样保留）
- `left_gripper` / `right_gripper` xyz `(0,0,-0.06)` axis `(1,0,0)`

运动学抽检：`head_yaw` 指令 `0.2 rad`，位置传感器 `before ≈ 0`，`after ≈ 0.1993`，`delta ≈ 0.1993`，走了 16 个物理步（另 +1 步 enable）。**只证明该电机能转，不证明走路/抓取。**

碰撞盒用 STL AABB（米）+ `Pose`，**不是**三角网格接触。重力 `0`，无地面。

## 质量 / 惯量 / 单位

- 视觉：`Transform scale 0.001 0.001 0.001` 包一层 `Mesh { url "../meshes/<link>.stl" }`，对应 URDF 毫米 STL。
- `Physics.density -1` + URDF `mass` + `inertiaMatrix`（ixx/iyy/izz 与 ixy/ixz/iyz）。
- 抽检：pelvis 0.211738 kg、torso 0.582278、head 0.132336、left_thigh 0.14557、left_grip/right_grip 0.031761，与 URDF 一致。
- 21 个 solid **没有** mass=0、没有 &lt;1e-6、没有 &gt;20 kg。
- 这些质量仍是 `urdf.py` 的 **目标质量分摊**，不是 CAD 体积密度，也不是称重。惯量由盒公式分配，不能当动力学真值。

根节点：`DEF pelvis Robot { name "atri_v2" }`，pelvis 质量挂在 Robot 上（报告里 `atri_v2` 与 `pelvis_via_robot` 都是 0.211738）。

## 夹爪与 VL53L1X

- `left_grip` / `right_grip` 作为 `Solid` 存在，质量非零，网格 `left_grip.stl` / `right_grip.stl`。
- VL53L1X：CAD 零件（`electronics_cad.py`，挂在 `head` link，20×24×1.6 mm 包络）。**没有**单独 URDF joint/link，**没有** Webots DistanceSensor。ToF 几何在 `meshes/head.stl` 里。导入 **不会** 因为缺 ToF 节点而失败——缺节点是预期，不是漏导入。

## 失败与警告（原文）

控制器 `failures: []`。世界能打开，没有回退到 `empty.wbt`。

Webots 仍打印网格过密警告（`castShadows FALSE` 之后阴影那条已消失）。节选：

```
WARNING: DEF pelvis Robot > Transform  > Shape  > Mesh "": Mesh '' has more than 100'000 vertices, it is recommended to reduce the number of vertices.
WARNING: ... DEF torso Solid > Transform  > Shape  > Mesh "": Mesh '' has more than 100'000 vertices ...
INFO: atri_v2_import_check: Starting controller: python3 -u atri_v2_import_check.py
INFO: atri_v2_import_check: Terminating.
```

torso STL 约 427k 三角（21 MB）。`--no-rendering` 冒烟能跑；GUI / 带接触的重力仿真会很重。

## 还需要改什么（未做）

- **降面**：给仿真一份 &lt;20k 三角的凸包或抽稀网格；现在是审查用 CAD 网格。
- **重力 + 地面 + 接触**：本次 `gravity 0`、无 Plane、碰撞是 AABB 盒子。不能当静立/扭矩/走路证据。
- **22 DOF 控制器 / 任务卡**：电机名是 v2 URDF 名，没有 `hip_yaw`。直接套 `atri_controller` + `joint_mapping.json` 会按 22 关节绑，**不要**拿这次冒烟当任务闭环。
- **传感器**：无相机、无 VL53 DistanceSensor、无 IMU。T2/T3 对位未测。
- **惯量真值**：要 CAD 质量属性或实测再回填。
- **自碰撞 / 网格碰撞**：`selfCollision FALSE`；密网格不宜直接当 `boundingObject`。
- GUI 实时：未开渲染窗口做目视检查。

## 明确不是什么

- **不是 G4。**
- **不是 5/5 任务验证，没有跑 T1–T5。**
- **不是真机、不是舵机总线、不是赛场。**
- 只证明：这份 20 轴 URDF 能进 Webots R2025a，关节名/轴/零位/质量能对上，夹爪 solid 在，hip_yaw 不在，头 yaw 能转过一小角。
