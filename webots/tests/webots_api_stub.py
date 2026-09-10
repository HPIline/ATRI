"""Webots ``controller`` 模块的最小可信替身。

目的：让 ``atri_controller.py`` 在没有安装 Webots 的机器和 CI 上也能被端到端验证。

替身刻意复刻了几个**真实 Webots 的坑**，否则测了等于没测：

* ``PositionSensor.getValue()`` 在 ``enable()`` 之前返回 ``NaN``；
* ``Robot.getDevice(name)`` 对模型里不存在的设备返回 ``None``；
* ``Robot.step(dt)`` 在仿真结束后返回 ``-1``；
* 电机默认 ``velocity`` 未设置时为 ``None``（真实 Webots 里是"最大速度"）。

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
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

NAN = float("nan")

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTROLLER_DIR = REPO_ROOT / "webots" / "controllers" / "atri_controller"
CONTROLLER_PATH = CONTROLLER_DIR / "atri_controller.py"


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
        return self.motor.target_position


class FakeMotor:
    """RotationalMotor：位置以弧度为单位。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.target_position = 0.0
        self.velocity: Optional[float] = None
        self.position_sensor = FakePositionSensor(f"{name}_sensor", self)
        self.position_history: List[float] = []

    def setPosition(self, position: float) -> None:
        self.target_position = float(position)
        self.position_history.append(self.target_position)

    def getTargetPosition(self) -> float:
        return self.target_position

    def setVelocity(self, velocity: float) -> None:
        self.velocity = float(velocity)

    def getVelocity(self) -> float:
        return self.velocity if self.velocity is not None else -1.0

    def getMaxVelocity(self) -> float:
        return 10.0

    def getPositionSensor(self) -> Optional[FakePositionSensor]:
        return self.position_sensor

    def getType(self) -> int:
        return 1


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
            world.step_count += 1
            world.sim_time_ms += int(duration)
            if world.max_steps is not None and world.step_count > world.max_steps:
                world.ended = True
            return -1 if world.ended else 0

    return Robot


class FakeWebots:
    """一次可配置的伪 Webots 运行环境。"""

    def __init__(
        self,
        device_names: Sequence[str],
        time_step: int = 32,
        max_steps: Optional[int] = 200_000,
    ) -> None:
        self.devices: Dict[str, FakeMotor] = {n: FakeMotor(n) for n in device_names}
        self.time_step = time_step
        self.max_steps = max_steps
        self.step_count = 0
        self.sim_time_ms = 0
        self.ended = False
        self.instances: List[Any] = []
        self._module: Optional[types.ModuleType] = None
        self._previous: Any = None

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
        return [name for name, motor in self.devices.items() if motor.position_history]

    def sensors_enabled(self) -> List[str]:
        return [
            name
            for name, motor in self.devices.items()
            if motor.position_sensor.enabled
        ]

    def commanded_degrees(self, name: str) -> List[float]:
        return [math.degrees(rad) for rad in self.devices[name].position_history]


def load_controller_module(name: str = "atri_controller_under_test") -> types.ModuleType:
    """按文件路径加载控制器（Webots 也是这么加载控制器的）。"""
    spec = importlib.util.spec_from_file_location(name, CONTROLLER_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"无法加载控制器: {CONTROLLER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
