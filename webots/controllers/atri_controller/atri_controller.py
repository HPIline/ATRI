"""A.T.R.I. Webots 控制器（Windows 联调版）。

与第一版的区别（都是真机联调时才会暴露的问题）：

1. **位置传感器必须先 ``enable()``**：Webots 里未使能的 ``PositionSensor`` 返回 NaN，
   第一版直接把 NaN 当成关节角回传，``get_pose()`` 全废；
2. **显式设置关节最大角速度**：不设的话电机会以最大速度瞬间到位，看不出运动过程；
3. **回零后等待姿态稳定**再开始跑任务卡，否则第一张任务卡和回零动作叠在一起；
4. **推进仿真时间用 ``robot.step``**，按基础步长切片，仿真结束（返回 -1）时立即停止，
   不会继续对已结束的仿真下发角度；
5. **跑完可退出**（``--exit-on-done`` / ``ATRI_WEBOTS_EXIT_ON_DONE=1``），
   这样 ``webots --batch`` 能无人值守跑完并回收，而不是永远挂在保持循环里；
6. **结果可机读**（``--report``），便于把联调结论写进 CI / 文档；
7. 任务卡调度改为复用 ``atri.sim.run_task_cards``，与无硬件闭环演示跑**同一条链路**，
   不再各自维护一份 Mock 观测；
8. 找不到 ``controller`` 模块时以非零码退出，避免"看起来跑成功了"。
9. **可选的扭矩上限**（``--max-torque`` / ``ATRI_WEBOTS_MAX_TORQUE``）：默认 ``None`` = 一个字都不改；
   给了值就对全部绑定的电机调 ``setAvailableTorque()``——**做扭矩校核必须给**，
   因为 Webots 不设 ``maxTorque`` 时默认是 **10 N·m**，而 STS3215 堵转只有 2.94 N·m，
   等于把舵机权限放宽 3.4 倍，"要多少扭矩有多少"，S2 结论直接作废。

用法（GUI 演示）::

    webots webots/worlds/atri_v2.wbt

用法（无界面批量验证，Windows PowerShell）::

    webots --batch --mode=fast --stdout --stderr `
        webots/worlds/atri_v2.wbt -- --exit-on-done --report atri_report.json

用法（用 Webots 内置 Nao 做临时验证）::

    webots --batch --mode=fast --stdout --stderr `
        webots/worlds/atri_nao.wbt -- --exit-on-done --mapping joint_mapping_nao.json

退出码：``0`` = 五项任务全过、仿真全程存活、映射覆盖 20 个关节且全部绑定，
并且至少有一个关节产生了实际行程；``2`` = 上述任一条不满足。
任务卡跑完只证明 FSM 逻辑走通：映射被截断、ATRI 侧键名写错、电机被锁死
（``--velocity 0``）时动作并没有真的走完，不能算联调通过。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:
    from controller import Robot
    try:
        from controller import Supervisor
    except ImportError:  # pragma: no cover
        Supervisor = None  # type: ignore[misc, assignment]
except ImportError:  # pragma: no cover - 只有在 Webots 之外直接运行时才走到
    print(
        "本控制器需要在 Webots 环境中运行（Python 的 controller 模块由 Webots 提供）。\n"
        "离线自检请运行：python -m unittest discover -s webots/tests -v",
        file=sys.stderr,
    )
    raise SystemExit(2)

# 仓库根目录 = 本文件向上 3 级（webots/controllers/atri_controller/ -> 仓库根）
CONTROLLER_DIR = Path(__file__).resolve().parent
ROOT = CONTROLLER_DIR.parents[2]
SOFTWARE_ROOT = ROOT / "software" / "atri"
sys.path.insert(0, str(SOFTWARE_ROOT))

from atri.brain import Brain  # noqa: E402
from atri.cerebellum import Cerebellum, ServoBus  # noqa: E402
from atri.config import JOINTS  # noqa: E402
from atri.stand_balance import (  # noqa: E402
    STAND_KP_PITCH,
    STAND_KP_ROLL,
    STAND_SETTLE_S,
    balance_offsets,
    evaluate_stand,
    mix_pose,
    stand_base_pose,
)
from atri.perception import MockPerception  # noqa: E402
from atri.sim import run_task_cards  # noqa: E402
from atri.voice import MockTTS  # noqa: E402

ID_TO_NAME = {spec["id"]: name for name, spec in JOINTS.items()}

DEFAULT_MAPPING = CONTROLLER_DIR / "joint_mapping.json"
TASK_CARD_DIR = SOFTWARE_ROOT / "task_cards"

# 关节最大角速度（rad/s）。给一个"看得见"的速度，而不是让电机瞬间到位。
DEFAULT_VELOCITY = 2.0
# 回零后的稳定等待（仿真秒）
DEFAULT_SETTLE_S = 0.6


class WebotsServoBus(ServoBus):
    """把 ATRI 关节角写到 Webots ``RotationalMotor``，并回读位置传感器。"""

    def __init__(
        self,
        robot: Robot,
        mapping: Dict[str, str],
        timestep_ms: int,
        velocity: float = DEFAULT_VELOCITY,
        alive: Optional[Callable[[], bool]] = None,
        max_torque: Optional[float] = None,
    ) -> None:
        self.robot = robot
        self.timestep_ms = int(timestep_ms)
        self.velocity = float(velocity)
        # None = 不改行为（沿用世界文件里的 maxTorque，没写就是 Webots 默认 10 N·m）
        self.max_torque = None if max_torque is None else float(max_torque)
        # 真正被设上上限的电机数。桩没有 setAvailableTorque 时会是 0，报告里看得出来。
        self.torque_limited = 0
        self._torque_warned = False
        # 仿真存活判据：robot.step 返回 -1 后 alive() 变 False，之后不得再下发角度
        self._is_alive = alive or (lambda: True)
        self.motors: Dict[str, Any] = {}
        self.sensors: Dict[str, Any] = {}
        self.missing: List[Tuple[str, str]] = []
        # 映射里非空的条目数 = 该机型"应绑定"的关节数；留空表示没有这个自由度
        self.mapped_count = sum(1 for value in mapping.values() if str(value).strip())

        for atri_name, webots_name in mapping.items():
            if not webots_name:
                # 映射里显式留空 = 该机型没有这个自由度（例如 Nao 没有躯干关节）
                self.missing.append((atri_name, "（映射留空）"))
                continue
            motor = robot.getDevice(webots_name)
            if motor is None:
                self.missing.append((atri_name, webots_name))
                print(f"  [WebotsServoBus] 找不到电机: {webots_name} (ATRI: {atri_name})，已跳过")
                continue
            motor.setVelocity(self.velocity)
            self._limit_torque(motor)
            self.motors[atri_name] = motor
            print(f"  [WebotsServoBus] 已绑定: {atri_name} -> {webots_name}")

        self._enable_sensors()

    def _limit_torque(self, motor: Any) -> None:
        """给电机设可用扭矩上限（N·m），等价于世界文件里的 ``RotationalMotor.maxTorque``。

        Webots 不写 ``maxTorque`` 时默认 **10 N·m**（不是无限大，但比 STS3215 堵转
        2.94 N·m 宽 3.4 倍）；不收紧这一项，仿真里扭矩"要多少有多少"，S2 结论作废。

        桩（``webots/tests/webots_api_stub.py``）是个最小替身，没有
        ``setAvailableTorque``：这里**提示一次后跳过**而不是崩掉——离线测试不该因为一个
        可选开关挂掉，但也绝不能假装设上了（报告里的 ``torque_limited_joints`` 会露出来）。
        """
        if self.max_torque is None:
            return
        setter = getattr(motor, "setAvailableTorque", None)
        if setter is None:
            if not self._torque_warned:
                print(
                    "  [WebotsServoBus] 电机对象没有 setAvailableTorque()，"
                    f"maxTorque={self.max_torque} N·m 未生效（离线桩？）",
                    file=sys.stderr,
                )
                self._torque_warned = True
            return
        setter(self.max_torque)
        self.torque_limited += 1

    def _enable_sensors(self) -> None:
        """使能位置传感器。

        Webots 中未 enable 的 PositionSensor，``getValue()`` 返回 NaN，
        必须在第一个仿真步之前调用 ``enable(basicTimeStep)``。
        """
        for atri_name, motor in self.motors.items():
            sensor = motor.getPositionSensor()
            if sensor is None:
                continue
            sensor.enable(self.timestep_ms)
            self.sensors[atri_name] = sensor

    # -- ServoBus 接口 ---------------------------------------------------
    def _write_angle(self, joint_id: int, deg: float) -> None:
        """把基类按 ``limit_deg`` 钳制后的角度换算成弧度下发给电机。

        限位由 ``ServoBus.set_angle`` 模板方法统一保证，这里不再重复钳制。
        仿真已结束（``robot.step`` 返回 -1）时直接返回，不再对已停止的仿真下发。
        """
        if not self._is_alive():
            return
        name = ID_TO_NAME.get(joint_id)
        motor = self.motors.get(name) if name else None
        if motor is not None:
            motor.setPosition(math.radians(float(deg)))

    def read_angle(self, joint_id: int) -> float:
        """回读关节角（度）。

        优先用已使能的位置传感器；没有传感器或读数无效（NaN）时退回到目标角，
        保证 ``get_pose()`` 不会把 NaN 漏出去。
        """
        name = ID_TO_NAME.get(joint_id)
        if name is None:
            return 0.0

        sensor = self.sensors.get(name)
        if sensor is not None:
            value = sensor.getValue()
            if value == value:  # 过滤 NaN
                return math.degrees(value)

        motor = self.motors.get(name)
        if motor is not None:
            target = motor.getTargetPosition()
            if target == target:  # 过滤 NaN
                return math.degrees(target)
        return 0.0

    # -- 联调自检 --------------------------------------------------------
    @property
    def bound_count(self) -> int:
        return len(self.motors)

    def summary(self) -> str:
        text = f"已绑定 {self.bound_count}/{len(JOINTS)} 个关节，未绑定 {len(self.missing)} 个"
        if self.max_torque is not None:
            text += (
                f"；扭矩上限 {self.max_torque} N·m 已设 "
                f"{self.torque_limited}/{self.bound_count} 个"
            )
        return text


def load_mapping(path: Path) -> Dict[str, str]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"关节映射必须是 JSON 对象: {path}")
    return {str(k): str(v) for k, v in data.items()}


def mapping_problems(mapping: Dict[str, str]) -> List[str]:
    """校验映射的键集合恰好是 20 个 ATRI 关节名。

    只比对"绑定数 == 映射非空条目数"无法发现两类配置错误：映射被截断时两个计数
    一起变小；ATRI 侧键名写错时坏条目同时被计入两个计数。两种情况下对应关节
    整轮都不会收到指令，却仍会判通过。值留空是合法的（该机型无此自由度）。
    """
    problems = []
    unknown = sorted(set(mapping) - set(JOINTS))
    if unknown:
        problems.append(f"映射含非法 ATRI 关节名: {', '.join(unknown)}")
    absent = sorted(set(JOINTS) - set(mapping))
    if absent:
        problems.append(
            f"映射缺少 {len(absent)} 个关节（留空值表示该机型无此自由度，不能整条省略）: "
            + ", ".join(absent)
        )
    return problems


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A.T.R.I. Webots 控制器")
    parser.add_argument("--mapping", default=None, help="关节映射 JSON（默认同目录 joint_mapping.json）")
    parser.add_argument("--velocity", type=float, default=DEFAULT_VELOCITY, help="关节最大角速度 rad/s")
    parser.add_argument(
        "--max-torque", type=float, default=None,
        help="统一设置各电机的可用扭矩上限 N·m（默认 None = 不改，Webots 默认 10 N·m；"
             "扭矩校核请给 2.94 = STS3215 堵转）",
    )
    parser.add_argument("--settle-s", type=float, default=DEFAULT_SETTLE_S, help="回零后稳定等待（仿真秒）")
    parser.add_argument("--exit-on-done", action="store_true", help="任务跑完后退出（批量验证用）")
    parser.add_argument("--report", default=None, help="把联调结果写入 JSON 文件")
    parser.add_argument("--log", default=None, help="把控制器控制台输出同时写入文件")
    parser.add_argument("--task-card-dir", default=None, help="任务卡目录（默认 software/atri/task_cards）")
    parser.add_argument(
        "--stand-s",
        type=float,
        default=0.0,
        help=">0 时只做自主站立，不跑任务卡（仿真秒）",
    )
    parser.add_argument(
        "--movie",
        default=None,
        help="Supervisor 录屏 mp4 路径（需要世界里 Robot.supervisor TRUE）",
    )
    parser.add_argument(
        "--cam-dir",
        default=None,
        help="侧视相机 JPEG 目录（stand_cam.saveImage；无头录屏用这个）",
    )
    return parser


def resolve_options(args: argparse.Namespace) -> argparse.Namespace:
    """命令行参数优先，其次读环境变量。

    Webots 本身没有把参数透传给控制器的机制（``webots --help`` 里没有 ``--``），
    从命令行跑 ``--batch`` 时只能靠环境变量把配置传进来。

    这里对 ``--max-torque`` / ``ATRI_WEBOTS_MAX_TORQUE`` 的非法值是**报错退出**，
    不像 ``ATRI_WEBOTS_VELOCITY`` 那样"提示后忽略"：静默退回默认 10 N·m 时，
    仿真照样跑得完、报告照样全绿，只是扭矩数字全错——这种失败必须在启动时就拦住。
    """
    if args.mapping is None:
        args.mapping = os.environ.get("ATRI_WEBOTS_MAPPING") or None
    if args.report is None:
        args.report = os.environ.get("ATRI_WEBOTS_REPORT") or None
    if args.log is None:
        args.log = os.environ.get("ATRI_WEBOTS_LOG") or None
    if args.task_card_dir is None:
        args.task_card_dir = os.environ.get("ATRI_WEBOTS_TASK_CARD_DIR") or None
    if not args.exit_on_done:
        args.exit_on_done = os.environ.get("ATRI_WEBOTS_EXIT_ON_DONE") == "1"
    env_velocity = os.environ.get("ATRI_WEBOTS_VELOCITY")
    if env_velocity and args.velocity == DEFAULT_VELOCITY:
        try:
            args.velocity = float(env_velocity)
        except ValueError:
            print(f"  [控制器] 忽略无效的 ATRI_WEBOTS_VELOCITY={env_velocity!r}")
    env_max_torque = os.environ.get("ATRI_WEBOTS_MAX_TORQUE")
    if env_max_torque and args.max_torque is None:
        try:
            args.max_torque = float(env_max_torque)
        except ValueError:
            raise ValueError(
                f"环境变量 ATRI_WEBOTS_MAX_TORQUE={env_max_torque!r} 不是合法数字"
            ) from None
    if args.max_torque is not None and args.max_torque <= 0:
        raise ValueError(
            f"max-torque 必须 > 0，实际 {args.max_torque}（0 或负数 = 电机没有力矩）"
        )
    env_stand = os.environ.get("ATRI_WEBOTS_STAND_S")
    if env_stand and args.stand_s == 0.0:
        try:
            args.stand_s = float(env_stand)
        except ValueError:
            raise ValueError(f"环境变量 ATRI_WEBOTS_STAND_S={env_stand!r} 不是合法数字") from None
    if args.stand_s < 0:
        raise ValueError(f"stand-s 必须 ≥ 0，实际 {args.stand_s}")
    if args.movie is None:
        args.movie = os.environ.get("ATRI_WEBOTS_MOVIE") or None
    if args.cam_dir is None:
        args.cam_dir = os.environ.get("ATRI_WEBOTS_CAM_DIR") or None
    if not args.cam_dir and args.movie:
        args.cam_dir = str(Path(args.movie).with_suffix("")) + "_frames"
    return args


class _Tee:
    """把控制器输出同时写到终端和文件。

    Webots 的 ``--stdout`` 要等 Webots 自己退出才 flush；批量跑的时候 Webots 因为
    仿真还在继续而不会退出，控制台内容就永远看不到。写到文件里最稳。
    """

    def __init__(self, *streams: Any) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def install_console_log(path_str: Optional[str]) -> Optional[Any]:
    """按需把 stdout/stderr 复制一份到文件，返回文件对象（失败返回 None）。"""
    if not path_str:
        return None
    path = Path(path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "w", encoding="utf-8")
    except OSError as exc:
        print(f"  [控制器] 无法写控制台日志 {path}: {exc}", file=sys.stderr)
        return None
    sys.stdout = _Tee(sys.__stdout__, handle)
    sys.stderr = _Tee(sys.__stderr__, handle)
    print(f"  [控制器] 控制台日志: {path}")
    return handle


def step_seconds(
    robot: Robot,
    timestep_ms: int,
    seconds: float,
    clock: Optional[Dict[str, Any]] = None,
    on_step: Optional[Callable[[], None]] = None,
) -> bool:
    """按基础步长推进 ``seconds`` 仿真秒；仿真结束返回 False。

    传入 ``clock`` 时把真正走过的仿真毫秒累加进去，这样报告里的仿真时间是
    "Webots 实际推进了多少"，而不是"控制器以为自己 sleep 了多少"。
    """
    remaining = max(timestep_ms, int(round(seconds * 1000)))
    while remaining > 0:
        dt = min(timestep_ms, remaining)
        if robot.step(dt) == -1:
            return False
        if clock is not None:
            clock["sim_ms"] = clock.get("sim_ms", 0) + dt
        if on_step is not None:
            on_step()
        remaining -= dt
    return True


def start_movie(robot: Any, path_str: str) -> Optional[str]:
    """开始 Supervisor 录屏；成功返回绝对路径，否则 None。"""
    starter = getattr(robot, "movieStartRecording", None)
    if starter is None:
        print(
            "  [控制器] 当前对象没有 movieStartRecording（需要 Supervisor + supervisor TRUE）",
            file=sys.stderr,
        )
        return None
    path = Path(path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    starter(str(path), 1280, 720, 0, 80, 1, False)
    print(f"  [控制器] 开始录屏: {path}")
    return str(path)


def enable_stand_camera(robot: Any, timestep_ms: int, cam_dir: Optional[str]) -> Optional[Any]:
    """打开骨盆侧视相机。没有这个设备时返回 None（桩/零重力世界）。"""
    if not cam_dir:
        return None
    getter = getattr(robot, "getDevice", None)
    if getter is None:
        return None
    cam = getter("stand_cam")
    if cam is None:
        print("  [控制器] 世界里没有 stand_cam，跳过相机存帧")
        return None
    enable = getattr(cam, "enable", None)
    if enable is not None:
        enable(int(timestep_ms))
    path = Path(cam_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    cam._atri_dir = path  # type: ignore[attr-defined]
    cam._atri_i = 0  # type: ignore[attr-defined]
    print(f"  [控制器] 侧视相机存帧: {path}")
    return cam


def dump_stand_camera(cam: Any, every: int = 5) -> None:
    if cam is None:
        return
    cam._atri_i = int(getattr(cam, "_atri_i", 0)) + 1
    if cam._atri_i % every != 1:
        return
    saver = getattr(cam, "saveImage", None)
    if saver is None:
        return
    dest = Path(cam._atri_dir) / f"{cam._atri_i:05d}.jpg"
    saver(str(dest), 80)


def dump_pose_log(
    fh: Any,
    state: Dict[str, Any],
    xyz,
    rpy,
    pose: Dict[str, float],
    every: int = 10,
) -> None:
    if fh is None:
        return
    fh._atri_n = int(getattr(fh, "_atri_n", 0)) + 1
    if fh._atri_n % every != 1:
        return
    rec = {
        "t": round(state.get("sim_ms", 0) / 1000.0, 3),
        "xyz": [round(float(v), 4) for v in xyz] if xyz is not None else None,
        "rpy": [round(float(v), 5) for v in rpy] if rpy is not None else [0.0, 0.0, 0.0],
        "pose": {k: round(float(v), 3) for k, v in pose.items()},
    }
    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    fh.flush()


def finish_movie(robot: Any, timestep_ms: int) -> None:
    """停录并等到编码器写完文件。"""
    stopper = getattr(robot, "movieStopRecording", None)
    if stopper is None:
        return
    stopper()
    ready = getattr(robot, "movieIsReady", None)
    failed = getattr(robot, "movieFailed", None)
    if ready is not None:
        for _ in range(8000):
            if ready():
                break
            if robot.step(int(timestep_ms)) == -1:
                break
    if failed is not None and failed():
        print("  [控制器] 录屏编码失败", file=sys.stderr)
    else:
        print("  [控制器] 录屏结束")


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Webots 也可能往控制器进程塞自己的参数，用 parse_known_args 不因未知参数崩掉
    args, unknown = build_arg_parser().parse_known_args(argv)
    if unknown:
        print(f"  [控制器] 忽略未知参数: {unknown}")
    try:
        args = resolve_options(args)
    except ValueError as exc:
        # 参数非法时直接失败：带着默认 10 N·m 跑完一轮，扭矩数字全是错的，比跑不起来更糟
        print(f"  [控制器] 参数错误：{exc}", file=sys.stderr)
        return 2
    console_log = install_console_log(args.log)

    movie_path = args.movie
    if movie_path:
        if Supervisor is None:
            print("  [控制器] --movie 需要 Supervisor，当前环境没有", file=sys.stderr)
            return 2
        robot = Supervisor()
    else:
        robot = Robot()
    timestep = int(robot.getBasicTimeStep())
    recording = start_movie(robot, movie_path) if movie_path else None
    stand_cam = enable_stand_camera(robot, timestep, args.cam_dir)

    mapping_path = Path(args.mapping) if args.mapping else DEFAULT_MAPPING
    if not mapping_path.is_absolute():
        mapping_path = CONTROLLER_DIR / mapping_path
    mapping = load_mapping(mapping_path)
    mapping_issues = mapping_problems(mapping)

    print("=" * 64)
    print("A.T.R.I. Webots 控制器启动")
    print(f"  basicTimeStep = {timestep} ms")
    print(f"  关节映射      = {mapping_path.name}")
    print(f"  关节角速度    = {args.velocity} rad/s")
    torque_text = (
        "未设置（沿用世界文件/Webots 默认 10 N·m）"
        if args.max_torque is None
        else f"{args.max_torque} N·m（逐个电机 setAvailableTorque）"
    )
    print(f"  可用扭矩上限  = {torque_text}")
    print("=" * 64)

    # 用 robot.step 推进仿真时间，而不是 time.sleep；alive 与总线共享，
    # 仿真结束后总线不再下发角度。
    state: Dict[str, Any] = {"alive": True, "sim_ms": 0}

    bus = WebotsServoBus(
        robot, mapping, timestep, velocity=args.velocity,
        alive=lambda: state["alive"], max_torque=args.max_torque,
    )
    print(f"  [WebotsServoBus] {bus.summary()}")
    if bus.bound_count == 0:
        print("  [控制器] 一个关节都没绑定上，检查关节映射与机器人模型是否匹配。", file=sys.stderr)

    # 关节实际行程追踪。任务卡跑完只说明 FSM 走通了，不能证明电机真的动了；
    # 这里在每个仿真步之后用位置传感器回读，记录各关节在整轮联调里到过的
    # 最小/最大角，报告里给出真实行程——这才是"联调通过"的证据。
    travel_min: Dict[str, float] = {}
    travel_max: Dict[str, float] = {}
    pelvis_xyz: List[List[float]] = []
    imu_rpy: List[List[float]] = []
    gps = robot.getDevice("pelvis_gps")
    imu = robot.getDevice("imu")
    if gps is not None:
        gps.enable(timestep)
    if imu is not None:
        imu.enable(timestep)

    def sample_pose() -> None:
        for name, spec in JOINTS.items():
            deg = bus.read_angle(spec["id"])
            if deg != deg:  # NaN
                continue
            if name not in travel_min or deg < travel_min[name]:
                travel_min[name] = deg
            if name not in travel_max or deg > travel_max[name]:
                travel_max[name] = deg
        if gps is not None:
            values = list(gps.getValues() or [])
            if len(values) >= 3 and values[2] == values[2]:
                pelvis_xyz.append([float(values[0]), float(values[1]), float(values[2])])
        if imu is not None:
            getter = getattr(imu, "getRollPitchYaw", None)
            if getter is not None:
                rpy = list(getter() or [])
                if len(rpy) >= 3 and rpy[0] == rpy[0]:
                    imu_rpy.append([float(rpy[0]), float(rpy[1]), float(rpy[2])])

    def sleeper(dt_s: float) -> None:
        if not state["alive"]:
            return
        if not step_seconds(robot, timestep, dt_s, state):
            state["alive"] = False
        sample_pose()

    cerebellum = Cerebellum(servo_bus=bus, sleeper=sleeper)
    brain = Brain(cerebellum, perception=MockPerception(), tts=MockTTS())

    started = time.time()

    stand_verdict: Optional[Dict[str, Any]] = None
    stand_trace: List[Dict[str, Any]] = []
    pose_first: Optional[Dict[str, float]] = None
    pose_last: Optional[Dict[str, float]] = None
    if args.stand_s > 0:
        # 自主站立：微蹲 + IMU PD，不跑任务卡。
        for motor in bus.motors.values():
            setter = getattr(motor, "setControlPID", None)
            if setter is not None:
                setter(400.0, 0.0, 20.0)
            torque_set = getattr(motor, "setAvailableTorque", None)
            if torque_set is not None:
                # 盒体世界要撑住 2.3 kg，2.94 N·m 会蹲穿；静立仿真用 20 N·m。
                torque_set(20.0)
        base = stand_base_pose()
        cerebellum.set_pose(base)
        pose_log_fh = None
        if args.cam_dir:
            log_dir = Path(args.cam_dir)
            if not log_dir.is_absolute():
                log_dir = Path.cwd() / log_dir
            log_dir.mkdir(parents=True, exist_ok=True)
            pose_log_fh = open(log_dir / "pose_log.jsonl", "w", encoding="utf-8")
            print(f"  [控制器] 姿态日志: {log_dir / 'pose_log.jsonl'}")

        def dump_media() -> None:
            dump_stand_camera(stand_cam)
            xyz = pelvis_xyz[-1] if pelvis_xyz else None
            rpy = imu_rpy[-1] if imu_rpy else None
            dump_pose_log(pose_log_fh, state, xyz, rpy, cerebellum.get_pose())

        settle_s = max(float(args.settle_s), STAND_SETTLE_S)
        if not step_seconds(
            robot, timestep, settle_s, state,
            on_step=dump_media,
        ):
            state["alive"] = False
        sample_pose()
        dump_media()
        pose_first = cerebellum.get_pose()

        def _trace_stand() -> None:
            z = pelvis_xyz[-1][2] if pelvis_xyz else None
            roll_d = pitch_d = None
            if imu_rpy:
                roll_d = imu_rpy[-1][0] * 180.0 / math.pi
                pitch_d = imu_rpy[-1][1] * 180.0 / math.pi
            stand_trace.append({
                "t": round(state.get("sim_ms", 0) / 1000.0, 3),
                "z": None if z is None else round(float(z), 4),
                "roll_deg": None if roll_d is None else round(float(roll_d), 2),
                "pitch_deg": None if pitch_d is None else round(float(pitch_d), 2),
            })

        _trace_stand()
        print(
            f"  [控制器] 站立姿态就绪 z={stand_trace[-1]['z']} "
            f"roll={stand_trace[-1]['roll_deg']} pitch={stand_trace[-1]['pitch_deg']}，"
            f"开始自主站立 {args.stand_s:.2f} 仿真秒"
        )
        remaining = max(timestep, int(round(args.stand_s * 1000)))
        next_trace_ms = state.get("sim_ms", 0) + 200
        while remaining > 0 and state["alive"]:
            rpy = [0.0, 0.0, 0.0]
            if imu is not None:
                getter = getattr(imu, "getRollPitchYaw", None)
                if getter is not None:
                    got = list(getter() or [])
                    if len(got) >= 3:
                        rpy = [float(got[0]), float(got[1]), float(got[2])]
            offsets = balance_offsets(
                rpy[0], rpy[1], kp_pitch=STAND_KP_PITCH, kp_roll=STAND_KP_ROLL
            )
            cerebellum.set_pose(mix_pose(base, offsets))
            dt = min(timestep, remaining)
            if robot.step(dt) == -1:
                state["alive"] = False
                break
            state["sim_ms"] = state.get("sim_ms", 0) + dt
            remaining -= dt
            sample_pose()
            dump_media()
            if state["sim_ms"] >= next_trace_ms:
                _trace_stand()
                next_trace_ms += 200
        _trace_stand()
        pose_last = cerebellum.get_pose()
        if pose_log_fh is not None:
            pose_log_fh.close()
            pose_log_fh = None
        zs = [p[2] for p in pelvis_xyz]
        rolls = [p[0] * 180.0 / math.pi for p in imu_rpy] if imu_rpy else [0.0] * len(zs)
        pitches = [p[1] * 180.0 / math.pi for p in imu_rpy] if imu_rpy else [0.0] * len(zs)
        if not imu_rpy and zs:
            rolls = [0.0] * len(zs)
            pitches = [0.0] * len(zs)
        stand_verdict = evaluate_stand(zs, rolls, pitches)
        passed = 1 if stand_verdict.get("ok") else 0
        total = 1
        results = [{"task_id": "STAND", "ok": bool(stand_verdict.get("ok")), "history": [], "error": stand_verdict.get("reason")}]
        print(
            f"  [控制器] 站立判定: ok={stand_verdict.get('ok')} "
            f"reason={stand_verdict.get('reason')} "
            f"z=[{stand_verdict.get('z_min')}, {stand_verdict.get('z_max')}] "
            f"tilt={stand_verdict.get('tilt_peak_deg')}"
        )
    else:
        # 1) 先回零，让机器人进入初始站姿，并等姿态稳定
        cerebellum.home()
        if not step_seconds(robot, timestep, args.settle_s, state):
            state["alive"] = False
        sample_pose()
        print(f"  [控制器] 回零完成并稳定 {args.settle_s:.2f} 仿真秒")

        # 2) 顺序执行五项任务卡（与 run_demo.py 同一条链路）
        task_card_dir = Path(args.task_card_dir) if args.task_card_dir else TASK_CARD_DIR
        results, passed, total = run_task_cards(brain, task_card_dir=task_card_dir, verbose=True)

        # 3) 让最后一次动作走完，再回零
        if state["alive"]:
            step_seconds(robot, timestep, args.settle_s, state)
            cerebellum.home()
            step_seconds(robot, timestep, args.settle_s, state)
            sample_pose()

    # 每个关节在整轮联调里的实际行程（最大值 - 最小值，单位：度）
    travel: Dict[str, float] = {}
    for name in JOINTS:
        if name in travel_min and name in travel_max:
            travel[name] = round(travel_max[name] - travel_min[name], 2)
        else:
            travel[name] = 0.0
    moved_joints = sorted(n for n, d in travel.items() if d > 1.0)

    wall = time.time() - started
    sim_seconds = state["sim_ms"] / 1000.0

    # 绑定判据：实际绑定数 == 映射中非空条目数，且 > 0。
    # 不能写成"必须 22/22"——joint_mapping_nao.json 故意留空 4 个自由度（Nao 没有），
    # 绑定 18/22 是预期行为；但非空条目没绑上（电机改名、世界损坏）必须判失败。
    binding_ok = (
        not mapping_issues
        and bus.mapped_count > 0
        and bus.bound_count == bus.mapped_count
    )
    # 绑定完整不等于真的动了：velocity=0 时电机锁死，任务卡照样"逻辑上"跑完。
    # 站立模式目标是稳住，不要求大行程。
    motion_ok = True if args.stand_s > 0 else len(moved_joints) > 0

    print("=" * 64)
    print(f"Webots 闭环: {passed}/{total} 项任务通过")
    print(f"  关节绑定: {bus.bound_count}/{len(JOINTS)}（映射应绑定 {bus.mapped_count}）")
    print(f"  有实际行程的关节: {len(moved_joints)}/{len(JOINTS)}")
    print(f"  仿真时间: {sim_seconds:.2f} s（墙钟 {wall:.2f} s，{state['sim_ms'] // timestep} 步）")
    print("=" * 64)

    payload = {
        "passed": passed,
        "total": total,
        "bound_joints": bus.bound_count,
        "mapped_joints": bus.mapped_count,
        "binding_ok": binding_ok,
        "mapping_problems": mapping_issues,
        "motion_ok": motion_ok,
        "expected_joints": len(JOINTS),
        "unbound_joints": [{"atri": a, "webots": w} for a, w in bus.missing],
        "mapping": mapping_path.name,
        "basic_time_step_ms": timestep,
        "velocity_rad_s": args.velocity,
        # None = 本次没改扭矩上限（世界文件说了算）；扭矩校核场景必须不是 None
        "max_torque_nm": args.max_torque,
        "torque_limited_joints": bus.torque_limited,
        "sim_seconds": round(sim_seconds, 3),
        "sim_steps": state["sim_ms"] // timestep,
        "wall_seconds": round(wall, 3),
        "simulation_alive": state["alive"],
        "moved_joints": len(moved_joints),
        "joint_travel_deg": travel,
        "pelvis_z_m": (
            {
                "n": len(pelvis_xyz),
                "first": round(pelvis_xyz[0][2], 4),
                "last": round(pelvis_xyz[-1][2], 4),
                "min": round(min(p[2] for p in pelvis_xyz), 4),
                "max": round(max(p[2] for p in pelvis_xyz), 4),
                "xy_drift_m": round(
                    max((p[0] ** 2 + p[1] ** 2) ** 0.5 for p in pelvis_xyz), 4
                ),
            }
            if pelvis_xyz
            else {"n": 0, "first": None, "last": None, "min": None, "max": None, "xy_drift_m": None}
        ),
        "imu_tilt_deg": (
            {
                "n": len(imu_rpy),
                "roll_max_abs": round(max(abs(p[0]) for p in imu_rpy) * 180.0 / math.pi, 2),
                "pitch_max_abs": round(max(abs(p[1]) for p in imu_rpy) * 180.0 / math.pi, 2),
            }
            if imu_rpy
            else {"n": 0, "roll_max_abs": None, "pitch_max_abs": None}
        ),
        "mode": "stand" if args.stand_s > 0 else "tasks",
        "stand": stand_verdict,
        "stand_trace": stand_trace,
        "pose_first": (
            {k: round(v, 2) for k, v in pose_first.items()} if pose_first else None
        ),
        "pose_last": (
            {k: round(v, 2) for k, v in pose_last.items()} if pose_last else None
        ),
        "tasks": [
            {
                "task_id": r.get("task_id"),
                "ok": bool(r.get("ok")),
                "history": r.get("history", []),
                "error": r.get("error"),
            }
            for r in results
        ],
    }

    if recording:
        finish_movie(robot, timestep)
        payload["movie"] = recording

    if args.report:
        report_path = Path(args.report)
        if not report_path.is_absolute():
            report_path = Path.cwd() / report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"  联调报告已写入: {report_path}")

    # 退出码：0 = 五项任务全过、仿真全程存活，且映射中声明的关节全部绑定；
    # 绑定不完整（0 绑定、电机名写错、世界损坏）时任务只是"逻辑上"跑完了，
    # 运动并没有真的走完，不能算通过。
    success = (
        passed == total and total > 0 and state["alive"] and binding_ok and motion_ok
    )
    for issue in mapping_issues:
        print(f"  [控制器] 关节映射配置错误：{issue}", file=sys.stderr)
    if not binding_ok and not mapping_issues:
        print(
            f"  [控制器] 绑定不完整：映射应绑定 {bus.mapped_count} 个关节，实际绑定 "
            f"{bus.bound_count} 个，本次联调结果不可信。",
            file=sys.stderr,
        )
    if not motion_ok:
        print(
            "  [控制器] 没有任何关节产生实际行程（检查 --velocity 是否为 0、"
            "电机是否被锁死），任务卡只是逻辑上跑完，不算联调通过。",
            file=sys.stderr,
        )
    if not state["alive"]:
        print(
            "  [控制器] 仿真在任务跑完前结束（robot.step 返回 -1），本次联调结果不可信。",
            file=sys.stderr,
        )

    if args.exit_on_done or not state["alive"]:
        if args.exit_on_done:
            print("  [控制器] --exit-on-done，退出控制器让仿真结束。")
        if console_log is not None:
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
            console_log.close()
        return 0 if success else 2

    print("所有任务卡执行完毕，控制器进入保持循环（Ctrl+C 退出）。")
    while robot.step(timestep) != -1:
        pass
    if console_log is not None:
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
        console_log.close()
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
