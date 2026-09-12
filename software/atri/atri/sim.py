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


def build_face_recognizer(models_dir: str | Path, db_path: str | Path) -> tuple[Any, Any]:
    """构造真识别链路（T-01）；任何一环缺失都**说清缺什么并返回 (None, None)**，不静默降级。

    返回 ``(recognizer, None)``；第二个元素留给调用方接取帧来源。
    """
    try:
        from .perception.faces import FaceDB, FaceRecognizer, SFaceEmbedder, YuNetDetector
    except ImportError as exc:
        print(f"  ⚠ 未启用真识别：缺少依赖（{exc}）")
        print(
            '    请执行： pip install "opencv-contrib-python==4.11.0.86" "numpy<2"'
            "（见 requirements-optional.txt）"
        )
        return None, None

    models = Path(models_dir)
    yunet = models / "face_detection_yunet_2023mar.onnx"
    sface = models / "face_recognition_sface_2021dec.onnx"
    missing = [str(p) for p in (yunet, sface) if not p.exists()]
    if missing:
        print("  ⚠ 未启用真识别：缺少模型 " + "、".join(missing))
        print("    先运行： python tools/fetch_models.py")
        return None, None

    db_file = Path(db_path)
    if not db_file.exists():
        print(f"  ⚠ 未启用真识别：找不到人脸库 {db_file}")
        return None, None

    db = FaceDB.load(db_file)
    if len(db) == 0:
        print(f"  ⚠ 人脸库 {db_file} 里没有任何人（0 条向量），T-01 将对所有脸都判不认识")
        print("    注册： python tools/face_enroll.py --help")
        return None, None

    recognizer = FaceRecognizer(
        detector=YuNetDetector(str(yunet)),
        embedder=SFaceEmbedder(str(sface)),
        db=db,
    )
    print(f"  ✓ 真识别已启用：{len(db)} 条向量 / {len(db.names)} 人，阈值 {db.threshold}")
    return recognizer, None


def build_robot(
    config: Dict[str, Any],
    sleeper: Any = None,
    face_recognizer: Any = None,
    frame_source: Any = None,
) -> Dict[str, Any]:
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
        face_recognizer=face_recognizer,
        frame_source=frame_source,
    )

    return {
        "brain": brain,
        "cerebellum": cerebellum,
        "servo_bus": servo_bus,
        "perception": perception,
        "tts": tts,
        "motion_backend": motion_backend,
        "gait": gait,
        "face_recognizer": face_recognizer,
        "frame_source": frame_source,
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
    param_overrides: Dict[str, Dict[str, Any]] | None = None,
) -> tuple[List[Dict[str, Any]], int, int]:
    """顺序执行任务卡目录下的全部任务。

    仿真（Webots / 无硬件）与命令行入口共用这一段调度逻辑，避免各自复制一份。
    ``observation=None`` 时由 Brain 上注入的感知接口（MockPerception 等）提供观测。
    加载失败的任务卡记为 ``ok=False`` 并继续跑其余卡。
    ``param_overrides`` 按 ``{task_id: {参数: 值}}`` 覆盖任务卡参数（演示/联调用，默认不影响任何行为）。

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
        if param_overrides and card.task_id in param_overrides:
            # 演示/联调用：覆盖任务卡参数（例如把 T-01 的 expect_names 换成现场要认的人）
            card.params.update(param_overrides[card.task_id])
        if verbose:
            print(f"--- 任务卡 {card.task_id} | {card.name} ---")
        result = brain.execute_task(card, observation=observation)
        ok = bool(result.get("ok", False))
        if verbose:
            # 用词要准：ok 的含义是"流程走完且技能报 ok"，**不是**"任务目标达成"的另一种说法。
            # 技能自己的业务结论在 status 字段里（ok / rejected / no_face / failed …）。
            print(f"    执行结果: {'成功' if ok else '失败'}")
            if not ok:
                print(f"    错误: {result.get('error')}")
            for item in (result.get("result") or {}).get("results", []):
                detail = [f"skill={item.get('skill')}", f"status={item.get('status')}"]
                if "source" in item:
                    detail.append(f"source={item['source']}")
                if item.get("name") is not None:
                    detail.append(f"name={item['name']}")
                if item.get("similarity") is not None:
                    detail.append(f"sim={item['similarity']}")
                print("    " + "  ".join(detail))
            print(f"    FSM: {' -> '.join(result.get('history', []))}")
            print()
        results.append({"task_id": card.task_id, "ok": ok, **result})
    passed = sum(1 for item in results if item.get("ok"))
    return results, passed, len(results)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="无硬件闭环演示")
    parser.add_argument("--fast", action="store_true", help="跳过 time.sleep，快速跑完闭环")
    parser.add_argument(
        "--face-image",
        default=None,
        help="用这张图片作为 T-01 的取帧来源（没有摄像头也能真跑人脸识别）",
    )
    parser.add_argument("--face-db", default=None, help="人脸库路径（默认 config/face_db.json）")
    parser.add_argument("--models", default=None, help="模型目录（默认 <仓库>/models）")
    parser.add_argument(
        "--face-expect",
        default=None,
        help="逗号分隔：临时覆盖 T-01 的 expect_names（现场要认的人；不认名单外的人）",
    )
    args = parser.parse_args(argv)

    print("=" * 64)
    print("A.T.R.I. 软件栈 · 无硬件闭环演示")
    print("=" * 64)

    config = load_robot_config()
    sleeper = (lambda dt: None) if args.fast else None

    repo_root = ROOT.parent.parent
    models_dir = Path(args.models) if args.models else repo_root / "models"
    db_path = Path(args.face_db) if args.face_db else CONFIG_PATH.parent / "face_db.json"

    face_recognizer = None
    frame_source = None
    if args.face_image:
        print(f"人脸取帧来源: {args.face_image}")
        face_recognizer, _ = build_face_recognizer(models_dir, db_path)
        if face_recognizer is not None:
            from .perception.sources import ImageFileSource

            frame_source = ImageFileSource(args.face_image)
            print("  → T-01 走**真识别**通路")
        else:
            print("  → T-01 退回感知接口通路（上面的原因说了缺什么）")

    robot = build_robot(
        config, sleeper=sleeper, face_recognizer=face_recognizer, frame_source=frame_source
    )
    brain = robot["brain"]

    print(f"运动控制后端: {robot['motion_backend']}（脚本动作库 + 步态生成，无 VLA）")
    print(f"视觉后端: {robot['perception'].name}")
    if face_recognizer is None:
        print("人脸识别通路: 未启用真识别（T-01 结果不代表真实识别能力）")
    print(f"任务卡目录: {TASK_CARD_DIR}")
    print()

    cards = load_task_cards()
    if not cards:
        print("未找到任务卡")
        return 1

    param_overrides: Dict[str, Dict[str, Any]] = {}
    if args.face_expect:
        names = [n.strip() for n in args.face_expect.split(",") if n.strip()]
        if names:
            param_overrides["T-01"] = {"expect_names": names}
            print(f"T-01 预期名单（--face-expect 覆盖）: {names}")
            print()

    # 演示不预填观测：由 MockPerception 提供 face/qr/ball 感知，
    # object/speech 使用技能默认参数，验证感知接口已串入技能链。
    overall, passed, total = run_task_cards(
        brain, observation=None, param_overrides=param_overrides or None
    )

    print("=" * 64)
    print(f"闭环演示完成: {passed}/{total} 项任务通过（流程指标，不是识别/抓取成功率）")
    print("=" * 64)
    return 0 if passed == total else 2


if __name__ == "__main__":
    raise SystemExit(main())
