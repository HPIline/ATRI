#!/usr/bin/env python3
"""注册人脸 → 生成人脸库（face_db.json）。

只存 128 维特征向量 + 姓名，**不复制任何原图进仓库**。

三种来源：

1. 图片目录（推荐，最可控）
       python software/atri/tools/face_enroll.py --from-dir 本地数据/faces/team \\
           --db software/atri/config/face_db.json --append
   目录结构：每个身份一个子目录，子目录名即姓名
       本地数据/faces/team/张三/1.jpg
       本地数据/faces/team/张三/2.jpg
       本地数据/faces/team/李四/1.jpg

2. LFW 数据集（用于跑通链路 / 做演示，不涉及真人隐私）
       python software/atri/tools/face_enroll.py --from-lfw 本地数据/faces/lfw_data.parquet \\
           --names George_W_Bush,Colin_Powell --per-name 5 --db /tmp/demo_db.json

3. 摄像头现场采集（需要授权，采集的图只写到你指定的本地目录）
       python software/atri/tools/face_enroll.py --camera --name 张三 --shots 5 \\
           --save-images 本地数据/faces/team/张三

阈值：默认沿用库里已有的阈值；用 --threshold 可覆盖。
**换成新相机/新环境后请用 software/atri/tools/face_eval.py 重新标定**。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# tools/ 位于 <repo>/software/atri/tools/ 下：上溯 3 层才是仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "software" / "atri"))

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
DEFAULT_DB = REPO_ROOT / "software" / "atri" / "config" / "face_db.json"
DEFAULT_MODELS = REPO_ROOT / "models"


def build_default_recognizer(models_dir: Path):
    from atri.perception.faces import SFaceEmbedder, YuNetDetector

    yunet = models_dir / "face_detection_yunet_2023mar.onnx"
    sface = models_dir / "face_recognition_sface_2021dec.onnx"
    for path in (yunet, sface):
        if not path.exists():
            raise SystemExit(f"缺少模型 {path}，请先运行： python software/atri/tools/fetch_models.py")
    return YuNetDetector(str(yunet)), SFaceEmbedder(str(sface))


def load_image(path: Path) -> Any:
    import cv2
    import numpy as np

    data = np.fromfile(str(path), dtype=np.uint8)
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"解码失败: {path}")
    return frame


def embed_frame(detector: Any, embedder: Any, frame: Any) -> Any:
    boxes = detector.detect(frame)
    if not boxes:
        raise ValueError("未检出人脸")
    box = max(boxes, key=lambda b: b.area)
    return embedder.embed(embedder.crop(frame, box))


def collect_from_dir(root: Path) -> Dict[str, List[Path]]:
    people: Dict[str, List[Path]] = {}
    for person_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        images = sorted(p for p in person_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
        if images:
            people[person_dir.name] = images
    return people


def collect_from_lfw(parquet: Path, names: List[str], per_name: int) -> Dict[str, List[Tuple[str, bytes]]]:
    import json

    import pyarrow.parquet as pq

    table = pq.read_table(parquet, columns=["label", "image"])
    raw = (table.schema.metadata or {}).get(b"huggingface")
    label_names = json.loads(raw.decode())["info"]["features"]["label"]["names"] if raw else []
    labels = table.column("label").to_pylist()
    images = table.column("image").to_pylist()

    wanted = set(names)
    out: Dict[str, List[Tuple[str, bytes]]] = {n: [] for n in names}
    for label, item in zip(labels, images):
        if not (0 <= label < len(label_names)):
            continue
        name = label_names[label]
        if name in wanted and len(out[name]) < per_name:
            out[name].append((item["path"], item["bytes"]))
    return {k: v for k, v in out.items() if v}


def decode_bytes(jpeg: bytes) -> Any:
    import cv2
    import numpy as np

    return cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)


def capture_from_camera(name: str, shots: int, save_dir: Optional[Path], index: int) -> List[Any]:
    """现场采集。按回车拍一张，q 退出。采集的图只写到 --save-images 指定的本地目录。"""
    import cv2

    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        raise SystemExit(
            f"打不开摄像头 index={index}。macOS 需在 系统设置→隐私与安全性→摄像头 授权给终端。"
        )
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)

    frames: List[Any] = []
    print(f"开始采集 {name}：每按一次回车拍一张，共 {shots} 张；输入 q 回车结束。")
    try:
        while len(frames) < shots:
            ok, frame = cap.read()
            if not ok:
                print("读取失败，跳过一帧")
                continue
            cmd = input(f"  [{len(frames)+1}/{shots}] 回车=拍摄, q=结束 > ").strip().lower()
            if cmd == "q":
                break
            frames.append(frame)
            if save_dir:
                path = save_dir / f"{name}_{len(frames):02d}.jpg"
                cv2.imwrite(str(path), frame)
                print(f"    已存 {path}")
            else:
                print("    已采集（未落盘）")
    finally:
        cap.release()
    return frames


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="注册人脸并生成人脸库")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-dir", help="图片目录（每身份一个子目录）")
    src.add_argument("--from-lfw", help="LFW parquet 数据集")
    src.add_argument("--camera", action="store_true", help="用摄像头现场采集")

    parser.add_argument("--db", default=str(DEFAULT_DB), help="输出人脸库路径")
    parser.add_argument("--models", default=str(DEFAULT_MODELS))
    parser.add_argument("--append", action="store_true", help="追加到已存在的库（默认覆盖）")
    parser.add_argument("--threshold", type=float, default=None, help="覆盖阈值（默认沿用库里的）")
    parser.add_argument("--names", default="", help="--from-lfw 时的身份名单，逗号分隔")
    parser.add_argument("--per-name", type=int, default=5, help="每人注册几张")
    parser.add_argument("--name", default=None, help="--camera 时的姓名")
    parser.add_argument("--shots", type=int, default=5, help="--camera 时拍几张")
    parser.add_argument("--save-images", default=None, help="--camera 时把原图存到这个本地目录")
    parser.add_argument("--camera-index", type=int, default=0)
    args = parser.parse_args(argv)

    from atri.perception.faces import FaceDB

    detector, embedder = build_default_recognizer(Path(args.models))

    db_file = Path(args.db)
    if args.append and db_file.exists():
        db = FaceDB.load(db_file)
        print(f"追加模式：已有 {len(db.names)} 人 / {len(db)} 条向量")
    else:
        threshold = args.threshold
        if threshold is None:
            threshold = FaceDB.load(db_file).threshold if db_file.exists() else 0.278
            print(f"沿用现有阈值 {threshold}（用 --threshold 可覆盖）")
        db = FaceDB(embedder="sface", dim=embedder.dim, threshold=threshold)

    if args.threshold is not None:
        db.threshold = args.threshold

    # ── 逐身份提取特征
    summary: Dict[str, Dict[str, Any]] = {}

    if args.from_dir:
        root = Path(args.from_dir)
        if not root.is_dir():
            raise SystemExit(f"目录不存在: {root}")
        people = collect_from_dir(root)
        if not people:
            raise SystemExit(f"{root} 下没有找到「子目录/图片」结构")
        for name, paths in people.items():
            vectors, used, failed = [], [], []
            for path in paths:
                try:
                    vectors.append(embed_frame(detector, embedder, load_image(path)))
                    used.append(str(path))
                except Exception as exc:
                    failed.append(f"{path.name}: {exc}")
            if vectors:
                db.enroll(name, vectors, meta={"source": "dir", "n": len(vectors)})
            summary[name] = {"ok": len(vectors), "failed": failed, "used": used}

    elif args.from_lfw:
        names = [n.strip() for n in args.names.split(",") if n.strip()]
        if not names:
            raise SystemExit("--from-lfw 需要 --names 指定身份")
        people = collect_from_lfw(Path(args.from_lfw), names, args.per_name)
        for name, items in people.items():
            vectors, used, failed = [], [], []
            for path, jpeg in items:
                try:
                    vectors.append(embed_frame(detector, embedder, decode_bytes(jpeg)))
                    used.append(path)
                except Exception as exc:
                    failed.append(f"{path}: {exc}")
            if vectors:
                db.enroll(name, vectors, meta={"source": "LFW", "n": len(vectors)})
            summary[name] = {"ok": len(vectors), "failed": failed, "used": used}

    else:
        if not args.name:
            raise SystemExit("--camera 需要 --name 指定姓名")
        save_dir = Path(args.save_images) if args.save_images else None
        frames = capture_from_camera(args.name, args.shots, save_dir, args.camera_index)
        vectors, failed = [], []
        for i, frame in enumerate(frames, 1):
            try:
                vectors.append(embed_frame(detector, embedder, frame))
            except Exception as exc:
                failed.append(f"第 {i} 张: {exc}")
        if vectors:
            db.enroll(args.name, vectors, meta={"source": "camera", "n": len(vectors)})
        summary[args.name] = {"ok": len(vectors), "failed": failed, "used": []}

    # ── 报告
    print("\n注册结果：")
    for name, stat in summary.items():
        print(f"  {name}: 成功 {stat['ok']} 张" + (f"，失败 {len(stat['failed'])} 张" if stat["failed"] else ""))
        for item in stat["failed"][:5]:
            print(f"      ✗ {item}")

    if not db.people:
        print("\n没有任何人注册成功，未写库。", file=sys.stderr)
        return 2

    db.save(db_file)
    print(f"\n人脸库已写入: {db_file}")
    print(f"  人数 {len(db.names)} / 向量 {len(db)} / 维度 {db.dim} / 阈值 {db.threshold}")
    print("  ⚠ 只写入了特征向量与姓名，未写入任何原图。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
