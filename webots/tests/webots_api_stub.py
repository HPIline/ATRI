"""Webots ``controller`` 模块的最小可信替身。

目的：让 ``atri_controller.py`` 在没有安装 Webots 的机器和 CI 上也能被端到端验证。

替身刻意复刻了几个**真实 Webots 的坑**，否则测了等于没测：

* ``PositionSensor.getValue()`` 在 ``enable()`` 之前返回 ``NaN``；
* ``Robot.getDevice(name)`` 对模型里不存在的设备返回 ``None``；
* ``Robot.step(dt)`` 在仿真结束后返回 ``-1``；
* 电机默认 ``velocity`` 未设置时为 ``None``（真实 Webots 里是"最大速度"）；
* 电机按 ``velocity``/``maxVelocity`` 限速趋近目标，且被关节 ``minStop``/``maxStop`` 截停，
  ``getValue()`` 返回的是实际位置而不是目标位置。

用法::

    world = FakeWebots(device_names=["head_yaw", ...])
    world.install()                      # 注入 sys.modules["controller"]
    module = load_controller_module()    # 再导入控制器
    code = module.main(["--exit-on-done"])   # 像在 Webots 里一样跑
    world.uninstall()
"""
from __future__ import annotations

import importlib.util
import math
import re
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

NAN = float("nan")

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTROLLER_DIR = REPO_ROOT / "webots" / "controllers" / "atri_controller"
CONTROLLER_PATH = CONTROLLER_DIR / "atri_controller.py"
WORLD_PATH = REPO_ROOT / "webots" / "worlds" / "atri_22dof.wbt"

# 世界文件里没有的电机（例如 Nao 映射的设备）兜底用；真实 Webots 里由模型决定
DEFAULT_MAX_VELOCITY = 10.0


def _string_field(block: str, key: str) -> Optional[str]:
    match = re.search(rf'\b{key}\s+"([^"]*)"', block)
    return match.group(1) if match else None


def _numeric_field(block: str, key: str) -> Optional[float]:
    match = re.search(rf"\b{key}\s+(-?[0-9][0-9eE.+-]*)", block)
    return float(match.group(1)) if match else None


def parse_world_actuators(world_path: Path = WORLD_PATH) -> Dict[str, Dict[str, float]]:
    """解析世界文件：每个电机的 maxVelocity 与其 HingeJoint 的 minStop/maxStop（弧度）。

    HingeJointParameters 与 RotationalMotor 在生成的文件里逐关节同序出现，按序配对。
    """
    text = Path(world_path).read_text(encoding="utf-8")
    params_blocks = re.findall(r"HingeJointParameters\s*\{(.*?)\}", text, re.S)
    motor_blocks = re.findall(r"RotationalMotor\s*\{(.*?)\}", text, re.S)
    specs: Dict[str, Dict[str, float]] = {}
    for params, motor in zip(params_blocks, motor_blocks):
        name = _string_field(motor, "name")
        if not name:
            continue
        specs[name] = {
            "maxVelocity": _numeric_field(motor, "maxVelocity"),
            "minStop": _numeric_field(params, "minStop"),
            "maxStop": _numeric_field(params, "maxStop"),
        }
    return specs


class FakePositionSensor:
    """位置传感器：未使能时 ``getValue()` 返回 NaN（与 Webots 行为一致）。"""

    def __init__(self, name: str, motor: "FakeMotor") -> None:
        self.name = name
        self.motor = motor
        self.enabled = False
        self.sampling_period: Optional[int] = None

    def enable(self, sampling_period: int) -> None:
        self.enabled = True
        self.sampling_period = int(sampling_period)

    def disable(self) -> None:
        self.enabled = False
        self.sampling_period = None

    def getSamplingPeriod(self) -> Optional[int]:
        return self.sampling_period

    def getValue(self) -> float:
        if not self.enabled:
            return NAN
        return self.motor.position


