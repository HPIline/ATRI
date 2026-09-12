"""无硬件闭环仿真：Mock 感知 + Mock 舵机 + 脚本运动控制（无 VLA）。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from .brain import Brain
from .cerebellum import Cerebellum, MockServoBus
from .perception import MockPerception, OpenCVPerception
from .task_card import TaskCard, TaskCardError
from .voice import build_tts

ROOT = Path(__file__).resolve().parent.parent
TASK_CARD_DIR = ROOT / "task_cards"
CONFIG_PATH = ROOT / "config" / "robot.json"

# 脚本动作层固定的轨迹采样周期（config 的 control_period_ms 与之对应）。
BUILTIN_CONTROL_PERIOD_MS = 20


def load_robot_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def build_perception(config: Dict[str, Any]) -> Any:
    """按配置选择视觉后端；请求 OpenCV 但不可用时降级并给出可见告警。"""
    backend = (config.get("perception") or {}).get("backend", "mock")
    if backend in ("auto", "opencv"):
        candidate = OpenCVPerception()
        if candidate.available():
            return candidate
        print(f"  [Perception] 请求后端 {backend}，但 OpenCV 不可用，降级为 MockPerception")
    elif backend != "mock":
        print(f"  [Perception] 未知感知后端 {backend!r}，退回 MockPerception")
    return MockPerception()


def _fsm_verbose(config: Dict[str, Any]) -> bool:
    value = (config.get("brain") or {}).get("fsm_verbosity", 1)
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return True


def build_robot(config: Dict[str, Any], sleeper: Any = None) -> Dict[str, Any]:
    servo_bus = MockServoBus()
    cerebellum = Cerebellum(servo_bus=servo_bus, sleeper=sleeper)
    perception = build_perception(config)
    tts = build_tts()

    motion_cfg = config.get("motion") or {}
    motion_backend = motion_cfg.get("backend", "scripted")
    gait = dict(motion_cfg.get("gait") or {})

    control_period_ms = (config.get("cerebellum") or {}).get(
        "control_period_ms", BUILTIN_CONTROL_PERIOD_MS
    )
    if control_period_ms != BUILTIN_CONTROL_PERIOD_MS:
        print(
            f"  [配置] control_period_ms={control_period_ms} 未生效："
            f"脚本动作层按固定 {BUILTIN_CONTROL_PERIOD_MS} ms 采样（小脑层实现）"
        )

    brain = Brain(
        cerebellum=cerebellum,
        perception=perception,
        tts=tts,
        gait=gait,
        fsm_verbose=_fsm_verbose(config),
    )

    return {
        "brain": brain,
        "cerebellum": cerebellum,
        "servo_bus": servo_bus,
        "perception": perception,
        "tts": tts,
        "motion_backend": motion_backend,
        "gait": gait,
    }


def load_task_card_entries(task_card_dir: str | Path | None = None) -> List[Dict[str, Any]]:
    """按文件名顺序加载任务卡目录。

    单张卡解析失败只记录错误并继续，避免一张坏卡中断整场演示。
    每项为 ``{"card": TaskCard}`` 或 ``{"path": Path, "task_id": str, "error": str}``。
    """
    directory = Path(task_card_dir) if task_card_dir is not None else TASK_CARD_DIR
    entries: List[Dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            entries.append({"card": TaskCard.load(path)})
        except TaskCardError as exc:
            entries.append(
                {"path": path, "task_id": path.stem, "error": f"{type(exc).__name__}: {exc}"}
            )
    return entries


def load_task_cards(task_card_dir: str | Path | None = None) -> List[TaskCard]:
    """加载目录下全部任务卡；坏卡跳过并告警，不中断其余卡。"""
    cards = []
    for entry in load_task_card_entries(task_card_dir):
        if "card" in entry:
            cards.append(entry["card"])
        else:
            print(f"警告：跳过坏任务卡 {entry['path']}：{entry['error']}")
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
    加载失败的任务卡记为 ``ok=False`` 并继续跑其余卡。

    返回 ``(results, passed, total)``。
    """
    results: List[Dict[str, Any]] = []
    for entry in load_task_card_entries(task_card_dir):
        if "card" not in entry:
            results.append({"task_id": entry["task_id"], "ok": False, "error": entry["error"]})
            if verbose:
                print(f"--- 任务卡 {entry['path'].name} 加载失败 ---")
                print(f"    错误: {entry['error']}")
                print()
            continue

        card = entry["card"]
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
    print(f"视觉后端: {robot['perception'].name}")
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
