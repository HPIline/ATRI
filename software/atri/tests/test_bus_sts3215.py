"""`atri.bus_sts3215.Sts3215Bus` 的单元测试：**用内存假串口，不需要任何硬件**。

覆盖范围（对应交付要求）
  1. 帧构造与校验和 —— 含手算的固定字节向量，防止驱动和测试"用同一个错的公式自证清白"
  2. sync_write 广播字节流 —— 证明是**一条广播帧**而不是循环单点写
  3. 角度换算往返 —— 脉冲量、限位钳制，且换算口径完全从 `config` 来
  4. 超时 / 坏校验和重试 —— 坏帧丢弃计数 + 重试耗尽后明确中文报错
  5. scan 发现 ID —— 只报告在线的那几只
  6. telemetry 解析 —— 位置/负载/电压/温度/电流/运动中 的字节级解码

假串口的设计
------------
`FakeSerial` 只实现 pyserial 里驱动真正用到的那一小撮接口
（`write` / `read` / `reset_input_buffer` / `flush` / `fileno` / `in_waiting`），
`FakeServoBus` 在内存里按**飞特协议**应帧：收到什么指令、就按寄存器表回什么包。
两边都不复用驱动里的组帧函数 —— 测试自己算校验和，才能真的测出驱动的组帧错误。
"""
from __future__ import annotations

import os
import select
import time
import unittest
from typing import Any, Dict, List, Optional, Tuple

from atri import bus_sts3215
from atri.bus_sts3215 import (ADDR_GOAL_POSITION, ADDR_GOAL_SPEED,
                              ADDR_MAX_ANGLE, ADDR_MIN_ANGLE, ADDR_POS_OFFSET,
                              ADDR_PRESENT_LOAD, ADDR_PRESENT_POSITION,
                              ADDR_PRESENT_SPEED, ADDR_PRESENT_TEMP,
                              ADDR_PRESENT_VOLTAGE, ADDR_TORQUE_ENABLE,
                              BROADCAST_ID, INST_PING, INST_READ,
                              INST_SYNC_WRITE, INST_WRITE, Sts3215Bus,
                              StsChecksumError, StsDeviceError,
                              StsProtocolError, StsSerialUnavailable,
                              StsTimeoutError, StsBus, build_frame, checksum,
                              make_sync_write_frame, parse_frames)
from atri.cerebellum import Cerebellum, ServoBus
from atri.config import DOF_COUNT, JOINTS, deg_to_pulse, pulse_limits, pulse_to_deg

# ---------------------------------------------------------------------------
# 假串口 + 内存舵机总线
# ---------------------------------------------------------------------------


class FakeSerial:
    """内存串口：写进去的字节喂给 `FakeServoBus`，回包进读缓冲。

    故意把读缓冲做成分段返回（`chunk_size`），让驱动的"读不完整就再等一轮"
    逻辑真的被走到 —— 一次 `read()` 就把整包喂完会掩盖收包边界的 bug。
    """

    def __init__(self, sim: "FakeServoBus", chunk_size: int = 0) -> None:
        self.sim = sim
        self.chunk_size = chunk_size
        self._rx = bytearray()
        self.writes: List[bytes] = []
        self._rfd, self._wfd = os.pipe()          # 给 select() 一个能查的真 fd
        self.closed = False
        self.timeout = 0.05

    # —— pyserial 接口子集 ——
    def write(self, data: bytes) -> int:
        if self.closed:
            raise OSError("假串口已关闭")
        data = bytes(data)
        self.writes.append(data)
        self._rx += self.sim.feed(data)           # 内存舵机应帧
        if self._rx:
            os.write(self._wfd, b"\x01")          # 通知 select 可读
        return len(data)

    def flush(self) -> None:
        return None

    @property
    def in_waiting(self) -> int:
        return len(self._rx)

    def read(self, size: int = 1) -> bytes:
        if size <= 0 or not self._rx:
            return b""
        if self.chunk_size:
            size = min(size, self.chunk_size)
        out = bytes(self._rx[:size])
        del self._rx[:size]
        if not self._rx:
            try:
                os.read(self._rfd, 1)
            except OSError:
                pass
        return out

    def reset_input_buffer(self) -> None:
        """pyserial 语义：丢弃**尚未取走**的接收数据。"""
        self._rx.clear()
        try:
            while select.select([self._rfd], [], [], 0)[0]:
                os.read(self._rfd, 1)
        except OSError:
            pass

    def fileno(self) -> int:
        return self._rfd

    def close(self) -> None:
        self.closed = True
        for fd in (self._rfd, self._wfd):
            try:
                os.close(fd)
            except OSError:
                pass

    # —— 测试辅助 ——
    def sent_bytes(self) -> bytes:
        return b"".join(self.writes)


