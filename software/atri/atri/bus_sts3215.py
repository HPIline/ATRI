"""飞特 STS3215 / STS3235 总线舵机真机驱动（TTL 半双工，1 Mbps）。

本模块把 `cerebellum.ServoBus` 的抽象语义落到飞特私有协议上，
**换算、限位、关节表一律调用 `atri.config`**，驱动内不重算任何角度/脉冲公式。

协议与寄存器地址的唯一真源
--------------------------
`design/reference/sts3215/PROTOCOL.md`（双源核验过）。本文件顶部把用到的地址
集中成常量，便于对着那份文档逐条核对：

    帧头 0xFF 0xFF；校验和 = ~(ID + Length + Instruction + Params) & 0xFF（不含帧头）

设计要点
--------
1. **无硬件可导入**：`import serial` 是延迟导入，缺 pyserial 时只有真正 `open()`
   才报错，且报的是中文提示 + 该装哪个解释器的 pip 命令，不是 ImportError 崩栈。
2. **串口可注入**：`ser=`（现成对象）或 `serial_factory=`（可调用对象）任一即可，
   单测用内存假串口跑全流程，不需要真实硬件。
3. **`sync_write` 是一条广播帧**（INST_SYNC_WRITE = 0x83），不是循环单点写。
   20 关节逐个写 ≈ 9–18 ms，20 ms 控制周期会直接爆掉（见交接文档 2.4 时序预算）。
4. **半双工**：发出帧后必须收完/放弃回包才能再发下一帧，否则自己的回包会被
   下一帧的起始字节污染。`_transaction()` 用一个锁把所有收发串行化。
5. **读要重试 + 校验和校验**：坏帧丢弃并计数，超次数抛 `StsTimeoutError`。
   写角度用 `config.pulse_limits()` 做边界钳制，绝不把越界脉冲发给舵机。

⚠️ 与 PROTOCOL.md 的一处已知冲突（详见 set_middle 的 docstring）
   交接文档写"中位标定 = 40 号地址写 128"，但两份寄存器表都写明 **40 = 扭矩使能**，
   128 落在该寄存器上等于"开扭矩"而不是"记中位"；真正的零位寄存器是 **31（位置偏置）**。
   本实现的 `set_middle()` 走真机制（读当前位置 → 反推偏置 → 写 31），
   同时把"写 128 到 40"作为可切换的兼容通路保留，并在报告里指出该冲突。

用法
----
    from atri.bus_sts3215 import Sts3215Bus
    bus = Sts3215Bus("/dev/ttyUSB0")         # 真机
    bus.relax_all()                          # 上电先松轴（安全第一）
    print(bus.scan())                        # bring-up 第一步：确认在线 ID
    bus.sync_write({0: 5.0, 6: -10.0})       # 一帧写完多关节
    print(bus.read_telemetry(0))             # 温度/电流/电压/负载

    # 无硬件自测（内存假串口）：
    bus = Sts3215Bus("/dev/fake", serial_factory=make_fake)
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .cerebellum import ServoBus
from .config import (JOINTS, deg_to_pulse, load_calibration, pulse_limits,
                     pulse_to_deg)

__all__ = [
    "Sts3215Bus", "StsBus",
    "StsProtocolError", "StsTimeoutError", "StsChecksumError",
    "StsDeviceError", "StsSerialUnavailable",
    "checksum", "build_frame", "parse_frames", "make_sync_write_frame",
]

# ---------------------------------------------------------------------------
# 协议常量（地址与指令全部来自 design/reference/sts3215/PROTOCOL.md）
# ---------------------------------------------------------------------------
HEADER = b"\xff\xff"

INST_PING = 0x01
INST_READ = 0x02
INST_WRITE = 0x03
INST_SYNC_WRITE = 0x83          # ST 系列取高位置 1（官方 scservo_def.py: 131）

BROADCAST_ID = 0xFE             # 254：广播
MAX_ID = 252                    # 253 与 254 不作为普通舵机 ID

# —— EEPROM（掉电保存；改动前必须关扭矩）——
ADDR_ID = 5
ADDR_BAUD = 6
ADDR_MIN_ANGLE = 9              # 2 字节 L/H
ADDR_MAX_ANGLE = 11             # 2 字节 L/H
ADDR_POS_OFFSET = 31            # 2 字节：零位标定值（真正的"中位"寄存器）
ADDR_MODE = 33
ADDR_LOCK = 55

# —— RAM（实时控制与状态）——
ADDR_TORQUE_ENABLE = 40
ADDR_GOAL_POSITION = 42         # 2 字节 L/H
ADDR_GOAL_TIME = 44             # 2 字节
ADDR_GOAL_SPEED = 46            # 2 字节
ADDR_PRESENT_POSITION = 56      # 2 字节 L/H
ADDR_PRESENT_SPEED = 58         # 2 字节（bit15 = 方向）
ADDR_PRESENT_LOAD = 60          # 2 字节（bit0–9 幅值，bit10 方向）
ADDR_PRESENT_VOLTAGE = 62       # 1 字节 ×0.1 V
ADDR_PRESENT_TEMP = 63          # 1 字节 ℃
ADDR_MOVING = 66                # 1 字节

# 一键状态块：56…66 一次读完（位置/速度/负载/电压/温度/运动中），11 字节
TELEM_START = ADDR_PRESENT_POSITION
TELEM_LEN = ADDR_MOVING - ADDR_PRESENT_POSITION + 1

# 遥测解码用的缩放（与 PROTOCOL.md 3.2 节一致）
VOLTAGE_SCALE = 0.1             # 寄存器 62：×0.1 V
CURRENT_SCALE = 0.0065          # 寄存器 69：×6.5 mA
LOAD_FULL_SCALE = 1000.0        # 寄存器 60：0–1000 对应 0–100%
POSITION_FULL_SCALE = 4095.0    # 位置量程（0–4095）
SPEED_MAX = 4095.0              # 速度量程（0–4095）

# 官方例程常用的速度/加速度档位（0 = 用舵机自身最大速度）
DEFAULT_GOAL_SPEED = 0
DEFAULT_GOAL_ACC = 0

def _pserial_help() -> str:
    """缺 pyserial 时的中文提示。解释器路径用 sys.executable，不写个人机器路径。"""
    import sys
    exe = sys.executable
    return (
        "真机总线需要一个串口后端：未找到 pyserial（`import serial` 失败）。\n"
        "  本仓库的驱动**不自动安装依赖**，请在系统终端手动执行其中一条：\n"
        "    · 装进本项目 venv（推荐，不要另建 venv）：\n"
        f"        {exe} -m pip install -i https://mirrors.aliyun.com/pypi/simple/ pyserial\n"
        "    · 或装进当前解释器：\n"
        f"        {exe} -m pip install -i https://mirrors.aliyun.com/pypi/simple/ pyserial\n"
        f"  装完用 `{exe} -c \"import serial; print(serial.VERSION)\"` 验证。\n"
        "  只想跑软件逻辑（无硬件）时不用装：直接用 MockServoBus，"
        "或给 Sts3215Bus 传 `ser=` / `serial_factory=` 注入假串口。"
    )

# 关节 ID → 关节名 的索引（config 是唯一真源）
def _id_name_map() -> Dict[int, str]:
    """每次现算：**不能缓存**。

    `config.load_calibration()` 会就地改 `JOINTS`，测试与 bring-up 也会临时改
    `spec["id"]`；缓存下来的映射在标定/改表之后就是错的（会把 A 关节的换算
    口径套到 B 关节上）。20 项的字典推导可忽略不计，正确性优先。
    """
    return {spec["id"]: name for name, spec in JOINTS.items()}


def _joint_of_id(joint_id: int) -> str:
    """把关节 ID 映射回 `config.JOINTS` 里的关节名；未知 ID 明确报错。"""
    jid = int(joint_id)
    table = _id_name_map()
    if jid not in table:
        raise StsProtocolError(
            f"未知关节 ID {jid}：不在 config.JOINTS 的 {len(JOINTS)} 个关节里。"
            f"合法 ID：{sorted(table)}"
        )
    return table[jid]


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------
class StsError(Exception):
    """本驱动所有异常的基类，便于调用方一把兜住。"""


class StsProtocolError(StsError):
    """帧格式/参数非法（这类错误重试没有意义，直接抛）。"""


class StsTimeoutError(StsError):
    """重试次数内没有收到完整合法回包（半双工换向没做好、ID 错、线序反了…）。"""


class StsChecksumError(StsProtocolError):
    """回包校验和不对（坏帧会先丢弃再重试，重试耗尽才抛这个）。"""


class StsDeviceError(StsError):
    """舵机回包 status 字节非 0（电压/温度/过载等错误位，见寄存器 65）。"""


class StsSerialUnavailable(StsError):
    """缺 pyserial 或串口打不开。"""


# ---------------------------------------------------------------------------
# 纯函数：帧构造与解析（无副作用，单测直接打这些函数）
# ---------------------------------------------------------------------------
def checksum(body: bytes) -> int:
    """飞特校验和：`~(ID + Length + Instruction + Params) & 0xFF`（不含帧头）。

    入参 body = ID 起、校验和之前的全部字节。
    """
    return (~sum(body)) & 0xFF


def build_frame(servo_id: int, instruction: int, params: bytes = b"") -> bytes:
    """组一帧：`FF FF | ID | Length | Instruction | Params… | Checksum`。

    Length = 参数字节数 + 2（Instruction 与 Checksum 各占 1）。
    """
    if not 0 <= int(servo_id) <= 0xFF:
        raise StsProtocolError(f"ID 必须在 0–255（收到 {servo_id}）")
    if not 0 <= int(instruction) <= 0xFF:
        raise StsProtocolError(f"指令必须在 0–255（收到 {instruction}）")
    params = bytes(params)
    length = len(params) + 2
    if length > 0xFF:
        raise StsProtocolError(f"帧过长：Length={length} > 255，请拆帧")
    body = bytes([int(servo_id), length, int(instruction)]) + params
    return HEADER + body + bytes([checksum(body)])


def make_sync_write_frame(start_addr: int, servo_data: List[bytes]) -> bytes:
    """组 SYNC WRITE（0x83）广播帧：一次把同一寄存器块写给多个 ID。

    ⚠️ 飞特的 SYNC WRITE 载荷是 `起始地址 | 每舵机数据长度 | (ID, data…)×N`，
    **每个舵机的行里都要自带 ID**（官方 SDK `syncWrite` 的实现如此）。
    `servo_data` 的每一项因此必须是"**含 ID 的整行**"，本函数只负责取行长与拼接，
    不替调用方插 ID —— 否则行边界会与 ID 错位一格（真机上表现为"舵机乱转/不动"）。
    """
    if not servo_data:
        raise StsProtocolError("SYNC WRITE 至少要有一个目标舵机（空帧会浪费一个周期）")
    widths = {len(row) - 1 for row in servo_data}         # 行长 − 1（ID 那字节）
    if len(widths) != 1:
        raise StsProtocolError(f"SYNC WRITE 各舵机数据长度必须一致，收到 {sorted(widths)}")
    width = widths.pop()
    if not 0 < width <= 0xFF:
        raise StsProtocolError(f"SYNC WRITE 单舵机数据长度非法：{width}")
    payload = bytes([int(start_addr) & 0xFF, width])
    for row in servo_data:
        if len(row) != width + 1:
            raise StsProtocolError(
                f"SYNC WRITE 行格式应为 [ID] + {width} 字节数据，收到 {len(row)} 字节")
        payload += bytes(row)
    return build_frame(BROADCAST_ID, INST_SYNC_WRITE, payload)


def parse_frames(buf: bytes) -> Tuple[List[Dict[str, Any]], bytes]:
    """从字节流里切出完整且校验正确的舵机回包。

    返回 `(frames, rest)`：frames 是解析出的帧列表，rest 是尚未凑齐/需要丢弃的尾巴。
    坏帧（帧头不对、校验和不对）**就地丢弃**——调用方若一帧都没拿到，会走重试。

    帧结构：`FF FF | ID | Length | Error | Params… | Checksum`（Length = 参数数 + 2）。
    """
    frames: List[Dict[str, Any]] = []
    i = 0
    n = len(buf)
    while i < n:
        if buf[i] != 0xFF:
            i += 1
            continue
        if i + 1 >= n:
            break                                    # 只有半个帧头，等后续字节
        if buf[i + 1] != 0xFF:
            i += 1
            continue
        if i + 3 >= n:
            break                                    # Length 还没到
        length = buf[i + 3]
        if length < 2:
            i += 2                                   # 非法长度，跳过这个帧头
            continue
        total = 2 + 1 + 1 + length                   # 帧头2 + ID1 + Length1 + (Error+Params)+Checksum
        if i + total > n:
            break                                    # 帧没收完，等后续字节
        chunk = buf[i:i + total]
        body = chunk[2:-1]
        if checksum(body) != chunk[-1]:
            i += 2                                   # 坏校验和：丢帧、从下一字节重找帧头
            continue
        frames.append({
            "id": chunk[2],
            "length": length,
            "status": chunk[4],
            "params": chunk[5:-1],
            "raw": chunk,
        })
        i += total
    return frames, buf[i:]


def _u16(lo: int, hi: int) -> int:
    """飞特是小端：低字节在前。"""
    return (int(lo) & 0xFF) | ((int(hi) & 0xFF) << 8)


# ---------------------------------------------------------------------------
# 真机总线
# ---------------------------------------------------------------------------
class Sts3215Bus(ServoBus):
    """飞特 STS3215 / STS3235 总线实现（实现 `cerebellum.ServoBus` 全部语义）。

    参数
    ----
    port          : 串口设备路径，如 `/dev/ttyUSB0`（macOS 常见 `/dev/tty.usbserial-*`）
    baudrate      : 默认 1 000 000（寄存器 6 出厂值 0）。改用别的档位必须先确认舵机已改过。
    timeout_s     : 单次收包超时。半双工总线上"没有回包"是常态（对不存在的 ID 发帧），
                    所以这个值要小：默认 50 ms。
    calibrations  : 直接传入的标定表 `{"joints": {关节名: {"sign":…, "zero_pulse":…}}}`，
                    与 `config/calibration.json` 同构；给了就就地覆盖 `JOINTS`。
                    不传则调用 `config.load_calibration()`（文件不存在时保持出厂默认）。
    ser           : **注入现成串口对象**（无硬件单测用）。给了就不 open。
    serial_factory: **注入串口工厂** `callable(port=…, baudrate=…, timeout=…) -> ser`，
                    用来在无 pyserial 环境下自测（替代 `serial.Serial`）。
    retries       : 读寄存器失败时的重试次数（总尝试 = retries + 1）。
    goal_speed    : 写位置时同时下发的目标速度（0 = 舵机最高速；1–4095 限速）。
    goal_acc      : 加速度（0 = 瞬时；1–254 平滑）。
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 1_000_000,
        timeout_s: float = 0.05,
        calibrations: Optional[dict] = None,
        serial_factory: Optional[Callable[..., Any]] = None,
        ser: Any = None,
        retries: int = 2,
        goal_speed: int = DEFAULT_GOAL_SPEED,
        goal_acc: int = DEFAULT_GOAL_ACC,
        verify: bool = True,
    ) -> None:
        self.port = port
        self.baudrate = int(baudrate)
        self.timeout_s = float(timeout_s)
        self.retries = int(retries)
        self.goal_speed = int(goal_speed)
        self.goal_acc = int(goal_acc)
        self.verify = bool(verify)          # 写后回读位置做闭环校验
        if self.baudrate not in (1_000_000, 500_000, 250_000, 128_000,
                                 115_200, 76_800, 57_600, 38_400):
            raise StsProtocolError(
                f"不支持的波特率 {self.baudrate}；寄存器 6 只认 "
                f"1M/500K/250K/128K/115200/76800/57600/38400"
            )

        # 标定：显式传入优先，否则走 config 的标定文件（不存在 → 出厂默认值）
        if calibrations is not None:
            self.calibration = load_calibration_dict(calibrations)
        else:
            self.calibration = load_calibration()

        self._serial_factory = serial_factory
        self._ser = ser
        self._owns_serial = ser is None
        self._lock = _make_lock()
        self.bad_frames = 0                 # 累计丢弃的坏帧数（诊断用）
        self.last_errors: List[str] = []    # 最近若干条错误描述（诊断用）

        if self._ser is not None:
            self._clamp_goal_speed()

    # ------------------------------------------------------------------
    # 串口生命周期
    # ------------------------------------------------------------------
    def _default_factory(self) -> Callable[..., Any]:
        """延迟导入 pyserial；缺库时给中文指引而不是 ImportError 崩栈。"""
        try:
            import serial                                    # noqa: PLC0415
        except ImportError as exc:                           # pragma: no cover - 环境相关
            raise StsSerialUnavailable(f"{_pserial_help()}\n（原始错误：{exc}）") from None
        return serial.Serial

    def open(self) -> "Sts3215Bus":
        """打开串口（幂等）。注入 `ser=` 时不需要调用。"""
        if self._ser is not None:
            return self
        factory = self._serial_factory or self._default_factory()
        try:
            self._ser = factory(port=self.port, baudrate=self.baudrate,
                                timeout=self.timeout_s)
        except StsSerialUnavailable:
            raise
        except Exception as exc:                             # 端口被占/权限/不存在
            raise StsSerialUnavailable(
                f"打不开串口 {self.port}（{self.baudrate} bps）：{exc}\n"
                f"  排查：① 设备是否插好（macOS `ls /dev/tty.*`，Linux `ls /dev/ttyUSB*`）；"
                f"② 有没有别的程序占着它（串口助手/上一次没退出的进程）；"
                f"③ Linux 下当前用户在不在 dialout 组（`sudo usermod -aG dialout $USER` 后重新登录）。"
            ) from exc
        self._clamp_goal_speed()
        return self

    def close(self) -> None:
        """关闭串口。**上电流程里先松轴再关**，否则舵机会保持最后的锁轴状态。"""
        if self._ser is not None and self._owns_serial:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def __enter__(self) -> "Sts3215Bus":
        return self.open()

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 收发底座
    # ------------------------------------------------------------------
    @contextmanager
    def _connected(self):
        """确保串口可用，并把一次收发整体串行化（半双工不能并发）。"""
        if self._ser is None:
            self.open()
        with self._lock:
            yield self._ser

    def _write_raw(self, data: bytes) -> None:
        ser = self._ser
        if ser is None:
            raise StsSerialUnavailable("串口未打开：先调用 open() 或传 ser=/serial_factory=")
        ser.write(data)
        flush = getattr(ser, "flush", None)
        if callable(flush):
            flush()

    def _read_raw(self, timeout_s: float) -> bytes:
        """在读超时窗口内尽量收字节：能收多少收多少，收不到就返回空。

        ⚠️ 这里**不能**清输入缓冲：半双工总线上回包是在 `write()` 之后才到，
        此刻缓冲里躺着的正是我们刚求来的应答。残留字节的清理由
        `_transaction()` 在发送前完成。
        """
        ser = self._ser
        buf = bytearray()
        try:
            import select                                    # noqa: PLC0415
        except ImportError:                                  # pragma: no cover
            select = None

        deadline = _monotonic() + max(0.0, timeout_s)
        while True:
            if select is not None:
                try:
                    ready, _, _ = select.select([ser], [], [], max(0.0, deadline - _monotonic()))
                    if not ready:
                        break
                except (OSError, ValueError):
                    break
            chunk = _drain(ser)
            if not chunk:
                if select is None:
                    break
                continue
            buf += chunk
            if _monotonic() >= deadline:
                break
        return bytes(buf)

    def _flush_input(self) -> None:
        """丢掉上一次没收干净的残字节（半双工总线上不丢会污染下一帧的解析）。"""
        ser = self._ser
        reset = getattr(ser, "reset_input_buffer", None)
        if callable(reset):
            try:
                reset()
            except Exception:                                # 某些虚拟串口不支持
                pass

    def _transaction(self, frame: bytes, expect_reply: bool,
                     timeout_s: Optional[float] = None) -> Optional[bytes]:
        """一帧一发一收：清残字节 → 写出去 →（需要时）读回；整段占住总线。"""
        wait = self.timeout_s if timeout_s is None else float(timeout_s)
        with self._connected():
            self._flush_input()                              # 必须在写之前
            self._write_raw(frame)
            if not expect_reply:
                return None
            return self._read_raw(wait)

    def _warn(self, msg: str) -> None:
        self.last_errors.append(msg)
        del self.last_errors[:-32]                           # 只留最近 32 条

    # ------------------------------------------------------------------
    # 单点指令
    # ------------------------------------------------------------------
    def write_regs(self, joint_id: int, addr: int, data: bytes) -> None:
        """WRITE：给单个 ID 写一段寄存器。"""
        frame = build_frame(int(joint_id), INST_WRITE, bytes([int(addr) & 0xFF]) + bytes(data))
        self._transaction(frame, expect_reply=False)

    def _read_regs(self, joint_id: int, addr: int, length: int,
                   retries: Optional[int] = None) -> bytes:
        """READ：读一段寄存器，**校验和校验 + 重试**；坏帧丢弃并计数。

        重试耗尽抛 `StsTimeoutError`（含累计的坏帧/超时信息，便于现场判断是
        线序反了、ID 不对，还是波特率不匹配）。
        """
        if not 0 < length <= 0xFF:
            raise StsProtocolError(f"要读的字节数必须 1–255（收到 {length}）")
        attempts = (self.retries if retries is None else int(retries)) + 1
        frame = build_frame(int(joint_id), INST_READ,
                            bytes([int(addr) & 0xFF, int(length) & 0xFF]))
        trouble: List[str] = []
        corrupted = 0
        for attempt in range(1, attempts + 1):
            raw = self._transaction(frame, expect_reply=True) or b""
            frames, _rest = parse_frames(raw)
            matched = False
            for f in frames:
                if f["id"] != int(joint_id):
                    trouble.append(f"第{attempt}次：回包 ID={f['id']} 不是 {joint_id}")
                    matched = True                    # 收到了别人的回包，不算坏帧
                    continue
                matched = True
                if f["status"] != 0:
                    raise StsDeviceError(
                        f"舵机 {joint_id} 回包 status={f['status']}（错误位掩码，见寄存器 65）"
                    )
                if len(f["params"]) < length:
                    trouble.append(
                        f"第{attempt}次：只回了 {len(f['params'])} 字节，少于请求的 {length}")
                    continue
                return bytes(f["params"][:length])
            if not matched:
                if raw:
                    corrupted += 1
                    self.bad_frames += 1
                    trouble.append(f"第{attempt}次：收到 {len(raw)} 字节但校验和不通过，坏帧已丢弃")
                else:
                    trouble.append(
                        f"第{attempt}次：超时（{self.timeout_s * 1000:.0f} ms 内无回包）")
        detail = "；".join(trouble)
        hint = ("每次都是校验和不对 → 优先查波特率是否 1 Mbps、线是否过长/未共地；"
                if corrupted == attempts else "全部超时 → 优先查 ID、半双工换向与供电；")
        self._warn(f"读舵机 {joint_id} 寄存器 {addr} 失败：{detail}")
        raise StsTimeoutError(
            f"读舵机 {joint_id} 寄存器 {addr}（{length} 字节）失败，"
            f"已重试 {attempts} 次（坏帧 {corrupted} 个）：{detail}\n"
            f"  排查：① 该 ID 是否在线（先 scan()）；② 波特率是否 1 Mbps（寄存器 6）；"
            f"③ 半双工换向（URT-1 自动换向 / 自绘板 DE-RE 时序）；④ 供电与共地。{hint}"
        )

    def ping(self, servo_id: int, timeout_s: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """PING 单个 ID：在线返回回包字典，不在线返回 None（**不抛异常**，scan 要用）。"""
        frame = build_frame(int(servo_id), INST_PING)
        wait = self.timeout_s if timeout_s is None else float(timeout_s)
        raw = self._transaction(frame, expect_reply=True, timeout_s=wait) or b""
        frames, _rest = parse_frames(raw)
        for f in frames:
            if f["id"] == int(servo_id):
                return f
        if raw:
            self.bad_frames += 1
        return None

    # ------------------------------------------------------------------
    # ServoBus：基础读写
    # ------------------------------------------------------------------
    def set_angle(self, joint_id: int, deg: float) -> None:
        """单关节写目标角：角度 → 脉冲走 `config.deg_to_pulse`，边界用 `pulse_limits` 钳制。"""
        name = _joint_of_id(joint_id)
        pulse = self._clamp_pulse(name, deg)
        self.write_regs(joint_id, ADDR_GOAL_POSITION, _le16(pulse))
        if self.verify:
            self._check_reach(joint_id, pulse, deg)

    def read_angle(self, joint_id: int) -> float:
        """回读角度：读寄存器 56（2 字节），反算走 `config.pulse_to_deg`。"""
        name = _joint_of_id(joint_id)
        raw = self._read_regs(joint_id, ADDR_PRESENT_POSITION, 2)
        return pulse_to_deg(name, _u16(raw[0], raw[1]))

    def read_pulse(self, joint_id: int) -> int:
        """回读原始脉冲（bring-up 标定时要用，比角度更直观）。"""
        _joint_of_id(joint_id)
        raw = self._read_regs(joint_id, ADDR_PRESENT_POSITION, 2)
        return _u16(raw[0], raw[1])

    # ------------------------------------------------------------------
    # ServoBus：批量写（20 ms 周期的硬性前提）
    # ------------------------------------------------------------------
    def sync_write(self, targets: Dict[int, float]) -> None:
        """**一条广播 SYNC WRITE 帧**写完全部目标关节。

        顺序：先匀速帧（地址 46，可选）→ 再位置帧（地址 42）。
        ⚠️ 位置必须放在最后：舵机一旦拿到完整的目标位置就朝它走，
        所以"限速"要先落地（见 PROTOCOL.md 的寄存器说明与交接文档 6.3）。
        """
        if not targets:
            return
        clamped: Dict[int, int] = {}
        wanted_deg: Dict[int, float] = {}
        for jid, deg in targets.items():
            name = _joint_of_id(jid)
            clamped[int(jid)] = self._clamp_pulse(name, deg)
            wanted_deg[int(jid)] = float(deg)

        # —— 限速/加速度帧（可选，必须先落地）——
        # 注意让只写加速度时也占 2 字节：SYNC WRITE 要求所有行等宽，而 46 号是 16 位。
        if self.goal_speed or self.goal_acc:
            speed_rows: List[bytes] = []
            for jid in sorted(clamped):
                if self.goal_speed:
                    body = _le16(self.goal_speed) + bytes([self.goal_acc & 0xFF])
                else:                                        # 只写加速度：地址后移 2
                    body = bytes([self.goal_acc & 0xFF, 0x00])
                speed_rows.append(bytes([int(jid)]) + body)
            start_addr = ADDR_GOAL_SPEED if self.goal_speed else ADDR_GOAL_SPEED + 2
            self._transaction(make_sync_write_frame(start_addr, speed_rows),
                              expect_reply=False)

        rows = [bytes([int(jid)]) + _le16(pulse) for jid, pulse in sorted(clamped.items())]
        self._transaction(make_sync_write_frame(ADDR_GOAL_POSITION, rows),
                          expect_reply=False)

        if self.verify:
            for jid, pulse in sorted(clamped.items()):
                self._check_reach(jid, pulse, wanted_deg[jid])

    def set_torque_enable(self, joint_ids: List[int], enable: bool) -> None:
        """松/锁轴（寄存器 40）。上电第一件事是 `relax_all()`。"""
        value = 1 if enable else 0
        for jid in joint_ids:
            _joint_of_id(jid)
            self.write_regs(jid, ADDR_TORQUE_ENABLE, bytes([value]))

    def relax_all(self) -> None:
        """全总线松轴：**广播**写 40=0，一帧搞定（上电/急停都该立刻能做）。"""
        self.write_regs(BROADCAST_ID, ADDR_TORQUE_ENABLE, b"\x00")

    # ------------------------------------------------------------------
    # ServoBus：遥测
    # ------------------------------------------------------------------
    def read_telemetry(self, joint_id: int) -> Dict[str, Any]:
        """读 56…66 一块（位置/速度/负载/电压/温度/运动中）+ 69/70 电流。

        键名与 `MockServoBus.read_telemetry` 对齐：
            pos_deg / load_pct / voltage_v / temp_c / current_a / moving
        另附真机专有的诊断键（Mock 没有，但多给不算破坏契约）：
            speed_raw / current_raw / load_raw / position_raw / status
        """
        name = _joint_of_id(joint_id)
        block = self._read_regs(joint_id, TELEM_START, TELEM_LEN)
        pos_raw = _u16(block[0], block[1])
        speed_raw = _u16(block[2], block[3])
        load_raw = _u16(block[4], block[5])
        voltage_raw = block[6]
        temp_c = block[7]
        moving = bool(block[TELEM_LEN - 1])

        load_dir = -1 if (load_raw & 0x0400) else 1              # bit10 = 方向
        load_pct = round(load_dir * (load_raw & 0x03FF) / LOAD_FULL_SCALE * 100.0, 1)

        speed_val = speed_raw & 0x7FFF                           # bit15 = 方向
        if speed_raw & 0x8000:
            speed_val = -speed_val

        current_a = None
        try:
            cur = self._read_regs(joint_id, 69, 2, retries=1)
            current_a = round(_u16(cur[0], cur[1]) * CURRENT_SCALE, 3)
        except StsError as exc:
            # 12V 版规格书声称支持电流回读；个别固件版本没有该寄存器 —— 不致命，标注即可
            self._warn(f"舵机 {joint_id} 电流回读失败（寄存器 69）：{exc}")

        return {
            "pos_deg": round(pulse_to_deg(name, pos_raw), 3),
            "load_pct": load_pct,
            "voltage_v": round(voltage_raw * VOLTAGE_SCALE, 1),
            "temp_c": float(temp_c),
            "current_a": current_a,
            "moving": moving,
            "speed_raw": speed_val,
            "current_raw": None if current_a is None else int(round(current_a / CURRENT_SCALE)),
            "load_raw": load_raw,
            "position_raw": pos_raw,
            "status": 0,
        }

    # ------------------------------------------------------------------
    # ServoBus：bring-up（扫描 / 限位 / 中位）
    # ------------------------------------------------------------------
    def scan(self, id_range: Iterable[int] = range(0, MAX_ID + 1),
             timeout_s: float = 0.002) -> List[int]:
        """0–253 逐个 PING，返回在线 ID 列表（升序）。

        ⚠️ 总线扫描必须用**小超时**：253 个 ID × 50 ms = 12.7 s，
        20 ms 控制周期里根本等不起；默认每 ID 只等 2 ms（1 Mbps 下一帧回包 ≈ 0.1 ms，
        足够宽裕）。真机上若发现漏扫，把这个值调到 5–10 ms 再试。
        """
        found: List[int] = []
        for sid in id_range:
            if 0 <= int(sid) <= MAX_ID and self.ping(int(sid), timeout_s=timeout_s):
                found.append(int(sid))
        return sorted(found)

    def write_limits(self, joint_id: int, pulse_lo: int, pulse_hi: int) -> None:
        """写 min/max angle 限位（**EEPROM 9 / 11**，2 字节小端）→ 复位 → 回读校验。

        限位在 EEPROM：必须先关扭矩，写完再复位让寄存器生效（PROTOCOL.md 3.3）。
        回读不一致抛 `StsDeviceError`——静默失败会导致"软件以为限住了、舵机照转"。
        """
        _joint_of_id(joint_id)
        lo, hi = int(pulse_lo), int(pulse_hi)
        if not 0 <= lo < hi <= 4095:
            raise StsProtocolError(f"限位脉冲非法：lo={lo}, hi={hi}（要求 0 ≤ lo < hi ≤ 4095）")

        torque_before = True
        try:
            torque_before = bool(self._read_regs(joint_id, ADDR_TORQUE_ENABLE, 1)[0])
        except StsError:
            torque_before = False                            # 读不到就按"关着"处理，写完不回锁
        self.write_regs(joint_id, ADDR_TORQUE_ENABLE, b"\x00")
        self.write_regs(joint_id, ADDR_MIN_ANGLE, _le16(lo))
        self.write_regs(joint_id, ADDR_MAX_ANGLE, _le16(hi))
        self.reset(joint_id)

        back = self._read_regs(joint_id, ADDR_MIN_ANGLE, 4)
        got_lo, got_hi = _u16(back[0], back[1]), _u16(back[2], back[3])
        if (got_lo, got_hi) != (lo, hi):
            raise StsDeviceError(
                f"舵机 {joint_id} 限位回读不一致：写入 ({lo}, {hi})，回读 ({got_lo}, {got_hi})。"
                f"EEPROM 可能被锁（寄存器 55=1）——先写 55=0 解锁再写限位。"
            )
        if torque_before:
            self.write_regs(joint_id, ADDR_TORQUE_ENABLE, b"\x01")

    def set_middle(self, joint_id: int, addr: int = ADDR_POS_OFFSET,
                   expect_pulse: int = 2048) -> Optional[int]:
        """中位标定：把**当前位置**记为该关节的机械零位。

        ⚠️ 与交接文档的一处冲突（本实现按"能真正生效"的做法走）
        ------------------------------------------------------
        交接文档（`design/handoff/给Grok-真机链路对接文档.md` 2.2 / 3.2）与
        `cerebellum.set_middle` 的 docstring 都写"中位标定 = 40 号地址写 128"。
        但两份寄存器表（`PROTOCOL.md` 3.2 与 `STS3215_Register_Reference.md`）
        都写明 **40 = Torque Enable（0=松轴, 1=锁轴）**，128 落在该寄存器上
        只是"开扭矩"（非 0 即使能），并**不会**改变零位；
        真正的零位寄存器是 **31 = Position Offset（位置偏置，2 字节）**。
        猜测"128"来自另一套量纲：把这个关节在 0–255 里居中就是 −128 的偏置
        （2048 − 0x0C80 → 偏置 −3200×… 见下），或来自飞特上位机工具的提示文案。
        处理方式：**默认走真机制**（读当前位置 → 反推偏置 → 写 31），
        并把"写 128 到 40"作为可切换通路（`addr=ADDR_TORQUE_ENABLE`）保留，
        冲突已记进 `design/handoff/线程报告-真机总线驱动.md`，请以 PROTOCOL.md 为准。

        流程（EEPROM 写入的标准顺序）：
            读当前位置 P → 关扭矩(40=0) → 写偏置(31 = P − expect_pulse) → 复位 → 开扭矩
        返回实际写入的偏置值（int16）。
        """
        _joint_of_id(joint_id)
        if addr == ADDR_TORQUE_ENABLE:
            # 兼容通路：交接文档字面写法（只开扭矩，**不改零位**）
            self.write_regs(joint_id, ADDR_TORQUE_ENABLE, bytes([128 & 0xFF]))
            self._warn(
                f"set_middle({joint_id}) 走的是兼容通路（40 号地址写 128）——"
                f"它只开扭矩、不改零位；真实零位需写寄存器 31。"
            )
            return None

        cur = self._read_regs(joint_id, ADDR_PRESENT_POSITION, 2)
        pulse = _u16(cur[0], cur[1])
        offset = int(pulse) - int(expect_pulse)               # 以当前位置为零位
        torque_before = bool(self._read_regs(joint_id, ADDR_TORQUE_ENABLE, 1)[0])

        self.write_regs(joint_id, ADDR_TORQUE_ENABLE, b"\x00")
        self.write_regs(joint_id, addr, _le16_signed(offset))
        self.reset(joint_id)
        if torque_before:
            self.write_regs(joint_id, ADDR_TORQUE_ENABLE, b"\x01")

        back = _u16s(*self._read_regs(joint_id, addr, 2))
        if back != offset:
            raise StsDeviceError(
                f"舵机 {joint_id} 零位偏置回读不一致：写入 {offset}，回读 {back}"
            )
        return offset

    def reset(self, joint_id: int = BROADCAST_ID) -> None:
        """给舵机一点刷新时间（EEPROM 写完后生效）。

        飞特协议**没有独立的 RESET 指令**，也没有真正的软复位帧；EEPROM 项
        （限位 9/11、偏置 31、ID 5、波特率 6）写完即生效，但官方 SDK 在
        `writeTxRx` 之后统一 `time.sleep(0.02)`，因为部分固件版本对 EEPROM
        写入有几十毫秒的落盘时间。这里保留同样的延时语义，避免"写完立刻回读读到旧值"。
        """
        _sleep(0.02)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _clamp_pulse(self, name: str, deg: float) -> int:
        """角度 → 脉冲，并用 `config.pulse_limits` 钳到机械安全范围内。"""
        pulse = deg_to_pulse(name, deg)
        lo, hi = pulse_limits(name)
        clamped = max(int(lo), min(int(hi), int(pulse)))
        if clamped != int(pulse):
            self._warn(f"{name}: {deg}° → 脉冲 {pulse} 越界，已钳到 {clamped}（{lo}…{hi}）")
        return clamped

    def _check_reach(self, joint_id: int, pulse: int, deg: float,
                     tol_pulse: int = 12) -> None:
        """写后回读位置做闭环校验：不达标只记警告，不打断控制周期。

        12 脉冲 ≈ 1°（0.088°/脉冲），是"到位 vs 卡住"的合理判据。
        抖动大/正在走的关节可能读回旧值，所以这里**只警告不抛异常**。
        """
        try:
            now = self.read_pulse(joint_id)
        except StsError as exc:
            self._warn(f"舵机 {joint_id} 写后回读失败：{exc}")
            return
        if abs(now - int(pulse)) > tol_pulse:
            self._warn(
                f"舵机 {joint_id} 未到位：目标 {deg:.2f}°→{pulse}，实测 {now}"
                f"（差 {now - int(pulse)} 脉冲，约 {(now - int(pulse)) * 360 / 4096:.1f}°）"
                f"——查机械干涉/装配过紧/限位寄存器。"
            )

    def _clamp_goal_speed(self) -> None:
        if not 0 <= self.goal_speed <= SPEED_MAX:
            raise StsProtocolError(f"goal_speed 必须 0–4095（0=最高速），收到 {self.goal_speed}")
        if not 0 <= self.goal_acc <= 254:
            raise StsProtocolError(f"goal_acc 必须 0–254（0=瞬时），收到 {self.goal_acc}")

    def describe(self) -> Dict[str, Any]:
        """当前连接与配置摘要（打印进 bring-up 报告用）。"""
        return {
            "port": self.port,
            "baudrate": self.baudrate,
            "timeout_s": self.timeout_s,
            "goal_speed": self.goal_speed,
            "goal_acc": self.goal_acc,
            "verify": self.verify,
            "opened": self._ser is not None,
            "injected_serial": not self._owns_serial,
            "calibrated_joints": sorted(self.calibration),
            "bad_frames": self.bad_frames,
        }


# 交接文档里用的类名是 StsBus，这里给个别名，免得 bring-up 命令要改
StsBus = Sts3215Bus


# ---------------------------------------------------------------------------
# 小工具（不依赖第三方库）
# ---------------------------------------------------------------------------
def load_calibration_dict(calibrations: dict) -> Dict[str, Any]:
    """把外部传入的标定字典就地覆盖到 `JOINTS`（与 config.load_calibration 同构）。

    支持两种写法：`{"joints": {...}}`（文件格式）或直接 `{关节名: {...}}`。
    """
    from .config import JOINTS as _JOINTS

    joints = calibrations.get("joints") if isinstance(calibrations, dict) else None
    if joints is None:
        joints = calibrations if isinstance(calibrations, dict) else {}
    applied: Dict[str, Any] = {}
    for name, cal in (joints or {}).items():
        if name not in _JOINTS or not isinstance(cal, dict):
            continue
        spec = _JOINTS[name]
        if "sign" in cal:
            spec["sign"] = -1 if int(cal["sign"]) < 0 else 1
        if "zero_pulse" in cal:
            spec["zero_pulse"] = int(max(0, min(4095, int(cal["zero_pulse"]))))
        applied[name] = {"sign": spec["sign"], "zero_pulse": spec["zero_pulse"]}
    return applied


def _le16(value: int) -> bytes:
    """16 位小端（飞特寄存器 42/56 等都是 L 在前）。"""
    v = int(value) & 0xFFFF
    return bytes([v & 0xFF, (v >> 8) & 0xFF])


def _le16_signed(value: int) -> bytes:
    """有符号 16 位小端（寄存器 31 位置偏置可为负，按二补码下发）。"""
    v = int(value)
    if not -32768 <= v <= 32767:
        raise StsProtocolError(f"偏置超出 int16 范围：{v}")
    return _le16(v & 0xFFFF)


def _u16s(lo: int, hi: int) -> int:
    """有符号 16 位小端解码。"""
    v = _u16(lo, hi)
    return v - 0x10000 if v & 0x8000 else v


def _monotonic() -> float:
    import time
    return time.monotonic()


def _sleep(seconds: float) -> None:
    import time
    time.sleep(seconds)


def _drain(ser: Any) -> bytes:
    """把串口里当前可读的字节尽量取出（兼容 pyserial 与内存假串口）。"""
    waiting = getattr(ser, "in_waiting", 0)
    try:
        waiting = int(waiting or 0)
    except (TypeError, ValueError):
        waiting = 0
    if waiting:
        data = ser.read(waiting)
    else:
        try:
            data = ser.read(1)
        except Exception:
            data = b""
    return bytes(data or b"")


def _make_lock() -> Any:
    import threading
    return threading.RLock()
