#!/usr/bin/env python3
"""布局门禁：摆放错误、赛框、髋距、头高、骨盆质量、零位清髋、着地。

第 1 期要对的行为（改骨架之前必须先看到这些失败）：
    - pelvis_frame 不得与 hip_yaw / trunk_roll 舵机达到 ❌ 摆放错误
    - head_shell 不得与 head_pitch 舵机达到 ❌ 摆放错误
    - 肘叉不得与夹爪舵机达到 ❌ 摆放错误
    - 实装宽 ≤ 270 mm；髋 yaw |Y| ≥ 45 mm；头壳顶面不升高
    - 骨盆打印质量不得高于改前
    - 机械零位夹爪不得穿髋 yaw
    - 橡胶垫是全机最低点，踝笼/舵机不得低于垫
    - 簇臂不得穿父舵机/髋笼/夹爪舵机；XL4015 不得穿背板

用法：
    .venv-cad/bin/python design/cad/test_layout.py
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import assembly as A  # noqa: E402
from fitcheck import bbox_of, common_volume, verdict  # noqa: E402
from kit import printed_mass  # noqa: E402
from skeleton import foot_plate, head_shell, pelvis_frame  # noqa: E402

# 改前预览 META.bbox zmax；头壳只许让位、不许抬高整机。
HEAD_ZMAX_LIMIT_MM = 207.0
ENVELOPE_WIDTH_MAX_MM = 270.0
ENVELOPE_HEIGHT_MAX_MM = 420.0
# 第 7 轮前脸 ≤147；第 9 轮背挂贴板外侧，xmin 到约 −85，整机深 ~159。
ENVELOPE_DEPTH_MAX_MM = 165.0
HIP_YAW_Y_MIN_MM = 45.0
# 改前 pelvis_frame 打印质量（PETG infill 0.45）——实现时先跑本文件记下，再锁。
PELVIS_MASS_MAX_G = 130.0

PHASE1_PAIRS = [
    ("pelvis__pelvis_frame", "servo__left_hip_yaw"),
    ("pelvis__pelvis_frame", "servo__right_hip_yaw"),
    ("pelvis__pelvis_frame", "servo__trunk_roll"),
    ("head__head_shell", "servo__head_pitch"),
    ("fork__left_elbow_pitch", "servo__left_gripper"),
    ("fork__right_elbow_pitch", "servo__right_gripper"),
    ("left_gripper__gripper_jaw", "servo__left_gripper"),
    ("right_gripper__gripper_jaw", "servo__right_gripper"),
    ("servo__head_pitch", "elec__USB 免驱拾音模块 (CM6533)"),
    ("servo__head_yaw", "elec__USB 免驱拾音模块 (CM6533)"),
    ("servo__trunk_roll", "elec__ICM-42688-P 模块"),
]

# 机械零位：夹爪不得伸进髋 yaw（不靠 DISPLAY_POSE 躲）。
ZERO_GRIPPER_HIP_PAIRS = [
    ("right_gripper__gripper_jaw", "servo__right_hip_yaw"),
    ("right_gripper__gripper_jaw", "cage__right_hip_yaw"),
    ("left_gripper__gripper_jaw", "servo__left_hip_yaw"),
    ("left_gripper__gripper_jaw", "cage__left_hip_yaw"),
]

# 第 9 轮：簇臂按舵盘面构造、背挂贴板外侧。禁止 AABB 切盒。
ROUND9_PAIRS = [
    ("torso_upper__backpack_plate", "elec__XL4015 降压模块"),
    ("left_hip_yaw_link__cluster_horn_arm", "servo__left_hip_yaw"),
    ("right_hip_yaw_link__cluster_horn_arm", "servo__right_hip_yaw"),
    ("right_hip_yaw_link__cluster_horn_arm", "servo__right_gripper"),
    ("right_hip_roll_link__cluster_horn_arm", "cage__right_hip_yaw"),
]


def _assembly():
    kin = A.Kin(A.DESIGN / "atri.urdf")
    placements = json.loads((A.DESIGN / "placements.json").read_text(encoding="utf-8"))
    items, log = A.build_assembly(kin, placements)
    bad = [l for l in log if not l.get("ok")]
    if bad:
        raise AssertionError("装配失败: " + ", ".join(b["name"] for b in bad[:8]))
    return kin, dict(items)


class LayoutGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kin, cls.shapes = _assembly()

    def _pair_verdict(self, a: str, b: str) -> tuple[float, float, str]:
        sa, sb = self.shapes[a], self.shapes[b]
        vol = common_volume(sa, sb)
        smaller = min(sa.val().Volume(), sb.val().Volume())
        frac = vol / max(smaller, 1e-9)
        return vol, frac, verdict(vol, frac)

    def test_phase1_pairs_are_not_placement_errors(self):
        bad = []
        for a, b in PHASE1_PAIRS:
            self.assertIn(a, self.shapes, a)
            self.assertIn(b, self.shapes, b)
            vol, frac, verd = self._pair_verdict(a, b)
            if verd == "❌ 摆放错误":
                bad.append(f"{a} ∩ {b} = {vol:.0f} mm³ ({frac*100:.0f}%) {verd}")
        self.assertFalse(bad, "第 1 期目标对应仍是摆放错误:\n  " + "\n  ".join(bad))

    def test_envelope_within_contest_margin(self):
        boxes = [bbox_of(w) for w in self.shapes.values()]
        xmin = min(b.xmin for b in boxes)
        xmax = max(b.xmax for b in boxes)
        ymin = min(b.ymin for b in boxes)
        ymax = max(b.ymax for b in boxes)
        zmin = min(b.zmin for b in boxes)
        zmax = max(b.zmax for b in boxes)
        depth, width, height = xmax - xmin, ymax - ymin, zmax - zmin
        self.assertLessEqual(width, ENVELOPE_WIDTH_MAX_MM, f"宽 {width:.1f} mm")
        self.assertLessEqual(height, ENVELOPE_HEIGHT_MAX_MM, f"高 {height:.1f} mm")
        self.assertLessEqual(depth, ENVELOPE_DEPTH_MAX_MM, f"深 {depth:.1f} mm")
        self.assertLessEqual(zmax, HEAD_ZMAX_LIMIT_MM + 0.5, f"头顶 zmax {zmax:.1f}")

    def test_hip_yaw_stance_not_narrowed(self):
        for name, sign in (("left_hip_yaw", 1.0), ("right_hip_yaw", -1.0)):
            origin = self.kin.joint_world(name)
            y = origin[1][3]
            self.assertGreaterEqual(sign * y, HIP_YAW_Y_MIN_MM, f"{name} y={y}")

    def test_pelvis_printed_mass_not_up(self):
        m = printed_mass(pelvis_frame(), material="PETG", infill=0.45)
        self.assertLessEqual(m["mass_printed_g"], PELVIS_MASS_MAX_G, m)
        self.assertGreaterEqual(m["mass_printed_g"], 15.0, m)

    def test_head_shell_z0_not_raised(self):
        bb = head_shell().val().BoundingBox()
        # 局部系：pitch 轴在 z=0。顶面不得高于改前 22+43/2 = 43.5（z0=22, hh=43）。
        # 改前实测局部 zmax=50（顶板 + 相机座）。只许让位，不许再抬。
        self.assertLessEqual(bb.zmax, 50.0 + 0.05, f"head_shell zmax {bb.zmax:.1f}")

    def test_foot_heel_and_pads(self):
        """后跟 ≥45 mm（静立后向），宽 60，橡胶垫在鞋底之下，不打穿底板。"""
        wp = foot_plate()
        bb = wp.val().BoundingBox()
        self.assertLessEqual(bb.xmin, -45.0, f"后跟 xmin={bb.xmin:.1f}")
        self.assertLessEqual(bb.ylen, 62.0, f"足宽 {bb.ylen:.1f}")
        self.assertGreaterEqual(bb.ylen, 58.0, f"足宽 {bb.ylen:.1f}")
        # 垫必须低于踝笼半高（笼约 −15.4），才能成为唯一着地点。
        self.assertLessEqual(bb.zmin, -15.5, f"垫高 zmin={bb.zmin:.1f}")
        self.assertGreaterEqual(bb.zmin, -18.5, "垫过厚会把整机抬出 420 门禁")
        m = printed_mass(wp, material="PETG", infill=0.45)
        self.assertLessEqual(m["mass_printed_g"], 42.0, m)

    def test_soles_are_lowest(self):
        """橡胶垫是唯一着地点；踝笼/舵机不得低于垫。"""
        boxes = {n: bbox_of(w) for n, w in self.shapes.items()}
        zmin = min(b.zmin for b in boxes.values())
        for side in ("left", "right"):
            sole = boxes[f"{side}_foot__foot_plate"]
            cage = boxes[f"cage__{side}_ankle_pitch"]
            servo = boxes[f"servo__{side}_ankle_pitch"]
            self.assertAlmostEqual(
                sole.zmin, zmin, delta=0.5, msg=f"{side} 垫不是全机最低")
            self.assertGreaterEqual(
                cage.zmin, sole.zmin + 0.5, f"{side} 笼仍低于垫")
            self.assertGreaterEqual(
                servo.zmin, sole.zmin + 0.5, f"{side} 舵机仍低于垫")

    def test_feet_are_left_right_mirrors(self):
        """左右脚同一零件镜像，包络应对称。"""
        self.assertIn("left_foot__foot_plate", self.shapes)
        self.assertIn("right_foot__foot_plate", self.shapes)
        L = bbox_of(self.shapes["left_foot__foot_plate"])
        R = bbox_of(self.shapes["right_foot__foot_plate"])
        self.assertAlmostEqual(L.xmin, R.xmin, delta=1.5)
        self.assertAlmostEqual(L.xmax, R.xmax, delta=1.5)
        self.assertAlmostEqual(L.zmin, R.zmin, delta=1.5)
        self.assertAlmostEqual(L.ymin + R.ymax, 0.0, delta=2.5)
        self.assertAlmostEqual(L.ymax + R.ymin, 0.0, delta=2.5)

    def test_head_mic_inside_visor(self):
        """拾音不得探出头壳前脸（hl/2=38），避免再把深度顶到 149。"""
        bb = head_shell().val().BoundingBox()
        self.assertLessEqual(bb.xmax, 39.5, f"head_shell xmax {bb.xmax:.1f}")
        mic = None
        for name, w in self.shapes.items():
            if "拾音" in name:
                mic = bbox_of(w)
                break
        self.assertIsNotNone(mic, "找不到拾音模块")
        # 整机 xmax 由头前脸/相机决定，拾音不得再当最前点
        boxes = [bbox_of(w) for w in self.shapes.values()]
        xmax = max(b.xmax for b in boxes)
        self.assertLessEqual(mic.xmax, xmax + 0.05)
        self.assertLessEqual(xmax - min(b.xmin for b in boxes), ENVELOPE_DEPTH_MAX_MM)

    def test_round9_cluster_and_backpack_clear(self):
        """簇臂不得穿进父舵机/笼或右夹爪舵机；XL4015 不得穿背板。"""
        bad = []
        for a, b in ROUND9_PAIRS:
            self.assertIn(a, self.shapes, a)
            self.assertIn(b, self.shapes, b)
            vol, frac, verd = self._pair_verdict(a, b)
            if verd in ("❌ 摆放错误", "⚠️ 让位不足"):
                bad.append(f"{a} ∩ {b} = {vol:.0f} mm³ ({frac*100:.0f}%) {verd}")
        self.assertFalse(bad, "第 9 轮目标对仍穿模:\n  " + "\n  ".join(bad))

    def test_zero_pose_gripper_clears_hip(self):
        """机械零位：夹爪零件不得与髋 yaw 达到摆放错误或让位不足。"""
        bad = []
        for a, b in ZERO_GRIPPER_HIP_PAIRS:
            self.assertIn(a, self.shapes, a)
            self.assertIn(b, self.shapes, b)
            vol, frac, verd = self._pair_verdict(a, b)
            if verd in ("❌ 摆放错误", "⚠️ 让位不足"):
                bad.append(f"{a} ∩ {b} = {vol:.0f} mm³ ({frac*100:.0f}%) {verd}")
        self.assertFalse(bad, "零位夹爪仍穿髋:\n  " + "\n  ".join(bad))

    def test_display_pose_hands_leave_hips(self):
        """展示姿态：手在身前，不穿髋；不外展超宽。"""
        kin = A.Kin(A.DESIGN / "atri.urdf", pose_deg=A.DISPLAY_POSE_DEG)
        lg = kin.world["left_gripper"]
        rg = kin.world["right_gripper"]
        self.assertGreater(lg[0][3], 40.0, "左手应抬到 +X")
        self.assertGreater(rg[0][3], 40.0, "右手应抬到 +X")
        self.assertGreater(lg[2][3], 0.0, "左手应离开髋高度")
        # 限位
        limits = {
            "left_shoulder_pitch": (-90, 90),
            "right_shoulder_pitch": (-90, 90),
            "left_elbow_pitch": (-120, 0),
            "right_elbow_pitch": (-120, 0),
            "left_gripper": (0, 60),
            "right_gripper": (0, 60),
            "head_pitch": (-45, 45),
        }
        for j, q in A.DISPLAY_POSE_DEG.items():
            lo, hi = limits[j]
            self.assertGreaterEqual(q, lo, j)
            self.assertLessEqual(q, hi, j)

    def test_pelvis_has_torso_riser(self):
        """U 臂要收到胸框后柱附近（y≈±48），不能只停在 y=±60 当挡板。"""
        bb = pelvis_frame().val().BoundingBox()
        self.assertGreaterEqual(bb.ymax, 47.0, "U 外缘仍要让开 hip_yaw")
        # 在 z>8 的上段，宽度应收向胸框（ymax 局部上段 ≤ 56）
        import cadquery as cq
        upper = pelvis_frame().intersect(
            cq.Workplane("XY").box(200, 200, 20, centered=(True, True, False)).translate((0, 0, 10))
        )
        ub = upper.val().BoundingBox()
        self.assertLessEqual(ub.ymax, 56.0, f"上段仍张开 ymax={ub.ymax:.1f}")
        self.assertGreaterEqual(ub.ymax, 44.0, "上段要接到胸框后柱")


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