class FakeServoBus:
    """内存舵机总线：按飞特协议解析指令并应帧，寄存器值可直接读写用于断言。"""

    def __init__(self, ids: Optional[List[int]] = None) -> None:
        self.ids = list(range(DOF_COUNT) if ids is None else ids)
        self.servos: Dict[int, Dict[int, int]] = {
            sid: self._fresh() for sid in self.ids
        }
        self.respond = True             # False → 完全不应答（测超时）
        self.corrupt = False            # True  → 故意回坏校验和（测坏帧重试）
        self.block_servo = False        # True  → 舵机卡死：写目标位不改变当前位置
        self.sync_write_frames = 0
        self._pending = bytearray()

    @staticmethod
    def _fresh() -> Dict[int, int]:
        """出厂默认值（见 PROTOCOL.md 3.1/3.2）。

        ⚠️ 16 位寄存器必须把 **L/H 两个字节都摆出来**：2048 = 0x0800，
        低字节恰好是 0x00，只写低字节会让回读变成 0（这个坑真踩过一次）。
        """
        return {
            ADDR_MIN_ANGLE: 0x00, ADDR_MIN_ANGLE + 1: 0x00,          # 0
            ADDR_MAX_ANGLE: 0xFF, ADDR_MAX_ANGLE + 1: 0x0F,          # 4095
            ADDR_POS_OFFSET: 0x00, ADDR_POS_OFFSET + 1: 0x00,        # 0
            ADDR_TORQUE_ENABLE: 1,                                   # 出厂锁轴
            ADDR_GOAL_POSITION: 0x00, ADDR_GOAL_POSITION + 1: 0x08,  # 2048
            ADDR_GOAL_SPEED: 0x00, ADDR_GOAL_SPEED + 1: 0x00,
            ADDR_PRESENT_POSITION: 0x00, ADDR_PRESENT_POSITION + 1: 0x08,   # 2048
            ADDR_PRESENT_SPEED: 0x00, ADDR_PRESENT_SPEED + 1: 0x00,
            ADDR_PRESENT_LOAD: 0x00, ADDR_PRESENT_LOAD + 1: 0x00,
            ADDR_PRESENT_VOLTAGE: 120,                               # 12.0 V
            ADDR_PRESENT_TEMP: 30,                                   # 30 ℃
            66: 0,                                                   # 运动中标志
            69: 0x00, 70: 0x00,                                      # 电流（×6.5 mA）
        }

    # —— 寄存器读写（16 位小端）——
    def read_reg(self, sid: int, addr: int, length: int) -> bytes:
        regs = self.servos[sid]
        return bytes(regs.get(addr + i, 0) & 0xFF for i in range(length))

    def write_reg(self, sid: int, addr: int, data: bytes,
                  width: Optional[int] = None) -> None:
        """把 `data` 写进寄存器；`width` 给 SYNC WRITE 用（行 = 1 ID + width 数据）。

        写目标位置 = 舵机真的走过去（假总线立即到位），便于回读校验。
        SYNC WRITE 的行里既有目标位置也可能带目标速度，所以要按 width 定位。
        """
        base = 0 if width is None else 1             # SYNC WRITE 每行首字节是舵机 ID
        payload = data[base:base + width] if width is not None else data
        for i, byte in enumerate(payload):
            self.servos[sid][addr + i] = byte
        if (addr <= ADDR_GOAL_POSITION < addr + len(payload)
                and ADDR_GOAL_POSITION - addr + 1 < len(payload)
                and not self.block_servo):
            off = ADDR_GOAL_POSITION - addr
            self.servos[sid][ADDR_PRESENT_POSITION] = payload[off]
            self.servos[sid][ADDR_PRESENT_POSITION + 1] = payload[off + 1]

    # —— 协议应帧 ——
    @staticmethod
    def _frame(servo_id: int, status: int, params: bytes, corrupt: bool = False) -> bytes:
        """独立于驱动再实现一遍组帧（故意不调 bus_sts3215.build_frame）。"""
        length = len(params) + 2
        body = bytes([servo_id, length, status]) + params
        chk = (~sum(body)) & 0xFF
        if corrupt:
            chk ^= 0x5A
        return b"\xff\xff" + body + bytes([chk])

    def feed(self, data: bytes) -> bytes:
        """吃进一段主机发来的字节，吐出该回的字节（可能为空）。

        ⚠️ 必须先把"凑不出一帧"的字节丢掉再重试，否则 `_take_frame` 的 None
        会让 while 原地打转（测试挂死）。这条曾经真把测试跑挂过。
        """
        if not self.respond:
            return b""
        self._pending += data
        out = bytearray()
        while True:
            if len(self._pending) < 4:
                break
            if (self._pending[0] != 0xFF or self._pending[1] != 0xFF
                    or self._pending[3] < 2):
                del self._pending[0]                  # 丢一个字节，重新找帧头
                continue
            frame = self._take_frame()
            if frame is None:
                break                                 # 帧还没收完，等下一段
            out += self._handle(*frame)
        return bytes(out)

    def _take_frame(self) -> Optional[Tuple[int, int, bytes]]:
        """切出下一帧 `(ID, instruction, params)`；数据不够时返回 None。

        主机指令帧 = `FF FF | ID | Length | Instruction | Params… | Checksum`，
        总长 = 4 + Length（Length = 参数数 + 2）。
        """
        buf = self._pending
        while len(buf) >= 4:
            if buf[0] != 0xFF or buf[1] != 0xFF:
                del buf[0]
                continue
            length = buf[3]
            if length < 2:
                del buf[0]                            # 非法 Length，换下一个字节找
                continue
            total = 4 + length
            if len(buf) < total:
                return None
            frame = bytes(buf[:total])
            del buf[:total]
            if checksum(frame[2:-1]) != frame[-1]:
                continue                              # 主机帧也校验，测试里更严格
            return frame[2], frame[4], frame[5:-1]
        return None

    def _handle(self, servo_id: int, instruction: int, params: bytes) -> bytes:
        if instruction == INST_PING:
            if servo_id in self.servos:
                return self._frame(servo_id, 0, b"", self.corrupt)
            return b""
        if instruction == INST_READ:
            if servo_id not in self.servos:
                return b""
            addr, length = params[0], params[1]
            return self._frame(servo_id, 0,
                               self.read_reg(servo_id, addr, length), self.corrupt)
        if instruction == INST_WRITE:
            if servo_id == BROADCAST_ID:
                for sid in self.servos:
                    self.write_reg(sid, params[0], params[1:])
            elif servo_id in self.servos:
                self.write_reg(servo_id, params[0], params[1:])
            return b""
        if instruction == INST_SYNC_WRITE:
            self.sync_write_frames += 1
            addr, width = params[0], params[1]
            rows = params[2:]
            # 行 = [ID] + width 字节数据；切片要带上行首 ID，所以是 width + 1
            for i in range(0, len(rows), width + 1):
                sid = rows[i]
                row = rows[i:i + width + 1]
                if sid in self.servos:
                    self.write_reg(sid, addr, row, width=width)
            return b""
        return b""

    # —— 测试辅助 ——
    def set_reg(self, sid: int, addr: int, value: int, length: int = 1) -> None:
        """直接摆一个寄存器值（模拟温度升高、负载变化等现场）。"""
        for i in range(length):
            self.servos[sid][addr + i] = (value >> (8 * i)) & 0xFF


