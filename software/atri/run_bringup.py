#!/usr/bin/env python3
"""真机 bring-up 命令行入口。

用法（先用 Mock 把流程跑通，硬件到了换 --bus 即可）：

    # ① 打印关节总表（ID/分支/转向/零偏/脉冲限位）——不接硬件
    python3 run_bringup.py --table

    # ② 用 Mock 总线把整条流程跑一遍（自检/演示，不接硬件）
    python3 run_bringup.py --mock

    # ③ 接真机（驱动写好后）：
    python3 run_bringup.py --bus atri.bus_sts3215:StsBus --port /dev/ttyUSB0 --step scan
    python3 run_bringup.py --bus atri.bus_sts3215:StsBus --port /dev/ttyUSB0 --step limits
    python3 run_bringup.py --bus atri.bus_sts3215:StsBus --port /dev/ttyUSB0 --step middle --interactive
    python3 run_bringup.py --bus atri.bus_sts3215:StsBus --port /dev/ttyUSB0 --step jog --joint left_knee_pitch

⚠️ 真机总线的交付物是 `atri/bus_sts3215.py`（实现 `atri.cerebellum.ServoBus`）：
   协议、寄存器、校验和见 `design/reference/sts3215/PROTOCOL.md`。
   本文件**不含串口代码**，只负责流程编排与记录。
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from atri import bringup  # noqa: E402
from atri.cerebellum import MockServoBus, ServoBus  # noqa: E402


def load_bus(spec: Optional[str], port: Optional[str]) -> ServoBus:
    """按 `模块:类` 动态装载真机总线；缺省用 Mock。"""
    if not spec:
        print("（未指定 --bus，使用 MockServoBus：只验证流程，不驱动硬件）")
        return MockServoBus()
    mod_name, _, cls_name = spec.partition(":")
    if not cls_name:
        raise SystemExit(f"--bus 需要写成 模块:类，例如 atri.bus_sts3215:StsBus（收到 {spec!r}）")
    try:
        mod = importlib.import_module(mod_name)
    except ImportError as exc:
        raise SystemExit(f"装载真机总线失败：{exc}\n"
                         f"提示：真机驱动尚未实现时，先用 --mock 或 --table。")
    bus = getattr(mod, cls_name)
    try:
        return bus(port=port) if port else bus()
    except TypeError:
        return bus()


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="A.T.R.I. 真机 bring-up")
    ap.add_argument("--table", action="store_true", help="只打印关节总表")
    ap.add_argument("--mock", action="store_true", help="用 Mock 总线跑完整流程")
    ap.add_argument("--bus", type=str, default=None, help="真机总线 模块:类")
    ap.add_argument("--port", type=str, default=None, help="串口，如 /dev/ttyUSB0")
    ap.add_argument("--step", type=str, default=None,
                    choices=["scan", "limits", "middle", "jog", "all"])
    ap.add_argument("--joint", type=str, default="head_yaw", help="点动测试的关节")
    ap.add_argument("--interactive", action="store_true",
                    help="中位标定：逐步等待人工摆位后回车")
    ap.add_argument("--json", type=str, default=None, help="把报告写到该文件")
    args = ap.parse_args(argv)

    if args.table or (not args.mock and not args.step):
        bringup.table_report()
        if not args.mock and not args.step:
            print("\n提示：加 --mock 跑流程自检，或 --bus/--step 操作真机。")
        return 0

    bus = load_bus(args.bus, args.port)
    if args.mock:
        report = bringup.run_all(bus, sleeper=lambda _dt: None,
                                 interactive=args.interactive)
    elif args.step == "scan":
        report = bringup.scan_and_check(bus)
    elif args.step == "limits":
        report = bringup.write_all_limits(bus)
    elif args.step == "middle":
        report = bringup.middle_calibration(bus, interactive=args.interactive)
        bringup.write_calibration(report)
    elif args.step == "jog":
        report = bringup.jog_test(bus, args.joint)
    else:
        report = bringup.run_all(bus, interactive=args.interactive)

    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8")
        print(f"报告已写出：{args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
