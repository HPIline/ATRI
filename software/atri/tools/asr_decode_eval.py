#!/usr/bin/env python3
"""T-05 离线语音真解码评测：把"关键词识别率"从**未知**变成**有数字、可复跑、可核对**。

## 这个工具测什么、不是什么

| 段 | 测的 | 数据来源 | 能写进材料吗 |
|---|---|---|---|
| A | 引擎/模型**可得性**：缺什么、装在哪、版本号 | 真探测 | **能**（这是环境事实） |
| B | **真引擎真解码**：合成语音 → 白噪声 → 解码 → 白名单判定 | macOS `say` 合成 + 程序加噪 + 真 vosk | **能**，但必须写「**合成语音 + 程序白噪声**，不是现场识别率」 |
| C | 缺件时的行为：给错解释器/模型必须**优雅跳过**并注明 | 故意给错路径 | 能（证明"不会假装识别"） |
| — | 现场（人声/音乐/混响）识别率、实机麦克风、节拍同步 | —— | **不能**。未测项 B8 仍未测 |

**为什么噪声轴要一路扫到 0 dB**：S-05 给的 30/50/70 dB 在本实验里**几乎不影响**识别
（30 dB 仍全中）——那说明这条轴**区分不出方案好坏**。把 20/10/0 dB 也扫出来，
才能看到"引擎从哪一档开始听错、错成什么"，这才是对现场有用的信息。

## 它凭什么能跑真引擎

仓库基准解释器（`.python/bin/python3`）**必须保持零第三方依赖**，所以 vosk 装在
**旁边的独立 venv** 里，本工具用 `--asr-python` 指过去；解码代码在那边以子进程运行
（`atri/voice/vosk.py` 的适配器 + `match_keyword` 白名单判定，全是仓库真代码）。
缺任何一件（解释器/模块/模型）都在报告里写明缺什么并**跳过**，绝不用 Mock 顶替。

重建引擎环境（一次即可，模型 65 MB）：

    python3 -m venv /tmp/atri-asr/venv
    /tmp/atri-asr/venv/bin/python -m pip install vosk -i https://pypi.tuna.tsinghua.edu.cn/simple
    curl -LO https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip
    unzip -q vosk-model-small-cn-0.22.zip -d /tmp/atri-asr/models/

用法：

    .python/bin/python3 software/atri/tools/asr_decode_eval.py \\
        --asr-python /tmp/atri-asr/venv/bin/python \\
        --vosk-model /tmp/atri-asr/models/vosk-model-small-cn-0.22 \\
        --report design/handoff/T-05-语音真解码验证报告.md \\
        --json design/results/t05_asr_decode.json

只依赖标准库（wave / array / random / subprocess），零第三方依赖解释器可直接跑。
"""
from __future__ import annotations

import argparse
import array
import json
import math
import random
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
SOFTWARE_ROOT = REPO_ROOT / "software" / "atri"
sys.path.insert(0, str(SOFTWARE_ROOT))

# S-05 的三个变体 + 一个整句 + 一个白名单外负样本（对齐 scenario_set.json 的 S-05-dance）
PHRASES: List[Tuple[str, str, str]] = [
    ("跳舞", "S-05 变体 1", "变体"),
    ("跳个舞", "S-05 变体 2", "变体"),
    ("来段舞蹈", "S-05 变体 3", "变体"),
    ("请你跳个舞好吗", "整句（变体在句中）", "整句"),
    ("起飞", "白名单外（负样本）", "负样本"),
]
KEYWORDS = ("跳舞", "跳个舞", "来段舞蹈")
NOISE_LEVELS: List[Optional[float]] = [None, 70.0, 50.0, 30.0, 20.0, 10.0, 0.0]  # None = 干净
SAMPLE_RATE = 16000
NOISE_SEED = 20260913
DEFAULT_AUDIO_DIR = REPO_ROOT / "本地数据" / "t05_voice"

