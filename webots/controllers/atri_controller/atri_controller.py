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

用法（GUI 演示）::

    webots webots/worlds/atri_22dof.wbt

用法（无界面批量验证，Windows PowerShell）::

    webots --batch --mode=fast --stdout --stderr `
        webots/worlds/atri_22dof.wbt -- --exit-on-done --report atri_report.json

用法（用 Webots 内置 Nao 做临时验证）::

    webots --batch --mode=fast --stdout --stderr `
        webots/worlds/atri_nao.wbt -- --exit-on-done --mapping joint_mapping_nao.json

退出码：``0`` = 五项任务全过且仿真全程存活；``2`` = 有任务失败、或仿真提前结束
（此时任务只是"逻辑上"跑完，动作并没有真的走完，不能算联调通过）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from controller import Robot
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
SOFTWARE_ROOT = ROOT / "软件" / "atri"
sys.path.insert(0, str(SOFTWARE_ROOT))

from atri.brain import Brain  # noqa: E402
from atri.cerebellum import Cerebellum, ServoBus  # noqa: E402
from atri.config import JOINTS  # noqa: E402
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
    ) -> None:
        self.robot = robot
        self.timestep_ms = int(timestep_ms)
        self.velocity = float(velocity)
        self.motors: Dict[str, Any] = {}
        self.sensors: Dict[str, Any] = {}
        self.missing: List[Tuple[str, str]] = []

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
            self.motors[atri_name] = motor
            print(f"  [WebotsServoBus] 已绑定: {atri_name} -> {webots_name}")

        self._enable_sensors()

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
    def set_angle(self, joint_id: int, deg: float) -> None:
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
        return f"已绑定 {self.bound_count}/{len(JOINTS)} 个关节，未绑定 {len(self.missing)} 个"


def load_mapping(path: Path) -> Dict[str, str]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"关节映射必须是 JSON 对象: {path}")
    return {str(k): str(v) for k, v in data.items()}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A.T.R.I. Webots 控制器")
    parser.add_argument("--mapping", default=None, help="关节映射 JSON（默认同目录 joint_mapping.json）")
    parser.add_argument("--velocity", type=float, default=DEFAULT_VELOCITY, help="关节最大角速度 rad/s")
    parser.add_argument("--settle-s", type=float, default=DEFAULT_SETTLE_S, help="回零后稳定等待（仿真秒）")
    parser.add_argument("--exit-on-done", action="store_true", help="任务跑完后退出（批量验证用）")
    parser.add_argument("--report", default=None, help="把联调结果写入 JSON 文件")
    parser.add_argument("--log", default=None, help="把控制器控制台输出同时写入文件")
    parser.add_argument("--task-card-dir", default=None, help="任务卡目录（默认 软件/atri/task_cards）")
    return parser


def resolve_options(args: argparse.Namespace) -> argparse.Namespace:
    """命令行参数优先，其次读环境变量。

    Webots 本身没有把参数透传给控制器的机制（``webots --help`` 里没有 ``--``），
    从命令行跑 ``--batch`` 时只能靠环境变量把配置传进来。
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
        remaining -= dt
    return True


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Webots 也可能往控制器进程塞自己的参数，用 parse_known_args 不因未知参数崩掉
    args, unknown = build_arg_parser().parse_known_args(argv)
    if unknown:
        print(f"  [控制器] 忽略未知参数: {unknown}")
    args = resolve_options(args)
    console_log = install_console_log(args.log)

    robot = Robot()
    timestep = int(robot.getBasicTimeStep())

    mapping_path = Path(args.mapping) if args.mapping else DEFAULT_MAPPING
    if not mapping_path.is_absolute():
        mapping_path = CONTROLLER_DIR / mapping_path
    mapping = load_mapping(mapping_path)

    print("=" * 64)
    print("A.T.R.I. Webots 控制器启动")
    print(f"  basicTimeStep = {timestep} ms")
    print(f"  关节映射      = {mapping_path.name}")
    print(f"  关节角速度    = {args.velocity} rad/s")
    print("=" * 64)

    bus = WebotsServoBus(robot, mapping, timestep, velocity=args.velocity)
    print(f"  [WebotsServoBus] {bus.summary()}")
    if bus.bound_count == 0:
        print("  [控制器] 一个关节都没绑定上，检查关节映射与机器人模型是否匹配。", file=sys.stderr)

    # 用 robot.step 推进仿真时间，而不是 time.sleep
    state: Dict[str, Any] = {"alive": True, "sim_ms": 0}

    # 关节实际行程追踪。任务卡跑完只说明 FSM 走通了，不能证明电机真的动了；
    # 这里在每个仿真步之后用位置传感器回读，记录各关节在整轮联调里到过的
    # 最小/最大角，报告里给出真实行程——这才是"联调通过"的证据。
    travel_min: Dict[str, float] = {}
    travel_max: Dict[str, float] = {}

    def sample_pose() -> None:
        for name, spec in JOINTS.items():
            deg = bus.read_angle(spec["id"])
            if deg != deg:  # NaN
                continue
            if name not in travel_min or deg < travel_min[name]:
                travel_min[name] = deg
            if name not in travel_max or deg > travel_max[name]:
                travel_max[name] = deg

    def sleeper(dt_s: float) -> None:
        if not state["alive"]:
            return
        if not step_seconds(robot, timestep, dt_s, state):
            state["alive"] = False
        sample_pose()

    cerebellum = Cerebellum(servo_bus=bus, sleeper=sleeper)
    brain = Brain(cerebellum, perception=MockPerception(), tts=MockTTS())

    started = time.time()

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
    print("=" * 64)
    print(f"Webots 闭环: {passed}/{total} 项任务通过")
    print(f"  关节绑定: {bus.bound_count}/{len(JOINTS)}")
    print(f"  有实际行程的关节: {len(moved_joints)}/{len(JOINTS)}")
    print(f"  仿真时间: {sim_seconds:.2f} s（墙钟 {wall:.2f} s，{state['sim_ms'] // timestep} 步）")
    print("=" * 64)

    payload = {
        "passed": passed,
        "total": total,
        "bound_joints": bus.bound_count,
        "expected_joints": len(JOINTS),
        "unbound_joints": [{"atri": a, "webots": w} for a, w in bus.missing],
        "mapping": mapping_path.name,
        "basic_time_step_ms": timestep,
        "velocity_rad_s": args.velocity,
        "sim_seconds": round(sim_seconds, 3),
        "sim_steps": state["sim_ms"] // timestep,
        "wall_seconds": round(wall, 3),
        "simulation_alive": state["alive"],
        "moved_joints": len(moved_joints),
        "joint_travel_deg": travel,
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

    if args.report:
        report_path = Path(args.report)
        if not report_path.is_absolute():
            report_path = Path.cwd() / report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"  联调报告已写入: {report_path}")

    # 退出码：0 = 五项任务全过且仿真全程存活；2 = 有任务失败，或仿真提前结束
    # （仿真提前结束时任务只是"逻辑上"跑完了，运动并没有真的走完，不能算通过）
    success = passed == total and total > 0 and state["alive"]
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
