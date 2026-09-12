#!/usr/bin/env python3
"""拉取人脸 / 二维码模型并校验 sha256。

模型不入 git（二进制会永久污染历史），改为按需拉取 + 哈希校验。
哈希不匹配就**直接失败**，不覆盖本地文件：宁可停下，也不要用一个来路不明的模型。

用法：
    python software/atri/tools/fetch_models.py              # 全部拉到 <repo>/models/
    python software/atri/tools/fetch_models.py --only face  # 只拉人脸
    python software/atri/tools/fetch_models.py --only qr    # 只拉二维码
    python software/atri/tools/fetch_models.py --check      # 只校验已有文件，不下载
    python software/atri/tools/fetch_models.py --dir /tmp/m # 指定模型根目录

## 为什么每个模型有多个 URL

本机实测（2026-09-12）：GitHub 对同一仓库里两类文件的响应路径不同——

- **LFS 文件**（``.caffemodel`` / ``.sface.onnx`` 等）：``github.com/.../raw/`` 会 302 到
  ``media.githubusercontent.com``，这条**通**；
- **普通文件**（``.prototxt`` 等）：``github.com/.../raw/`` 会 302 到
  ``raw.githubusercontent.com``，这条在本机**不通**，但 GitHub API 的
  ``Accept: application/vnd.github.raw`` 能直接取到内容。

所以就按顺序试：哪个先通过 sha256 校验就用哪个。**下载被截断是最常见的失败模式**
（曾把 37 MB 的 SFace 下成 438 KB，还差点误判成"模型有问题"），
所以每个 URL 失败后都会换下一个再试，而不是直接放弃。
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, NamedTuple, Sequence

# tools/ 位于 <repo>/software/atri/tools/ 下：上溯 3 层才是仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DIR = REPO_ROOT / "models"

ZOO_RAW = "https://github.com/opencv/opencv_zoo/raw/main/models"
ZOO_API = "https://api.github.com/repos/opencv/opencv_zoo/contents/models"


class Model(NamedTuple):
    filename: str
    subdir: str          # 相对模型根目录的子目录（空串=根目录）
    urls: Sequence[str]  # 按顺序尝试
    sha256: str
    size: int
    group: str           # face / qr
    purpose: str


def _zoo_urls(zoo_subdir: str, filename: str) -> Sequence[str]:
    """同一个文件的两种取法：raw 域优先，失败后退到 API 直取。"""
    return (
        f"{ZOO_RAW}/{zoo_subdir}/{filename}",
        f"{ZOO_API}/{zoo_subdir}/{filename}",
    )


MODELS: List[Model] = [
    # ── 人脸（T-01）──────────────────────────────────────────────
    Model(
        filename="face_detection_yunet_2023mar.onnx",
        subdir="",
        urls=_zoo_urls("face_detection_yunet", "face_detection_yunet_2023mar.onnx"),
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        size=232589,
        group="face",
        purpose="人脸检测（YuNet）",
    ),
    Model(
        filename="face_recognition_sface_2021dec.onnx",
        subdir="",
        urls=_zoo_urls("face_recognition_sface", "face_recognition_sface_2021dec.onnx"),
        sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        size=38696353,
        group="face",
        purpose="人脸特征提取（SFace, 128 维）",
    ),
    # ── 二维码（T-02）────────────────────────────────────────────
    # 文件名保留官方 _2021nov 版本号；四个文件共约 1 MB。
    Model(
        filename="detect_2021nov.prototxt",
        subdir="wechat_qrcode",
        urls=_zoo_urls("qrcode_wechatqrcode", "detect_2021nov.prototxt"),
        sha256="e8acfc395caf443a47f15686a9b9207b36cb8f7e6ceb8fbaf6466665e68a9466",
        size=42656,
        group="qr",
        purpose="二维码检测网络结构（WeChatQRCode）",
    ),
    Model(
        filename="detect_2021nov.caffemodel",
        subdir="wechat_qrcode",
        urls=_zoo_urls("qrcode_wechatqrcode", "detect_2021nov.caffemodel"),
        sha256="cc49b8c9babaf45f3037610fe499df38c8819ebda29e90ca9f2e33270f6ef809",
        size=965430,
        group="qr",
        purpose="二维码检测网络权重（WeChatQRCode）",
    ),
    Model(
        filename="sr_2021nov.prototxt",
        subdir="wechat_qrcode",
        urls=_zoo_urls("qrcode_wechatqrcode", "sr_2021nov.prototxt"),
        sha256="8ae41acba97e8b4a8e741ee350481e49b8e01d787193f470a4c95ee1c02d5b61",
        size=5984,
        group="qr",
        purpose="二维码超分网络结构（WeChatQRCode）",
    ),
    Model(
        filename="sr_2021nov.caffemodel",
        subdir="wechat_qrcode",
        urls=_zoo_urls("qrcode_wechatqrcode", "sr_2021nov.caffemodel"),
        sha256="e5d36889d8e6ef2f1c1f515f807cec03979320ac81792cd8fb927c31fd658ae3",
        size=23929,
        group="qr",
        purpose="二维码超分网络权重（WeChatQRCode）",
    ),
]

TIMEOUT_S = 120


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
            print("      → 实际更小：多半是下载被超时/断流截断了，重跑本脚本即可")
    return ok


def _fetch(url: str, target: Path) -> None:
    """下载单个 URL。API 那条路需要 raw 的 Accept 头，否则返回 base64 JSON。"""
    request = urllib.request.Request(url)
    if "api.github.com" in url:
        request.add_header("Accept", "application/vnd.github.raw")
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp, target.open("wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)


def download(path: Path, model: Model) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  {model.purpose}: {model.size/1048576:.2f} MB")
    errors: List[str] = []
    for index, url in enumerate(model.urls, 1):
        tmp = path.with_suffix(path.suffix + f".part{index}")
        host = url.split("/")[2]
        try:
            print(f"    尝试 {index}/{len(model.urls)}: {host} …", flush=True)
            _fetch(url, tmp)
        except Exception as exc:
            errors.append(f"{host}: {type(exc).__name__}: {exc}")
            print(f"      下载失败：{type(exc).__name__}: {str(exc)[:80]}")
            if tmp.exists():
                tmp.unlink()
            continue
        if verify(tmp, model):
            tmp.replace(path)
            return True
        errors.append(f"{host}: sha256/大小校验失败")
        tmp.unlink()

    print("    ✗ 所有来源均失败：")
    for item in errors:
        print(f"        - {item}")
    return False


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="拉取并校验人脸 / 二维码模型")
    parser.add_argument("--dir", default=str(DEFAULT_DIR), help="模型根目录")
    parser.add_argument("--only", choices=["face", "qr"], default=None, help="只处理某一组")
    parser.add_argument("--check", action="store_true", help="只校验，不下载")
    parser.add_argument("--force", action="store_true", help="即使已存在也重新下载")
    args = parser.parse_args(argv)

    root = Path(args.dir)
    root.mkdir(parents=True, exist_ok=True)
    selected = [m for m in MODELS if args.only is None or m.group == args.only]

    print(f"模型根目录: {root}")
    print(f"来源: {ZOO_RAW}")
    print(f"待处理: {len(selected)} 个（{args.only or 'face + qr'}）")

    results: Dict[str, bool] = {}
    for model in selected:
        path = root / model.subdir / model.filename if model.subdir else root / model.filename
        print(f"\n[{model.group}] {model.filename}")
        if args.check or (path.exists() and not args.force):
            results[model.filename] = verify(path, model)
            if args.check:
                continue
            if results[model.filename]:
                continue
        results[model.filename] = download(path, model)

    ok = all(results.values())
    if ok:
        print(f"\n全部就绪 ✓（{len(results)} 个文件）")
    else:
        bad = [name for name, good in results.items() if not good]
        print(f"\n有文件不可用 ✗：{', '.join(bad)}", file=sys.stderr)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
