#!/usr/bin/env python3
"""一键生成带重力 / 地面 / 扭矩上限的校核世界（不改默认世界）。

默认世界 ``webots/worlds/atri_v2.wbt`` 必须保持 ``gravity 0``（CI 钉死）。
本脚本**只调用**现有生成器 ``generate_atri_world.py``，把派生世界写到
``docs/process/sim/worlds/atri_v2_gravity.wbt``，再做三条静态自检。

用法（仓库根目录）::

    python3 webots/tools/make_gravity_world.py

本机（Mac）可能没有 Webots GUI：本脚本只负责生成 + grep 自检 + 打印给队友的
启动/录屏命令。真正打开世界、静立、扭矩探针、录屏都在队友机器上做。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GENERATOR = Path(__file__).resolve().parent / "generate_atri_world.py"
DEFAULT_OUT = REPO / "docs" / "process" / "sim" / "worlds" / "atri_v2_gravity.wbt"
DEFAULT_WORLD = REPO / "webots" / "worlds" / "atri_v2.wbt"

GRAVITY = -9.81
MAX_TORQUE = 2.94


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="生成 A.T.R.I. 带重力校核世界（不覆盖默认零重力世界）"
    )
    parser.add_argument(
        "--out",
        default=None,
        help="派生世界输出路径（默认 docs/process/sim/worlds/atri_v2_gravity.wbt）",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="调用生成器时用的 Python（默认当前解释器）",
    )
    return parser


def resolve_out(raw: str | None) -> Path:
    out = Path(raw) if raw else DEFAULT_OUT
    if not out.is_absolute():
        out = Path.cwd() / out
    return out


def run_generator(python_exe: str, out: Path) -> int:
    """按 README 校核跑法调用现有生成器（命令行开关，不改生成器默认值）。"""
    cmd = [
        python_exe,
        str(GENERATOR),
        f"--gravity={GRAVITY}",
        f"--max-torque={MAX_TORQUE}",
        "--ground",
        "--out",
        str(out),
    ]
    print("调用生成器：")
    print("  " + " ".join(cmd))
    print()
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, cwd=str(REPO))
    return int(proc.returncode)


def grep_count(text: str, needle: str) -> int:
    return text.count(needle)


def verify(out: Path) -> dict:
    """三条硬自检：gravity / maxTorque ×22 / 地面 Plane。"""
    text = out.read_text(encoding="utf-8")
    gravity_hits = grep_count(text, "gravity -9.81")
    torque_hits = grep_count(text, "maxTorque 2.94")
    plane_hits = text.count("Plane")
    floor_hits = text.count("Floor")
    ground_hits = plane_hits + floor_hits
    ok = gravity_hits >= 1 and torque_hits == 22 and ground_hits >= 1
    return {
        "ok": ok,
        "gravity_hits": gravity_hits,
        "torque_hits": torque_hits,
        "plane_hits": plane_hits,
        "floor_hits": floor_hits,
        "ground_hits": ground_hits,
        "bytes": out.stat().st_size,
        "default_untouched": default_world_still_zero_g(),
    }


def default_world_still_zero_g() -> bool:
    """确认没有误写默认世界：gravity 必须仍是单个 0。"""
    if not DEFAULT_WORLD.is_file():
        return False
    text = DEFAULT_WORLD.read_text(encoding="utf-8")
    return "\n  gravity 0\n" in text and "gravity -9.81" not in text


def print_grep(result: dict, out: Path) -> None:
    rel = _rel(out)
    print("自检 grep（与 webots/README.md「带重力/带地面的校核跑法」同一套）：")
    print(f"  grep -c \"gravity -9.81\"  {rel}   → {result['gravity_hits']}   （期望 1）")
    print(f"  grep -c \"maxTorque 2.94\" {rel}   → {result['torque_hits']}  （期望恰好 22）")
    print(
        f"  grep -cE \"Floor|Plane\"    {rel}   → Plane={result['plane_hits']}"
        f" Floor={result['floor_hits']}  （期望 ≥1）"
    )
    print()
    if result["ok"]:
        print("自检通过。")
    else:
        print("自检失败：不要拿这份世界去跑 S1/S2 / 录屏。", file=sys.stderr)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def print_teammate_commands(out: Path) -> None:
    rel = _rel(out)
    run_copy = "webots/worlds/atri_v2_gravity.wbt"
    print()
    print("=" * 60)
    print("给队友的启动命令（本机可能没有 Webots GUI，下面都是给有 Webots 的机器用的）")
    print("=" * 60)
    print(
        """
