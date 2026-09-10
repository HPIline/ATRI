"""A.T.R.I. Webots 控制器的离线端到端测试。

在没装 Webots 的机器 / CI 上，用 ``webots_api_stub`` 顶替 ``controller`` 模块，
把控制器完整跑一遍。覆盖的都是"只在仿真里才会暴露"的回归点。
"""
from __future__ import annotations

import contextlib
import io
import json
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
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "软件" / "atri"))

from atri.config import JOINTS  # noqa: E402

ATRI_JOINT_NAMES = list(JOINTS.keys())


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

    def test_all_22_joints_bound(self):
        self.assertEqual(len(self.world.moved_joints()), 22)

    def test_position_sensors_are_enabled(self):
        """第一版没 enable 传感器，getValue() 全是 NaN——这是本测试要钉住的回归。"""
        self.assertEqual(len(self.world.sensors_enabled()), 22)

    def test_sensor_reads_are_finite(self):
        for name, motor in self.world.devices.items():
            with self.subTest(joint=name):
                value = motor.position_sensor.getValue()
                self.assertEqual(value, value, "getValue() 返回 NaN，说明传感器没被 enable")

    def test_motor_velocity_is_set(self):
        for name, motor in self.world.devices.items():
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
        # Nao 没有躯干 2 DOF 和夹爪 2 DOF，映射里留空 -> 绑定 18/22
        self.assertEqual(len(self.world.moved_joints()), 18)

    def test_reports_unbound_joints(self):
        self.assertIn("已绑定 18/22 个关节", self.out)


class TestWebotsControllerMissingMotor(unittest.TestCase):
    """映射里写了模型上不存在的电机名：跳过并提示，不能崩。"""

    def test_unknown_motor_is_skipped(self):
        mapping = {name: name for name in ATRI_JOINT_NAMES}
        mapping["left_gripper"] = "NoSuchMotor"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapping.json"
            path.write_text(json.dumps(mapping), encoding="utf-8")
            world = FakeWebots(device_names=ATRI_JOINT_NAMES)
            code, out = _run(world, ["--exit-on-done", "--mapping", str(path)])

        self.assertEqual(code, 0, msg=out)
        self.assertIn("找不到电机: NoSuchMotor", out)
        self.assertIn("已绑定 21/22 个关节", out)


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
        self.assertEqual(payload["bound_joints"], 22)
        self.assertEqual(payload["expected_joints"], 22)
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
            with self.subTest(joint=name):
                self.assertEqual(motor.velocity, 1.5)


class TestAtriWorldFile(unittest.TestCase):
    """世界文件的结构检查。

    这里的 `gravity` 一条是真实踩过的坑：Webots R2025a 的 `WorldInfo.gravity`
    是 **SFFloat**（沿"下"轴的大小），不是 SFVec3f。写成 `gravity 0 0 0` 会让世界
    解析失败，Webots 静默回退到内置 empty.wbt——机器人根本不存在，控制器一个都不会启动，
    而且**没有任何报错**。离线唯一能钉住它的就是这条断言。
    """

    WORLD = Path(__file__).resolve().parents[1] / "worlds" / "atri_22dof.wbt"

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
        self.assertEqual(len(motors), 22, f"应有 22 个电机，实际 {len(motors)}")
        self.assertEqual(set(motors), set(JOINTS), "世界里的电机名与 atri.config.JOINTS 不一致")

    def test_sensors_and_joints_count(self):
        self.assertEqual(self.text.count("PositionSensor {"), 22)
        self.assertEqual(self.text.count("HingeJoint {"), 22)

    def test_controller_is_atri_controller(self):
        self.assertIn('controller "atri_controller"', self.text)


if __name__ == "__main__":
    unittest.main()
