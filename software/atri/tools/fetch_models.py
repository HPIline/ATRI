#!/usr/bin/env python3
"""拉取人脸模型并校验 sha256。

模型不入 git（37 MB 二进制会永久污染历史），改为按需拉取 + 哈希校验。
哈希不匹配就**直接失败**，不覆盖本地文件：宁可停下，也不要用一个来路不明的模型。

用法：
    python software/atri/tools/fetch_models.py            # 拉到 <repo>/models/
    python software/atri/tools/fetch_models.py --dir /tmp/m   # 指定目录
    python software/atri/tools/fetch_models.py --check     # 只校验已有文件，不下载
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, NamedTuple

# tools/ 位于 <repo>/software/atri/tools/ 下：上溯 3 层才是仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DIR = REPO_ROOT / "models"

ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"


class Model(NamedTuple):
    filename: str
    url: str
    sha256: str
    size: int
    purpose: str


MODELS: List[Model] = [
    Model(
        filename="face_detection_yunet_2023mar.onnx",
        url=f"{ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        size=232589,
        purpose="人脸检测（YuNet）",
    ),
    Model(
        filename="face_recognition_sface_2021dec.onnx",
        url=f"{ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        size=38696353,
        purpose="人脸特征提取（SFace, 128 维）",
    ),
]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, model: Model) -> bool:
    if not path.exists():
        print(f"  ✗ {model.filename} 不存在")
        return False
    actual_size = path.stat().st_size
    actual_hash = sha256_of(path)
    ok = actual_hash == model.sha256
    mark = "✓" if ok else "✗"
    print(f"  {mark} {model.filename}  {actual_size} B  sha256={actual_hash[:16]}…")
    if not ok:
        print(f"      期望 sha256={model.sha256}")
        print(f"      期望大小={model.size} B（实际 {actual_size} B）")
        if actual_size < model.size:
            print("      → 实际更小：多半是下载被超时/断流截断了，删掉重下即可")
    return ok


def download(path: Path, model: Model) -> bool:
    tmp = path.with_suffix(path.suffix + ".part")
    print(f"  下载 {model.filename}（{model.size/1048576:.1f} MB）…")
    try:
        with urllib.request.urlopen(model.url, timeout=60) as resp, tmp.open("wb") as out:
            total = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                total += len(chunk)
                if total % (8 << 20) < (1 << 20):
                    print(f"    {total/1048576:.1f} MB …", flush=True)
    except Exception as exc:
        print(f"  ✗ 下载失败: {exc}")
        if tmp.exists():
            tmp.unlink()
        return False

    if not verify(tmp, model):
        tmp.unlink()
        print("  ✗ 校验失败，已删除不完整文件")
        return False
    tmp.replace(path)
    return True


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="拉取并校验人脸模型")
    parser.add_argument("--dir", default=str(DEFAULT_DIR), help="模型目录")
    parser.add_argument("--check", action="store_true", help="只校验，不下载")
    parser.add_argument("--force", action="store_true", help="即使已存在也重新下载")
    args = parser.parse_args(argv)

    target_dir = Path(args.dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    print(f"模型目录: {target_dir}")
    print(f"来源: {ZOO}")

    results: Dict[str, bool] = {}
    for model in MODELS:
        path = target_dir / model.filename
        print(f"\n[{model.purpose}]")
        if path.exists() and not args.force:
            results[model.filename] = verify(path, model)
            continue
        if args.check:
            results[model.filename] = verify(path, model)
            continue
        results[model.filename] = download(path, model)

    ok = all(results.values())
    print("\n" + ("全部就绪 ✓" if ok else "有模型不可用 ✗"))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
