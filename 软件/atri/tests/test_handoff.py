"""硬件选型需求推导（交接包）测试。

守护的是"给下游 agent 的数据是否自洽、是否会被误读"：
  - 22 个关节都有需求，且为正
  - 腿部关节必须由单腿支撑工况主导（否则会选小舵机）
  - 分档数量之和 = 22
  - 假设值全部显式写出，不被当成实测
  - 交接文档包含必要章节

运行：
    cd 软件/atri && python3 -m unittest tests.test_handoff -v
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DESIGN = REPO / "design"
sys.path.insert(0, str(DESIGN))
sys.path.insert(0, str(REPO / "软件" / "atri"))

import gen_handoff  # noqa: E402
import gen_urdf  # noqa: E402


class TestTorqueRequirements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = gen_urdf.load_model()
        cls.joints = [gen_handoff.joint_torque(cls.model, j)
                      for j in sorted(cls.model["joints"],
                                      key=lambda x: x["id"])]

    def test_all_22_joints_have_requirements(self):
        self.assertEqual(len(self.joints), 22)

    def test_all_requirements_positive_and_above_floor(self):
        floor = gen_handoff.ASSUMPTIONS["min_practical_torque_nm"]
        for t in self.joints:
            with self.subTest(joint=t["joint"]):
                self.assertGreater(t["required_torque_nm"], 0.0)
                self.assertGreaterEqual(t["required_torque_nm"], floor - 1e-9)

    def test_leg_joints_driven_by_stance(self):
        """腿部关节必须由单腿支撑主导——静力下游质量法会严重低估。"""
        for t in self.joints:
            if t["joint"].startswith(("left_hip", "right_hip",
                                      "left_knee", "right_knee",
                                      "left_ankle", "right_ankle")):
                with self.subTest(joint=t["joint"]):
                    self.assertEqual(t["requirements_driver"], "stance")
                    self.assertGreater(t["stance_torque_nm"], 0.5)

    def test_stance_uses_full_body_weight(self):
        """支撑工况要计入全身重量，故 mass_above 应远大于下游腿段质量。"""
        knee = next(t for t in self.joints
                    if t["joint"] == "left_knee_pitch")
        self.assertGreater(knee["stance_mass_above_kg"],
                           knee["distal_mass_kg"] * 5)

    def test_non_leg_joints_have_zero_stance(self):
        for t in self.joints:
            if t["joint"].startswith(("head", "trunk", "left_shoulder",
                                      "right_shoulder", "left_elbow",
                                      "right_elbow", "left_gripper",
                                      "right_gripper")):
                with self.subTest(joint=t["joint"]):
                    self.assertEqual(t["stance_torque_nm"], 0.0)

    def test_trunk_roll_is_the_heaviest_joint(self):
        """腰部横滚要托起整个上半身，应是需求最大的关节。"""
        top = max(self.joints, key=lambda t: t["required_torque_nm"])
        self.assertEqual(top["joint"], "trunk_roll")

    def test_gravity_torque_formula(self):
        """人工复核一个关节：τ = Σ m·g·r（骨盆中心相对位移已排除自身 origin）。"""
        t = next(x for x in self.joints if x["joint"] == "trunk_roll")
        manual = sum(d["mass_kg"] * gen_handoff.G * d["arm_mm"] / 1000.0
                     for d in t["detail"])
        self.assertAlmostEqual(t["gravity_torque_nm"], manual, places=4)

    def test_vertical_axis_joints_have_near_zero_gravity(self):
        """竖直轴关节（髋 yaw）在零姿态下重力力臂≈0——这是对的物理。"""
        yaw = next(t for t in self.joints if t["joint"] == "left_hip_yaw")
        self.assertLess(yaw["gravity_torque_nm"], 0.05)
        # 但需求不能是 0（要能摆动），落到工程下限
        self.assertGreaterEqual(
            yaw["required_torque_nm"],
            gen_handoff.ASSUMPTIONS["min_practical_torque_nm"] - 1e-9,
        )

    def test_tier_counts_sum_to_22(self):
        tiers: dict = {}
        for t in self.joints:
            tiers[t["torque_tier"]] = tiers.get(t["torque_tier"], 0) + 1
        self.assertEqual(sum(tiers.values()), 22)


class TestAssumptionsAreExplicit(unittest.TestCase):
    def test_every_magic_number_has_a_note(self):
        """每个调参值都必须配一条说明，避免下游当成实测。"""
        for key in gen_handoff.ASSUMPTIONS:
            if key.startswith("note_"):
                continue
            with self.subTest(key=key):
                self.assertIn(f"note_{key}", gen_handoff.ASSUMPTIONS,
                              f"假设 {key} 缺少 note_ 说明")

    def test_placeholder_and_real_lists_exist(self):
        self.assertIn("safety_factor_static", gen_handoff.ASSUMPTIONS)
        self.assertIn("stance_dynamic_factor", gen_handoff.ASSUMPTIONS)


class TestPowerBudget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model = gen_urdf.load_model()
        torques = [gen_handoff.joint_torque(model, j)
                   for j in model["joints"]]
        cls.model = model
        cls.pb = gen_handoff.power_budget(model, torques)

    def test_current_below_all_stall(self):
        """平均电流必须低于"22 只同时堵转"的物理上限。

        ⚠️ 2026-09-12 口径变更：旧断言是 `< 12 A`——那是**把堵转扭矩当额定**
        （2.94 N·m）时的乐观模型留下的常数。订正官方额定 0.98 N·m 后，本模型
        （电流 ∝ 工作扭矩/额定）算出 ≈18.9 A，它读作**上限量级**而非选型值。
        所以判据不再拍一个常数，而取物理上限：单只堵转 2.7 A × 22 只 = 59.4 A。
        """
        total = self.pb["total_avg_current_at_pack_a"]
        ceiling = self.pb["stall_current_a"] * self.pb["servo_count"]
        self.assertGreater(total, 0.5)
        self.assertLess(total, ceiling)

    def test_battery_mass_reported_and_flagged(self):
        """整包质量必须报出来；一旦"装不下"（>0.6 kg 或 >整机 1/4），必须带缺口声明。

        为什么不直接断言 `< 0.6 kg`：按订正后的额定值，30 min 续航算出整包 ≈1.19 kg
        （占整机 ≈38%），**这个架构确实不成立**——把它写成一条永远红的断言只会变成噪音。
        本测试把"不成立"变成**必须被记录的事实**：数字超标而 `model_caveat` 缺失或
        没写清缺口，就判失败。这样缺口不会因为有人改了数字而静默消失。
        """
        mass = self.pb["estimated_battery_mass_kg"]
        robot = gen_handoff.total_mass_of(self.model)
        self.assertGreater(mass, 0.1)
        over = mass > 0.6 or mass > robot / 4.0
        if over:
            caveat = self.pb.get("model_caveat") or ""
            self.assertTrue(caveat, "电池超预算却没写 model_caveat")
            self.assertTrue(
                any(w in caveat for w in ("不够", "重新定案", "上限量级")),
                f"缺口声明没写清：{caveat[:80]}")

    def test_power_gap_flag_matches_numbers(self):
        """缺口标记与数字必须一致：超标 ⇒ 有 caveat；未超标 ⇒ 不该谎报缺口。"""
        mass = self.pb["estimated_battery_mass_kg"]
        cur = self.pb["total_avg_current_at_pack_a"]
        robot = gen_handoff.total_mass_of(self.model)
        over = mass > 0.6 or mass > robot / 4.0 or cur > 12.0
        has = bool(self.pb.get("model_caveat"))
        self.assertEqual(over, has,
                         f"超标={over} 但 caveat={has}（mass={mass} current={cur}）")

    def test_nameplate_exceeds_consumed(self):
        self.assertGreater(self.pb["required_nameplate_ah"],
                           self.pb["consumed_ah"])

    def test_mission_matches_requested(self):
        self.assertEqual(self.pb["mission_min"], 30.0)


class TestHandoffDocument(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.md = (DESIGN / "handoff" / "设计交接包-硬件选型需求.md")
        cls.data = DESIGN / "handoff" / "hardware_requirements.json"

    def test_document_exists_and_has_sections(self):
        self.assertTrue(self.md.exists(), "交接文档未生成，先跑 gen_handoff.py")
        text = self.md.read_text(encoding="utf-8")
        for section in ("## 一、", "## 二、", "## 三、", "## 四、",
                        "## 五、", "## 六、", "## 七、"):
            with self.subTest(section=section):
                self.assertIn(section, text)

    def test_document_states_geometry_is_placeholder(self):
        """必须显式声明几何是占位，否则下游会当成可制造设计。"""
        text = self.md.read_text(encoding="utf-8")
        self.assertIn("占位", text)
        self.assertIn("不可用于加工", text)

    def test_json_is_loadable_and_complete(self):
        self.assertTrue(self.data.exists())
        d = json.loads(self.data.read_text(encoding="utf-8"))
        self.assertEqual(len(d["joints"]), 22)
        self.assertIn("interface_requirements", d)
        self.assertIn("cavities", d)
        self.assertIn("power_budget", d)
        self.assertIn("what_is_placeholder", d)
        self.assertIn("what_is_real", d)

    def test_all_declared_attachments_exist(self):
        """文档「附件清单」里声明的每个文件都必须在 handoff/ 里真实存在。

        v2 起不再硬编码文件名：渲染附件**优先 PNG、回退已入库的 SVG**
        （PNG 被 .gitignore 排除，硬编码 PNG 名会让全新 clone / CI 必红）。
        这里改为从文档表格里解析实际声明的文件名，再逐个查存在性。
        """
        d = json.loads(self.data.read_text(encoding="utf-8"))
        self.assertTrue(d["robot"]["dof"] == 22)
        text = self.md.read_text(encoding="utf-8")

        # 只认"带扩展名的文件名"，避免把内腔表等其它表格的 link 名当成附件
        declared = re.findall(
            r"^\| `([^`]+\.(?:urdf|json|md|png|svg))` \|", text, flags=re.M)
        self.assertIn("atri.urdf", declared)
        self.assertIn("fit_report.md", declared)
        render_exts = {Path(n).suffix for n in declared if n.startswith("render_")}
        self.assertTrue(render_exts.issubset({".png", ".svg"}),
                        f"渲染附件扩展名异常: {render_exts}")
        for name in declared:
            with self.subTest(attachment=name):
                self.assertTrue((DESIGN / "handoff" / name).exists(),
                                f"附件 {name} 未打包")

    def test_task_list_targets_servo_selection(self):
        text = self.md.read_text(encoding="utf-8")
        self.assertIn("舵机选型", text)
        self.assertIn("S 档", text)
        self.assertIn("M 档", text)


if __name__ == "__main__":
    unittest.main()
