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


def load_task_cards(task_card_dir: str | Path | None = None) -> List[TaskCard]:
    directory = Path(task_card_dir) if task_card_dir is not None else TASK_CARD_DIR
    cards = []
    for path in sorted(directory.glob("*.json")):
        cards.append(TaskCard.load(path))
    return cards


def run_task_cards(
    brain: Brain,
    task_card_dir: str | Path | None = None,
    observation: Dict[str, Any] | None = None,
    verbose: bool = True,
) -> tuple[List[Dict[str, Any]], int, int]:
    """顺序执行任务卡目录下的全部任务。

    仿真（Webots / 无硬件）与命令行入口共用这一段调度逻辑，避免各自复制一份。
    ``observation=None`` 时由 Brain 上注入的感知接口（MockPerception 等）提供观测。

    返回 ``(results, passed, total)``。
    """
    results: List[Dict[str, Any]] = []
    for card in load_task_cards(task_card_dir):
        if verbose:
            print(f"--- 任务卡 {card.task_id} | {card.name} ---")
        result = brain.execute_task(card, observation=observation)
        ok = bool(result.get("ok", False))
        if verbose:
            print(f"    执行结果: {'成功' if ok else '失败'}")
            if not ok:
                print(f"    错误: {result.get('error')}")
            print(f"    FSM: {' -> '.join(result.get('history', []))}")
            print()
        results.append({"task_id": card.task_id, "ok": ok, **result})
    passed = sum(1 for item in results if item.get("ok"))
    return results, passed, len(results)


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

    # 演示不预填观测：由 MockPerception 提供 face/qr/ball 感知，
    # object/speech 使用技能默认参数，验证感知接口已串入技能链。
    overall, passed, total = run_task_cards(brain, observation=None)

    print("=" * 64)
    print(f"闭环演示完成: {passed}/{total} 项任务通过")
    print("=" * 64)
    return 0 if passed == total else 2


if __name__ == "__main__":
    raise SystemExit(main())
