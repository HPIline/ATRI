"""几何基元、三维变换与工程图生成测试。

运行：
    cd software/atri && python3 -m unittest tests.test_geometry_drawings -v
"""
from __future__ import annotations

import math
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DESIGN = REPO / "archive" / "v1-22dof" / "design"
sys.path.insert(0, str(DESIGN))
sys.path.insert(0, str(REPO / "design"))  # geometry.py
sys.path.insert(0, str(REPO / "software" / "atri"))

import geometry  # noqa: E402
import gen_urdf  # noqa: E402
import gen_drawings  # noqa: E402


class TestPrimitives(unittest.TestCase):
    def test_box_bounding_box(self):
        g = {"type": "box", "size_mm": [10.0, 20.0, 30.0]}
        self.assertEqual(geometry.bounding_box(g), [10.0, 20.0, 30.0])

    def test_cylinder_bbox_respects_axis(self):
        base = {"type": "cylinder", "radius_mm": 5.0, "height_mm": 20.0}
        self.assertEqual(
            geometry.bounding_box({**base, "axis": "x"}), [20.0, 10.0, 10.0]
        )
        self.assertEqual(
            geometry.bounding_box({**base, "axis": "z"}), [10.0, 10.0, 20.0]
        )

    def test_sphere_bbox(self):
        g = {"type": "sphere", "radius_mm": 7.0}
        self.assertEqual(geometry.bounding_box(g), [14.0, 14.0, 14.0])

    def test_capsule_bbox_adds_hemispheres(self):
        g = {"type": "capsule", "radius_mm": 5.0, "length_mm": 30.0, "axis": "z"}
        # 轴向 = length + 2r = 40
        self.assertEqual(geometry.bounding_box(g), [10.0, 10.0, 40.0])

    def test_sphere_shell_bbox(self):
        g = {"type": "sphere_shell", "outer_r_mm": 20.0, "inner_r_mm": 18.0}
        self.assertEqual(geometry.bounding_box(g), [40.0, 40.0, 40.0])

    def test_invalid_definitions_raise(self):
        for bad in (
            {"type": "box", "size_mm": [1.0, 2.0]},
            {"type": "cylinder", "radius_mm": -1.0, "height_mm": 5.0},
            {"type": "sphere_shell", "outer_r_mm": 5.0, "inner_r_mm": 9.0},
            {"type": "nope"},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(geometry.GeometryError):
                    geometry.bounding_box(bad)

    def test_equivalent_box_preserves_extent(self):
        for g in (
            {"type": "sphere", "radius_mm": 6.0},
            {"type": "capsule", "radius_mm": 4.0, "length_mm": 10.0, "axis": "y"},
            {"type": "sphere_shell", "outer_r_mm": 9.0, "inner_r_mm": 7.0},
        ):
            with self.subTest(g=g["type"]):
                self.assertEqual(
                    geometry.equivalent_box(g)["size_mm"],
                    geometry.bounding_box(g),
                )


class TestInertia(unittest.TestCase):
    def test_box_matches_closed_form(self):
        m, (w, d, h) = 0.1, (0.010, 0.020, 0.030)
        g = {"type": "box", "size_mm": [10.0, 20.0, 30.0]}
        ixx, iyy, izz = geometry.inertia(g, m)
        self.assertAlmostEqual(ixx, m * (d * d + h * h) / 12.0, places=12)
        self.assertAlmostEqual(iyy, m * (w * w + h * h) / 12.0, places=12)
        self.assertAlmostEqual(izz, m * (w * w + d * d) / 12.0, places=12)

    def test_sphere_matches_closed_form(self):
        m, r = 0.2, 0.05
        g = {"type": "sphere", "radius_mm": 50.0}
        for i in geometry.inertia(g, m):
            self.assertAlmostEqual(i, 0.4 * m * r * r, places=12)

    def test_cylinder_axial_is_half_mr2(self):
        m, r, h = 0.1, 0.005, 0.02
        g = {"type": "cylinder", "radius_mm": 5.0, "height_mm": 20.0, "axis": "z"}
        ixx, iyy, izz = geometry.inertia(g, m)
        self.assertAlmostEqual(izz, 0.5 * m * r * r, places=12)
        self.assertAlmostEqual(ixx, m * (3 * r * r + h * h) / 12.0, places=12)
        self.assertAlmostEqual(ixx, iyy, places=12)

    def test_cylinder_axis_permutes_inertia(self):
        gx = {"type": "cylinder", "radius_mm": 5.0, "height_mm": 20.0, "axis": "x"}
        gz = {"type": "cylinder", "radius_mm": 5.0, "height_mm": 20.0, "axis": "z"}
        ix, iy, iz = geometry.inertia(gx, 0.1)
        zx, zy, zz = geometry.inertia(gz, 0.1)
        self.assertAlmostEqual(ix, zz, places=12)
        self.assertAlmostEqual(iz, zx, places=12)

    def test_capsule_axial_less_than_radial(self):
        """胶囊沿轴向细长，轴向惯量应明显小于径向。"""
        g = {"type": "capsule", "radius_mm": 5.0, "length_mm": 40.0, "axis": "z"}
        ixx, iyy, izz = geometry.inertia(g, 0.1)
        self.assertLess(izz, ixx)
        self.assertAlmostEqual(ixx, iyy, places=12)

    def test_all_positive(self):
        for g in (
            {"type": "box", "size_mm": [1, 2, 3]},
            {"type": "rounded_box", "size_mm": [10, 20, 30], "fillet_mm": 2},
            {"type": "cylinder", "radius_mm": 3, "height_mm": 9, "axis": "y"},
            {"type": "sphere", "radius_mm": 4},
            {"type": "capsule", "radius_mm": 3, "length_mm": 8, "axis": "x"},
            {"type": "sphere_shell", "outer_r_mm": 8, "inner_r_mm": 6},
        ):
            with self.subTest(g=g["type"]):
                self.assertTrue(all(i > 0 for i in geometry.inertia(g, 0.05)))


class TestTransforms(unittest.TestCase):
    def test_identity_transform(self):
        p = geometry.transform_point(geometry.identity(), (1.0, 2.0, 3.0))
        self.assertEqual(p, (1.0, 2.0, 3.0))

    def test_translation(self):
        m = geometry.translation(10.0, -5.0, 2.0)
        self.assertEqual(
            geometry.transform_point(m, (1.0, 1.0, 1.0)), (11.0, -4.0, 3.0)
        )

    def test_rotation_z_90deg(self):
        m = geometry.rotation_matrix((0, 0, 1), math.pi / 2)
        x, y, z = geometry.transform_point(m, (1.0, 0.0, 0.0))
        self.assertAlmostEqual(x, 0.0, places=9)
        self.assertAlmostEqual(y, 1.0, places=9)

    def test_rotation_x_90deg(self):
        m = geometry.rotation_matrix((1, 0, 0), math.pi / 2)
        x, y, z = geometry.transform_point(m, (0.0, 1.0, 0.0))
        self.assertAlmostEqual(z, 1.0, places=9)

    def test_joint_transform_translates_then_rotates(self):
        """关节变换：原点平移先生效，旋转绕新原点。"""
        m = geometry.joint_transform((0, 0, 100), (0, 1, 0), 90.0)
        # 原点本身应映射到 (0,0,100)
        p = geometry.transform_point(m, (0.0, 0.0, 0.0))
        self.assertAlmostEqual(p[2], 100.0, places=6)
        # 沿 +X 的点绕 Y 轴 90° 后应指向 -Z
        q = geometry.transform_point(m, (1.0, 0.0, 0.0))
        self.assertAlmostEqual(q[2], 99.0, places=6)

    def test_rotation_is_orthonormal(self):
        m = geometry.rotation_matrix((1, 2, 3), 0.7)
        for i in range(3):
            norm = math.sqrt(sum(m[i][j] ** 2 for j in range(3)))
            self.assertAlmostEqual(norm, 1.0, places=9)


class TestProjection(unittest.TestCase):
    def test_cylinder_is_circle_along_its_axis(self):
        g = {"type": "cylinder", "radius_mm": 5.0, "height_mm": 20.0, "axis": "z"}
        self.assertEqual(geometry.project_shape(g, "top")["kind"], "circle")
        self.assertEqual(geometry.project_shape(g, "front")["kind"], "rect")

    def test_sphere_is_circle_in_all_views(self):
        g = {"type": "sphere", "radius_mm": 6.0}
        for v in geometry.VIEWS:
            self.assertEqual(geometry.project_shape(g, v)["kind"], "circle")

    def test_sphere_shell_is_ring(self):
        g = {"type": "sphere_shell", "outer_r_mm": 10.0, "inner_r_mm": 8.0}
        for v in geometry.VIEWS:
            self.assertEqual(geometry.project_shape(g, v)["kind"], "ring")

    def test_capsule_orientation_detected(self):
        gz = {"type": "capsule", "radius_mm": 5.0, "length_mm": 30.0, "axis": "z"}
        gx = {"type": "capsule", "radius_mm": 5.0, "length_mm": 30.0, "axis": "x"}
        # 正视（横 Y 纵 Z）：z 轴胶囊是竖直的
        self.assertFalse(geometry.project_shape(gz, "front")["along_horizontal"])
        # 侧视（横 X 纵 Z）：x 轴胶囊是水平的
        self.assertTrue(geometry.project_shape(gx, "side")["along_horizontal"])

    def test_unknown_view_raises(self):
        with self.assertRaises(geometry.GeometryError):
            geometry.project_shape({"type": "sphere", "radius_mm": 1.0}, "bottom")


class TestKinematics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = gen_urdf.load_model()

    def test_every_link_has_a_transform(self):
        tfs = geometry.link_positions(self.model)
        for link in self.model["links"]:
            self.assertIn(link["name"], tfs)

    def test_root_is_at_base_pose(self):
        tfs = geometry.link_positions(self.model)
        pelvis = tfs["pelvis"]
        self.assertAlmostEqual(pelvis[2][3], self.model["base_pose_mm"][2], places=6)

    def test_feet_on_ground_at_zero_pose(self):
        env = gen_urdf.measured_envelope(self.model)
        self.assertAlmostEqual(env["min_z_mm"], 0.0, delta=0.5)

    def test_head_is_topmost(self):
        env = gen_urdf.measured_envelope(self.model)
        # v2 起身高是可标定参数（现对齐参考机 373 mm），不再硬编码 475 mm：
        # 改为断言"包络顶端 == 模型声明的身高"与"不超赛题上限"。
        self.assertAlmostEqual(env["max_z_mm"],
                               self.model["overall"]["height_mm"], delta=1.0)
        self.assertLessEqual(env["max_z_mm"], 600.0)

    def test_link_masses_include_servos_and_electronics(self):
        """v2 回归：link 质量必须含舵机与电子件，否则 URDF 的动力学是错的。"""
        m = self.model
        budget = m["mass_budget"]
        total = sum(l["mass_kg"] for l in m["links"]) * 1000.0
        self.assertAlmostEqual(total, budget["total_g"], delta=1.0)
        self.assertGreaterEqual(budget["servos_g"], 1000.0)
        for l in m["links"]:
            bd = l.get("mass_breakdown_g", {})
            self.assertIn("servos", bd)
            self.assertIn("structure", bd)

    def test_pose_changes_link_position(self):
        """给定非零关节角，末端位置必须变化（证明确实在算运动学）。"""
        zero = geometry.link_positions(self.model)
        bent = geometry.link_positions(self.model, {"left_knee_pitch": 60.0})
        p0 = geometry.transform_point(zero["left_foot"], (0, 0, 0))
        p1 = geometry.transform_point(bent["left_foot"], (0, 0, 0))
        self.assertNotAlmostEqual(p0[2], p1[2], places=3)

    def test_knee_rotation_lifts_foot(self):
        """膝关节屈曲应让足部抬升（绕 Y 轴向后摆）。"""
        zero = geometry.link_positions(self.model)
        bent = geometry.link_positions(self.model, {"left_knee_pitch": 45.0})
        z0 = geometry.transform_point(zero["left_foot"], (0, 0, 0))[2]
        z1 = geometry.transform_point(bent["left_foot"], (0, 0, 0))[2]
        self.assertGreater(z1, z0)


class TestAabb(unittest.TestCase):
    def test_overlap_detected(self):
        a = ((0.0, 0.0, 0.0), (10.0, 10.0, 10.0))
        b = ((5.0, 5.0, 5.0), (15.0, 15.0, 15.0))
        hit, depth = geometry.aabb_overlap(a, b)
        self.assertTrue(hit)
        self.assertAlmostEqual(depth, 5.0)

    def test_separated_boxes(self):
        a = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        b = ((2.0, 2.0, 2.0), (3.0, 3.0, 3.0))
        hit, depth = geometry.aabb_overlap(a, b)
        self.assertFalse(hit)
        self.assertEqual(depth, 0.0)

    def test_touching_face_is_not_overlap(self):
        a = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        b = ((1.0, 0.0, 0.0), (2.0, 1.0, 1.0))
        hit, _ = geometry.aabb_overlap(a, b)
        self.assertFalse(hit)


class TestUrdfGeometryExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = gen_urdf.load_model()
        cls.xml = gen_urdf.build_urdf(cls.model)
        cls.root = ET.fromstring(cls.xml)

    def test_visual_uses_real_primitives(self):
        """visual 不应全部退化为 box。"""
        kinds = set()
        for link in self.root.findall("link"):
            for tag in ("box", "cylinder", "sphere"):
                if link.find(f"visual/geometry/{tag}") is not None:
                    kinds.add(tag)
        self.assertIn("cylinder", kinds)
        self.assertIn("sphere", kinds)

    def test_collision_always_simplified_box(self):
        for link in self.root.findall("link"):
            self.assertIsNotNone(
                link.find("collision/geometry/box"),
                f"{link.get('name')} 的 collision 应为等效 box",
            )

    def test_capsule_exported_as_cylinder(self):
        link = next(l for l in self.root.findall("link")
                    if l.get("name") == "left_thigh")
        cyl = link.find("visual/geometry/cylinder")
        self.assertIsNotNone(cyl)
        model_link = next(l for l in self.model["links"]
                          if l["name"] == "left_thigh")
        g = model_link["geometry"]
        # capsule → cylinder：URDF 长度 = length + 2r（两端球头），半径 = r
        # 期望值取自模型（v2 起尺寸可重标定），不再硬编码 90 mm / 22.5 mm
        self.assertAlmostEqual(float(cyl.get("length")),
                               (g["length_mm"] + 2.0 * g["radius_mm"]) / 1000.0,
                               places=6)
        self.assertAlmostEqual(float(cyl.get("radius")),
                               g["radius_mm"] / 1000.0, places=6)

    def test_visual_origin_is_exported(self):
        """带 origin_mm 的 link，其 visual/collision/inertial 都要写出偏移。"""
        link = next(l for l in self.root.findall("link")
                    if l.get("name") == "left_thigh")
        model_link = next(l for l in self.model["links"]
                          if l["name"] == "left_thigh")
        ox, oy, oz = model_link["geometry"]["origin_mm"]
        for tag in ("visual", "collision", "inertial"):
            xyz = link.find(f"{tag}/origin").get("xyz").split()
            self.assertAlmostEqual(float(xyz[0]), ox / 1000.0, places=6)
            self.assertAlmostEqual(float(xyz[1]), oy / 1000.0, places=6)
            self.assertAlmostEqual(float(xyz[2]), oz / 1000.0, places=6)

    def test_segments_connect_without_gaps(self):
        """竖直链条上相邻 link 的包围盒必须重叠，不得出现悬空段。"""
        chain = ["head", "head_yaw_link", "torso_upper", "trunk_roll_link",
                 "pelvis", "left_hip_yaw_link", "left_hip_roll_link",
                 "left_thigh", "left_shank", "left_foot"]
        tfs = geometry.link_positions(self.model)
        ranges = []
        for name in chain:
            mins, maxs = geometry.link_world_aabb(self.model, name, tfs[name])
            ranges.append((name, mins[2], maxs[2]))
        for (n0, lo0, hi0), (n1, lo1, hi1) in zip(ranges, ranges[1:]):
            gap = max(lo0, lo1) - min(hi0, hi1)
            self.assertLessEqual(
                gap, 0.5,
                f"{n0} 与 {n1} 之间存在 {gap:.1f} mm 悬空间隙",
            )

    def test_sphere_shell_exported_as_sphere(self):
        link = next(l for l in self.root.findall("link")
                    if l.get("name") == "left_hip_yaw_link")
        sph = link.find("visual/geometry/sphere")
        self.assertIsNotNone(sph)
        model_link = next(l for l in self.model["links"]
                          if l["name"] == "left_hip_yaw_link")
        # 期望值取自模型（v2 起尺寸可重标定），不再硬编码 0.020
        self.assertAlmostEqual(float(sph.get("radius")),
                               model_link["geometry"]["outer_r_mm"] / 1000.0,
                               places=6)

    def test_urdf_still_well_formed_and_complete(self):
        self.assertEqual(len(self.root.findall("link")), 23)
        self.assertEqual(len(self.root.findall("joint")), 22)
        for link in self.root.findall("link"):
            self.assertIsNotNone(link.find("inertial"))


class TestDrawings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = gen_urdf.load_model()

    def _sheets(self):
        for key, (fname, fn) in gen_drawings.DRAWINGS.items():
            yield key, fn(self.model)

    def test_all_drawings_render_valid_svg(self):
        for key, sheet in self._sheets():
            with self.subTest(drawing=key):
                root = ET.fromstring(sheet.render())
                self.assertEqual(root.tag.split("}")[-1], "svg")

    def test_no_element_outside_canvas(self):
        """所有坐标必须落在画布内，否则打印/导出会被裁切。"""
        for key, sheet in self._sheets():
            with self.subTest(drawing=key):
                for part in sheet.parts:
                    for attr in ("x1", "x2", "cx", "x"):
                        for mo in re.finditer(attr + r'="(-?[\d.]+)"', part):
                            v = float(mo.group(1))
                            self.assertGreaterEqual(v, -0.01, f"{key}: {part[:70]}")
                            self.assertLessEqual(v, sheet.w, f"{key}: {part[:70]}")
                    for attr in ("y1", "y2", "cy", "y"):
                        for mo in re.finditer(attr + r'="(-?[\d.]+)"', part):
                            v = float(mo.group(1))
                            self.assertGreaterEqual(v, -0.01, f"{key}: {part[:70]}")
                            self.assertLessEqual(v, sheet.h, f"{key}: {part[:70]}")

    def test_joint_map_contains_22_bubble_labels(self):
        sheet = gen_drawings.draw_joint_map(self.model)
        joined = "\n".join(sheet.parts)
        # 每个关节编号至少出现一次（正视图气泡）
        for j in self.model["joints"]:
            self.assertIn(f">{j['id']:02d}</text>", joined,
                          f"关节 {j['id']:02d} 未在图中标注")

    def test_joint_table_lists_all_joints(self):
        sheet = gen_drawings.draw_joint_map(self.model)
        joined = "\n".join(sheet.parts)
        for j in self.model["joints"]:
            self.assertIn(j["name"], joined)

    def test_table_does_not_reach_title_block(self):
        """明细表右边界必须留在标题栏左侧。"""
        sheet = gen_drawings.draw_joint_map(self.model)
        title_x = sheet.w - 20 - 560
        # 从渲染元素里找表格外框：宽度等于 1050 的 rect
        for part in sheet.parts:
            mo = re.search(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)"', part)
            if mo and abs(float(mo.group(3)) - 1050.0) < 0.5:
                right = float(mo.group(1)) + float(mo.group(3))
                self.assertLessEqual(right, title_x,
                                     "关节明细表与标题栏重叠")

    def test_servo_tier_counts_are_consistent(self):
        """图例分档数量之和必须等于关节总数。"""
        model = self.model
        high = [j for j in model["joints"] if j.get("effort_nm", 1) >= 3.0]
        mid = [j for j in model["joints"]
               if 2.0 <= j.get("effort_nm", 1) < 3.0]
        low = [j for j in model["joints"] if j.get("effort_nm", 1) < 2.0]
        self.assertEqual(len(high) + len(mid) + len(low), 22)

    def test_drawing_contains_compliance_numbers(self):
        sheet = gen_drawings.draw_joint_map(self.model)
        joined = "\n".join(sheet.parts)
        env = gen_urdf.measured_envelope(self.model)
        self.assertIn(f"{env['height_mm']:.1f}", joined)
        self.assertIn("600", joined)

    def test_text_wrapping_stays_within_width(self):
        s = gen_drawings.Sheet()
        long_names = "、".join(f"left_joint_number_{i}" for i in range(12))
        before = len(s.parts)
        s.text_wrapped(0, 0, long_names, max_width=200, size=10)
        lines = s.parts[before:]
        self.assertGreater(len(lines), 1, "超长文本应折行")
        for line in lines:
            content = re.search(r">([^<]*)</text>", line).group(1)
            self.assertLess(len(content), len(long_names))


if __name__ == "__main__":
    unittest.main()


class TestMeshes(unittest.TestCase):
    """三角网格质量：水密性直接决定渲染有无破面。"""

    def _edge_sharing(self, tris):
        from collections import Counter
        e = Counter()
        for a, b, c in tris:
            for p, q in ((a, b), (b, c), (c, a)):
                key = tuple(sorted((
                    tuple(round(x, 5) for x in p),
                    tuple(round(x, 5) for x in q),
                )))
                e[key] += 1
        return e

    def _assert_watertight(self, geom, **kw):
        tris = geometry.mesh(geom, **kw)
        self.assertGreater(len(tris), 0)
        sharing = self._edge_sharing(tris)
        bad = [k for k, v in sharing.items() if v != 2]
        self.assertEqual(
            bad, [],
            f"{geom['type']} 网格非水密：{len(bad)} 条边未恰好被两个三角形共享",
        )

    def test_box_watertight(self):
        self._assert_watertight({"type": "box", "size_mm": [10, 20, 30]})

    def test_sphere_watertight(self):
        self._assert_watertight({"type": "sphere", "radius_mm": 7},
                                segments=12, rings=6)

    def test_cylinder_watertight_all_axes(self):
        for axis in "xyz":
            with self.subTest(axis=axis):
                self._assert_watertight(
                    {"type": "cylinder", "radius_mm": 6, "height_mm": 20,
                     "axis": axis}, segments=12)

    def test_capsule_watertight_all_axes(self):
        for axis in "xyz":
            with self.subTest(axis=axis):
                self._assert_watertight(
                    {"type": "capsule", "radius_mm": 8, "length_mm": 20,
                     "axis": axis}, segments=12, rings=4)

    def test_capsule_without_cylinder_section(self):
        """length=0 的胶囊应退化为球，仍然水密。"""
        self._assert_watertight(
            {"type": "capsule", "radius_mm": 8, "length_mm": 0.0, "axis": "z"},
            segments=12, rings=4)

    def test_mesh_respects_origin_offset(self):
        g = {"type": "sphere", "radius_mm": 5, "origin_mm": [0, 0, -40]}
        zs = [v[2] for t in geometry.mesh(g, 12, 6) for v in t]
        self.assertAlmostEqual(min(zs), -45.0, places=6)
        self.assertAlmostEqual(max(zs), -35.0, places=6)

    def test_mesh_matches_bounding_box(self):
        for geom in (
            {"type": "box", "size_mm": [10, 20, 30]},
            {"type": "cylinder", "radius_mm": 5, "height_mm": 20, "axis": "y"},
            {"type": "capsule", "radius_mm": 4, "length_mm": 12, "axis": "x"},
        ):
            with self.subTest(geom=geom["type"]):
                tris = geometry.mesh(geom, segments=24, rings=10)
                pts = [v for t in tris for v in t]
                span = [max(p[i] for p in pts) - min(p[i] for p in pts)
                        for i in range(3)]
                want = geometry.bounding_box(geom)
                for got, exp in zip(span, want):
                    self.assertAlmostEqual(got, exp, delta=0.01)


class TestRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = gen_urdf.load_model()

    def test_camera_projection_is_orthographic(self):
        cam = gen_drawings_import_camera()
        cam.scale = 2.0
        cam.cx = cam.cy = 0.0
        a = cam.project((0.0, 0.0, 0.0))
        b = cam.project((0.0, 0.0, 10.0))
        # 纯 Z 位移在俯仰角 0 时应只改变屏幕 y
        self.assertAlmostEqual(a[0], b[0], places=6)
        self.assertNotAlmostEqual(a[1], b[1], places=6)

    def test_camera_fit_keeps_model_inside_canvas(self):
        cam = gen_drawings_import_camera()
        scene = gen_drawings_import_scene()(cam)
        scene.build(self.model, {}, segments=10, rings=5)
        xs, ys = [], []
        for p in scene.world_pts:
            r = cam.rotate(p)
            x, y = cam.project(r)
            xs.append(x)
            ys.append(y)
        self.assertGreaterEqual(min(xs), -0.5)
        self.assertLessEqual(max(xs), cam.w + 0.5)
        self.assertGreaterEqual(min(ys), -0.5)
        self.assertLessEqual(max(ys), cam.h + 0.5)

    def test_all_render_views_produce_valid_svg(self):
        import gen_render
        for key in gen_render.VIEWS:
            with self.subTest(view=key):
                cam = gen_render.Camera(38.0, 18.0)
                scene = gen_render.Scene(cam)
                scene.build(self.model, gen_render.STANCE_POSE,
                            by_group=gen_render.VIEWS[key].get("by_group", False),
                            segments=10, rings=5)
                svg = scene.render(title="t", subtitle="s", note="n")
                root = ET.fromstring(svg)
                self.assertEqual(root.tag.split("}")[-1], "svg")
                self.assertIn("<polygon", svg)

    def test_render_produces_triangles(self):
        import gen_render
        cam = gen_render.Camera(38.0, 18.0)
        scene = gen_render.Scene(cam)
        scene.build(self.model, gen_render.STANCE_POSE,
                    segments=10, rings=5)
        self.assertGreater(len(scene.tris), 200, "三角形太少，渲染可能未生效")

    def test_backface_culling_removes_interior(self):
        """背面剔除后可见三角形应少于全部面片。"""
        import gen_render
        cam = gen_render.Camera(38.0, 18.0)
        scene = gen_render.Scene(cam)
        scene.build(self.model, {}, segments=10, rings=5)
        total = sum(len(geometry.mesh(l["geometry"], 10, 5))
                    for l in self.model["links"])
        self.assertLess(len(scene.tris), total)

    def test_drawing_and_render_camera_conventions_agree(self):
        """正视渲染的屏幕横轴应为 +Y，与工程图 front 视图一致。"""
        import gen_render
        cam = gen_render.Camera(gen_render.VIEWS["front"]["az"], 0.0)
        cam.scale = 1.0
        cam.cx = cam.cy = 0.0
        x_plus_y = cam.project(cam.rotate((0.0, 10.0, 0.0)))[0]
        x_zero = cam.project(cam.rotate((0.0, 0.0, 0.0)))[0]
        self.assertGreater(x_plus_y, x_zero, "正视图中 +Y 应位于屏幕右侧")


def gen_drawings_import_camera():
    import gen_render
    return gen_render.Camera(38.0, 18.0)


def gen_drawings_import_scene():
    import gen_render
    return gen_render.Scene