def make_bus(sim: FakeServoBus, **kwargs: Any) -> Tuple[Sts3215Bus, FakeSerial]:
    """造一条接了假串口的真机总线。"""
    ser = FakeSerial(sim)
    kw = {"retries": 2, "verify": True}
    kw.update(kwargs)
    bus = Sts3215Bus("/dev/fake", ser=ser, **kw)
    return bus, ser


# ---------------------------------------------------------------------------
# 1. 帧构造与校验和
# ---------------------------------------------------------------------------
class TestFrameConstruction(unittest.TestCase):
    """组帧错一位，整条总线就不应答 —— 这组测试是驱动的地基。"""

    def test_checksum_hand_computed_vector(self):
        """手算向量：PING ID=1 → FF FF 01 02 01 FB（校验和按位取反累加和）。"""
        self.assertEqual(checksum(bytes([0x01, 0x02, 0x01])), 0xFB)
        self.assertEqual(build_frame(1, 0x01), b"\xff\xff\x01\x02\x01\xfb")

    def test_checksum_second_hand_computed_vector(self):
        """再钉一个向量，防止"两个函数一起改错"：写 42 号地址 2048（0x0800）。"""
        params = bytes([0x00, 0x08, 0x2A, 0x00])
        body = bytes([0xFE, 0x06, 0x03]) + params
        self.assertEqual(checksum(body), 0xC6)
        self.assertEqual(build_frame(0xFE, 0x03, params),
                         b"\xff\xff\xfe\x06\x03\x00\x08\x2a\x00\xc6")

    def test_length_field_counts_params_plus_two(self):
        frame = build_frame(3, 0x02, bytes([56, 2]))
        self.assertEqual(frame[3], 4)                    # 2 参数 + 2
        self.assertEqual(len(frame), 4 + 4)

    def test_header_is_double_ff(self):
        self.assertTrue(build_frame(1, 1).startswith(b"\xff\xff"))

    def test_illegal_id_and_instruction_rejected(self):
        with self.assertRaises(StsProtocolError):
            build_frame(256, 1)
        with self.assertRaises(StsProtocolError):
            build_frame(1, 999)

    def test_sync_write_layout(self):
        """SYNC WRITE 载荷 = 起始地址 + 每舵机长度 + (ID, data…)…"""
        frame = make_sync_write_frame(ADDR_GOAL_POSITION, [
            bytes([0]) + bytes([0x00, 0x08]),
            bytes([1]) + bytes([0x00, 0x07]),
        ])
        # 帧布局：FF FF | ID | Length | Instruction | Param0=起始地址 | Param1=每舵机数据长度 | …
        # ⚠️ "数据长度"只数数据字节，**不含每行行首的舵机 ID**（飞特 SYNC WRITE 的关键细节）
        self.assertEqual(frame[2], BROADCAST_ID)         # 广播 ID = 254
        self.assertEqual(frame[4], INST_SYNC_WRITE)      # 指令 0x83 = 131
        self.assertEqual(frame[5], ADDR_GOAL_POSITION)   # 起始地址 42
        self.assertEqual(frame[6], 2)                    # 每舵机 2 字节数据
        self.assertEqual(frame[7:], bytes([0, 0x00, 0x08, 1, 0x00, 0x07, frame[-1]]))
        self.assertEqual(frame[3], 2 + 8)                # Length = 参数字节数 + 2
        self.assertEqual(checksum(frame[2:-1]), frame[-1])

    def test_sync_write_data_goes_to_each_servo(self):
        """行边界必须与 ID 对齐：每个关节拿到的脉冲要和 config 算出来的一致。"""
        sim = FakeServoBus()
        bus, ser = make_bus(sim, verify=False)
        bus.sync_write({0: 11.0, 7: 30.0})
        p0, p7 = deg_to_pulse("head_yaw", 11.0), deg_to_pulse("left_knee_pitch", 30.0)
        row = make_sync_write_frame(ADDR_GOAL_POSITION, [
            bytes([0, p0 & 0xFF, (p0 >> 8) & 0xFF]),
            bytes([7, p7 & 0xFF, (p7 >> 8) & 0xFF])])
        self.assertEqual(ser.writes[-1], row)
        self.assertEqual(sim.servos[0][ADDR_GOAL_POSITION]
                         | (sim.servos[0][ADDR_GOAL_POSITION + 1] << 8),
                         deg_to_pulse("head_yaw", 11.0))

    def test_sync_write_rejects_ragged_and_empty(self):
        with self.assertRaises(StsProtocolError):
            make_sync_write_frame(42, [])
        with self.assertRaises(StsProtocolError):
            make_sync_write_frame(42, [b"\x00\x00\x08", b"\x00\x08"])

    def test_parse_frames_accepts_valid(self):
        raw = FakeServoBus._frame(7, 0, b"\x08\x00")
        frames, rest = parse_frames(raw)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["id"], 7)
        self.assertEqual(frames[0]["params"], b"\x08\x00")
        self.assertEqual(rest, b"")

    def test_parse_frames_drops_bad_checksum(self):
        bad = bytearray(FakeServoBus._frame(7, 0, b"\x08\x00"))
        bad[-1] ^= 0xFF
        frames, _rest = parse_frames(bytes(bad))
        self.assertEqual(frames, [])

    def test_parse_frames_keeps_incomplete_tail(self):
        raw = FakeServoBus._frame(7, 0, b"\x08\x00")
        frames, rest = parse_frames(raw[:4])             # 只来了一半
        self.assertEqual(frames, [])
        self.assertEqual(rest, raw[:4])

    def test_parse_frames_skips_garbage_prefix(self):
        raw = b"\x00\x11\x22" + FakeServoBus._frame(9, 0, b"\x01\x02")
        frames, _rest = parse_frames(raw)
        self.assertEqual([f["id"] for f in frames], [9])

    def test_parse_frames_multiple(self):
        raw = FakeServoBus._frame(1, 0, b"") + FakeServoBus._frame(2, 0, b"")
        frames, _rest = parse_frames(raw)
        self.assertEqual([f["id"] for f in frames], [1, 2])


