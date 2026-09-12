"""命令行入口：atri-run <task_card.json>。"""
from __future__ import annotations

import argparse
import json
import sys

from .sim import build_robot, load_robot_config
from .task_card import TaskCard, TaskCardError


def main() -> int:
    parser = argparse.ArgumentParser(description="运行单张 A.T.R.I. 任务卡")
    parser.add_argument("task_card", help="任务卡 JSON 路径")
    parser.add_argument("--observation", help="观测 JSON 路径（可选，默认使用内置 Mock 观测）")
    args = parser.parse_args()

    try:
        card = TaskCard.load(args.task_card)
    except TaskCardError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    obs = None
    if args.observation:
        try:
            with open(args.observation, "r", encoding="utf-8") as fh:
                obs = json.load(fh)
        except UnicodeDecodeError as exc:
            # UnicodeDecodeError 是 ValueError 子类，不在 OSError/JSONDecodeError 之内
            print(f"错误：观测文件不是 UTF-8 编码：{exc}", file=sys.stderr)
            return 2
        except (OSError, json.JSONDecodeError) as exc:
            print(f"错误：观测文件读取失败：{exc}", file=sys.stderr)
            return 2
        if not isinstance(obs, dict):
            print("错误：观测文件必须是 JSON 对象", file=sys.stderr)
            return 2

    robot = build_robot(load_robot_config())
    result = robot["brain"].execute_task(card, observation=obs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
