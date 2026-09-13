#!/usr/bin/env python3
"""T-05 娱乐休闲评测：关键词注入统计命中 / 拒识。

**先说清这个工具测的是什么、不是什么**：

| 测的 | 怎么测 | 能不能写进材料 |
|---|---|---|
| 技能门闩：通道未接入走 params 兜底 | 真 ``DanceSkill`` + 空观测 | 能。这是代码路径，不是识别率 |
| 白名单命中才跳舞 | 注入关键词观测 | 能。证明门闩，不是 ASR 命中率 |
| 通道已接入但词不在白名单 → TTS「我没听清」并失败 | 注入非法词 | 能。证明拒识门闩 |
| 离线 ASR 关键词命中率 | 真 vosk + 真模型 + wav | **本机才有数字**；赛场噪声未测 |
| 节拍同步 / 实机噪声识别率 | —— | **不能**。未标定、无样机 |

无 vosk / 无模型时仍跑「关键词注入」段（不依赖麦克风、不依赖 wav）。
有引擎时探测 ``available()``；真 wav 缺文件则跳过。

用法::

    python3 software/atri/tools/dance_eval.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

SOFTWARE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOFTWARE_ROOT))

from atri.cerebellum import Cerebellum, MockServoBus  # noqa: E402
from atri.skills.base import SkillContext  # noqa: E402
from atri.skills.dance import DEFAULT_KEYWORDS, DanceSkill, UNKNOWN_SPEECH  # noqa: E402
from atri.voice import MockTTS  # noqa: E402
from atri.voice.vosk import VoskKeywordRecognizer, match_keyword  # noqa: E402

KEYWORDS = tuple(DEFAULT_KEYWORDS)


def eval_keywords(keywords: Sequence[str] = KEYWORDS) -> List[Dict[str, Any]]:
    """纯字符串白名单匹配，不依赖 wav / 麦克风 / vosk。"""
    cases = [
        ("请跳舞", "跳舞"),
        ("挥手你好", "挥手"),
        ("鞠躬致谢", "鞠躬"),
        ("起飞", ""),
        ("", ""),
        ("今天天气不错", ""),
    ]
    rows = []
    for text, expect in cases:
        got = match_keyword(text, keywords)
        rows.append({"text": text, "expect": expect, "got": got, "ok": got == expect})
    return rows


def _run_skill(
    *,
    observation: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    tts = MockTTS()
    cere = Cerebellum(servo_bus=MockServoBus(), sleeper=lambda dt: None)
    merged = {"bars": 1}
    if params:
        merged.update(params)
    result = DanceSkill().run(
        SkillContext(
            task_id="T-05-eval",
            task_name="dance-eval",
            params=merged,
            cerebellum=cere,
            observation=observation,
            tts_engine=tts,
        )
    )
    out = dict(result)
    out["spoken"] = list(tts.spoken)
    return out


def eval_skill_gate() -> Dict[str, Any]:
    """真 DanceSkill 门闩：params 兜底 + 非法词拒识。"""
    reject = _run_skill(observation={"speech": {"keyword": "起飞", "found": True}})
    fallback = _run_skill(observation={}, params={"keyword": "跳舞", "bars": 1})
    hit = _run_skill(observation={"speech": {"keyword": "跳舞", "found": True}})
    empty = _run_skill(observation={"speech": {"found": True}})
    return {
        "reject_unknown": reject.get("status") != "ok" and UNKNOWN_SPEECH in reject["spoken"],
        "params_fallback": fallback.get("status") == "ok" and fallback.get("source") == "params",
        "hit_whitelist": hit.get("status") == "ok" and hit.get("keyword") == "跳舞",
        "reject_empty": empty.get("status") != "ok" and UNKNOWN_SPEECH in empty["spoken"],
        "reject_reason": str(reject.get("reason") or ""),
        "fallback_source": str(fallback.get("source") or ""),
    }


def eval_vosk_probe() -> Dict[str, Any]:
    """探测本机是否真有 vosk + 模型。禁止在这里 pip install。"""
    rec = VoskKeywordRecognizer()
    ready = rec.available()
    return {
        "vosk_ready": ready,
        "model_path": rec.model_path or "",
        "error": rec._load_error or "",
        "note": "有引擎才报本机离线命中率；赛场噪声识别率仍是未测项 B8。",
    }


def summarize(rows: Sequence[Dict[str, Any]], gate: Dict[str, Any]) -> Dict[str, Any]:
    hits = [r for r in rows if r["expect"]]
    rejects = [r for r in rows if not r["expect"]]
    gate_ok = all(bool(gate[k]) for k in ("reject_unknown", "params_fallback", "hit_whitelist", "reject_empty"))
    return {
        "match_total": len(rows),
        "match_ok": sum(1 for r in rows if r["ok"]),
        "hit": {"n": len(hits), "ok": sum(1 for r in hits if r["ok"])},
        "reject": {"n": len(rejects), "ok": sum(1 for r in rejects if r["ok"])},
        "gate_ok": gate_ok,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="T-05 关键词命中/拒识评测（注入，非真麦）")
    parser.parse_args(list(argv) if argv is not None else None)
    rows = eval_keywords()
    gate = eval_skill_gate()
    probe = eval_vosk_probe()
    summary = summarize(rows, gate)
    print("关键词匹配（注入转写，非麦克风）:")
    for row in rows:
        mark = "命中" if row["expect"] else "拒识"
        ok = "OK" if row["ok"] else "FAIL"
        print(f"  [{ok}] {mark} {row['text']!r} → {row['got']!r} (期望 {row['expect']!r})")
    print("技能门闩:", {k: gate[k] for k in ("reject_unknown", "params_fallback", "hit_whitelist", "reject_empty")})
    print(
        "汇总: 匹配 {ok}/{total}（命中 {hit_ok}/{hit_n}，拒识 {rej_ok}/{rej_n}）；门闩 {gate}".format(
            ok=summary["match_ok"],
            total=summary["match_total"],
            hit_ok=summary["hit"]["ok"],
            hit_n=summary["hit"]["n"],
            rej_ok=summary["reject"]["ok"],
            rej_n=summary["reject"]["n"],
            gate="OK" if summary["gate_ok"] else "FAIL",
        )
    )
    print("vosk:", probe)
    ok = summary["match_ok"] == summary["match_total"] and summary["gate_ok"]
    print("结果:", "OK" if ok else "FAIL")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