# ---------------------------------------------------------------------------
# 2. sync_write 广播字节流
# ---------------------------------------------------------------------------
class TestSyncWrite(unittest.TestCase):

    def test_single_broadcast_frame_for_many_joints(self):
        """核心断言：全部关节目标只产生**一条**帧，且 ID=254、指令=0x83。"""
        sim = FakeServoBus()
        bus, ser = make_bus(sim, verify=False)
        targets = {spec["id"]: 0.0 for spec in JOINTS.values()}
        bus.sync_write(targets)

        self.assertEqual(len(ser.writes), 1, "sync_write 必须只写一帧，不能循环单点写")
        frame = ser.writes[0]
        self.assertEqual(frame[:2], b"\xff\xff")
        self.assertEqual(frame[2], 0xFE)
        self.assertEqual(frame[4], 0x83)
        self.assertEqual(frame[5], ADDR_GOAL_POSITION)
        self.assertEqual(frame[6], 2)                    # 每舵机 2 字节数据（不含行首 ID）
        self.assertEqual(checksum(frame[2:-1]), frame[-1])
        # 数据段长度 = DOF × (1 ID + 2 字节数据)
        self.assertEqual(len(frame[7:-1]), DOF_COUNT * 3)
        self.assertEqual(sim.sync_write_frames, 1)

    def test_payload_matches_config_conversion(self):
        """帧里每个关节的脉冲必须等于 config.deg_to_pulse 的结果。"""
        sim = FakeServoBus()
        bus, ser = make_bus(sim, verify=False)
        bus.sync_write({JOINTS["head_yaw"]["id"]: 30.0,
                        JOINTS["left_knee_pitch"]["id"]: 45.0})

        frame = ser.writes[0]
        rows = frame[7:-1]
        got = {rows[i]: rows[i + 1] | (rows[i + 2] << 8) for i in range(0, len(rows), 3)}
        self.assertEqual(got[JOINTS["head_yaw"]["id"]], deg_to_pulse("head_yaw", 30.0))
        self.assertEqual(got[JOINTS["left_knee_pitch"]["id"]],
                         deg_to_pulse("left_knee_pitch", 45.0))

    def test_servo_actually_moves(self):
        sim = FakeServoBus()
        bus, _ser = make_bus(sim, verify=False)
        bus.sync_write({JOINTS["head_yaw"]["id"]: -20.0})
        self.assertAlmostEqual(bus.read_angle(JOINTS["head_yaw"]["id"]), -20.0, delta=0.1)

    def test_empty_targets_is_noop(self):
        sim = FakeServoBus()
        bus, ser = make_bus(sim, verify=False)
        bus.sync_write({})
        self.assertEqual(ser.writes, [])

    def test_goal_speed_frame_goes_first(self):
        """设了限速就先发一条地址 46 的 SYNC WRITE，再发位置帧。"""
        sim = FakeServoBus()
        bus, ser = make_bus(sim, verify=False, goal_speed=600)
        bus.sync_write({JOINTS["head_yaw"]["id"]: 5.0})
        self.assertEqual(len(ser.writes), 2)
        self.assertEqual(ser.writes[0][5], ADDR_GOAL_SPEED)
        self.assertEqual(ser.writes[1][5], ADDR_GOAL_POSITION)
        self.assertEqual(sim.servos[0][ADDR_GOAL_SPEED]
                         | (sim.servos[0][ADDR_GOAL_SPEED + 1] << 8), 600)

    def test_unknown_joint_id_raises(self):
        bus, _ser = make_bus(FakeServoBus())
        with self.assertRaises(StsProtocolError):
            bus.sync_write({99: 0.0})