⚠ 口径：只有这份带重力世界才能谈「站得住」。
  默认 webots/worlds/atri_v2.wbt 是 gravity 0、无地面、不写 maxTorque，
  零重力下机器人悬浮、静力矩 ≈ 0，用它录的「静立」不能进答辩材料。

⚠ 控制器发现：世界放在 docs/process/sim/worlds/ 时，Webots 会把
  docs/process/sim/ 当成 project，那里没有 controllers/atri_controller。
  稳妥做法：先复制到 webots/worlds/ 再打开（project 不变，控制器一定找得到）。
  这个副本是生成产物，不要提交。
""".rstrip()
    )
    print()
    print("# 0) 运行副本（推荐，控制器一定找得到）")
    print(f"cp {rel} {run_copy}")
    print()
    print("# 1) S1 静立 10 s（GUI 录屏；不要 --mode=fast）")
    print("mkdir -p docs/process/sim/empty_cards")
    print("export ATRI_WEBOTS_MAX_TORQUE=2.94")
    print("export ATRI_WEBOTS_TASK_CARD_DIR=docs/process/sim/empty_cards")
    print(f"webots --mode=realtime {run_copy}")
    print()
    print("# 2) S2 扭矩探针：GUI 里把 Robot.controller 改成 torque_probe")
    print("#    仓库已有 webots/controllers/torque_probe/torque_probe.py")
    print(f"webots --mode=realtime {run_copy}")
    print()
    print("# 3) T-05 舞蹈（只跑这一张卡）")
    print("mkdir -p docs/process/sim/cards_t05")
    print("cp software/atri/task_cards/T-05_dance.json docs/process/sim/cards_t05/")
    print("export ATRI_WEBOTS_MAX_TORQUE=2.94")
    print("export ATRI_WEBOTS_TASK_CARD_DIR=docs/process/sim/cards_t05")
    print("unset ATRI_WEBOTS_EXIT_ON_DONE   # 录屏时不要让控制器跑完就退")
    print(f"webots --mode=realtime {run_copy}")
    print()
    print("完整步骤、机位、压到 720p / ≤100 MB：docs/process/sim/重力世界录屏脚本.md")


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    if not GENERATOR.is_file():
        print(f"找不到生成器: {GENERATOR}", file=sys.stderr)
        return 2
    urdf = REPO / "design" / "v2" / "out" / "sim" / "atri_v2.urdf"
    if not urdf.is_file():
        print(
            f"找不到 {urdf}：生成器从 v2 URDF + profile.py 派生几何/质量/关节。",
            file=sys.stderr,
        )
        return 2

    out = resolve_out(args.out)
    if out.resolve() == DEFAULT_WORLD.resolve():
        print(
            "拒绝：--out 指向了默认世界 webots/worlds/atri_v2.wbt。"
            "派生世界必须写到别处（例如 docs/process/sim/worlds/）。",
            file=sys.stderr,
        )
        return 2

    print(f"仓库根: {REPO}")
    print(f"输出  : {out}")
    print(f"默认世界不会被改写: {_rel(DEFAULT_WORLD)}")
    print()

    code = run_generator(args.python, out)
    if code != 0:
        print(f"生成器退出码 {code}，未做自检。", file=sys.stderr)
        return code
    if not out.is_file():
        print(f"生成器声称成功，但文件不存在: {out}", file=sys.stderr)
        return 2

    result = verify(out)
    print()
    print_grep(result, out)
    print(f"文件大小: {result['bytes']} 字节")
    print(
        "默认世界仍是 gravity 0:"
        + (" 是" if result["default_untouched"] else " 否（出事了，立刻停）")
    )
    if not result["default_untouched"]:
        return 2
    print_teammate_commands(out)
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