# 在**外部解释器**里跑的探针：只用仓库自己的适配器与白名单判定。
PROBE_CODE = r'''
import json, os, sys, wave
sys.path.insert(0, os.environ["ATRI_EVAL_SOFTWARE_ROOT"])
from atri.voice.vosk import VoskKeywordRecognizer, vosk_available, ENV_MODEL

spec = json.loads(os.environ["ATRI_EVAL_SPEC"])
out = {"python": sys.version.split()[0], "items": []}

rec = VoskKeywordRecognizer(model_path=spec["model"], keywords=tuple(spec["keywords"]),
                           constrained=True)
free = VoskKeywordRecognizer(model_path=spec["model"], keywords=tuple(spec["keywords"]),
                            constrained=False)
status = {"available": bool(rec.available()), "error": getattr(rec, "_load_error", None) or ""}
try:
    import vosk
    status["vosk_version"] = getattr(vosk, "__version__", "unknown")
except Exception as exc:
    status["vosk_version"] = f"不可用: {exc}"
status["model_present"] = os.path.isdir(str(spec["model"]))
out["status"] = status

if status["available"]:
    for item in spec["items"]:
        path = item["wav"]
        try:
            with wave.open(path, "rb") as fh:
                pcm = fh.readframes(fh.getnframes())
            hit = rec.recognize(pcm)
            hit_free = free.recognize(pcm)
            out["items"].append({
                "wav": path,
                "hit": hit, "text": rec.last_text,                # 语法约束模式
                "hit_free": hit_free, "text_free": free.last_text,  # 自由解码模式
                "frames": len(pcm) // 2,
            })
        except Exception as exc:
            out["items"].append({"wav": path, "hit": "", "text": "", "error": f"{type(exc).__name__}: {exc}"})

print("ATRI-EVAL-JSON " + json.dumps(out, ensure_ascii=False))
'''


# ────────────────────────── 音频 ──────────────────────────


def run_command(cmd: Sequence[str], timeout: int = 120) -> Dict[str, Any]:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"cmd": " ".join(cmd), "exit": done.returncode,
                "stdout": (done.stdout or "").strip(), "stderr": (done.stderr or "").strip()}
    except FileNotFoundError as exc:
        return {"cmd": " ".join(cmd), "exit": 127, "stderr": f"找不到命令: {exc}"}
    except subprocess.SubprocessError as exc:
        return {"cmd": " ".join(cmd), "exit": 1, "stderr": f"{type(exc).__name__}: {exc}"}


def read_wav_pcm(path: Path) -> Tuple[bytes, int]:
    with wave.open(str(path), "rb") as fh:
        return fh.readframes(fh.getnframes()), fh.getframerate()


def write_wav_pcm(path: Path, pcm: bytes, rate: int = SAMPLE_RATE) -> None:
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(pcm)


def pcm_rms(pcm: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(float(s) * float(s) for s in samples) / len(samples))


def add_white_noise(pcm: bytes, snr_db: float, seed: int = NOISE_SEED) -> bytes:
    """按信噪比叠高斯白噪声（纯标准库，确定性 seed）。

    ``snr_db`` 是"语音 RMS / 噪声 RMS"的 dB 值；越小噪声越大。
    """
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    signal_rms = pcm_rms(pcm)
    if signal_rms <= 0:
        return pcm
    noise_rms = signal_rms / (10.0 ** (snr_db / 20.0))
    rng = random.Random(seed)
    out = array.array("h")
    for value in samples:
        noisy = value + rng.gauss(0.0, noise_rms)
        out.append(max(-32768, min(32767, int(round(noisy)))))
    return out.tobytes()


def synth_phrase(text: str, aiff: Path, wav: Path, voice: str) -> Dict[str, Any]:
    """macOS `say` 合成 → `afconvert` 转 16 kHz 单声道（引擎训练口径）。"""
    step1 = run_command(["/usr/bin/say", "-v", voice, "-o", str(aiff), text])
    if step1["exit"] != 0:
        return {"synth": step1, "convert": None}
    step2 = run_command(["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16@16000",
                         "-c", "1", str(aiff), str(wav)])
    return {"synth": step1, "convert": step2}