# ---------------------------------------------------------------------------
# 3. 角度换算往返与限位钳制
# ---------------------------------------------------------------------------
class TestAngleConversion(unittest.TestCase):

    def test_round_trip_for_all_joints(self):
        sim = FakeServoBus()
        bus, _ser = make_bus(sim)
        for name, spec in JOINTS.items():
            lo, hi = spec["limit_deg"]
            for deg in (lo, 0.0, hi):
                bus.set_angle(spec["id"], deg)
                self.assertAlmostEqual(bus.read_angle(spec["id"]), deg, delta=0.15,
                                       msg=f"{name} @ {deg}° 往返不一致")

    def test_pulse_equals_config_deg_to_pulse(self):
        sim = FakeServoBus()
        bus, _ser = make_bus(sim)
        bus.set_angle(0, 45.0)
        got = sim.servos[0][ADDR_GOAL_POSITION] | \
            (sim.servos[0][ADDR_GOAL_POSITION + 1] << 8)
        self.assertEqual(got, deg_to_pulse("head_yaw", 45.0))

    def test_zero_deg_is_mid_pulse(self):
        sim = FakeServoBus()
        bus, _ser = make_bus(sim)
        bus.set_angle(0, 0.0)
        self.assertEqual(bus.read_pulse(0), 2048)

    def test_set_angle_nan_does_not_write(self):
        sim = FakeServoBus()
        bus, ser = make_bus(sim, verify=False)
        before = bytes(ser.sent_bytes())
        with self.assertRaises(ValueError):
            bus.set_angle(0, float("nan"))
        after = bytes(ser.sent_bytes())
        self.assertEqual(after, before)

    def test_out_of_range_angle_is_clamped_to_pulse_limits(self):
        """超限角度必须被 pulse_limits 钳住，绝不能把越界脉冲发给舵机。"""
        sim = FakeServoBus()
        bus, _ser = make_bus(sim, verify=False)
        lo, hi = pulse_limits("left_knee_pitch")          # 软件限位 0…90° + 3° 外扩
        bus.set_angle(JOINTS["left_knee_pitch"]["id"], 999.0)
        self.assertEqual(bus.read_pulse(JOINTS["left_knee_pitch"]["id"]), hi)
        bus.set_angle(JOINTS["left_knee_pitch"]["id"], -999.0)
        self.assertEqual(bus.read_pulse(JOINTS["left_knee_pitch"]["id"]), lo)
        self.assertTrue(any("钳到" in e for e in bus.last_errors))

    def test_verify_warns_when_servo_does_not_reach(self):
        """写后回读不到位 → 记警告（真机上这就是机械干涉的第一信号）。"""
        sim = FakeServoBus()
        bus, _ser = make_bus(sim)
        sim.block_servo = True                           # 假装舵机卡住没动
        bus.set_angle(0, 10.0)
        self.assertTrue(any("未到位" in e for e in bus.last_errors),
                        f"应报未到位，实际 last_errors={bus.last_errors}")

    def test_calibration_is_applied(self):
        """传入 sign=-1 的标定后，同一角度必须打到中位另一侧。"""
        sim = FakeServoBus()
        old = (JOINTS["head_yaw"]["sign"], JOINTS["head_yaw"]["zero_pulse"])
        try:
            bus, _ser = make_bus(sim, calibrations={
                "joints": {"head_yaw": {"sign": -1, "zero_pulse": 2048}}})
            self.assertEqual(bus.calibration["head_yaw"]["sign"], -1)
            bus.set_angle(0, 30.0)
            self.assertLess(bus.read_pulse(0), 2048)
        finally:
            JOINTS["head_yaw"]["sign"], JOINTS["head_yaw"]["zero_pulse"] = old


# ---------------------------------------------------------------------------
# 4. 超时与坏校验和重试
# ---------------------------------------------------------------------------
class TestRetryAndErrors(unittest.TestCase):

    def test_timeout_raises_after_retries(self):
        sim = FakeServoBus()
        sim.respond = False                              # 舵机一律不应答
        bus, _ser = make_bus(sim, timeout_s=0.005, retries=2)
        t0 = time.monotonic()
        with self.assertRaises(StsTimeoutError) as ctx:
            bus.read_angle(0)
        self.assertLess(time.monotonic() - t0, 3.0)
        msg = str(ctx.exception)
        self.assertIn("已重试 3 次", msg)                # retries=2 → 总尝试 3
        self.assertIn("scan()", msg)                     # 报错要能指导现场排查
        self.assertTrue(bus.last_errors)

    def test_bad_checksum_is_dropped_and_retried(self):
        """前两次回坏校验和、第三次回好包 → 必须成功，且坏帧被计数。"""
        sim = FakeServoBus()
        bus, _ser = make_bus(sim, retries=3)
        original = sim._frame

        state = {"n": 0}

        def flaky(servo_id, status, params, corrupt=False):
            state["n"] += 1
            return original(servo_id, status, params, corrupt=(state["n"] <= 2))

        sim._frame = flaky                                # type: ignore[assignment]
        self.assertEqual(bus.read_pulse(0), 2048)
        self.assertEqual(state["n"], 3)

    def test_bad_checksum_exhausted_reports_clearly(self):
        sim = FakeServoBus()
        sim.corrupt = True
        bus, _ser = make_bus(sim, retries=2)
        with self.assertRaises(StsTimeoutError) as ctx:
            bus.read_angle(0)
        self.assertIn("校验和", str(ctx.exception))
        self.assertGreater(bus.bad_frames, 0)

    def test_wrong_id_reply_is_ignored(self):
        """回包 ID 不对（例如总线上有两个同 ID 舵机）→ 视作无效并重试。"""
        sim = FakeServoBus()
        bus, _ser = make_bus(sim, retries=1)
        sim._frame = lambda sid, st, params, corrupt=False: \
            FakeServoBus._frame(99, st, params)           # type: ignore[assignment]
        with self.assertRaises(StsTimeoutError) as ctx:
            bus.read_pulse(0)
        self.assertIn("ID=99", str(ctx.exception))

    def test_device_status_error_raises(self):
        sim = FakeServoBus()
        bus, _ser = make_bus(sim)
        sim._frame = lambda sid, st, params, corrupt=False: \
            FakeServoBus._frame(sid, 0x20, params)        # type: ignore[assignment]
        with self.assertRaises(StsDeviceError):
            bus.read_pulse(0)

    def test_read_length_too_short_is_retried(self):
        sim = FakeServoBus()
        bus, _ser = make_bus(sim, retries=1)
        sim._frame = lambda sid, st, params, corrupt=False: \
            FakeServoBus._frame(sid, st, b"")             # type: ignore[assignment]
        with self.assertRaises(StsTimeoutError):
            bus.read_pulse(0)

    def test_reply_arriving_in_small_chunks(self):
        """回包被拆成 1 字节一块到达时也要能拼回来（半双工总线上很常见）。"""
        sim = FakeServoBus()
        bus, ser = make_bus(sim)
        ser.chunk_size = 1
        self.assertEqual(bus.read_pulse(0), 2048)
        tele = bus.read_telemetry(0)
        self.assertEqual(tele["temp_c"], 30.0)

    def test_extra_garbage_bytes_do_not_break_sync(self):
        """上一次没读干净的残字节不能污染下一帧的解析。"""
        sim = FakeServoBus()
        bus, ser = make_bus(sim)
        ser._rx += b"\x11\xff\x00garbage"                 # 手工塞点噪声
        self.assertEqual(bus.read_pulse(0), 2048)


