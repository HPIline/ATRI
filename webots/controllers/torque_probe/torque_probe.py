"""S2 扭矩探针：零位站姿保持，记录 20 关节扭矩峰值。

来源：从 `design/handoff/仿真请求-Webots验证清单.md` §S2 抽出为可运行文件（2026-09-12）。
用法（队友机器）：把派生重力世界里的机器人 controller 改为 "torque_probe"，
再 `webots --mode=fast <world>.wbt`；阈值与读法见请求文档 §S2。
本机（Mac）无 Webots，**未运行过**，只做过 ast 语法检查。
"""
# docs/process/sim/torque_probe.py —— 静止站立工况下逐关节扭矩峰值
# 放在 docs/process/sim/ 下，把带重力世界副本的 Robot.controller 指到它（或写绝对路径）。
# 只做三件事：下发一次零位站姿 -> 保持 10 仿真秒 -> 记录峰值扭矩。
from controller import Robot
import json
import math

VELOCITY = 2.0          # rad/s，与 atri_controller.py 的 DEFAULT_VELOCITY 一致
HOLD_SIM_S = 10.0       # 站立观察时长（仿真秒）

# 机械零位站姿（design/atri.urdf 的零位；肘部 rest 不是 0，见 software/atri/atri/config.py::rest_pose）
REST_DEG = {"left_elbow_pitch": -10.0, "right_elbow_pitch": -10.0}

# 全部 20 个关节都下发目标角（漏掉的那个会在重力下瘫掉，但扭矩记成 0，看着像"很轻松"）
ALL_JOINTS = [
    "head_yaw", "head_pitch", "trunk_pitch", "trunk_roll",
    "left_shoulder_pitch", "left_shoulder_roll", "left_elbow_pitch", "left_gripper",
    "right_shoulder_pitch", "right_shoulder_roll", "right_elbow_pitch", "right_gripper",
    "left_hip_roll", "left_hip_pitch", "left_knee_pitch", "left_ankle_pitch",
    "right_hip_roll", "right_hip_pitch", "right_knee_pitch", "right_ankle_pitch",
]

robot = Robot()
dt = int(robot.getBasicTimeStep())

motors, sensors = {}, {}
for name in ALL_JOINTS:
    m = robot.getDevice(name)
    if m is None:
        print(f"[torque_probe] 找不到电机 {name}"); continue
    m.setVelocity(VELOCITY)                       # 不设速度会瞬间到位，看不出过程
    m.enableTorqueFeedback(dt)                    # ★ Webots Python API
    s = m.getPositionSensor()
    if s is not None:
        s.enable(dt)                              # 未 enable 的 PositionSensor 返回 NaN
    motors[name] = m
    sensors[name] = s
    print(f"[torque_probe] 已绑定 + 扭矩反馈: {name}")

# 下发零位站姿
for name, m in motors.items():
    m.setPosition(math.radians(REST_DEG.get(name, 0.0)))

peak_abs, lo, hi = {n: 0.0 for n in motors}, {n: 0.0 for n in motors}, {n: 0.0 for n in motors}
steps = 0
while robot.step(dt) != -1:
    steps += 1
    for name, m in motors.items():
        t = m.getTorqueFeedback()
        if t != t:          # 过滤 NaN
            continue
        peak_abs[name] = max(peak_abs[name], abs(t))
        lo[name] = min(lo[name], t)
        hi[name] = max(hi[name], t)
    if steps * dt >= HOLD_SIM_S * 1000:
        break

payload = {
    "sim_seconds": steps * dt / 1000.0,
    "velocity_rad_s": VELOCITY,
    "note": "峰值扭矩为 |τ| 最大值；lo/hi 是带符号的最小/最大值，用于判断加载方向",
    "peak_abs_torque_nm": {k: round(v, 4) for k, v in peak_abs.items()},
    "min_torque_nm": {k: round(v, 4) for k, v in lo.items()},
    "max_torque_nm": {k: round(v, 4) for k, v in hi.items()},
    "final_joint_deg": {k: round(math.degrees(s.getValue()), 2)
                        for k, s in sensors.items() if s is not None},
}
with open("docs/process/sim/s2_torque_peak.json", "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2)
print(json.dumps(payload, ensure_ascii=False, indent=2))
