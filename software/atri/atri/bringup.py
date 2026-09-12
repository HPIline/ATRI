"""真机 bring-up 流程：扫描 → 分配 ID → 写限位 → 中位标定 → 单关节点动 → 温升/电流记录。

设计原则
--------
1. **物理动作由人做，脚本负责"驱动 + 记录 + 校验"**（工作区约定：脚本难做、人工易做的
   步骤不硬写自动化）。例如"把这只舵机接到总线并装到 7 号位"由人执行，脚本负责逐只点名、
   下发指令、回读校验、把结果写进标定文件。
2. **每一步可单独调用**（`run_bringup.py --step scan`），不必一次跑完；中途断电不丢进度。
3. 所有 ID / 角度 / 脉冲都来自 `atri.config.joint_table()`（唯一真源），工具里不写死。
4. **真机总线用 `--bus 模块:类` 注入**，本模块不含任何串口代码 ——
   "驱动还没写"不阻塞流程编写与自测（先用 `MockServoBus` 把全流程跑通）。

对应关系：真机驱动的交付物是 `atri/bus_sts3215.py`（实现 `cerebellum.ServoBus`），
协议与寄存器见 `design/reference/sts3215/PROTOCOL.md` 与
`design/cad/vendor/feetech/STS3215_7.4V_19kg_spec.pdf`（官方规格书）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .cerebellum import ServoBus
from .config import (CALIBRATION_PATH, JOINTS, deg_to_pulse, joint_table,
                     load_calibration, pulse_limits, pulse_to_deg)

# 点动测试用的小角度序列（相对中位；小到不会撞结构）
JOG_SEQUENCE_DEG = (-10.0, 0.0, +10.0, 0.0)
JOG_HOLD_S = 1.0
TEMP_WARN_C = 55.0          # 超过就停手，查机械干涉/装配（舵机自身 70℃ 才切扭矩）
CURRENT_WARN_A = 1.2        # 空载点动不该超过这个数（额定 0.9A 附近）


def table_report() -> Dict[str, Any]:
    """打印并返回关节总表（ID / 分支 / 方向 / 零偏 / 脉冲限位）。"""
    table = joint_table()
    print(f"{'关节':22s} {'ID':>3s} {'分支':11s} {'限位(°)':>14s} "
          f"{'方向':>4s} {'零偏':>5s} {'脉冲限位':>13s}")
    print("-" * 80)
    for name, row in table.items():
        lo, hi = row["limit_deg"]
        plo, phi = row["pulse_range"]
        print(f"{name:22s} {row['id']:3d} {row['branch']:11s} "
              f"{lo:6.0f}…{hi:<6.0f} {row['sign']:+4d} {row['zero_pulse']:5d} "
              f"{plo:6d}…{phi:<6d}")
    print(f"\n共 {len(table)} 个关节；ID 覆盖 "
          f"{sorted(r['id'] for r in table.values()) == list(range(len(table)))}")
    return table


def scan_and_check(bus: ServoBus) -> Dict[str, Any]:
    """扫描总线并与关节表比对：缺哪些 ID、多哪些 ID。"""
    found = sorted(bus.scan())
    expected = sorted(spec["id"] for spec in JOINTS.values())
    missing = [i for i in expected if i not in found]
    extra = [i for i in found if i not in expected]
    id2name = {spec["id"]: n for n, spec in JOINTS.items()}
    print(f"总线上线 {len(found)} 只：{found}")
    if missing:
        print("  ✗ 缺失 ID：" + "、".join(f"{i}({id2name[i]})" for i in missing))
    if extra:
        print(f"  ✗ 意外 ID（未在关节表里）：{extra}")
    if not missing and not extra:
        print("  ✅ 与关节表完全一致")
    return {"found": found, "missing": missing, "extra": extra}


def write_all_limits(bus: ServoBus) -> Dict[str, Any]:
    """把每个关节的脉冲限位写进舵机 min/max angle 寄存器。"""
    written: Dict[str, List[int]] = {}
    for name in JOINTS:
        lo, hi = pulse_limits(name)
        bus.write_limits(JOINTS[name]["id"], lo, hi)
        written[name] = [lo, hi]
    print(f"已写入 {len(written)} 个关节的限位寄存器（软件限位外扩 "
          f"{pulse_limits(next(iter(JOINTS)))[0]}…）")
    return written


def middle_calibration(bus: ServoBus, order: Optional[Sequence[str]] = None,
                       interactive: bool = True) -> Dict[str, Any]:
    """中位标定：**人工把关节摆到机械零位后**，脚本把当前位置记为 2048。

    ⚠️ 2026-09-12 订正：旧注释写的「飞特做法：40 号地址写 128」**是错的**——
    40 号是**扭矩使能**（写 128 只是开扭矩，并不改零位），真正的零位寄存器是
    **31 号位置偏置**（写入 `当前脉冲 − 2048`）。本函数调 `bus.set_middle()`，
    真机驱动 `bus_sts3215.py` 已按 31 号实现；依据见
    `design/reference/sts3215/PROTOCOL.md` 与 `design/handoff/线程报告-真机总线驱动.md`。
    标定顺序建议：
    先躯干/头 → 再髋 → 膝 → 踝 → 肩 → 肘 → 夹爪（从近端到远端）。
    """
    names = list(order or JOINTS.keys())
    out: Dict[str, Any] = {}
    for name in names:
        jid = JOINTS[name]["id"]
        if interactive:
            print(f"→ 请把 {name}（ID {jid}）摆到机械零位，然后回车…")
            try:
                input()
            except EOFError:
                pass
        bus.set_middle(jid)
        pulse = deg_to_pulse(name, 0.0)
        out[name] = {"sign": JOINTS[name]["sign"], "zero_pulse": pulse}
        print(f"   {name:22s} 中位已记：zero_pulse={pulse}")
    return out


def jog_test(bus: ServoBus, joint: str, sequence: Sequence[float] = JOG_SEQUENCE_DEG,
             hold_s: float = JOG_HOLD_S, sleeper: Any = None) -> Dict[str, Any]:
    """单关节小角度点动 + 遥测记录（温升/电流/负载）。

    这是"实测连续扭矩与温升"的最小起点：先在**空载**下确认方向对不对、
    有没有机械干涉，再逐步加载。
    """
    sleep = sleeper or time.sleep
    jid = JOINTS[joint]["id"]
    samples: List[Dict[str, Any]] = []
    print(f"点动 {joint}（ID {jid}），序列 {list(sequence)}°，每步 {hold_s}s")
    for deg in sequence:
        bus.set_angle(jid, deg)
        sleep(hold_s)
        try:
            tele = bus.read_telemetry(jid)
        except NotImplementedError:
            tele = {"note": "该总线未实现遥测"}
        row = {"cmd_deg": deg, **tele}
        samples.append(row)
        warn = ""
        if isinstance(tele.get("temp_c"), (int, float)) and tele["temp_c"] >= TEMP_WARN_C:
            warn += " ⚠️ 温度偏高"
        if isinstance(tele.get("current_a"), (int, float)) and \
                tele["current_a"] >= CURRENT_WARN_A:
            warn += " ⚠️ 电流偏高（疑似干涉/装配过紧）"
        print(f"   cmd {deg:+6.1f}° → 实测 {tele.get('pos_deg')} "
              f"负载 {tele.get('load_pct')}% 电压 {tele.get('voltage_v')}V "
              f"温度 {tele.get('temp_c')}℃ 电流 {tele.get('current_a')}A{warn}")
    bus.set_angle(jid, 0.0)
    return {"joint": joint, "id": jid, "samples": samples}


def write_calibration(joints: Dict[str, Any],
                      path: Optional[Path] = None) -> Path:
    """把标定结果写进 `config/calibration.json`（bring-up 的正式产物）。"""
    p = Path(path) if path is not None else CALIBRATION_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, Any] = {}
    if p.exists():
        existing = json.loads(p.read_text(encoding="utf-8")).get("joints", {})
    existing.update(joints)
    payload = {
        "schema_version": "1.0",
        "note": ("装配标定表：sign（转向）与 zero_pulse（机械零位脉冲）。"
                 "由 run_bringup.py 生成，程序启动时经 config.load_calibration() 载入。"),
        "joints": existing,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    print(f"✓ 标定表已写出：{p}（{len(existing)} 个关节）")
    return p


def run_all(bus: ServoBus, sleeper: Any = None, interactive: bool = False
            ) -> Dict[str, Any]:
    """完整流程（真机第一次上电按这个顺序走）。

    顺序不能颠倒：**先扫描确认身份，再写限位，最后才使能/点动**。
    """
    report: Dict[str, Any] = {}
    load_calibration()
    report["table"] = table_report()
    report["scan"] = scan_and_check(bus)
    report["limits"] = write_all_limits(bus)
    if interactive:
        report["middle"] = middle_calibration(bus, interactive=True)
        write_calibration(report["middle"])
    report["jog"] = {n: jog_test(bus, n, sleeper=sleeper) for n in ("head_yaw",)}
    return report
