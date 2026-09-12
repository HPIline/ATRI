#!/usr/bin/env python3
"""T-01 人脸识别评测：在 LFW 上量出真实成功率。

为什么不是一个数字：
1. **阈值必须先标定再评测。** 标定用**另一批身份**（不在识别测试集里）的配对相似度求 EER，
   避免"用测试集自己调阈值再拿同一批测"这种自己给自己发奖的做法。
2. **画廊规模会决定难度。** 认 5 个人和认 50 个人不是一件事，所以出规模扫描曲线，
   而不是只报一个好看的数字。
3. **检测和识别要分开报。** 检测不到脸 → 自然也识别不了，两者混在一起会掩盖问题。

用法：
    .venv-face/bin/python software/atri/tools/face_eval.py \\
        --dataset 本地数据/faces/lfw_data.parquet \\
        --report design/handoff/T-01-LFW评测报告.md \\
        --json design/results/t01_face_eval.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# tools/ 位于 <repo>/software/atri/tools/ 下：上溯 3 层才是仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
SOFTWARE_ROOT = REPO_ROOT / "software" / "atri"
sys.path.insert(0, str(SOFTWARE_ROOT))

from atri.perception.faces import (  # noqa: E402
    FaceDB,
    FaceRecognizer,
    HaarDetector,
    SFaceEmbedder,
    YuNetDetector,
)

DEFAULT_MODELS = REPO_ROOT / "models"
DEFAULT_ENROLL_PER_PERSON = 5
DEFAULT_TEST_PER_PERSON = 10
CALIB_GENUINE_SEED = 20260912


# ────────────────────────── 数据加载 ──────────────────────────


@dataclass
class LFWImage:
    name: str
    path: str
    jpeg: bytes


def load_lfw(dataset: Path, min_images: int = 15) -> Dict[str, List[LFWImage]]:
    """读 LFW parquet，按身份分组（每组按文件名升序，保证划分确定性）。"""
    import pyarrow.parquet as pq

    table = pq.read_table(dataset, columns=["label", "image"])
    meta = table.schema.metadata or {}
    label_names: Optional[List[str]] = None
    raw_meta = meta.get(b"huggingface")
    if raw_meta:
        try:
            info = json.loads(raw_meta.decode("utf-8"))["info"]["features"]["label"]
            label_names = list(info["names"])
        except Exception:
            label_names = None

    labels = table.column("label").to_pylist()
    images = table.column("image").to_pylist()

    groups: Dict[str, List[LFWImage]] = defaultdict(list)
    for label, item in zip(labels, images):
        name = label_names[label] if label_names and 0 <= label < len(label_names) else f"id{label}"
        groups[name].append(LFWImage(name=name, path=item["path"], jpeg=item["bytes"]))

    for name in groups:
        groups[name].sort(key=lambda x: x.path)
    return {name: items for name, items in groups.items() if len(items) >= min_images}


def decode(jpeg: bytes) -> Any:
    import cv2

    arr = np.frombuffer(jpeg, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("JPEG 解码失败")
    return img


def split_items(
    items: List[LFWImage],
    enroll_n: int,
    test_n: int,
    mode: str = "sequential",
    seed: int = 0,
) -> Tuple[List[LFWImage], List[LFWImage]]:
    """把某个身份的图片划成 (注册集, 测试集)。

    sequential：前 N 张注册、接着 M 张测试。**注意这是最松的划分**——
    LFW 里同一人的文件名往往按拍摄场次连号，"前 5 张"和"后 10 张"常常来自
    同一次连拍，长得几乎一样，会显著高估准确率。
    random：固定种子随机划分，打破连号邻接，是对现实的更保守近似。
    """
    if mode == "random":
        rng = random.Random(seed)
        idx = list(range(len(items)))
        rng.shuffle(idx)
        enroll_idx = sorted(idx[:enroll_n])
        test_idx = sorted(idx[enroll_n : enroll_n + test_n])
        return [items[i] for i in enroll_idx], [items[i] for i in test_idx]
    return items[:enroll_n], items[enroll_n : enroll_n + test_n]


# ────────────────────────── 阈值标定 ──────────────────────────


@dataclass
class Calibration:
    threshold: float
    eer: float
    fmr_at_threshold: float
    fnmr_at_threshold: float
    genuine_mean: float
    genuine_std: float
    impostor_mean: float
    impostor_std: float
    curve: List[Tuple[float, float, float]] = field(default_factory=list)
    n_genuine: int = 0
    n_impostor: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "threshold": round(self.threshold, 4),
            "eer": round(self.eer, 4),
            "fmr_at_threshold": round(self.fmr_at_threshold, 4),
            "fnmr_at_threshold": round(self.fnmr_at_threshold, 4),
            "genuine_mean": round(self.genuine_mean, 4),
            "genuine_std": round(self.genuine_std, 4),
            "impostor_mean": round(self.impostor_mean, 4),
            "impostor_std": round(self.impostor_std, 4),
            "n_genuine": self.n_genuine,
            "n_impostor": self.n_impostor,
        }


def calibrate(
    embed,
    identities: Sequence[str],
    groups: Dict[str, List[LFWImage]],
    per_person: int = 10,
    seed: int = CALIB_GENUINE_SEED,
) -> Calibration:
    """在**独立身份池**上标定阈值：同人配对 vs 异人配对 → EER。

    embed: 传入 image → vector 的函数（已包好检测+对齐+特征）
    """
    vectors: Dict[str, List[np.ndarray]] = {}
    for name in identities:
        vecs = []
        for img in groups[name][:per_person]:
            try:
                vecs.append(embed(decode(img.jpeg)))
            except Exception:
                continue
        if len(vecs) >= 2:
            vectors[name] = vecs

    genuine: List[float] = []
    for vecs in vectors.values():
        for i in range(len(vecs)):
            for j in range(i + 1, len(vecs)):
                genuine.append(float(vecs[i] @ vecs[j]))

    names = sorted(vectors)
    rng = random.Random(seed)
    impostor: List[float] = []
    if len(names) >= 2:
        target = max(len(genuine), 200)
        guard = 0
        while len(impostor) < target and guard < target * 50:
            guard += 1
            a, b = rng.sample(names, 2)
            va = vectors[a][rng.randrange(len(vectors[a]))]
            vb = vectors[b][rng.randrange(len(vectors[b]))]
            impostor.append(float(va @ vb))

    if not genuine or not impostor:
        raise RuntimeError("标定失败：genuine/impostor 配对不足")

    gen = np.asarray(genuine)
    imp = np.asarray(impostor)
    curve: List[Tuple[float, float, float]] = []
    best = None
    for t in np.arange(-0.2, 0.999, 0.002):
        fmr = float((imp >= t).mean())
        fnmr = float((gen < t).mean())
        curve.append((float(t), fmr, fnmr))
        gap = abs(fmr - fnmr)
        if best is None or gap < best[0]:
            best = (gap, float(t), fmr, fnmr)

    assert best is not None
    _, threshold, fmr, fnmr = best
    return Calibration(
        threshold=threshold,
        eer=(fmr + fnmr) / 2.0,
        fmr_at_threshold=fmr,
        fnmr_at_threshold=fnmr,
        genuine_mean=float(gen.mean()),
        genuine_std=float(gen.std()),
        impostor_mean=float(imp.mean()),
        impostor_std=float(imp.std()),
        curve=curve,
        n_genuine=len(genuine),
        n_impostor=len(impostor),
    )


# ────────────────────────── 识别评测 ──────────────────────────


@dataclass
class IdentificationResult:
    gallery: List[str]
    enroll_per_person: int
    test_per_person: int
    total: int = 0
    detected: int = 0
    correct: int = 0
    rejected: int = 0
    wrong: int = 0
    per_person: Dict[str, Dict[str, int]] = field(default_factory=dict)
    confusion: Dict[str, Counter] = field(default_factory=dict)
    similarities_correct: List[float] = field(default_factory=list)
    similarities_wrong: List[float] = field(default_factory=list)
    detect_ms: List[float] = field(default_factory=list)
    embed_ms: List[float] = field(default_factory=list)

    @property
    def detection_rate(self) -> float:
        return self.detected / self.total if self.total else 0.0

    @property
    def rank1_accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def accuracy_when_detected(self) -> float:
        return self.correct / self.detected if self.detected else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gallery": self.gallery,
            "gallery_size": len(self.gallery),
            "enroll_per_person": self.enroll_per_person,
            "test_per_person": self.test_per_person,
            "total": self.total,
            "detected": self.detected,
            "detection_rate": round(self.detection_rate, 4),
            "correct": self.correct,
            "wrong": self.wrong,
            "rejected": self.rejected,
            "rank1_accuracy": round(self.rank1_accuracy, 4),
            "accuracy_when_detected": round(self.accuracy_when_detected, 4),
            "per_person": self.per_person,
            "confusion": {k: dict(v) for k, v in self.confusion.items()},
            "similarity_correct_mean": round(float(np.mean(self.similarities_correct)), 4)
            if self.similarities_correct
            else None,
            "similarity_wrong_mean": round(float(np.mean(self.similarities_wrong)), 4)
            if self.similarities_wrong
            else None,
            "detect_ms_mean": round(float(np.mean(self.detect_ms)), 2) if self.detect_ms else None,
            "embed_ms_mean": round(float(np.mean(self.embed_ms)), 2) if self.embed_ms else None,
        }


def stable_seed(name: str) -> int:
    """稳定的字符串→整数（Python 内置 hash 对 str 有随机盐，会破坏可复现性）。"""
    import hashlib

    return int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:8], 16)


def evaluate_identification(
    recognizer: FaceRecognizer,
    db: FaceDB,
    groups: Dict[str, List[LFWImage]],
    gallery: Sequence[str],
    enroll_per_person: int,
    test_per_person: int,
    split_mode: str = "sequential",
    split_seed: int = 0,
) -> IdentificationResult:
    result = IdentificationResult(
        gallery=list(gallery),
        enroll_per_person=enroll_per_person,
        test_per_person=test_per_person,
    )

    for name in gallery:
        result.per_person[name] = {"total": 0, "detected": 0, "correct": 0, "wrong": 0, "rejected": 0}
        result.confusion[name] = Counter()

        items = groups[name]
        _, test_items = split_items(
            items, enroll_per_person, test_per_person, split_mode, split_seed + stable_seed(name) % 100000
        )
        for img in test_items:
            result.total += 1
            result.per_person[name]["total"] += 1
            frame = decode(img.jpeg)

            t0 = time.perf_counter()
            boxes = recognizer.detector.detect(frame)
            t1 = time.perf_counter()
            result.detect_ms.append((t1 - t0) * 1000.0)

            if not boxes:
                result.confusion[name]["<未检出>"] += 1
                continue
            result.detected += 1
            result.per_person[name]["detected"] += 1

            box = max(boxes, key=lambda b: b.area)
            try:
                t2 = time.perf_counter()
                vector = recognizer.embedder.embed(recognizer.embedder.crop(frame, box))
                result.embed_ms.append((time.perf_counter() - t2) * 1000.0)
            except Exception:
                result.confusion[name]["<特征失败>"] += 1
                continue

            match = db.match(vector)
            if not match.recognized:
                result.rejected += 1
                result.per_person[name]["rejected"] += 1
                result.confusion[name]["<拒识>"] += 1
                result.similarities_wrong.append(match.similarity)
                continue

            result.confusion[name][match.name or "?"] += 1
            if match.name == name:
                result.correct += 1
                result.per_person[name]["correct"] += 1
                result.similarities_correct.append(match.similarity)
            else:
                result.wrong += 1
                result.per_person[name]["wrong"] += 1
                result.similarities_wrong.append(match.similarity)

    return result


def build_db(
    recognizer: FaceRecognizer,
    groups: Dict[str, List[LFWImage]],
    gallery: Sequence[str],
    enroll_per_person: int,
    threshold: float,
    split_mode: str = "sequential",
    split_seed: int = 0,
) -> FaceDB:
    db = FaceDB(embedder="sface", dim=recognizer.embedder.dim, threshold=threshold)
    for name in gallery:
        vectors = []
        used = []
        enroll_items, _ = split_items(
            groups[name], enroll_per_person, 0, split_mode, split_seed + stable_seed(name) % 100000
        )
        for img in enroll_items:
            frame = decode(img.jpeg)
            boxes = recognizer.detector.detect(frame)
            if not boxes:
                continue
            box = max(boxes, key=lambda b: b.area)
            try:
                vectors.append(recognizer.embedder.embed(recognizer.embedder.crop(frame, box)))
                used.append(img.path)
            except Exception:
                continue
        if vectors:
            db.enroll(name, vectors, meta={"source": "LFW", "images": used})
    return db


# ────────────────────────── 报告 ──────────────────────────


def render_report(
    args: argparse.Namespace,
    calibration: Calibration,
    main_result: IdentificationResult,
    sweep: List[IdentificationResult],
    hard: List[IdentificationResult],
    haar_result: Optional[IdentificationResult],
    platform_info: Dict[str, Any],
    gallery_counts: Dict[str, int],
) -> str:
    def pct(x: float) -> str:
        return f"{x * 100:.1f}%"

    lines: List[str] = []
    lines.append("# T-01 人脸识别 · LFW 实测报告")
    lines.append("")
    lines.append("> 本报告由 `software/atri/tools/face_eval.py` 自动生成，**所有数字均为本机实测**，未做任何手工润色。")
    lines.append("> 方案：`design/handoff/T-01-人脸识别-方案.md`")
    lines.append("")
    lines.append("## 0. 复现命令")
    lines.append("")
    lines.append("```bash")
    lines.append(" ".join(sys.argv))
    lines.append("```")
    lines.append("")

    lines.append("## 1. 环境与配置（可复现口径）")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    for key, value in platform_info.items():
        lines.append(f"| {key} | {value} |")
    lines.append(f"| 检测器 | {args.detector} |")
    lines.append(f"| 特征提取 | SFace（128 维，L2 归一化，余弦相似度） |")
    lines.append(f"| 注册/人 | {main_result.enroll_per_person} 张 |")
    lines.append(f"| 测试/人 | {main_result.test_per_person} 张 |")
    lines.append(f"| 画廊选人 | {args.gallery_select} |")
    lines.append(f"| 注册/测试划分 | {args.split} |")
    lines.append("")
    lines.append("> ⚠️ **选人与划分会显著影响数字。** LFW 里图片最多的人（Bush 530 张等）")
    lines.append("> 是同一批摄影场次的连拍，「前 5 张注册、后 10 张测试」等于用近似重复的图考试，")
    lines.append("> 会高估准确率。第 5 节的**困难协议**（末位选人 + 单张注册 + 随机划分）是更保守的读数，")
    lines.append("> 请以它作为对外口径的下界。")
    lines.append("")

    lines.append("## 2. 阈值标定（用独立身份池，不碰测试集）")
    lines.append("")
    lines.append("标定池身份与识别测试集**完全不重叠**，避免用测试集自己调阈值。")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 同人配对（genuine）数 | {calibration.n_genuine} |")
    lines.append(f"| 异人配对（impostor）数 | {calibration.n_impostor} |")
    lines.append(f"| genuine 相似度 均值±σ | {calibration.genuine_mean:.4f} ± {calibration.genuine_std:.4f} |")
    lines.append(f"| impostor 相似度 均值±σ | {calibration.impostor_mean:.4f} ± {calibration.impostor_std:.4f} |")
    lines.append(f"| **EER** | **{pct(calibration.eer)}** |")
    lines.append(f"| 标定阈值（EER 点） | **{calibration.threshold:.4f}** |")
    lines.append(f"| 该阈值下 FMR / FNMR | {pct(calibration.fmr_at_threshold)} / {pct(calibration.fnmr_at_threshold)} |")
    lines.append("")
    lines.append("> 设计取向：**宁可拒识，不可认错**——报错名字比说\"不认识\"更糟。")
    lines.append("")

    lines.append("## 3. 主结果（5 人画廊）")
    lines.append("")
    lines.append("| 指标 | 实测 | 目标（BOM与阶段性指标.md） | 判定 |")
    lines.append("|---|---|---|---|")
    det_ok = "✅" if main_result.detection_rate >= 0.9 else "❌"
    acc_ok = "✅" if main_result.rank1_accuracy >= 0.9 else "❌"
    lines.append(
        f"| 人脸检测成功率 | {pct(main_result.detection_rate)} "
        f"({main_result.detected}/{main_result.total}) | ≥90% | {det_ok} |"
    )
    lines.append(
        f"| 播报姓名正确率（rank-1） | {pct(main_result.rank1_accuracy)} "
        f"({main_result.correct}/{main_result.total}) | ≥90% | {acc_ok} |"
    )
    lines.append(
        f"| 检出后识别正确率 | {pct(main_result.accuracy_when_detected)} "
        f"({main_result.correct}/{main_result.detected}) | — | — |"
    )
    lines.append(f"| 拒识（相似度不足） | {main_result.rejected} 张 | — | — |")
    lines.append(f"| 认错人 | {main_result.wrong} 张 | — | — |")
    lines.append("")

    lines.append("### 3.1 逐人明细")
    lines.append("")
    lines.append("| 身份 | 测试张数 | 检出 | 正确 | 认错 | 拒识 |")
    lines.append("|---|---|---|---|---|---|")
    for name, stat in main_result.per_person.items():
        lines.append(
            f"| {name} | {stat['total']} | {stat['detected']} | {stat['correct']} | "
            f"{stat['wrong']} | {stat['rejected']} |"
        )
    lines.append("")

    lines.append("### 3.2 混淆矩阵（行=真实身份，列=识别结果）")
    lines.append("")
    cols = list(main_result.gallery) + ["<拒识>", "<未检出>", "<特征失败>"]
    lines.append("| 真实 \\ 识别 | " + " | ".join(cols) + " |")
    lines.append("|" + "---|" * (len(cols) + 1))
    for name in main_result.gallery:
        row = [str(main_result.confusion[name].get(c, 0)) for c in cols]
        lines.append(f"| **{name}** | " + " | ".join(row) + " |")
    lines.append("")

    lines.append("## 4. 画廊规模扫描（难度随人数上升）")
    lines.append("")
    lines.append("| 画廊人数 | 测试张数 | 检测成功率 | rank-1 正确率 | 认错 | 拒识 |")
    lines.append("|---|---|---|---|---|---|")
    for res in sweep:
        lines.append(
            f"| {len(res.gallery)} | {res.total} | {pct(res.detection_rate)} | "
            f"{pct(res.rank1_accuracy)} | {res.wrong} | {res.rejected} |"
        )
    lines.append("")

    if hard:
        lines.append("## 5. 困难协议（末位选人 + 单张注册 + 随机划分）")
        lines.append("")
        lines.append("这一节才是**对外该引用的保守读数**：")
        lines.append("")
        lines.append("- **末位选人**：挑 LFW 里图片最少的人（≥15 张），不是连拍大户；")
        lines.append("- **单张注册**：每人只注册 1 张 —— 接近「现场只登记一次」的现实；")
        lines.append("- **随机划分**：注册与测试图随机分，打破文件名连号带来的同场次泄漏。")
        lines.append("")
        lines.append("| 画廊人数 | 注册/人 | 测试张数 | 检测成功率 | rank-1 正确率 | 认错 | 拒识 |")
        lines.append("|---|---|---|---|---|---|---|")
        for res in hard:
            lines.append(
                f"| {len(res.gallery)} | {res.enroll_per_person} | {res.total} | "
                f"{pct(res.detection_rate)} | {pct(res.rank1_accuracy)} | {res.wrong} | {res.rejected} |"
            )
        lines.append("")

    section = 6 if hard else 5
    if haar_result is not None:
        lines.append(f"## {section}. 检测器对照：YuNet vs Haar（同一批测试图）")
        lines.append("")
        lines.append("| 检测器 | 检出率 | rank-1 正确率 | 备注 |")
        lines.append("|---|---|---|---|")
        lines.append(
            f"| YuNet | {pct(main_result.detection_rate)} | {pct(main_result.rank1_accuracy)} | 主力 |"
        )
        lines.append(
            f"| Haar | {pct(haar_result.detection_rate)} | {pct(haar_result.rank1_accuracy)} | "
            "对照组，无关键点、只认正脸 |"
        )
        lines.append("")

    lines.append(f"## {section + 1}. 性能（本机，非目标平台）")
    lines.append("")
    if main_result.detect_ms:
        lines.append(
            f"- 检测：均值 {np.mean(main_result.detect_ms):.1f} ms，"
            f"中位 {np.median(main_result.detect_ms):.1f} ms（n={len(main_result.detect_ms)}）"
        )
    if main_result.embed_ms:
        lines.append(
            f"- 特征提取：均值 {np.mean(main_result.embed_ms):.1f} ms，"
            f"中位 {np.median(main_result.embed_ms):.1f} ms（n={len(main_result.embed_ms)}）"
        )
    lines.append("")
    lines.append("> ⚠️ 这是**开发机**数字，**不是**树莓派 4B 的数字。目标平台帧率**未测**。")
    lines.append("")

    lines.append(f"## {section + 2}. 口径声明（不可省）")
    lines.append("")
    lines.append("- 本报告的 rank-1 是 **identification（闭集识别）** 协议。")
    lines.append("  opencv_zoo 公布的 SFace LFW 准确率 **99.60%** 是 **verification（配对验证）** 协议，")
    lines.append("  **两者协议不同，数字不可直接对比**。")
    lines.append("- 阈值标定池与识别测试集身份不重叠；但两者同来自 LFW，**同分布**。")
    lines.append("  换到自采集数据（不同相机、光照、距离）表现**不能由本报告外推**。—— 未测。")
    lines.append("- 距离档（0.5/1.0/1.5 m）**未测**：LFW 无距离信息。")
    lines.append("")
    lines.append(f"## {section + 3}. 画廊身份与图片数")
    lines.append("")
    lines.append("| 身份 | LFW 总图片数 |")
    lines.append("|---|---|")
    for name, count in gallery_counts.items():
        lines.append(f"| {name} | {count} |")
    lines.append("")
    return "\n".join(lines)


# ────────────────────────── 主流程 ──────────────────────────


def build_detector(kind: str, models_dir: Path):
    if kind == "haar":
        return HaarDetector()
    return YuNetDetector(str(models_dir / "face_detection_yunet_2023mar.onnx"))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="T-01 人脸识别 LFW 评测")
    parser.add_argument("--dataset", default=str(REPO_ROOT / "本地数据" / "faces" / "lfw_data.parquet"))
    parser.add_argument("--models", default=str(DEFAULT_MODELS))
    parser.add_argument("--report", default=None, help="markdown 报告输出路径")
    parser.add_argument("--json", default=None, help="机器可读结果输出路径")
    parser.add_argument("--detector", default="yunet", choices=["yunet", "haar"])
    parser.add_argument("--gallery-size", type=int, default=5, help="主结果画廊人数")
    parser.add_argument("--enroll", type=int, default=DEFAULT_ENROLL_PER_PERSON)
    parser.add_argument("--test-per-person", type=int, default=DEFAULT_TEST_PER_PERSON)
    parser.add_argument("--sweep", default="2,5,10,20", help="画廊规模扫描，逗号分隔；空串关闭")
    parser.add_argument("--calib-people", type=int, default=20, help="标定池身份数")
    parser.add_argument("--min-images", type=int, default=15)
    parser.add_argument(
        "--gallery-select",
        default="top",
        choices=["top", "bottom", "random"],
        help="画廊选人方式：top=图片最多的人（最易，LFW 里这些人是连拍大户）；"
        "bottom=图片最少的人（较难）；random=固定种子随机",
    )
    parser.add_argument(
        "--split",
        default="sequential",
        choices=["sequential", "random"],
        help="注册/测试划分：sequential=前N张注册后M张测试（同场次连拍，偏松）；random=随机划分",
    )
    parser.add_argument("--split-seed", type=int, default=0)
    parser.add_argument(
        "--hard",
        action="store_true",
        help="额外跑一遍困难协议：末位选人 + 单张注册 + 随机划分（更接近现场注册一次的现实）",
    )
    parser.add_argument("--hard-sweep", default="5,20,50", help="困难协议的画廊规模扫描")
    parser.add_argument("--compare-haar", action="store_true", help="额外跑一遍 Haar 检测器对照")
    args = parser.parse_args(argv)

    dataset = Path(args.dataset)
    if not dataset.exists():
        print(f"数据集不存在: {dataset}", file=sys.stderr)
        return 2
    models_dir = Path(args.models)

    import cv2
    import platform as _platform

    groups = load_lfw(dataset, min_images=args.min_images)
    ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    print(f"LFW: {sum(len(v) for v in groups.values())} 张 / {len(groups)} 人（每人 ≥{args.min_images} 张）")

    needed = max(args.gallery_size, max([int(x) for x in args.sweep.split(",") if x.strip()] or [0])) \
        + args.calib_people
    if len(ranked) < needed:
        print(f"身份数不足：需要 {needed}，只有 {len(ranked)}", file=sys.stderr)
        return 2

    max_gallery = max(args.gallery_size, max([int(x) for x in args.sweep.split(",") if x.strip()] or [0]))
    eligible = [name for name, _ in ranked]
    if args.gallery_select == "bottom":
        select_pool = list(reversed(eligible))
    elif args.gallery_select == "random":
        select_pool = list(eligible)
        random.Random(args.split_seed).shuffle(select_pool)
    else:
        select_pool = list(eligible)
    gallery_pool = select_pool[:max_gallery]
    used = set(gallery_pool)
    calib_pool = [n for n in eligible if n not in used][: args.calib_people]

    main_gallery = gallery_pool[: args.gallery_size]
    print(f"主画廊（{len(main_gallery)} 人）: " + ", ".join(main_gallery))
    print(f"标定池（{len(calib_pool)} 人）: " + ", ".join(calib_pool[:5]) + " …")

    embedder = SFaceEmbedder(str(models_dir / "face_recognition_sface_2021dec.onnx"))
    detector = build_detector(args.detector, models_dir)

    # ── 阈值标定（独立身份池）
    probe = FaceRecognizer(detector=detector, embedder=embedder, db=None)

    def embed_image(frame):
        boxes = probe.detector.detect(frame)
        if not boxes:
            raise RuntimeError("未检出人脸")
        box = max(boxes, key=lambda b: b.area)
        return probe.embedder.embed(probe.embedder.crop(frame, box))

    print("标定阈值中（独立身份池）…")
    calibration = calibrate(embed_image, calib_pool, groups, per_person=10)
    print(f"  EER={calibration.eer*100:.2f}%  阈值={calibration.threshold:.4f}")

    # ── 主结果
    print(f"评测主画廊（{len(main_gallery)} 人）…")
    db = build_db(
        probe, groups, main_gallery, args.enroll, calibration.threshold, args.split, args.split_seed
    )
    main_result = evaluate_identification(
        probe, db, groups, main_gallery, args.enroll, args.test_per_person, args.split, args.split_seed
    )
    print(
        f"  检测 {main_result.detection_rate*100:.1f}% | "
        f"rank-1 {main_result.rank1_accuracy*100:.1f}% | "
        f"拒识 {main_result.rejected} | 认错 {main_result.wrong}"
    )

    # ── 规模扫描
    sweep_results: List[IdentificationResult] = []
    if args.sweep.strip():
        for k in sorted({int(x) for x in args.sweep.split(",") if x.strip()}):
            if k > len(gallery_pool):
                continue
            sub = gallery_pool[:k]
            sub_db = build_db(
                probe, groups, sub, args.enroll, calibration.threshold, args.split, args.split_seed
            )
            res = evaluate_identification(
                probe, sub_db, groups, sub, args.enroll, args.test_per_person, args.split, args.split_seed
            )
            sweep_results.append(res)
            print(f"  画廊 {k:>3} 人 → rank-1 {res.rank1_accuracy*100:.1f}%  检出 {res.detection_rate*100:.1f}%")

    # ── 困难协议：末位选人 + 单张注册 + 随机划分
    hard_results: List[IdentificationResult] = []
    if args.hard:
        print("困难协议（末位选人 / 单张注册 / 随机划分）…")
        hard_eligible = list(reversed(eligible))  # 图片最少的人 = 最不"连拍友好"
        for k in sorted({int(x) for x in args.hard_sweep.split(",") if x.strip()}):
            if k > len(hard_eligible):
                continue
            sub = hard_eligible[:k]
            assert not (set(sub) & {p for p in calib_pool}), "困难协议画廊与标定池重叠"
            sub_db = build_db(probe, groups, sub, 1, calibration.threshold, "random", args.split_seed)
            res = evaluate_identification(
                probe, sub_db, groups, sub, 1, args.test_per_person, "random", args.split_seed
            )
            hard_results.append(res)
            print(
                f"  画廊 {k:>3} 人（1 张注册）→ rank-1 {res.rank1_accuracy*100:.1f}%  "
                f"检出 {res.detection_rate*100:.1f}%  拒识 {res.rejected}  认错 {res.wrong}"
            )

    # ── Haar 对照
    haar_result: Optional[IdentificationResult] = None
    if args.compare_haar:
        print("Haar 对照评测…")
        haar_rec = FaceRecognizer(detector=HaarDetector(), embedder=embedder, db=None)
        haar_db = build_db(
            haar_rec, groups, main_gallery, args.enroll, calibration.threshold, args.split, args.split_seed
        )
        haar_result = evaluate_identification(
            haar_rec, haar_db, groups, main_gallery, args.enroll, args.test_per_person,
            args.split, args.split_seed,
        )
        print(f"  Haar 检出 {haar_result.detection_rate*100:.1f}% | rank-1 {haar_result.rank1_accuracy*100:.1f}%")

    platform_info = {
        "数据集": f"LFW（{dataset.name}），{sum(len(v) for v in groups.values())} 张 / {len(groups)} 人（≥{args.min_images} 张/人）",
        "开发机": f"{_platform.system()} {_platform.machine()} / Python {_platform.python_version()}",
        "OpenCV": cv2.__version__,
        "numpy": np.__version__,
        "目标平台": "树莓派 4B 4GB（**未实测**，本报告数字与之无关）",
    }

    gallery_counts = {name: len(groups[name]) for name in main_gallery}
    report = render_report(
        args, calibration, main_result, sweep_results, hard_results, haar_result,
        platform_info, gallery_counts,
    )

    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"报告已写入: {out}")

    if args.json:
        out_json = Path(args.json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "platform": platform_info,
            "detector": args.detector,
            "calibration": calibration.to_dict(),
            "calibration_curve": [
                {"threshold": round(t, 4), "fmr": round(f, 5), "fnmr": round(n, 5)}
                for t, f, n in calibration.curve
            ],
            "main": main_result.to_dict(),
            "sweep": [r.to_dict() for r in sweep_results],
            "hard_protocol": [r.to_dict() for r in hard_results],
            "haar": haar_result.to_dict() if haar_result else None,
        }
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 已写入: {out_json}")

    if not args.report and not args.json:
        print(report)

    # 退出码：主结果达标 0，未达标 2（让 CI/脚本能直接判）
    passed = main_result.rank1_accuracy >= 0.9 and main_result.detection_rate >= 0.9
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