class FakeMotor:
    """RotationalMotor：位置以弧度为单位。

    限速与限位是真实语义的一部分：``setPosition`` 只改目标，位置按当前速度逐步
    趋近，并被 ``minStop``/``maxStop`` 截停——否则“控制器不下发钳制”在离线测试里
    看不出来。

    ``commanded_positions`` 记录每次 ``setPosition`` 收到**未经钳制**的目标，
    供测试断言“下发的角度本身是否越限”。
    """

    def __init__(
        self,
        name: str,
        max_velocity: float = DEFAULT_MAX_VELOCITY,
        min_stop: Optional[float] = None,
        max_stop: Optional[float] = None,
    ) -> None:
        self.name = name
        self.max_velocity = float(max_velocity)
        self.min_stop = min_stop
        self.max_stop = max_stop
        self.target_position = 0.0
        self.position = 0.0
        self.velocity: Optional[float] = None
        self.commanded_positions: List[float] = []
        self.position_sensor = FakePositionSensor(f"{name}_sensor", self)

    def setPosition(self, position: float) -> None:
        self.target_position = float(position)
        self.commanded_positions.append(self.target_position)

    def getTargetPosition(self) -> float:
        return self.target_position

    def setVelocity(self, velocity: float) -> None:
        self.velocity = min(float(velocity), self.max_velocity)

    def getVelocity(self) -> float:
        return self.velocity if self.velocity is not None else -1.0

    def getMaxVelocity(self) -> float:
        return self.max_velocity

    def getPositionSensor(self) -> Optional[FakePositionSensor]:
        return self.position_sensor

    def getType(self) -> int:
        return 1

    def advance(self, dt_s: float) -> None:
        """按当前速度向目标靠拢一步，再被关节限位截停。"""
        speed = self.velocity if self.velocity is not None else self.max_velocity
        speed = min(abs(speed), self.max_velocity)
        remaining = self.target_position - self.position
        step = speed * dt_s
        if abs(remaining) <= step:
            self.position = self.target_position
        else:
            self.position += math.copysign(step, remaining)
        self.position = self._clamp_to_stops(self.position)

    def _clamp_to_stops(self, value: float) -> float:
        if self.min_stop is not None:
            value = max(value, self.min_stop)
        if self.max_stop is not None:
            value = min(value, self.max_stop)
        return value


def make_robot_class(world: "FakeWebots") -> type:
    class Robot:
        def __init__(self) -> None:
            self.name = "atri_fake_robot"
            world.instances.append(self)

        def getDevice(self, name: str) -> Optional[FakeMotor]:
            return world.devices.get(name)

        def getBasicTimeStep(self) -> float:
            return float(world.time_step)

        def step(self, duration: int) -> int:
            return world.step(duration)

    return Robot


class FakeWebots:
    """一次可配置的伪 Webots 运行环境。

    ``motor_specs`` 缺省从世界文件解析：电机拿到真实的 ``maxVelocity`` 与
    关节 ``minStop``/``maxStop``，与真机一致；不在世界文件里的设备（Nao）走兜底值。
    """

    def __init__(
        self,
        device_names: Sequence[str],
        time_step: int = 32,
        max_steps: Optional[int] = 200_000,
        motor_specs: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> None:
        specs = parse_world_actuators() if motor_specs is None else motor_specs
        self.devices: Dict[str, FakeMotor] = {}
        for name in device_names:
            spec = specs.get(name) or {}
            self.devices[name] = FakeMotor(
                name,
                max_velocity=spec.get("maxVelocity") or DEFAULT_MAX_VELOCITY,
                min_stop=spec.get("minStop"),
                max_stop=spec.get("maxStop"),
            )
        self.time_step = time_step
        self.max_steps = max_steps
        self.step_count = 0
        self.sim_time_ms = 0
        self.ended = False
        self.instances: List[Any] = []
        self._module: Optional[types.ModuleType] = None
        self._previous: Any = None

    def step(self, duration_ms: int) -> int:
        """推进一个仿真步：所有电机按速率模型趋近目标。"""
        self.step_count += 1
        self.sim_time_ms += int(duration_ms)
        for motor in self.devices.values():
            motor.advance(int(duration_ms) / 1000.0)
        if self.max_steps is not None and self.step_count > self.max_steps:
            self.ended = True
        return -1 if self.ended else 0

    # -- 生命周期 --------------------------------------------------------
    def install(self) -> types.ModuleType:
        module = types.ModuleType("controller")
        module.Robot = make_robot_class(self)  # type: ignore[attr-defined]
        module.__dict__["__all__"] = ["Robot"]
        self._previous = sys.modules.get("controller")
        sys.modules["controller"] = module
        self._module = module
        return module

    def uninstall(self) -> None:
        if self._previous is not None:
            sys.modules["controller"] = self._previous
        else:
            sys.modules.pop("controller", None)

    # -- 断言辅助 --------------------------------------------------------
    def moved_joints(self) -> List[str]:
        """返回目标角真的被改动过的关节名。"""
        return [name for name, motor in self.devices.items() if motor.commanded_positions]

    def sensors_enabled(self) -> List[str]:
        return [
            name
            for name, motor in self.devices.items()
            if motor.position_sensor.enabled
        ]

    def commanded_degrees(self, name: str) -> List[float]:
        return [math.degrees(rad) for rad in self.devices[name].commanded_positions]


def load_controller_module(name: str = "atri_controller_under_test") -> types.ModuleType:
    """按文件路径加载控制器（Webots 也是这么加载控制器的）。"""
    spec = importlib.util.spec_from_file_location(name, CONTROLLER_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"无法加载控制器: {CONTROLLER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
