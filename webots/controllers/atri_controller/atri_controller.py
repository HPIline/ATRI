"""A.T.R.I. Webots 控制器（第一版）。

用法：
1. 在 Webots 中打开机器人世界；
2. 将机器人 controller 字段设为 <extern>；
3. 在 Webots 命令行/IDE 中启动本控制器，或直接把本目录作为机器人控制器目录；
4. 控制器会读取同目录 joint_mapping.json，按任务卡顺序执行五项技能。

如果电机名与 ATRI 关节名不一致（例如使用内置 Nao），请把
joint_mapping_nao.json 的内容覆盖到 joint_mapping.json，再按实际模型调整。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict

try:
    from controller import Robot
except ImportError:
    print("本控制器需要在 Webots 环境中运行（Python 的 controller 模块由 Webots 提供）。")
    sys.exit(0)

# 仓库根目录 = 本文件向上 3 级（webots/controllers/atri_controller/ -> 仓库根）
ROOT = Path(__file__).resolve().parents[3]
SOFTWARE_ROOT = ROOT / "软件" / "atri"
sys.path.insert(0, str(SOFTWARE_ROOT))

from atri.brain import Brain  # noqa: E402
from atri.cerebellum import Cerebellum, ServoBus  # noqa: E402
from atri.config import JOINTS  # noqa: E402
from atri.task_card import TaskCard  # noqa: E402

ID_TO_NAME = {spec["id"]: name for name, spec in JOINTS.items()}

MOCK_OBSERVATIONS = {
    "face": {"name": "测试员A", "confidence": 0.93},
    "qr": {"payload": {"action": "walk", "steps": 3}},
    "object": {"target": "红块", "distance_cm": 8.0},
    "ball": {"x_cm": 1.5, "distance_cm": 12.0},
    "speech": {"keyword": "跳舞"},
}


class WebotsServoBus(ServoBus):
    """把 ATRI 关节角写到 Webots RotationalMotor。"""

    def __init__(self, robot: Robot, mapping: Dict[str, str]) -> None:
        self.robot = robot
        self.motors: Dict[str, Any] = {}
        for atri_name, webots_name in mapping.items():
            if not webots_name:
                continue
            motor = robot.getDevice(webots_name)
            if motor is None:
                print(f"  [WebotsServoBus] 找不到电机: {webots_name} (ATRI: {atri_name})，已跳过")
                continue
            self.motors[atri_name] = motor
            print(f"  [WebotsServoBus] 已绑定: {atri_name} -> {webots_name}")

    def set_angle(self, joint_id: int, deg: float) -> None:
        name = ID_TO_NAME.get(joint_id)
        motor = self.motors.get(name) if name else None
        if motor is not None:
            motor.setPosition(math.radians(deg))

    def read_angle(self, joint_id: int) -> float:
        name = ID_TO_NAME.get(joint_id)
        motor = self.motors.get(name) if name else None
        if motor is not None:
            sensor = motor.getPositionSensor()
            if sensor is not None:
                return math.degrees(sensor.getValue())
            return math.degrees(motor.getTargetPosition())
        return 0.0


def load_mapping() -> Dict[str, str]:
    path = Path(__file__).resolve().parent / "joint_mapping.json"
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main() -> None:
    robot = Robot()
    timestep = int(robot.getBasicTimeStep())

    mapping = load_mapping()
    bus = WebotsServoBus(robot, mapping)
    # 关键：用 robot.step 推进仿真时间，而不是 time.sleep
    cerebellum = Cerebellum(
        servo_bus=bus,
        sleeper=lambda dt_s: robot.step(max(1, int(dt_s * 1000))),
    )
    brain = Brain(cerebellum)

    print("=" * 60)
    print("A.T.R.I. Webots 控制器启动")
    print(f"timestep = {timestep} ms")
    print("=" * 60)

    # 先回零，让机器人进入初始站姿
    cerebellum.home()
    robot.step(timestep)

    task_card_dir = SOFTWARE_ROOT / "task_cards"
    for path in sorted(task_card_dir.glob("*.json")):
        card = TaskCard.load(path)
        print(f"--- 执行任务卡 {card.task_id} | {card.name} ---")
        obs = {k: dict(v) for k, v in MOCK_OBSERVATIONS.items()}
        result = brain.execute_task(card, observation=obs)
        print(f"    结果: {'成功' if result.get('ok') else '失败'}")
        if not result.get("ok"):
            print(f"    错误: {result.get('error')}")
        print(f"    FSM: {' -> '.join(result.get('history', []))}")

    print("所有任务卡执行完毕，控制器进入保持循环（Ctrl+C 退出）。")
    while robot.step(timestep) != -1:
        pass


if __name__ == "__main__":
    main()
