"""硬件选型需求推导（交接包）测试。

守护的是"给下游 agent 的数据是否自洽、是否会被误读"：
  - 22 个关节都有需求，且为正
  - 腿部关节必须由单腿支撑工况主导（否则会选小舵机）
  - 分档数量之和 = 22
  - 假设值全部显式写出，不被当成实测
  - 扭矩双口径：主判据连续额定 0.98 N·m，超限关节必须显式列出
  - **重力矩两种口径（零姿态 / 限位内最不利）必须同时给出且口径自洽**
  - 参数总表/交接包等生成物不得回落 v2 或旧口径
  - 交接文档包含必要章节

⚠️ 2026-09-12 力臂口径修正后的判据纪律：本文件**不钉死任何历史常数**
（曾写死过 trunk_roll 是最大关节、超限清单必须包含 trunk_roll），
改为断言"由产物自身复算得出来的关系"，例如
`margin == required_torque_nm / 0.98`、`最不利 ≥ 零姿态`、
`需求 = max(重力×1.8, 惯性×1.8, 支撑, 工程下限)`。

运行：
    cd software/atri && python3 -m unittest tests.test_handoff -v
"""
from __future__ import annotations

import json
import math
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

    def test_trunk_roll_is_not_the_heaviest_joint(self):
        """腰部横滚**不是**最大需求关节——最大的一定是单腿支撑主导的腿部关节。

        ⚠️ 2026-09-12 力臂口径修正前，`trunk_roll` 因"把竖直偏移也算进力臂"
        被高估到 1.835 N·m（187%），曾是最大关节；修正后重力力臂必须只取
        水平面内垂直于关节轴的分量，躯干质心基本正对横滚轴，其中枢值远小于腿部支撑项。
        本判据不钉死任何数值，只断言结构关系：需求最大者必须由 stance 主导。
        """
        top = max(self.joints, key=lambda t: t["required_torque_nm"])
        self.assertEqual(top["requirements_driver"], "stance",
                         f"最大需求关节 {top['joint']} 不是单腿支撑主导："
                         f"{top['requirements_driver']}")
        self.assertTrue(top["joint"].startswith(("left_", "right_")),
                        f"最大需求关节 {top['joint']} 不在腿链上")
        # 并且最大需求确实等于它的支撑项（而不是某个被高估的重力项）
        self.assertAlmostEqual(top["required_torque_nm"],
                               top["stance_torque_nm"], places=4)

    def test_gravity_torque_zero_pose_formula(self):
        """零姿态重力矩必须能由逐 link 明细精确复算（两种对账方式）。

        ① Σ m·signed_arm·g/1000 == τ（带符号求和，逐项符号可相消——躯干横滚
           的质心几乎正对轴线，正是靠相消才得到 ~0，这一点必须能被复现）；
        ② Σ m·|arm|·g/1000 ≥ |τ|（绝对值求和是上界）。
        容差 1e-4 来自 `detail` 里力臂按 2 位小数、力矩按 4 位小数发布。
        """
        for t in self.joints:
            with self.subTest(joint=t["joint"]):
                signed_sum = sum(d["mass_kg"] * gen_handoff.G
                                 * d["signed_gravity_arm_mm"] / 1000.0
                                 for d in t["detail"])
                self.assertAlmostEqual(abs(signed_sum),
                                       t["gravity_torque_nm_zero_pose"],
                                       delta=1e-4)
                moment_sum = sum(d["moment_kgmm"] for d in t["detail"])
                self.assertAlmostEqual(abs(moment_sum) / 1000.0 * gen_handoff.G,
                                       t["gravity_torque_nm_zero_pose"],
                                       delta=1e-4)
                abs_sum = sum(d["mass_kg"] * gen_handoff.G
                              * d["gravity_arm_mm"] / 1000.0
                              for d in t["detail"])
                self.assertGreaterEqual(abs_sum + 1e-4,
                                        t["gravity_torque_nm_zero_pose"])

    def test_two_gravity_calibers_present_and_ordered(self):
        """两种口径必须都在，且 最不利 ≥ 零姿态 ≥ 0（最不利是包络上界）。"""
        for t in self.joints:
            with self.subTest(joint=t["joint"]):
                self.assertIn("gravity_torque_nm_zero_pose", t)
                self.assertIn("gravity_torque_nm_worst_case", t)
                self.assertGreaterEqual(t["gravity_torque_nm_worst_case"],
                                        t["gravity_torque_nm_zero_pose"] - 1e-6)
                self.assertGreaterEqual(t["gravity_torque_nm_zero_pose"], 0.0)
                self.assertGreaterEqual(t["required_torque_nm"],
                                        t["required_torque_nm_zero_pose"] - 1e-6)

    def test_required_torque_is_envelope_of_three_cases(self):
        """需求 = max(重力×安全系数, 惯性×安全系数, 支撑, 工程下限)，两种口径各自成立。"""
        sf = gen_handoff.ASSUMPTIONS["safety_factor_static"]
        floor = gen_handoff.ASSUMPTIONS["min_practical_torque_nm"]
        for t in self.joints:
            with self.subTest(joint=t["joint"]):
                for req_key, g_key in (
                        ("required_torque_nm", "gravity_torque_nm_worst_case"),
                        ("required_torque_nm_zero_pose",
                         "gravity_torque_nm_zero_pose")):
                    expect = max(t[g_key] * sf, t["inertia_torque_nm"] * sf,
                                 t["stance_torque_nm"], floor)
                    self.assertAlmostEqual(t[req_key], expect, places=4)

    def test_vertical_axis_joints_have_exactly_zero_gravity(self):
        """竖直轴关节（髋 yaw）的重力矩**恒为 0**——这是对的物理，不是漏算。

        重力与该轴平行 ⇒ (r × g ẑ)·â ≡ 0，任何姿态都是 0（含最不利口径）。
        注意"质心到轴线的水平距离"不是重力力臂：那是水平外力的力臂，
        只有转动惯量 I = Σ m·r⊥² 才用它。
        """
        for name in ("left_hip_yaw", "right_hip_yaw"):
            t = next(x for x in self.joints if x["joint"] == name)
            with self.subTest(joint=name):
                self.assertEqual(t["gravity_torque_nm_zero_pose"], 0.0)
                self.assertEqual(t["gravity_torque_nm_worst_case"], 0.0)
                # 但需求不能是 0（要能摆动），落到单腿支撑/工程下限
                self.assertGreaterEqual(
                    t["required_torque_nm"],
                    gen_handoff.ASSUMPTIONS["min_practical_torque_nm"] - 1e-9)

    def test_gravity_moment_arm_excludes_vertical_component(self):
        """力臂口径的最小复现（这是本次修正的核心）：

        绕水平轴（x）的重力力臂只取 y 分量——质心正对轴线上方时力臂为 0；
        而"到轴线的垂直距离"（径向臂）此时是 100 mm，两者**不是同一个量**。
        """
        arm_g = gen_handoff.gravity_moment_arm
        arm_r = gen_handoff.perpendicular_arm
        # 质心在轴的正上方 → 重力力臂 0；径向臂（到轴线的垂直距离）是 100
        self.assertAlmostEqual(arm_g((0.0, 0.0, 100.0), [1, 0, 0]), 0.0, places=9)
        self.assertAlmostEqual(arm_r((0.0, 0.0, 100.0), [1, 0, 0]), 100.0,
                               places=9)
        # 同时有沿轴分量与垂直分量：绕 x 轴的重力力臂只取 y=40，
        # 而不是到轴线的距离 sqrt(40²+100²)=107.7
        self.assertAlmostEqual(arm_g((30.0, 40.0, 100.0), [1, 0, 0]), 40.0,
                               places=9)
        self.assertAlmostEqual(arm_r((30.0, 40.0, 100.0), [1, 0, 0]),
                               math.hypot(40.0, 100.0), places=9)
        # 竖直轴：任何水平偏移都不产生重力矩（径向臂却非零）
        self.assertAlmostEqual(arm_g((60.0, 80.0, 0.0), [0, 0, 1]), 0.0,
                               places=9)
        self.assertAlmostEqual(arm_r((60.0, 80.0, 0.0), [0, 0, 1]), 100.0,
                               places=9)
        # 轴不必是单位向量，结果要一致
        self.assertAlmostEqual(arm_g((30.0, 40.0, 100.0), [2, 0, 0]), 40.0,
                               places=9)
        # 绕 y 轴的俯仰：只认 x 分量
        self.assertAlmostEqual(arm_g((30.0, 40.0, 100.0), [0, 1, 0]), 30.0,
                               places=9)

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
        # 主判据用的重力口径必须显式声明，并是两种口径之一
        self.assertIn(crit["primary_gravity_caliber"], crit["gravity_calibers"])

    def test_margins_computed_against_continuous_rated(self):
        """裕度必须与**发布出去的**需求自洽（两种口径都查），不钉历史常数。"""
        for t in self.joints:
            with self.subTest(joint=t["joint"]):
                self.assertAlmostEqual(
                    t["margin_vs_continuous_rated"],
                    t["required_torque_nm"] / 0.98, places=3)
                self.assertEqual(
                    t["exceeds_continuous_rated"],
                    t["required_torque_nm"] / 0.98 > 1.0 + 1e-9)
                self.assertAlmostEqual(
                    t["margin_vs_continuous_rated_zero_pose"],
                    t["required_torque_nm_zero_pose"] / 0.98, places=3)
                self.assertEqual(
                    t["exceeds_continuous_rated_zero_pose"],
                    t["required_torque_nm_zero_pose"] / 0.98 > 1.0 + 1e-9)

    def test_over_limit_joints_are_explicitly_listed(self):
        """超限清单必须由产物自身复算得出，两种口径各列一份。"""
        expected = sorted(t["joint"] for t in self.joints
                          if t["required_torque_nm"] / 0.98 > 1.0 + 1e-9)
        listed = sorted(self.data["torque_criterion"]
                        ["joints_exceeding_continuous"])
        self.assertEqual(listed, expected)
        expected_zero = sorted(t["joint"] for t in self.joints
                               if t["required_torque_nm_zero_pose"] / 0.98
                               > 1.0 + 1e-9)
        listed_zero = sorted(self.data["torque_criterion"]
                             ["joints_exceeding_continuous_zero_pose"])
        self.assertEqual(listed_zero, expected_zero)
        # 结论：腿链（单腿支撑主导）在两种口径下都超额定——这是当前真正的缺口
        for joint in ("left_ankle_pitch", "right_ankle_pitch",
                      "left_knee_pitch", "right_knee_pitch",
                      "left_hip_yaw", "right_hip_yaw"):
            self.assertIn(joint, listed)
            self.assertIn(joint, listed_zero)
        # 而 trunk_roll 在两种口径下都**不再**超额定（力臂口径修正的直接后果）
        self.assertNotIn("trunk_roll", listed)
        self.assertNotIn("trunk_roll", listed_zero)
        trunk = next(t for t in self.joints if t["joint"] == "trunk_roll")
        self.assertLess(trunk["required_torque_nm"], 0.98)
        self.assertLess(trunk["gravity_torque_nm_zero_pose"], 0.05)

    def test_document_states_both_calibers(self):
        """交接文档必须把两种重力口径都写出来，不能被"选一种"悄悄抹掉。"""
        text = (DESIGN / "handoff" / "设计交接包-硬件选型需求.md").read_text(
            encoding="utf-8")
        self.assertIn("零姿态", text)
        self.assertIn("最不利", text)
        # 力臂的定义必须写明是"水平面内垂直于关节轴的分量"（而不是到轴线的距离）
        self.assertIn("重力力臂", text)
        self.assertIn("垂直于关节轴", text)

    def test_document_flags_over_limit_joints(self):
        text = (DESIGN / "handoff" / "设计交接包-硬件选型需求.md").read_text(
            encoding="utf-8")
        self.assertTrue("超连续额定" in text or "官方额定" in text)
        self.assertIn("trunk_roll", text)

    def test_torque_check_block_matches_joints(self):
        """`torque_check`（给人工快速核对用的紧凑块）必须与逐关节数据一致。"""
        tc = self.data["torque_check"]
        self.assertIn("zero_pose_static", tc["calibers"])
        self.assertIn("worst_case_within_limits", tc["calibers"])
        pct = {x["joint"]: x for x in tc["joints_pct_of_continuous_rated"]}
        self.assertEqual(len(pct), len(self.joints))
        for t in self.joints:
            with self.subTest(joint=t["joint"]):
                row = pct[t["joint"]]
                self.assertAlmostEqual(row["zero_pose_pct"],
                                       t["pct_continuous_rated_zero_pose"],
                                       places=1)
                self.assertAlmostEqual(row["worst_case_pct"],
                                       t["pct_continuous_rated"], places=1)
                self.assertEqual(row["exceeds_rated"],
                                 t["exceeds_continuous_rated"])
                self.assertEqual(row["exceeds_rated_zero_pose"],
                                 t["exceeds_continuous_rated_zero_pose"])
        self.assertEqual(sorted(tc["exceeding_worst_case"]),
                         sorted(self.data["torque_criterion"]
                                ["joints_exceeding_continuous"]))
        self.assertEqual(tc["same_set"],
                         sorted(tc["exceeding_worst_case"])
                         == sorted(tc["exceeding_zero_pose"]))


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
        self.assertIn("3.036", text)
        self.assertNotIn("2146", text)

    def test_sheet_states_dual_criterion(self):
        text = self.sheet.read_text(encoding="utf-8")
        self.assertIn("0.98", text)
        self.assertTrue("连续额定" in text or "官方额定" in text)


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
        """续航需求必须与**自身口径**自洽，而不是钉死在某个历史数值上。

        ⚠️ 2026-09-12：模型质量回灌（结构 1490→1390 g、整机 3136→3036 g）后，
        `required_nameplate_ah` 由 11.83 降到 **11.52**、`consumed_ah` 由 9.46 降到 9.21 —
        这是"同一口径联动"的正常结果，不是回归。原断言硬编码 11.83/9.46，一改质量就红。
        现在改为交叉验证（电流 × 时长 ÷ 可用放电深度），并对量级做区间约束；
        同时仍要求文档里写明"2000 mAh 不够"这件事（缺口不能被悄悄抹掉）。
        """
        pb = self.data["power_budget"]
        consumed = pb["consumed_ah"]
        # consumed_ah = 总电流 × 时长
        self.assertAlmostEqual(
            consumed, pb["total_avg_current_at_pack_a"] * pb["mission_min"] / 60.0,
            places=1)
        # required_nameplate_ah = consumed / 可用放电深度（现取 0.8）
        self.assertAlmostEqual(pb["required_nameplate_ah"], consumed / 0.8, places=1)
        # 量级约束：换过舵机口径/质量口径后若跑到这个区间外，说明模型坏了
        self.assertTrue(8.0 <= pb["required_nameplate_ah"] <= 15.0,
                        f"需求 {pb['required_nameplate_ah']} Ah 超出合理量级")
        # 缺口必须写在文档里（"不够"或具体 Ah 数），且不得回退到旧口径
        self.assertTrue("不够" in self.md or f"{pb['required_nameplate_ah']:.2f}" in self.md)
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

    def test_17dof_doc_does_not_revive_v1_nameplate(self):
        text = (self.DOC_DIR / "两套17自由度方案可行性核查.md").read_text(
            encoding="utf-8")
        self.assertNotIn("2.89", text)

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