# ---------------------------------------------------------------------------
# 5. scan
# ---------------------------------------------------------------------------
class TestScan(unittest.TestCase):

    def test_scan_finds_only_online_ids(self):
        sim = FakeServoBus(ids=[0, 3, 7, 21])
        bus, _ser = make_bus(sim)
        self.assertEqual(bus.scan(id_range=range(0, 22)), [0, 3, 7, 21])

    def test_scan_on_silent_bus_returns_empty(self):
        sim = FakeServoBus()
        sim.respond = False
        bus, _ser = make_bus(sim, timeout_s=0.01)
        self.assertEqual(bus.scan(id_range=range(0, 8)), [])

    def test_scan_sorts_result(self):
        sim = FakeServoBus(ids=[5, 1, 3])
        bus, _ser = make_bus(sim)
        self.assertEqual(bus.scan(id_range=range(0, 6)), [1, 3, 5])

    def test_scan_ignores_broadcast_guard(self):
        """253/254 不是合法舵机 ID，扫描范围即使给到 255 也不能把 254 收进来。"""
        sim = FakeServoBus(ids=[254])
        bus, _ser = make_bus(sim)
        self.assertEqual(bus.scan(id_range=range(250, 256)), [])


# ---------------------------------------------------------------------------
# 6. telemetry 解析
# ---------------------------------------------------------------------------
class TestTelemetry(unittest.TestCase):

    def _bus_with(self, sid: int = 0) -> Tuple[Sts3215Bus, FakeServoBus]:
        sim = FakeServoBus()
        bus, _ser = make_bus(sim)
        return bus, sim

    def test_key_names_match_mock(self):
        """键名必须与 MockServoBus.read_telemetry 一致 —— 上层逻辑靠它切换实现。"""
        bus, _sim = self._bus_with()
        tele = bus.read_telemetry(0)
        for key in ("pos_deg", "load_pct", "voltage_v", "temp_c", "current_a", "moving"):
            self.assertIn(key, tele)

    def test_values_decoded_from_registers(self):
        bus, sim = self._bus_with()
        sim.set_reg(0, ADDR_PRESENT_POSITION, deg_to_pulse("head_yaw", 20.0), 2)
        sim.set_reg(0, ADDR_PRESENT_LOAD, 250, 2)        # 25.0 %
        sim.set_reg(0, ADDR_PRESENT_VOLTAGE, 119)        # 11.9 V
        sim.set_reg(0, ADDR_PRESENT_TEMP, 42)            # 42 ℃
        sim.set_reg(0, 69, 200, 2)                       # 200 × 6.5 mA = 1.3 A
        tele = bus.read_telemetry(0)
        self.assertAlmostEqual(tele["pos_deg"], 20.0, delta=0.2)
        self.assertEqual(tele["load_pct"], 25.0)
        self.assertEqual(tele["voltage_v"], 11.9)
        self.assertEqual(tele["temp_c"], 42.0)
        self.assertAlmostEqual(tele["current_a"], 1.3, places=3)
        self.assertFalse(tele["moving"])

    def test_load_direction_bit(self):
        """寄存器 60 的 bit10 = 方向：置位表示反向负载（负值）。"""
        bus, sim = self._bus_with()
        sim.set_reg(0, ADDR_PRESENT_LOAD, 0x0400 | 300, 2)
        self.assertEqual(bus.read_telemetry(0)["load_pct"], -30.0)

    def test_speed_sign_bit(self):
        bus, sim = self._bus_with()
        sim.set_reg(0, ADDR_PRESENT_SPEED, 0x8000 | 450, 2)
        self.assertEqual(bus.read_telemetry(0)["speed_raw"], -450)

    def test_moving_flag(self):
        bus, sim = self._bus_with()
        sim.set_reg(0, 66, 1)
        self.assertTrue(bus.read_telemetry(0)["moving"])

    def test_voltage_and_current_scale(self):
        bus, sim = self._bus_with()
        sim.set_reg(0, ADDR_PRESENT_VOLTAGE, 126)
        sim.set_reg(0, 69, 1000, 2)                      # 1000 × 6.5 mA = 6.5 A
        tele = bus.read_telemetry(0)
        self.assertEqual(tele["voltage_v"], 12.6)
        self.assertAlmostEqual(tele["current_a"], 6.5, places=3)

    def test_missing_current_register_is_not_fatal(self):
        """个别固件没有 69 号寄存器：电流记 None，其余照常返回。"""
        bus, sim = self._bus_with()
        original_handle = sim._handle

        def no_current(servo_id, instruction, params):
            if instruction == INST_READ and params[0] == 69:
                return b""
            return original_handle(servo_id, instruction, params)

        sim._handle = no_current                       # type: ignore[assignment]
        tele = bus.read_telemetry(0)
        self.assertIsNone(tele["current_a"])
        self.assertEqual(tele["temp_c"], 30.0)
        self.assertTrue(any("电流回读失败" in e for e in bus.last_errors))


