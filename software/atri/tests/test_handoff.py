"""硬件选型需求推导（交接包）测试。

守护的是"给下游 agent 的数据是否自洽、是否会被误读"：
  - 22 个关节都有需求，且为正
  - 腿部关节必须由单腿支撑工况主导（否则会选小舵机）
  - 分档数量之和 = 22
  - 假设值全部显式写出，不被当成实测
  - 扭矩双口径：主判据连续额定 0.98 N·m，超限关节必须显式列出
  - 参数总表/交接包等生成物不得回落 v2 或旧口径
  - 交接文档包含必要章节

运行：
    cd software/atri && python3 -m unittest tests.test_handoff -v
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
sys.path.insert(0, str(REPO / "software" / "atri"))

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
        cls.pb = gen_handoff.power_budget(model, torques)

    def test_current_is_plausible(self):
        """总电流应在合理量级——既不能是 0，也不该是几十安。"""
        total = self.pb["total_avg_current_at_pack_a"]
        self.assertGreater(total, 0.5)
        self.assertLess(total, 12.0)

    def test_battery_mass_is_plausible(self):
        """整包质量应在 0.1–0.6 kg（1.8kg 机器人）。"""
        self.assertGreater(self.pb["estimated_battery_mass_kg"], 0.1)
        self.assertLess(self.pb["estimated_battery_mass_kg"], 0.6)

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


class TestTorqueCriterion(unittest.TestCase):
    """D-1/D-9：扭矩裕度必须按连续额定 0.98 计算，超额定的关节必须被显式列出。"""

    @classmethod
    def setUpClass(cls):
        cls.model = gen_urdf.load_model()
        cls.joints = [gen_handoff.joint_torque(cls.model, j)
                      for j in sorted(cls.model["joints"],
                                      key=lambda x: x["id"])]
        cls.data = json.loads(
            (DESIGN / "handoff" / "hardware_requirements.json")
            .read_text(encoding="utf-8"))

    def test_primary_criterion_is_continuous_rated(self):
        crit = self.data["torque_criterion"]
        self.assertEqual(crit["primary"], "continuous_rated")
        self.assertAlmostEqual(crit["continuous_rated_torque_nm"], 0.98,
                               places=3)
        self.assertAlmostEqual(crit["peak_torque_nm"], 1.47, places=3)

    def test_margins_computed_against_continuous_rated(self):
        for t in self.joints:
            with self.subTest(joint=t["joint"]):
                self.assertAlmostEqual(
                    t["margin_vs_continuous_rated"],
                    t["required_torque_nm"] / 0.98, places=3)
                self.assertEqual(
                    t["exceeds_continuous_rated"],
                    t["required_torque_nm"] / 0.98 > 1.0 + 1e-9)

    def test_over_limit_joints_are_explicitly_listed(self):
        expected = sorted(t["joint"] for t in self.joints
                          if t["required_torque_nm"] / 0.98 > 1.0 + 1e-9)
        self.assertTrue(expected, "当前质量下应有超连续额定的关节")
        listed = sorted(self.data["torque_criterion"]
                        ["joints_exceeding_continuous"])
        self.assertEqual(listed, expected)
        # 关键结论：腿链与腰部横滚确实超标，且必须出现在清单里
        for joint in ("trunk_roll", "left_ankle_pitch", "right_ankle_pitch",
                      "left_knee_pitch", "right_knee_pitch"):
            self.assertIn(joint, listed)

    def test_document_flags_over_limit_joints(self):
        text = (DESIGN / "handoff" / "设计交接包-硬件选型需求.md").read_text(
            encoding="utf-8")
        self.assertIn("超连续额定", text)
        self.assertIn("trunk_roll", text)


class TestSpecSheetConsistency(unittest.TestCase):
    """D-2：参数总表是生成物，必须与当前 v3 模型一致，不得停留在 v2。"""

    @classmethod
    def setUpClass(cls):
        cls.sheet = DESIGN / "handoff" / "新架构参数总表.md"

    def test_sheet_exists(self):
        self.assertTrue(self.sheet.exists(),
                        "参数总表未生成，先跑 gen_spec_sheet.py")

    def test_sheet_uses_v3_link_masses(self):
        text = self.sheet.read_text(encoding="utf-8")
        self.assertIn("| `pelvis` | trunk | rounded_box | 100 × 80 × 35 | 160 | 340 |",
                      text)
        self.assertNotIn(
            "| `pelvis` | trunk | rounded_box | 100 × 80 × 35 | 45 | 225 |",
            text)
        self.assertIn("3.437", text)
        self.assertNotIn("2146", text)

    def test_sheet_states_dual_criterion(self):
        text = self.sheet.read_text(encoding="utf-8")
        self.assertIn("连续额定", text)
        self.assertIn("0.98", text)


class TestBatteryAndServoPresentation(unittest.TestCase):
    """D-3/D-5：电池容量口径与舵机外形必须与生成器一致。"""

    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(
            (DESIGN / "handoff" / "hardware_requirements.json")
            .read_text(encoding="utf-8"))
        cls.md = (DESIGN / "handoff" / "设计交接包-硬件选型需求.md").read_text(
            encoding="utf-8")

    def test_battery_requirement_is_current(self):
        pb = self.data["power_budget"]
        self.assertAlmostEqual(pb["required_nameplate_ah"], 4.53, places=2)
        self.assertAlmostEqual(pb["consumed_ah"], 3.63, places=2)
        self.assertIn("4.53", self.md)
        self.assertNotIn("2.89", self.md)

    def test_servo_size_is_model_size(self):
        text = " ".join(self.data["what_is_placeholder"])
        self.assertIn("45.2×24.7×35.0", text)
        self.assertNotIn("40×20×40.5", text)


class TestProjectDocsConsistency(unittest.TestCase):
    """项目文档不得残留旧电源口径（标称 2.89 Ah）；17DOF 核查必须用现行数字。"""

    DOC_DIR = REPO / "docs" / "research" / "项目文档"

    def test_no_stale_battery_nameplate(self):
        for path in sorted(self.DOC_DIR.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(doc=path.name):
                self.assertNotIn("2.89", text,
                                 f"{path.name} 残留旧电池标称 2.89 Ah")

    def test_17dof_doc_uses_current_power_numbers(self):
        text = (self.DOC_DIR / "两套17自由度方案可行性核查.md").read_text(
            encoding="utf-8")
        for token in ("3.63", "4.53", "7.25"):
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_design_generators_carry_no_stale_nameplate(self):
        """生成器脚本里的 note 会被写进 components/placements.json。

        即使 v1→v2 迁移当前对 v3 模型拒绝执行，字符串留着旧口径就是一枚
        待触发的回归——回退模型重跑迁移会把 2.89 Ah 写回生成物。
        """
        for path in sorted(DESIGN.glob("gen_*.py")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(script=path.name):
                self.assertNotIn("2.89", text,
                                 f"{path.name} 残留旧电池标称 2.89 Ah")


if __name__ == "__main__":
    unittest.main()
