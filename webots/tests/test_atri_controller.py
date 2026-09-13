"""A.T.R.I. Webots 控制器的离线端到端测试。

在没装 Webots 的机器 / CI 上，用 ``webots_api_stub`` 顶替 ``controller`` 模块，
把控制器完整跑一遍。覆盖的都是"只在仿真里才会暴露"的回归点。
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from webots_api_stub import (  # noqa: E402
    CONTROLLER_DIR,
    FakeWebots,
    load_controller_module,
    parse_world_actuators,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "software" / "atri"))

from atri.config import JOINTS  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "design"))
from v2.profile import JOINTS as PROFILE_JOINTS  # noqa: E402

ATRI_JOINT_NAMES = list(JOINTS.keys())
DOF = len(ATRI_JOINT_NAMES)

# v2 限位单一事实：software config ↔ design/v2/profile.py
MODEL_JOINTS = {j["name"]: j for j in PROFILE_JOINTS}


def _run(world: FakeWebots, argv):
    """在伪 Webots 环境里跑一次控制器，返回 (退出码, 控制台输出)。"""
    world.install()
    buffer = io.StringIO()
    try:
        module = load_controller_module()
        with contextlib.redirect_stdout(buffer):
            code = module.main(argv)
    finally:
        world.uninstall()
        sys.modules.pop("atri_controller_under_test", None)
    return code, buffer.getvalue()


class TestWebotsControllerIdentityMapping(unittest.TestCase):
    """机器人模型里的电机名与 ATRI 关节名一致（默认 joint_mapping.json）。"""

    def setUp(self) -> None:
        self.world = FakeWebots(device_names=ATRI_JOINT_NAMES)
        self.code, self.out = _run(self.world, ["--exit-on-done"])

    def test_all_tasks_pass(self):
        self.assertEqual(self.code, 0, msg=self.out)
        self.assertIn("Webots 闭环: 5/5 项任务通过", self.out)

    def test_all_20_joints_bound(self):
        self.assertEqual(len(self.world.moved_joints()), DOF)

    def test_position_sensors_are_enabled(self):
        """第一版没 enable 传感器，getValue() 全是 NaN——这是本测试要钉住的回归。"""
        self.assertEqual(len(self.world.sensors_enabled()), DOF)

    def test_sensor_reads_are_finite(self):
        for name, motor in self.world.devices.items():
            if name in ("pelvis_gps", "imu"):
                continue
            with self.subTest(joint=name):
                value = motor.position_sensor.getValue()
                self.assertEqual(value, value, "getValue() 返回 NaN，说明传感器没被 enable")

    def test_motor_velocity_is_set(self):
        for name, motor in self.world.devices.items():
            if name in ("pelvis_gps", "imu"):
                continue
            with self.subTest(joint=name):
                self.assertIsNotNone(motor.velocity, "控制器没有设置关节角速度")
                self.assertGreater(motor.velocity, 0.0)

    def test_joints_actually_move(self):
        """确认下发的角度不是"一直是零位"。"""
        moved = 0
        for name in ATRI_JOINT_NAMES:
            history = self.world.commanded_degrees(name)
            if history and (max(history) - min(history)) > 0.5:
                moved += 1
        self.assertGreaterEqual(moved, 15, f"只有 {moved} 个关节发生了明显运动")


class TestWebotsControllerNaoMapping(unittest.TestCase):
    """用 Webots 内置 Nao（映射里有留空的自由度）。"""

    def setUp(self) -> None:
        mapping = json.loads(
            (CONTROLLER_DIR / "joint_mapping_nao.json").read_text(encoding="utf-8")
        )
        nao_devices = sorted({v for v in mapping.values() if v})
        self.world = FakeWebots(device_names=nao_devices)
        self.code, self.out = _run(
            self.world, ["--exit-on-done", "--mapping", "joint_mapping_nao.json"]
        )

    def test_runs_without_crashing(self):
        self.assertEqual(self.code, 0, msg=self.out)

    def test_binds_only_existing_nao_joints(self):
        # Nao 没有躯干 2 DOF 和夹爪 2 DOF，映射里留空 -> 绑定 16/20
        self.assertEqual(len(self.world.moved_joints()), 16)

    def test_reports_unbound_joints(self):
        self.assertIn(f"已绑定 16/{DOF} 个关节", self.out)

    def test_intentionally_empty_entries_do_not_fail_the_run(self):
        """留空 = 该机型没有这个自由度，不计入“应绑定”，所以 16/20 仍判通过。"""
        self.assertEqual(self.code, 0, msg=self.out)
        self.assertIn("映射应绑定 16", self.out)
        self.assertNotIn("绑定不完整", self.out)


class TestWebotsControllerMissingMotor(unittest.TestCase):
    """映射里写了模型上不存在的电机名：跳过并提示，且必须判失败。"""

    def test_missing_motor_fails_the_run(self):
        mapping = {name: name for name in ATRI_JOINT_NAMES}
        mapping["left_gripper"] = "NoSuchMotor"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapping.json"
            path.write_text(json.dumps(mapping), encoding="utf-8")
            report = Path(tmp) / "report.json"
            world = FakeWebots(device_names=ATRI_JOINT_NAMES)
            code, out = _run(
                world, ["--exit-on-done", "--mapping", str(path), "--report", str(report)]
            )
            payload = json.loads(report.read_text(encoding="utf-8"))

        # 非空映射条目没能绑定 = 世界与映射不匹配，无论任务跑得多顺都不算联调通过
        self.assertEqual(code, 2, msg=out)
        self.assertIn("找不到电机: NoSuchMotor", out)
        self.assertIn(f"已绑定 {DOF - 1}/{DOF} 个关节", out)
        self.assertEqual(payload["bound_joints"], DOF - 1)
        self.assertEqual(payload["mapped_joints"], DOF)
        self.assertFalse(payload["binding_ok"])


class TestWebotsControllerZeroBinding(unittest.TestCase):
    """映射全指向不存在的电机：0 绑定必须判失败（任务逻辑跑通也不放行）。"""

    def _run_zero_binding(self):
        mapping = {name: "NO_SUCH_" + name for name in ATRI_JOINT_NAMES}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapping.json"
            path.write_text(json.dumps(mapping), encoding="utf-8")
            report = Path(tmp) / "report.json"
            world = FakeWebots(device_names=[])
            code, out = _run(
                world, ["--exit-on-done", "--mapping", str(path), "--report", str(report)]
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
        return code, out, payload

    def test_zero_binding_is_not_a_pass(self):
        code, out, _ = self._run_zero_binding()
        self.assertNotEqual(code, 0, msg=out)
        self.assertIn(f"已绑定 0/{DOF}", out)
        self.assertIn(f"映射应绑定 {DOF}", out)

    def test_zero_binding_report_is_explicit(self):
        _, _, payload = self._run_zero_binding()
        self.assertEqual(payload["bound_joints"], 0)
        self.assertEqual(payload["mapped_joints"], DOF)
        self.assertFalse(payload["binding_ok"])
        # 任务卡本身仍然跑完（FSM 与电机无关），但结论不能是“联调通过”
        self.assertEqual(payload["passed"], payload["total"])


class TestWebotsControllerMappingCoverage(unittest.TestCase):
    """映射必须覆盖全部 20 个 ATRI 关节名，且不得出现非法关节名。

    只比较"绑定数 == 映射非空条目数"是不够的：映射被截断、或 ATRI 侧的键名写错时，
    两个计数会一起变小/一起把坏条目算进去，恰好相互抵消而判通过。
    """

    def _run_mapping(self, mapping):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapping.json"
            path.write_text(json.dumps(mapping), encoding="utf-8")
            report = Path(tmp) / "report.json"
            world = FakeWebots(device_names=ATRI_JOINT_NAMES)
            code, out = _run(
                world, ["--exit-on-done", "--mapping", str(path), "--report", str(report)]
            )
            payload = (json.loads(report.read_text(encoding="utf-8"))
                       if report.exists() else {})
        return code, out, payload

    def test_truncated_mapping_is_not_a_pass(self):
        """只声明 1 个关节：其余关节从未被下发指令，不能算联调通过。"""
        code, out, payload = self._run_mapping({"head_yaw": "head_yaw"})
        self.assertNotEqual(code, 0, msg=out)
        self.assertFalse(payload.get("binding_ok", True))

    def test_unknown_atri_joint_name_is_not_a_pass(self):
        """ATRI 侧键名写错（head_pitchh）会让 head_pitch 静默失联，必须判失败。"""
        mapping = {name: name for name in ATRI_JOINT_NAMES}
        mapping["head_pitchh"] = mapping.pop("head_pitch")
        code, out, payload = self._run_mapping(mapping)
        self.assertNotEqual(code, 0, msg=out)
        self.assertFalse(payload.get("binding_ok", True))

    def test_complete_mapping_still_passes(self):
        code, out, payload = self._run_mapping({name: name for name in ATRI_JOINT_NAMES})
        self.assertEqual(code, 0, msg=out)
        self.assertTrue(payload["binding_ok"])

    def test_nao_mapping_with_empty_entries_still_passes(self):
        """留空条目是合法的"该机型无此自由度"，不能被覆盖度校验误杀。"""
        mapping = json.loads(
            (CONTROLLER_DIR / "joint_mapping_nao.json").read_text(encoding="utf-8")
        )
        nao_devices = sorted({v for v in mapping.values() if v})
        world = FakeWebots(device_names=nao_devices)
        code, out = _run(
            world, ["--exit-on-done", "--mapping", "joint_mapping_nao.json"]
        )
        self.assertEqual(code, 0, msg=out)


class TestWebotsControllerMotionEvidence(unittest.TestCase):
    """绑定完整也可能一步未动：velocity=0 时电机锁死，不能判联调通过。"""

    def test_zero_velocity_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            world = FakeWebots(device_names=ATRI_JOINT_NAMES)
            code, out = _run(
                world,
                ["--exit-on-done", "--velocity", "0", "--report", str(report)],
            )
            payload = (json.loads(report.read_text(encoding="utf-8"))
                       if report.exists() else {})
        self.assertNotEqual(code, 0, msg=out)
        self.assertEqual(payload.get("moved_joints", -1), 0)


class TestJointLimitsSingleSource(unittest.TestCase):
    """控制器软钳制读 atri.config，限位读 design/v2/profile.py——两份数据必须一致。

    不一致时：软钳制更宽会让指令被 Webots 硬限位截停而报告仍按指令角记账；
    更窄则世界允许的行程永远到不了。
    """

    def test_config_limits_match_model_limits(self):
        self.assertEqual(set(JOINTS), set(MODEL_JOINTS))
        for name, spec in JOINTS.items():
            with self.subTest(joint=name):
                self.assertEqual(
                    list(spec["limit_deg"]),
                    list(MODEL_JOINTS[name]["limit_deg"]),
                    f"{name} 的限位在 atri.config 与 v2 profile 之间不一致",
                )


def _make_bus(world: FakeWebots, module_name: str, **kwargs):
    """在伪 Webots 里直接构造 WebotsServoBus，用于不经任务链路的单元断言。"""
    world.install()
    try:
        module = load_controller_module(module_name)
        robot = sys.modules["controller"].Robot()
        bus = module.WebotsServoBus(
            robot, {name: name for name in ATRI_JOINT_NAMES}, timestep_ms=32, **kwargs
        )
    except Exception:
        world.uninstall()
        sys.modules.pop(module_name, None)
        raise
    return module, bus


class TestWebotsServoBusLimits(unittest.TestCase):
    """WebotsServoBus 不再自己写 set_angle，越限必须由基类模板方法钳制（C-2）。"""

    def setUp(self) -> None:
        self.world = FakeWebots(device_names=ATRI_JOINT_NAMES)
        self.module, self.bus = _make_bus(self.world, "atri_bus_limits")
        self.addCleanup(self.world.uninstall)
        self.addCleanup(sys.modules.pop, "atri_bus_limits", None)

    def _last_command_deg(self, name: str) -> float:
        return math.degrees(self.world.devices[name].commanded_positions[-1])

    def test_uses_base_template_method(self):
        self.assertNotIn(
            "set_angle",
            vars(self.module.WebotsServoBus),
            "WebotsServoBus 不应再覆写 set_angle，限位必须走基类模板方法",
        )
        self.assertTrue(
            callable(getattr(self.module.WebotsServoBus, "_write_angle", None)),
            "WebotsServoBus 必须实现 _write_angle",
        )

    def test_over_limit_request_is_clamped(self):
        name = "head_yaw"
        self.bus.set_angle(JOINTS[name]["id"], 9999.0)
        self.assertAlmostEqual(self._last_command_deg(name), 90.0, places=6)

    def test_below_limit_request_is_clamped(self):
        name = "left_knee_pitch"
        self.bus.set_angle(JOINTS[name]["id"], -9999.0)
        self.assertAlmostEqual(self._last_command_deg(name), 0.0, places=6)

    def test_every_joint_command_stays_within_limits(self):
        for name in ATRI_JOINT_NAMES:
            lo, hi = JOINTS[name]["limit_deg"]
            with self.subTest(joint=name):
                self.bus.set_angle(JOINTS[name]["id"], 10000.0)
                self.bus.set_angle(JOINTS[name]["id"], -10000.0)
                for rad in self.world.devices[name].commanded_positions:
                    self.assertGreaterEqual(math.degrees(rad), lo - 1e-6)
                    self.assertLessEqual(math.degrees(rad), hi + 1e-6)


class TestWebotsServoBusStopsWhenSimulationEnds(unittest.TestCase):
    """仿真结束后（robot.step 返回 -1）不得再向电机下发角度。"""

    def setUp(self) -> None:
        self.world = FakeWebots(device_names=ATRI_JOINT_NAMES)
        self.state = {"alive": True}
        self.module, self.bus = _make_bus(
            self.world, "atri_bus_alive", alive=lambda: self.state["alive"]
        )
        self.addCleanup(self.world.uninstall)
        self.addCleanup(sys.modules.pop, "atri_bus_alive", None)

    def test_no_command_after_simulation_ends(self):
        jid = JOINTS["head_yaw"]["id"]
        motor = self.world.devices["head_yaw"]
        self.bus.set_angle(jid, 10.0)
        before = len(motor.commanded_positions)
        self.assertGreater(before, 0, "存活时本该下发角度")

        self.state["alive"] = False  # 等价于 robot.step 返回 -1
        self.bus.set_angle(jid, 20.0)
        self.assertEqual(len(motor.commanded_positions), before)


class TestWebotsStubFidelity(unittest.TestCase):
    """桩要复刻限速与限位，否则控制器不钳制也测不出来（C-4）。"""

    def test_max_velocity_comes_from_world_file(self):
        specs = parse_world_actuators()
        world = FakeWebots(device_names=ATRI_JOINT_NAMES)
        for name in ATRI_JOINT_NAMES:
            with self.subTest(joint=name):
                self.assertAlmostEqual(
                    world.devices[name].getMaxVelocity(),
                    specs[name]["maxVelocity"],
                    places=6,
                )

    def test_position_needs_time_to_reach_target(self):
        """限速 2 rad/s、步长 32 ms：一步只该走约 3.7°，不可能直接到 90°。"""
        world = FakeWebots(device_names=["head_yaw"])
        motor = world.devices["head_yaw"]
        motor.setVelocity(2.0)
        motor.position_sensor.enable(32)
        motor.setPosition(math.radians(90.0))
        world.step(32)
        moved_deg = math.degrees(motor.position_sensor.getValue())
        self.assertGreater(moved_deg, 0.0, "电机根本没动")
        self.assertLess(moved_deg, 90.0, "电机瞬间到位，没有复刻速率限制")

    def test_position_cannot_cross_joint_stop(self):
        world = FakeWebots(device_names=["head_yaw"])
        motor = world.devices["head_yaw"]
        motor.setVelocity(50.0)
        motor.position_sensor.enable(32)
        motor.setPosition(math.radians(9999.0))
        for _ in range(200):
            world.step(32)
        deg = math.degrees(motor.position_sensor.getValue())
        self.assertLessEqual(deg, JOINTS["head_yaw"]["limit_deg"][1] + 1e-3)

    def test_commanded_positions_are_recorded_separately(self):
        world = FakeWebots(device_names=["head_yaw"])
        motor = world.devices["head_yaw"]
        motor.setPosition(math.radians(30.0))
        self.assertEqual(motor.commanded_positions, [math.radians(30.0)])
        motor.position_sensor.enable(32)
        self.assertEqual(
            math.degrees(motor.position_sensor.getValue()),
            0.0,
            "位置传感器读的应是实际位置，不是目标位置",
        )


class TestWebotsControllerSimulationEnds(unittest.TestCase):
    """仿真提前结束（robot.step 返回 -1）时控制器必须干净退出，不能死循环。"""

    def test_controller_returns_when_simulation_ends(self):
        world = FakeWebots(device_names=ATRI_JOINT_NAMES, max_steps=40)
        code, out = _run(world, ["--exit-on-done"])
        self.assertTrue(world.ended)
        self.assertIn("项任务通过", out)
        # 仿真没跑完 -> 任务不可能全通过，退出码非 0
        self.assertNotEqual(code, 0)


class TestWebotsControllerReport(unittest.TestCase):
    """--report 产出可机读的联调结论。"""

    def test_report_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "nested" / "atri_report.json"
            world = FakeWebots(device_names=ATRI_JOINT_NAMES)
            code, out = _run(world, ["--exit-on-done", "--report", str(report)])

            self.assertEqual(code, 0, msg=out)
            self.assertTrue(report.exists(), "报告文件没有生成")
            payload = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(payload["passed"], 5)
        self.assertEqual(payload["total"], 5)
        self.assertEqual(payload["bound_joints"], DOF)
        self.assertEqual(payload["expected_joints"], DOF)
        self.assertEqual(payload["unbound_joints"], [])
        self.assertTrue(payload["simulation_alive"])
        self.assertEqual(len(payload["tasks"]), 5)
        self.assertTrue(all(t["ok"] for t in payload["tasks"]))
        self.assertGreater(payload["sim_seconds"], 0.0)
        self.assertGreater(payload["sim_steps"], 0)

        # 关节行程：证明电机真的被驱动了，而不是只有 FSM 逻辑跑通
        travel = payload["joint_travel_deg"]
        self.assertEqual(set(travel), set(ATRI_JOINT_NAMES))
        self.assertGreater(payload["moved_joints"], 0)
        self.assertEqual(payload["moved_joints"], sum(1 for d in travel.values() if d > 1.0))
        for name in ("left_shoulder_pitch", "right_knee_pitch", "head_yaw"):
            with self.subTest(joint=name):
                self.assertGreater(travel[name], 1.0, f"{name} 没有实际行程")


class TestWebotsControllerEnvOptions(unittest.TestCase):
    """Webots 没有把参数透传给控制器的机制，命令行批量验证只能靠环境变量。"""

    KEYS = (
        "ATRI_WEBOTS_EXIT_ON_DONE",
        "ATRI_WEBOTS_REPORT",
        "ATRI_WEBOTS_VELOCITY",
    )

    def test_env_vars_configure_batch_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "env_report.json"
            os.environ["ATRI_WEBOTS_EXIT_ON_DONE"] = "1"
            os.environ["ATRI_WEBOTS_REPORT"] = str(report)
            os.environ["ATRI_WEBOTS_VELOCITY"] = "1.5"
            try:
                world = FakeWebots(device_names=ATRI_JOINT_NAMES)
                code, out = _run(world, [])
            finally:
                for key in self.KEYS:
                    os.environ.pop(key, None)

            self.assertEqual(code, 0, msg=out)
            self.assertTrue(report.exists(), "环境变量指定的报告没有生成")
            payload = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(payload["velocity_rad_s"], 1.5)
        self.assertEqual(payload["passed"], 5)
        for name, motor in world.devices.items():
            if name in ("pelvis_gps", "imu"):
                continue
            with self.subTest(joint=name):
                self.assertEqual(motor.velocity, 1.5)


class TestAtriWorldFile(unittest.TestCase):
    """世界文件的结构检查。

    这里的 `gravity` 一条是真实踩过的坑：Webots R2025a 的 `WorldInfo.gravity`
    是 **SFFloat**（沿"下"轴的大小），不是 SFVec3f。写成 `gravity 0 0 0` 会让世界
    解析失败，Webots 静默回退到内置 empty.wbt——机器人根本不存在，控制器一个都不会启动，
    而且**没有任何报错**。离线唯一能钉住它的就是这条断言。
    """

    WORLD = Path(__file__).resolve().parents[1] / "worlds" / "atri_v2.wbt"

    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = cls.WORLD.read_bytes()
        cls.text = cls.raw.decode("utf-8")

    def test_starts_with_vrml_header(self):
        self.assertTrue(self.text.startswith("#VRML_SIM "), "缺少 #VRML_SIM 头")

    def test_is_lf_only(self):
        self.assertNotIn(b"\r\n", self.raw, "世界文件必须是 LF；.gitattributes 里已强制 eol=lf")

    def test_gravity_is_a_scalar(self):
        line = next(
            (ln for ln in self.text.splitlines() if ln.strip().startswith("gravity")),
            None,
        )
        self.assertIsNotNone(line, "WorldInfo 里没有 gravity")
        values = line.split()[1:]
        self.assertEqual(
            len(values), 1,
            f"WorldInfo.gravity 必须是单个数字（SFFloat），实际是 {values!r}",
        )
        self.assertEqual(float(values[0]), 0.0)

    def test_joint_names_match_config(self):
        import re

        motors = re.findall(r'RotationalMotor\s*\{\s*name\s+"([^"]+)"', self.text)
        self.assertEqual(len(motors), DOF, f"应有 {DOF} 个电机，实际 {len(motors)}")
        self.assertEqual(set(motors), set(JOINTS), "世界里的电机名与 atri.config.JOINTS 不一致")
        self.assertNotIn("left_hip_yaw", motors)
        self.assertNotIn("right_hip_yaw", motors)

    def test_sensors_and_joints_count(self):
        self.assertEqual(self.text.count("PositionSensor {"), DOF)
        self.assertEqual(self.text.count("HingeJoint {"), DOF)

    def test_controller_is_atri_controller(self):
        self.assertIn('controller "atri_controller"', self.text)

    def test_joint_stops_match_model_limits(self):
        """每个关节必须写 minStop/maxStop，否则 Webots 默认无限位（C-3）。"""
        specs = parse_world_actuators()
        self.assertEqual(set(specs), set(JOINTS))
        for name, spec in specs.items():
            lo, hi = MODEL_JOINTS[name]["limit_deg"]
            with self.subTest(joint=name):
                self.assertIsNotNone(spec["minStop"], f"{name} 没有 minStop")
                self.assertIsNotNone(spec["maxStop"], f"{name} 没有 maxStop")
                self.assertAlmostEqual(spec["minStop"], math.radians(lo), places=4)
                self.assertAlmostEqual(spec["maxStop"], math.radians(hi), places=4)

    def test_motor_max_velocity_matches_model(self):
        """maxVelocity 必须来自 v2 URDF，不能再统一写 2 rad/s。"""
        sys.path.insert(0, str(REPO_ROOT / "webots" / "tools"))
        import generate_atri_world as gen
        model = {j["name"]: j for j in gen.load_model()["joints"]}
        specs = parse_world_actuators()
        for name, spec in specs.items():
            expected = math.radians(model[name]["velocity_dps"])
            with self.subTest(joint=name):
                self.assertAlmostEqual(spec["maxVelocity"], expected, places=4)
                self.assertNotAlmostEqual(spec["maxVelocity"], 2.0, places=3)

    def test_joint_damping_is_set(self):
        """每个关节必须写 dampingConstant > 0（不写 = 世界在启动瞬间被弹飞）。

        实测（2026-09-12，Windows + Webots R2025a）：不写阻尼时 trunk_pitch /
        hip_pitch / knee_pitch / shoulder_pitch / elbow_pitch / gripper 会在启动
        4 个物理步内被弹到上千度后卡死，位置传感器读数不再是关节角——控制器据此
        测出的"有行程关节"从 18/20 掉到 11/20，看起来像动作没下发。
        """
        specs = parse_world_actuators()
        for name, spec in specs.items():
            with self.subTest(joint=name):
                damping = spec.get("dampingConstant")
                self.assertIsNotNone(damping, f"{name} 没有 dampingConstant")
                self.assertGreater(damping, 0.0, f"{name} 的阻尼必须 > 0，实际 {damping}")

    def test_all_motors_have_nonzero_velocity(self):
        specs = parse_world_actuators()
        for name, spec in specs.items():
            with self.subTest(joint=name):
                self.assertGreater(spec["maxVelocity"], 0.0)

    def test_each_endpoint_is_translated_to_joint_origin(self):
        """不写 endPoint.translation 时子连杆叠在骨盆，脚盒碰不到地，静立必塌。"""
        robot = self.text.split("Robot {", 1)[1]
        self.assertGreaterEqual(
            robot.count("translation "),
            DOF,
            "每个 HingeJoint 的 endPoint Solid 必须带 URDF 关节原点 translation",
        )


class TestJointFrames(unittest.TestCase):
    """盒体世界必须把子 Solid 放到关节原点，与 urdf2webots / CAD 导入世界同一约定。"""

    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(REPO_ROOT / "webots" / "tools"))
        import generate_atri_world as gen  # noqa: WPS433

        cls.gen = gen

    def test_render_joint_writes_translation_equal_to_anchor(self):
        def check(node: dict) -> None:
            rendered = self.gen.render_joint(node, indent=2)
            idx = next(i for i, ln in enumerate(rendered) if "endPoint Solid" in ln)
            window = "\n".join(rendered[idx:idx + 6])
            expected = f"translation {self.gen.vec(node['anchor'])}"
            self.assertIn(expected, window, msg=f"{node['name']}: {window}")
            for child in node["children"]:
                check(child)

        for root in self.gen.robot_children():
            check(root)

    def test_gravity_world_enables_supervisor_for_movie(self):
        text = self.gen.render_world(gravity=9.81, max_torque=20.0, ground=True)
        self.assertIn("supervisor TRUE", text)
        self.assertIn('follow "ATRI"', text)
        self.assertIn("diffuseColor 0.18 0.42 0.86", text)
        self.assertIn("DirectionalLight", text)
        self.assertIn("Background", text)
        self.assertIn('material1 "TPU95A"', text)
        self.assertIn('material2 "vinyl_floor"', text)
        self.assertIn('contactMaterial "TPU95A"', text)
        self.assertIn("coulombFriction 0.7", text)
        default = self.gen.render_world()
        self.assertNotIn("supervisor TRUE", default)
        self.assertNotIn("diffuseColor 0.18 0.42 0.86", default)
        self.assertNotIn("DirectionalLight", default)

    def test_gravity_foot_box_sits_at_cad_sole(self):
        """Solid 在踝（URDF 惯量原点）；碰撞盒 120×70×44 mm，盒底在鞋底。"""
        from v2.profile import K

        text = self.gen.render_world(gravity=9.81, ground=True)
        sole_m = K["foot_to_ankle_z"] / 1000.0
        left = text.split('name "left_ankle_pitch_link"', 1)[1].split("HingeJoint {", 1)[0]
        self.assertIn("boundingObject Pose {", left)
        self.assertIn(f"translation 0 0 {self.gen.num(-sole_m / 2.0)}", left)
        self.assertIn(f"size {self.gen.num(K['foot_l']/1000)} {self.gen.num(K['foot_w']/1000)} {self.gen.num(sole_m)}", left)
        default = self.gen.render_world()
        self.assertNotIn("boundingObject Pose {", default)
        spawn = self.gen.pelvis_spawn_z_m(
            chain_z_m=self.gen.left_foot_chain_z_m(),
            foot_half_z_m=sole_m,
            clearance_m=0.008,
        )
        self.assertIn(f"translation 0 0 {self.gen.num(spawn)}", text)

    def test_gravity_uses_urdf_inertia_not_sphere(self):
        model = self.gen.load_model()
        pelvis = next(l for l in model["links"] if l["name"] == "pelvis")
        text = self.gen.render_world(gravity=9.81, ground=True)
        self.assertIn("inertiaMatrix [", text)
        self.assertIn(self.gen.num_inertia(pelvis["inertia"][0]), text)
        default = self.gen.render_world()
        self.assertNotIn("inertiaMatrix [", default)

    def test_gravity_writes_urdf_center_of_mass(self):
        """Webots inertiaMatrix 绕 CoM；空 centerOfMass 会按 8 mm 球重算。"""
        model = self.gen.load_model()
        torso = next(l for l in model["links"] if l["name"] == "torso")
        cx, cy, cz = torso["com"]
        self.assertGreater(abs(cx) + abs(cy) + abs(cz), 0.005)
        text = self.gen.render_world(gravity=9.81, ground=True)
        torso_block = text.split('name "trunk_pitch_link"', 1)[1].split("HingeJoint {", 1)[0]
        self.assertIn("centerOfMass [", torso_block)
        self.assertIn(self.gen.vec((cx, cy, cz)), torso_block)
        default = self.gen.render_world()
        self.assertNotIn("centerOfMass [", default)

    def test_gravity_motor_torque_is_sts3215_stall(self):
        from v2.profile import SERVO

        text = self.gen.render_world(gravity=9.81, ground=True)
        self.assertIn(f"maxTorque {self.gen.num(SERVO['stall_nm'])}", text)
        default = self.gen.render_world()
        self.assertNotIn("maxTorque", default)

    def test_gravity_ground_is_static_box(self):
        """ODE 无限平面上薄盒摩擦经常失效；官方 NAO/KHR 地面是静态盒。"""
        text = self.gen.render_world(gravity=9.81, max_torque=20.0, ground=True)
        ground = text.split('name "ground"', 1)[1].split("Robot {", 1)[0]
        self.assertIn("boundingObject Box {", ground)
        self.assertNotIn("boundingObject Plane {", ground)
        self.assertIn('contactMaterial "vinyl_floor"', ground)
        default = self.gen.render_world()
        self.assertNotIn('name "ground"', default)

    def test_left_ankle_chain_reaches_below_pelvis(self):
        z = 0.0
        nodes = self.gen.robot_children()

        def find(items, name):
            for node in items:
                if node["name"] == name:
                    return node
                got = find(node["children"], name)
                if got is not None:
                    return got
            return None

        for name in (
            "left_hip_roll",
            "left_hip_pitch",
            "left_knee_pitch",
            "left_ankle_pitch",
        ):
            node = find(nodes, name)
            self.assertIsNotNone(node, name)
            z += node["anchor"][2]
        self.assertAlmostEqual(z, -0.188, places=4)


class TestStandMode(unittest.TestCase):
    def test_stand_seconds_passes_on_level_stub(self):
        world = FakeWebots(device_names=ATRI_JOINT_NAMES)
        code, out = _run(world, ["--exit-on-done", "--stand-s", "1"])
        self.assertEqual(code, 0, msg=out)
        self.assertIn("站立判定: ok=True", out)

    def test_stand_report_logs_contact_and_static_balance(self):
        """官方调试：getContactPoints(includeDescendants) + getStaticBalance。"""
        world = FakeWebots(device_names=ATRI_JOINT_NAMES)
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "stand.json"
            code, out = _run(
                world,
                ["--exit-on-done", "--stand-s", "1", "--report", str(report)],
            )
            payload = json.loads(Path(report).read_text(encoding="utf-8"))
        self.assertEqual(code, 0, msg=out)
        self.assertIn("contacts=", out)
        dbg = payload.get("stand_debug") or {}
        self.assertEqual(dbg.get("n_contacts"), 2)
        self.assertTrue(dbg.get("static_balance"))
        self.assertEqual(len(dbg.get("contact_xy") or []), 2)

    def test_movie_flag_is_a_no_op_on_stub(self):
        world = FakeWebots(device_names=ATRI_JOINT_NAMES)
        with tempfile.TemporaryDirectory() as tmp:
            movie = str(Path(tmp) / "stand.mp4")
            code, out = _run(
                world, ["--exit-on-done", "--stand-s", "1", "--movie", movie]
            )
        self.assertEqual(code, 0, msg=out)
        self.assertIn("开始录屏", out)


if __name__ == "__main__":
    unittest.main()