# ---------------------------------------------------------------------------
# 7. 安全与 bring-up 语义（松轴 / 限位 / 中位）
# ---------------------------------------------------------------------------
class TestSafetyAndBringup(unittest.TestCase):

    def test_relax_all_is_one_broadcast_frame(self):
        sim = FakeServoBus()
        bus, ser = make_bus(sim)
        bus.relax_all()
        self.assertEqual(len(ser.writes), 1)
        frame = ser.writes[0]
        self.assertEqual(frame[2], 0xFE)                 # 广播
        self.assertEqual(frame[5], ADDR_TORQUE_ENABLE)
        self.assertEqual(frame[6], 0)
        self.assertTrue(all(s[ADDR_TORQUE_ENABLE] == 0 for s in sim.servos.values()))

    def test_scan_all_joints_smokesafe(self):
        """scan() 不能触发任何动作：真机接线未定时，扫描是唯一安全的动作。"""
        sim = FakeServoBus()
        bus, ser = make_bus(sim)
        for sid in sim.servos:
            sim.servos[sid][ADDR_GOAL_POSITION] = 1234
        bus.scan(id_range=range(DOF_COUNT))
        for sid in sim.servos:
            self.assertEqual(sim.servos[sid][ADDR_GOAL_POSITION], 1234)
        # 扫描期间发出的帧必须全部是 PING（指令字段在帧的第 5 字节）
        for frame in ser.writes:
            self.assertEqual(frame[4], INST_PING)

    def test_set_torque_enable(self):
        sim = FakeServoBus()
        bus, _ser = make_bus(sim)
        bus.set_torque_enable([0, 1], False)
        self.assertEqual(sim.servos[0][ADDR_TORQUE_ENABLE], 0)
        self.assertEqual(sim.servos[1][ADDR_TORQUE_ENABLE], 0)
        bus.set_torque_enable([0], True)
        self.assertEqual(sim.servos[0][ADDR_TORQUE_ENABLE], 1)

    def test_write_limits_round_trip_and_power_cycle(self):
        sim = FakeServoBus()
        bus, _ser = make_bus(sim)
        lo, hi = pulse_limits("head_yaw")
        sim.servos[0][ADDR_TORQUE_ENABLE] = 1
        bus.write_limits(0, lo, hi)
        self.assertEqual(sim.servos[0][ADDR_MIN_ANGLE]
                         | (sim.servos[0][ADDR_MIN_ANGLE + 1] << 8), lo)
        self.assertEqual(sim.servos[0][ADDR_MAX_ANGLE]
                         | (sim.servos[0][ADDR_MAX_ANGLE + 1] << 8), hi)
        self.assertEqual(sim.servos[0][ADDR_TORQUE_ENABLE], 1,
                         "写完限位要恢复原来的扭矩状态")

    def test_write_limits_rejects_illegal_range(self):
        bus, _ser = make_bus(FakeServoBus())
        with self.assertRaises(StsProtocolError):
            bus.write_limits(0, 3000, 2000)
        with self.assertRaises(StsProtocolError):
            bus.write_limits(0, -1, 2000)
        with self.assertRaises(StsProtocolError):
            bus.write_limits(0, 0, 5000)

    def test_write_limits_detects_silent_failure(self):
        """写进去了但回读不一致（EEPROM 被锁）→ 必须报错，不能静默通过。"""
        sim = FakeServoBus()
        bus, _ser = make_bus(sim)
        original_handle = sim._handle

        def ignore_writes(servo_id, instruction, params):
            if instruction == INST_WRITE and params[0] in (ADDR_MIN_ANGLE, ADDR_MAX_ANGLE):
                return b""
            return original_handle(servo_id, instruction, params)

        sim._handle = ignore_writes                  # type: ignore[assignment]
        with self.assertRaises(StsDeviceError) as ctx:
            bus.write_limits(0, 1800, 2200)
        self.assertIn("寄存器 55", str(ctx.exception))     # 报错要指向 EEPROM 锁

    def test_set_middle_writes_offset_register(self):
        """默认走真机制：把当前位置记为零位 → 写 31 号位置偏置。"""
        sim = FakeServoBus()
        bus, _ser = make_bus(sim)
        sim.set_reg(0, ADDR_PRESENT_POSITION, 2100, 2)
        offset = bus.set_middle(0)
        self.assertEqual(offset, 2100 - 2048)
        got = sim.servos[0][ADDR_POS_OFFSET] | (sim.servos[0][ADDR_POS_OFFSET + 1] << 8)
        self.assertEqual(got, 52)

    def test_set_middle_negative_offset_is_twos_complement(self):
        sim = FakeServoBus()
        bus, _ser = make_bus(sim)
        sim.set_reg(0, ADDR_PRESENT_POSITION, 1900, 2)
        offset = bus.set_middle(0)
        self.assertEqual(offset, -148)
        got = sim.servos[0][ADDR_POS_OFFSET] | (sim.servos[0][ADDR_POS_OFFSET + 1] << 8)
        self.assertEqual(got, 0x10000 - 148)

    def test_set_middle_compat_path_writes_128_to_40(self):
        """兼容通路：交接文档写的"40 号地址写 128"（只开扭矩、不改零位）。"""
        sim = FakeServoBus()
        bus, _ser = make_bus(sim)
        result = bus.set_middle(0, addr=ADDR_TORQUE_ENABLE)
        self.assertIsNone(result)
        self.assertEqual(sim.servos[0][ADDR_TORQUE_ENABLE], 128)
        self.assertEqual(sim.servos[0][ADDR_POS_OFFSET], 0)
        self.assertTrue(any("兼容通路" in e for e in bus.last_errors))

    def test_unknown_joint_raises_for_every_method(self):
        bus, _ser = make_bus(FakeServoBus())
        for call in (lambda: bus.set_angle(77, 0.0),
                     lambda: bus.read_angle(77),
                     lambda: bus.set_torque_enable([77], True),
                     lambda: bus.write_limits(77, 100, 200),
                     lambda: bus.set_middle(77),
                     lambda: bus.read_telemetry(77)):
            with self.assertRaises(StsProtocolError):
                call()


