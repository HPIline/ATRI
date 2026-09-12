"""Manufacturing artifacts must preserve geometry and explicit process holds."""
import tempfile
import unittest
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

try:
    import cadquery as cq
except ImportError:
    cq = None


@unittest.skipUnless(cq, "requires repository .venv-cad")
class ManufacturingTests(unittest.TestCase):
    def test_print_face_and_3mf_use_millimeters_and_all_solids(self):
        from v2.manufacturing import export_manufacturing
        shape = cq.Workplane("XY").box(7, 11, 19).translate((3, 5, 23))
        shape = shape.add(cq.Workplane("XY").box(2, 3, 4).translate((20, 5, 23)))
        with tempfile.TemporaryDirectory() as tmp:
            report = export_manufacturing([dict(name="asymmetric", link="head", kind="petg",
                                                wp=shape, print_face="+X")], tmp)
            row = report["parts"][0]
            self.assertEqual(row["solid_count"], 2)
            self.assertAlmostEqual(row["volume_mm3"], 7 * 11 * 19 + 24)
            with zipfile.ZipFile(Path(tmp) / row["files"]["3mf"]) as archive:
                root = ET.fromstring(archive.read("3D/3dmodel.model"))
                self.assertEqual(root.attrib["unit"], "millimeter")
                ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
                vertices = root.findall(".//m:vertex", ns)
                points = [[float(v.attrib[a]) for a in "xyz"] for v in vertices]
                self.assertAlmostEqual(min(v[2] for v in points), 0)
                self.assertAlmostEqual(max(v[2] for v in points), 21.5)
                self.assertAlmostEqual(max(v[0] for v in points)-min(v[0] for v in points), 19)
                self.assertEqual(len(root.findall(".//m:object", ns)), 2)
                for mesh in root.findall(".//m:mesh", ns):
                    edges = Counter()
                    for triangle in mesh.findall("m:triangles/m:triangle", ns):
                        indices = [int(triangle.attrib[f"v{i}"]) for i in (1, 2, 3)]
                        for a, b in zip(indices, indices[1:]+indices[:1]):
                            edges[tuple(sorted((a, b)))] += 1
                    self.assertTrue(all(count == 2 for count in edges.values()),
                                    "3MF objects must have closed shared-index mesh topology")

    def test_missing_print_orientation_holds_part_without_losing_inventory(self):
        from v2.manufacturing import export_manufacturing
        with tempfile.TemporaryDirectory() as tmp:
            result = export_manufacturing([dict(name="sole", link="foot", kind="tpu",
                                                wp=cq.Workplane("XY").box(2, 3, 1))], tmp)
            row = result["parts"][0]
            self.assertIn("print_face_missing", row["unresolved"])
            self.assertNotIn("3mf", row["files"])
            self.assertIn("review_stl", row["files"])
            self.assertFalse(result["release_ready"])

    def test_laser_blank_and_countersink_remain_separate_processes(self):
        from v2.manufacturing import export_manufacturing
        flat = cq.Workplane("XY").box(20, 12, 2, centered=(True, True, False)).faces(">Z").workplane().hole(3.2)
        finished = flat.cut(cq.Solid.makeCone(1.6, 3, 1, cq.Vector(0, 0, 1)))
        with tempfile.TemporaryDirectory() as tmp:
            result = export_manufacturing([dict(name="plate", link="base", kind="al", wp=finished,
                flat=flat, manufacturing="laser 2 mm; countersink after cutting")], tmp)
            row = result["parts"][0]
            self.assertGreater(row["laser_blank_volume_mm3"], row["volume_mm3"])
            self.assertIn("secondary_operations_require_drawing", row["unresolved"])
            self.assertTrue((Path(tmp) / row["files"]["laser_dxf"]).is_file())

    def test_duplicate_names_and_non_solids_are_rejected_before_export(self):
        from v2.manufacturing import export_manufacturing
        item = dict(name="same", link="base", kind="al", wp=cq.Workplane("XY").box(1, 2, 3))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                export_manufacturing([item, item], tmp)
            item["wp"] = cq.Workplane("XY").circle(4)
            with self.assertRaisesRegex(ValueError, "solid"):
                export_manufacturing([item], tmp)

    def test_nonuniform_flat_is_held_as_reference_not_laser_blank(self):
        from v2.manufacturing import export_manufacturing
        shape = cq.Workplane("XY").box(20, 12, 2, centered=(True, True, False)).faces(">Z").workplane().cskHole(3.2, 6, 90)
        with tempfile.TemporaryDirectory() as tmp:
            row = export_manufacturing([dict(name="bad-flat", link="base", kind="al",
                                            wp=shape, flat=shape)], tmp)["parts"][0]
            self.assertNotIn("laser_dxf", row["files"])
            self.assertIn("flat_is_not_constant_thickness_profile", row["unresolved"])
