"""命令行入口：atri-run <task_card.json>。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .sim import build_robot, load_robot_config
from .task_card import TaskCard


def main() -> int:
    parser = argparse.ArgumentParser(description="运行单张 A.T.R.I. 任务卡")
    parser.add_argument("task_card", help="任务卡 JSON 路径")
    parser.add_argument("--observation", help="观测 JSON 路径（可选，默认使用内置 Mock 观测）")
    args = parser.parse_args()

    card = TaskCard.load(args.task_card)
    obs = None
    if args.observation:
        with open(args.observation, "r", encoding="utf-8") as fh:
            obs = json.load(fh)

    robot = build_robot(load_robot_config())
    result = robot["brain"].execute_task(card, observation=obs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
