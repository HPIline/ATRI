#!/usr/bin/env python3
"""布局门禁：摆放错误、赛框、髋距、头高、骨盆质量。

第 1 期要对的行为（改骨架之前必须先看到这些失败）：
    - pelvis_frame 不得与 hip_yaw / trunk_roll 舵机达到 ❌ 摆放错误
    - head_shell 不得与 head_pitch 舵机达到 ❌ 摆放错误
    - 肘叉不得与夹爪舵机达到 ❌ 摆放错误
    - 实装宽 ≤ 270 mm；髋 yaw |Y| ≥ 45 mm；头壳顶面不升高
    - 骨盆打印质量不得高于改前

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
ENVELOPE_DEPTH_MAX_MM = 180.0
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
        self.assertLessEqual(bb.zmin, -4.5, f"垫高 zmin={bb.zmin:.1f}")
        self.assertGreaterEqual(bb.zmin, -8.0, "垫太厚会抬整机")
        m = printed_mass(wp, material="PETG", infill=0.45)
        self.assertLessEqual(m["mass_printed_g"], 42.0, m)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