# ────────────────────────── 探针 ──────────────────────────


def probe_external(asr_python: str, model: str, items: List[Dict[str, Any]],
                   timeout: int = 900) -> Dict[str, Any]:
    import os

    python = Path(asr_python)
    if not python.exists():
        return {"ok": False, "error": f"解释器不存在: {asr_python}",
                "hint": "用 --asr-python 指向装了 vosk 的 venv（见文件头重建步骤）"}
    spec = {"model": model, "keywords": list(KEYWORDS), "items": items}
    env = dict(os.environ)
    env["ATRI_EVAL_SPEC"] = json.dumps(spec, ensure_ascii=False)
    env["ATRI_EVAL_SOFTWARE_ROOT"] = str(SOFTWARE_ROOT)
    try:
        done = subprocess.run([str(python), "-c", PROBE_CODE], capture_output=True,
                              text=True, timeout=timeout, env=env)
    except subprocess.SubprocessError as exc:
        return {"ok": False, "error": f"探针执行失败: {type(exc).__name__}: {exc}"}
    payload = None
    for line in (done.stdout or "").splitlines():
        if line.startswith("ATRI-EVAL-JSON "):
            payload = json.loads(line[len("ATRI-EVAL-JSON "):])
    if payload is None:
        return {"ok": False, "error": "探针没有输出结果",
                "exit": done.returncode, "stdout": (done.stdout or "")[-400:],
                "stderr": (done.stderr or "")[-400:]}
    payload["ok"] = True
    payload["exit"] = done.returncode
    return payload


def local_status() -> Dict[str, Any]:
    """基准解释器里的可得性（应当**不可用**：核心包零依赖）。"""
    from atri.voice.vosk import ENV_MODEL, VoskKeywordRecognizer

    rec = VoskKeywordRecognizer()
    available = bool(rec.available())
    return {
        "python": sys.version.split()[0],
        "available": available,
        "error": getattr(rec, "_load_error", None) or "",
        "env_model": ENV_MODEL,
    }