# ---------------------------------------------------------------------------
# 8. 契约：真的能替换 MockServoBus
# ---------------------------------------------------------------------------
class TestServoBusContract(unittest.TestCase):

    def test_is_subclass_and_implements_all(self):
        self.assertTrue(issubclass(Sts3215Bus, ServoBus))
        for name in ("set_angle", "read_angle", "sync_write", "set_torque_enable",
                     "relax_all", "read_telemetry", "scan", "write_limits",
                     "set_middle"):
            impl = getattr(Sts3215Bus, name)
            base = getattr(ServoBus, name)
            self.assertIsNot(impl, base, f"{name} 没有实现（还在用抽象基类那个）")

    def test_cerebellum_can_drive_it(self):
        """小脑层 `set_pose` → sync_write → 假舵机真的动 —— 无缝替换的关键验收。"""
        sim = FakeServoBus()
        bus, _ser = make_bus(sim, verify=False)
        cere = Cerebellum(servo_bus=bus, sleeper=lambda _dt: None)
        applied = cere.set_pose({"head_yaw": 12.0, "left_knee_pitch": 30.0})
        self.assertEqual(applied["head_yaw"], 12.0)
        self.assertEqual(len(sim.servos), DOF_COUNT)
        self.assertAlmostEqual(bus.read_angle(JOINTS["left_knee_pitch"]["id"]),
                               30.0, delta=0.2)

    def test_get_pose_reads_all_joints(self):
        sim = FakeServoBus()
        bus, _ser = make_bus(sim)
        cere = Cerebellum(servo_bus=bus, sleeper=lambda _dt: None)
        pose = cere.get_pose()
        self.assertEqual(len(pose), DOF_COUNT)
        for name, deg in pose.items():
            self.assertAlmostEqual(deg, 0.0, delta=0.2, msg=name)

    def test_alias_stsbus_exists(self):
        """交接文档里的类名是 StsBus，别名必须指向同一个类。"""
        self.assertIs(StsBus, Sts3215Bus)

    def test_describe_reports_configuration(self):
        bus, _ser = make_bus(FakeServoBus())
        info = bus.describe()
        self.assertEqual(info["port"], "/dev/fake")
        self.assertEqual(info["baudrate"], 1_000_000)
        self.assertTrue(info["opened"])
        self.assertTrue(info["injected_serial"])


# ---------------------------------------------------------------------------
# 9. 无 pyserial 环境下的可用性
# ---------------------------------------------------------------------------
class TestNoPyserialEnvironment(unittest.TestCase):
    """缺 pyserial 时：模块要能导入、构造要能成功，只有 open() 才报中文错。

    ⚠️ 这里**绝不能 `importlib.reload(bus_sts3215)`**：reload 会重建模块里的异常类，
      于是本文件顶部 import 进来的 `StsTimeoutError` 等就成了"旧类"，
      后面所有 `assertRaises` 都会失配（表现为"单独跑绿、一起跑红"）。
      正确做法见 `test_module_imports_without_pyserial_subprocess`：在**子进程**里验证。
    """

    def test_module_imports_without_pyserial_subprocess(self):
        """子进程里屏蔽 pyserial 后仍能 `import atri.bus_sts3215`。"""
        import subprocess
        import sys
        from pathlib import Path

        pkg_root = Path(bus_sts3215.__file__).resolve().parent.parent      # software/atri
        code = (
            "import sys\n"
            "sys.modules['serial'] = None\n"              # import serial 会 ImportError
            "sys.path.insert(0, %r)\n"
            "from atri.bus_sts3215 import Sts3215Bus, StsSerialUnavailable\n"
            "bus = Sts3215Bus('/dev/definitely-not-a-real-port')\n"
            "try:\n"
            "    bus.open()\n"
            "except StsSerialUnavailable as exc:\n"
            "    msg = str(exc)\n"
            "    assert 'pyserial' in msg, 'Missing pyserial must be named in the error'\n"
            "    assert sys.executable in msg, 'interpreter path must be printed'\n"
            "    print('OK')\n"
            "else:\n"
            "    raise SystemExit('open() should have failed without pyserial')\n"
        ) % (str(pkg_root),)
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, timeout=60, cwd=str(pkg_root))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK", proc.stdout)

    def test_serial_factory_injection_bypasses_pyserial(self):
        """注入 serial_factory 时应完全不走 pyserial —— 无库无硬件也能测。"""
        sim = FakeServoBus()
        created: List[FakeSerial] = []

        def factory(**kwargs: Any) -> FakeSerial:
            ser = FakeSerial(sim)
            created.append(ser)
            return ser

        bus = Sts3215Bus("/dev/fake", serial_factory=factory, verify=False)
        bus.sync_write({JOINTS["head_yaw"]["id"]: 0.0})
        self.assertEqual(len(created), 1)
        self.assertEqual(len(created[0].writes), 1)

    def test_constructor_does_not_open_port(self):
        """构造即连接会让 bring-up 流程无法"先看关节表再决定要不要连"。"""
        sim = FakeServoBus()
        called: List[int] = []

        def factory(**kwargs: Any) -> FakeSerial:
            called.append(1)
            return FakeSerial(sim)

        bus = Sts3215Bus("/dev/fake", serial_factory=factory)
        self.assertEqual(called, [])
        bus.open()
        self.assertEqual(len(called), 1)
        bus.close()
        self.assertFalse(bus.describe()["opened"])

    def test_bad_baudrate_rejected(self):
        with self.assertRaises(StsProtocolError):
            Sts3215Bus("/dev/fake", baudrate=9600, ser=FakeSerial(FakeServoBus()))


if __name__ == "__main__":
    unittest.main()
