"""无硬件闭环仿真：Mock 感知 + Mock 舵机 + 脚本运动控制（无 VLA）。"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List

from .brain import Brain
from .cerebellum import Cerebellum, MockServoBus
from .perception import MockPerception
from .task_card import TaskCard
from .voice import MockTTS

ROOT = Path(__file__).resolve().parent.parent
TASK_CARD_DIR = ROOT / "task_cards"
CONFIG_PATH = ROOT / "config" / "robot.json"

MOCK_OBSERVATIONS = {
    "face": {"name": "测试员A", "confidence": 0.93},
    "qr": {"payload": {"action": "walk", "steps": 3}},
    "object": {"target": "红块", "distance_cm": 8.0},
    "ball": {"x_cm": 1.5, "distance_cm": 12.0},
    "speech": {"keyword": "跳舞"},
}


def load_robot_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def build_robot(config: Dict[str, Any], sleeper: Any = None) -> Dict[str, Any]:
    servo_bus = MockServoBus()
    cerebellum = Cerebellum(servo_bus=servo_bus, sleeper=sleeper)
    perception = MockPerception()
    tts = MockTTS()
    brain = Brain(cerebellum=cerebellum, perception=perception, tts=tts)

    motion_cfg = config.get("motion", {})
    motion_backend = motion_cfg.get("backend", "scripted")

    return {
        "brain": brain,
        "cerebellum": cerebellum,
        "servo_bus": servo_bus,
        "perception": perception,
        "tts": tts,
        "motion_backend": motion_backend,
    }


def load_task_cards() -> List[TaskCard]:
    cards = []
    for path in sorted(TASK_CARD_DIR.glob("*.json")):
        cards.append(TaskCard.load(path))
    return cards


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="无硬件闭环演示")
    parser.add_argument("--fast", action="store_true", help="跳过 time.sleep，快速跑完闭环")
    args = parser.parse_args(argv)

    print("=" * 64)
    print("A.T.R.I. 软件栈 · 无硬件闭环演示")
    print("=" * 64)

    config = load_robot_config()
    sleeper = (lambda dt: None) if args.fast else None
    robot = build_robot(config, sleeper=sleeper)
    brain = robot["brain"]

    print(f"运动控制后端: {robot['motion_backend']}（脚本动作库 + 步态生成，无 VLA）")
    print(f"任务卡目录: {TASK_CARD_DIR}")
    print()

    cards = load_task_cards()
    if not cards:
        print("未找到任务卡")
        return 1

    overall = []
    for card in cards:
        print(f"--- 任务卡 {card.task_id} | {card.name} ---")
        # 演示改为不预填观测，由 MockPerception 提供 face/qr/ball 感知，
        # object/speech 使用技能默认参数，验证感知接口已串入技能链。
        result = brain.execute_task(card, observation=None)
        ok = result.get("ok", False)
        print(f"    执行结果: {'成功' if ok else '失败'}")
        if not ok:
            print(f"    错误: {result.get('error')}")
        print(f"    FSM: {' -> '.join(result.get('history', []))}")
        print()
        overall.append({"task_id": card.task_id, "ok": ok, **result})

    print("=" * 64)
    passed = sum(1 for item in overall if item.get("ok"))
    print(f"闭环演示完成: {passed}/{len(overall)} 项任务通过")
    print("=" * 64)
    return 0 if passed == len(overall) else 2


if __name__ == "__main__":
    raise SystemExit(main())