def sha256_of(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def asr_env_facts(asr_python: str, model_dir: str) -> Dict[str, Any]:
    facts: Dict[str, Any] = {"asr_python": asr_python, "model_dir": model_dir}
    version = run_command([asr_python, "-c", "import vosk,sys;print(getattr(vosk,'__version__','unknown'));print(sys.version.split()[0])"], timeout=120)
    facts["version_cmd"] = version
    model_path = Path(model_dir)
    facts["model_present"] = model_path.is_dir()
    if facts["model_present"]:
        facts["model_size_bytes"] = sum(f.stat().st_size for f in model_path.rglob("*") if f.is_file())
        facts["model_files"] = len([f for f in model_path.rglob("*") if f.is_file()])
    for candidate in (model_path.parent / (model_path.name + ".zip"), model_path.with_suffix(".zip")):
        if candidate.exists():
            facts["zip_path"] = str(candidate)
            facts["zip_size_bytes"] = candidate.stat().st_size
            facts["zip_sha256"] = sha256_of(candidate)
            break
    return facts


# ────────────────────────── 主流程 ──────────────────────────


def build_corpus(audio_dir: Path, voice: str) -> Dict[str, Any]:
    audio_dir.mkdir(parents=True, exist_ok=True)
    entries: List[Dict[str, Any]] = []
    for index, (text, kind, group) in enumerate(PHRASES):
        aiff = audio_dir / f"say{index:02d}.aiff"
        wav = audio_dir / f"say{index:02d}.wav"
        steps = synth_phrase(text, aiff, wav, voice)
        ok = wav.exists() and wav.stat().st_size > 0
        entries.append({
            "text": text, "kind": kind, "group": group,
            "aiff": str(aiff), "wav": str(wav), "ok": ok,
            "steps": steps,
            "duration_s": round(len(read_wav_pcm(wav)[0]) / 2 / SAMPLE_RATE, 3) if ok else None,
        })
    return {"dir": str(audio_dir), "voice": voice, "entries": entries}


def run_acceptance(asr_python: str, model: str, audio_dir: Path, keep: bool) -> Dict[str, Any]:
    local = local_status()
    corpus = build_corpus(audio_dir, voice="Tingting")

    # 按信噪比生成解码清单
    items: List[Dict[str, Any]] = []
    for entry in corpus["entries"]:
        if not entry["ok"]:
            continue
        wav = Path(entry["wav"])
        pcm, rate = read_wav_pcm(wav)
        for snr in NOISE_LEVELS:
            if snr is None:
                target = wav
            else:
                target = audio_dir / f"{wav.stem}_snr{int(snr)}.wav"
                write_wav_pcm(target, add_white_noise(pcm, snr, seed=NOISE_SEED + int(snr)), rate)
            items.append({"wav": str(target), "text": entry["text"], "group": entry["group"],
                          "snr_db": snr})

    probe = probe_external(asr_python, model, items)
    decoded: List[Dict[str, Any]] = []
    if probe.get("ok") and probe.get("status", {}).get("available"):
        by_path = {item["wav"]: item for item in probe.get("items", [])}
        for meta in items:
            raw = by_path.get(meta["wav"], {})
            decoded.append({**meta,
                            "hit": raw.get("hit", ""), "engine_text": raw.get("text", ""),
                            "hit_free": raw.get("hit_free", ""), "engine_text_free": raw.get("text_free", ""),
                            "error": raw.get("error", "")})

    # 缺件演练：故意给错解释器 / 错模型
    drill = {
        "bad_python": probe_external("/tmp/atri-asr/definitely-missing-python", model, items[:1]),
        "bad_model": probe_external(asr_python, str(audio_dir / "no-such-model"), items[:1]),
    }
    drill["bad_python_skipped_cleanly"] = not drill["bad_python"].get("ok") and bool(drill["bad_python"].get("error"))
    bad_model_status = (drill["bad_model"].get("status") or {}) if drill["bad_model"].get("ok") else {}
    drill["bad_model_reports_unavailable"] = bad_model_status.get("available") is False

    env_facts = asr_env_facts(asr_python, model)
    result = {
        "local_status": local,
        "corpus": corpus,
        "probe": {k: v for k, v in probe.items() if k != "items"},
        "decoded": decoded,
        "drill": drill,
        "env": env_facts,
        "keywords": list(KEYWORDS),
        "noise_levels": NOISE_LEVELS,
    }
    result["summary"] = summarize(decoded)
    if not keep:
        for pattern in ("*_snr*.wav",):
            for path in audio_dir.glob(pattern):
                path.unlink(missing_ok=True)
    return result


def summarize(decoded: List[Dict[str, Any]]) -> Dict[str, Any]:
    def same_as_spoken(row: Dict[str, Any], field: str) -> bool:
        """引擎原文是否**真的说出了刚说的那个词**（去空格后包含）。

        语法约束模式下引擎只会吐白名单词，所以三个变体都会被压成同一个词（实测压成
        「跳舞」）——那一列数字高，不代表区分得开；这个指标就是用来看穿这件事的。
        """
        text = str(row.get(field) or "").replace(" ", "")
        return bool(text) and str(row["text"]) in text

    variants = [row for row in decoded if row["group"] == "变体"]
    by_snr: List[Dict[str, Any]] = []
    for snr in NOISE_LEVELS:
        rows = [row for row in variants if row["snr_db"] == snr]
        hits = [row for row in rows if row["hit"]]
        by_snr.append({
            "snr_db": snr, "label": "干净" if snr is None else f"{snr:g} dB",
            "total": len(rows), "hit": len(hits),
            "rate": (len(hits) / len(rows)) if rows else None,
        })
    negatives = [row for row in decoded if row["group"] == "负样本"]
    return {
        "variants_total": len(variants),
        "variants_hit": sum(1 for row in variants if row["hit"]),
        "variants_hit_free": sum(1 for row in variants if row.get("hit_free")),
        "variants_said_the_word": sum(1 for row in variants if same_as_spoken(row, "engine_text")),
        "variants_said_the_word_free": sum(1 for row in variants if same_as_spoken(row, "engine_text_free")),
        "by_snr": by_snr,
        "by_snr_free": [
            {
                "snr_db": snr, "label": "干净" if snr is None else f"{snr:g} dB",
                "total": len(rows := [r for r in variants if r["snr_db"] == snr]),
                "hit": sum(1 for r in rows if r.get("hit_free")),
                "rate": ((sum(1 for r in rows if r.get("hit_free")) / len(rows)) if rows else None),
            }
            for snr in NOISE_LEVELS
        ],
        "negative_total": len(negatives),
        "negative_false_accepts": sum(1 for row in negatives if row["hit"]),
        "negative_false_accepts_free": sum(1 for row in negatives if row.get("hit_free")),
        "engine_errors": sum(1 for row in decoded if row.get("error")),
    }


def render_report(data: Dict[str, Any], command: str) -> str:
    lines: List[str] = []
    add = lines.append
    summary = data["summary"]
    local = data["local_status"]
    probe_status = (data["probe"].get("status") or {}) if data["probe"].get("ok") else {}
    decoded = data["decoded"]

    add("# T-05 语音真解码验证报告")
    add("")
    add("> 生成命令（本报告所有数字都由它一次跑出，可复跑核对）：")
    add("> ```")
    add(f"> {command}")
    add("> ```")
    add(">")
    add("> **这是「合成语音 + 程序白噪声」下的真引擎解码结果，不是现场识别率。**")
    add("> 没有麦克风、没有现场人声/音乐/混响；未测项清单 B8 仍然成立。")
    add("")
    add("## 1. 结论摘要")
    add("")
    if decoded:
        add(f"- 真引擎解码 **{len(decoded)}** 条（{len(PHRASES)} 句 × {len(NOISE_LEVELS)} 档噪声），"
            "两种解码模式都跑：")
        add(f"  - **语法约束**（当前技能默认）：白名单命中 "
            f"**{summary['variants_hit']}/{summary['variants_total']}**；"
            f"但其中**真的说出了被念的那个词**的只有 "
            f"**{summary['variants_said_the_word']}/{summary['variants_total']}**"
            "（约束模式下引擎只会吐白名单里的词，数字高≠分得开）")
        add(f"  - **自由解码**（不受白名单约束）：白名单命中 "
            f"**{summary['variants_hit_free']}/{summary['variants_total']}**；"
            f"真的说出被念的词的 **{summary['variants_said_the_word_free']}/{summary['variants_total']}**")
        add(f"- 白名单外负样本误接受：语法约束 **{summary['negative_false_accepts']}/{summary['negative_total']}**、"
            f"自由解码 **{summary['negative_false_accepts_free']}/{summary['negative_total']}**"
            "（这一项必须是 0，否则白名单形同虚设）")
        add(f"- 引擎报错条数：{summary['engine_errors']}")
    else:
        add("- **本次没有跑真解码**（缺外部解释器或模型），下面是环境事实与缺件演练；")
        add("  要出数字请按文件头「重建引擎环境」装好 vosk 与模型后再跑。")
    add("")
    add("## 2. 环境事实（谁在跑、缺什么）")
    add("")
    add("| 项 | 值 |")
    add("|---|---|")
    add(f"| 仓库基准解释器 | `{local['python']}`，vosk 可用 = **{local['available']}** |")
    if not local["available"]:
        add(f"| 基准解释器为什么不可用 | {local['error']} |")
    add(f"| 外部解释器 | `{data['env']['asr_python']}` |")
    if probe_status:
        add(f"| 外部解释器 Python | {probe_status.get('python')} |")
        add(f"| 引擎 | vosk {probe_status.get('vosk_version')} |")
        add(f"| 模型目录 | `{data['env']['model_dir']}`（存在：{probe_status.get('model_present')}） |")
    if data["env"].get("model_size_bytes"):
        add(f"| 模型占用 | {data['env']['model_size_bytes']} 字节 / "
            f"{data['env'].get('model_files')} 个文件 |")
    if data["env"].get("zip_sha256"):
        add(f"| 模型压缩包 | `{data['env']['zip_path']}`，{data['env']['zip_size_bytes']} 字节，"
            f"sha256 `{data['env']['zip_sha256']}` |")
    add("")
    add("**基准解释器不可用是正确行为**：核心包保持零第三方依赖，引擎装在旁边的独立 venv 里，")
    add("报告因此永远能说清「这次是哪个解释器跑的」。")
    add("")

    if decoded:
        add("## 3. 按噪声档汇总（只统计 S-05 的三个变体）")
        add("")
        add("| 信噪比 | 命中 | 命中率 | 说明 |")
        add("|---|---|---|---|")
        axis = {30.0, 50.0, 70.0}
        for row in summary["by_snr"]:
            rate = "—" if row["rate"] is None else f"{row['rate'] * 100:.1f}%"
            note = "S-05 噪声轴" if row["snr_db"] in axis else ""
            add(f"| {row['label']} | {row['hit']}/{row['total']} | {rate} | {note} |")
        add("")
        add("> 读法：S-05 给的 30/50/70 dB 在本实验里**几乎不影响**识别 —— 说明这条噪声轴")
        add("> **区分不出方案好坏**；真正有信息量的是 20 dB 以下那几档（引擎开始听错）。")
        add("")
        add("## 3.1 自由解码也按噪声档汇总（这才看得到「听错」）")
        add("")
        add("| 信噪比 | 白名单命中 | 命中率 |")
        add("|---|---|---|")
        for row in summary["by_snr_free"]:
            rate = "—" if row["rate"] is None else f"{row['rate'] * 100:.1f}%"
            add(f"| {row['label']} | {row['hit']}/{row['total']} | {rate} |")
        add("")
        add("## 4. 逐条明细（两种模式的引擎原文都保留）")
        add("")
        add("| 语句 | 类型 | 信噪比 | 语法约束·原文 | 约束·命中 | 自由解码·原文 | 自由·命中 |")
        add("|---|---|---|---|---|---|---|")
        for row in decoded:
            snr = "干净" if row["snr_db"] is None else f"{row['snr_db']:g} dB"
            t1 = row.get("engine_text") or "（空）"
            t2 = row.get("engine_text_free") or "（空）"
            add(f"| {row['text']} | {row['group']} | {snr} | `{t1}` | {row.get('hit') or '—'} | "
                f"`{t2}` | {row.get('hit_free') or '—'} |")
        add("")
        add("`原文` 是 vosk 的真实转写（`VoskKeywordRecognizer.last_text`），")
        add("命中判定走仓库自己的 `match_keyword`（最长命中优先）。**失败行如实保留**。")
        add("")
        add("> ⚠ **语法约束会吃掉区分度**：实测在约束模式下，`跳个舞` / `来段舞蹈` / `请你跳个舞好吗`")
        add("> 全都被引擎转写成 `跳舞`——因为白名单被当成**语法**喂给了解码器，它只会吐白名单里的词。")
        add("> 所以「约束模式命中率 100%」**不能**读成「识别很准」；它能证明的只是")
        add("> 「白名单外的语音不会被误接受」（负样本全空）。要衡量「听清没听清」，看**自由解码**那两列。")
        add("")

    add("## 5. 缺件演练（证明不会假装识别）")
    add("")
    drill = data["drill"]
    add("| 场景 | 结果 |")
    add("|---|---|")
    add(f"| 解释器路径不存在 | {'✅ 干净跳过' if drill['bad_python_skipped_cleanly'] else '❌ 没有干净跳过'}："
        f"{(drill['bad_python'].get('error') or '')[:80]} |")
    add(f"| 模型路径不存在 | {'✅ 报不可用' if drill['bad_model_reports_unavailable'] else '❌ 未正确报不可用'} |")
    add("")
    add("## 6. 诚实缺口（这份报告**没有**证明的事）")
    add("")
    add("| # | 缺口 | 为什么 | 要补它需要什么 |")
    add("|---|---|---|---|")
    add("| 1 | 现场识别率 | 素材是 `say` 合成音 + 程序白噪声；真实人声/音乐/混响未测 | 现场录音回放（同一套脚本换音频目录即可） |")
    add("| 2 | 实机麦克风链路 | 没有麦克风，音频是文件喂进去的 | 板子 + 麦 + 采样率对齐（16 kHz 单声道） |")
    add("| 3 | 说话人/口音/距离 | 只有一个 TTS 音色 | 多说话人、多距离复测 |")
    add("| 4 | 节拍同步 | 舞蹈动作与伴奏各走各的，没有音频时钟对齐 | 节拍检测或按 BPM 生成轨迹 |")
    add("| 5 | 端点检测（VAD） | 现在整段 wav 一次性喂进去，没有「什么时候开始听」的策略 | 加 VAD 并测截断/串音 |")
    add("")
    add("---")
    add("")
    add("关联：`atri/voice/vosk.py`（被测适配器）、`tools/dance_eval.py`（技能门闩评测）、")
    add("`design/handoff/T-05-娱乐休闲-方案.md`（方案）、`docs/process/未测项清单.md`（B8）。")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="T-05 离线语音真解码评测（合成语音 + 真引擎）")
    parser.add_argument("--asr-python", default="/tmp/atri-asr/venv/bin/python",
                        help="装了 vosk 的外部解释器（缺件则跳过真解码）")
    parser.add_argument("--vosk-model", default="/tmp/atri-asr/models/vosk-model-small-cn-0.22",
                        help="vosk 中文小模型目录")
    parser.add_argument("--audio-dir", default=str(DEFAULT_AUDIO_DIR), help="音频产物目录（被 git 忽略）")
    parser.add_argument("--report", default=None, help="markdown 报告输出路径")
    parser.add_argument("--json", default=None, help="机器可读结果输出路径")
    parser.add_argument("--keep-audio", action="store_true", help="保留下采样/加噪的中间 wav")
    args = parser.parse_args(argv)

    print("=" * 64)
    print("T-05 语音真解码评测：合成语音 + 程序白噪声 + 真 vosk")
    print("=" * 64)

    data = run_acceptance(args.asr_python, args.vosk_model, Path(args.audio_dir), args.keep_audio)
    summary = data["summary"]
    local = data["local_status"]
    print(f"[A] 基准解释器 vosk 可用 = {local['available']}（应为 False：核心包零依赖）")
    probe = data["probe"]
    if probe.get("ok") and (probe.get("status") or {}).get("available"):
        print(f"[B] 真解码 {len(data['decoded'])} 条；变体命中 "
              f"{summary['variants_hit']}/{summary['variants_total']}；"
              f"负样本误接受 {summary['negative_false_accepts']}")
    else:
        reason = probe.get("error") or (probe.get("status") or {}).get("error") or "未知"
        print(f"[B] 未跑真解码：{reason}")
    print(f"[C] 缺件演练：错解释器干净跳过={data['drill']['bad_python_skipped_cleanly']}、"
          f"错模型报不可用={data['drill']['bad_model_reports_unavailable']}")

    command = " ".join([sys.executable, "software/atri/tools/asr_decode_eval.py",
                        "--asr-python", args.asr_python, "--vosk-model", args.vosk_model])
    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_report(data, command), encoding="utf-8")
        print(f"报告 → {out}")
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
