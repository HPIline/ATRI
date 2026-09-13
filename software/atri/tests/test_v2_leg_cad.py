"""Actual B-rep motion and mounting tests; run with repository .venv-cad.

Sampled collision tests are not continuous collision detection or proof of
clamp capacity. Friction, housing deformation and creep require a specimen.
"""
import unittest

try:
    import cadquery as cq
except ImportError:
    cq = None


@unittest.skipUnless(cq, "requires repository .venv-cad")
class TestLegCad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from v2.leg_cad import build_leg_items, parameters
        from v2.cad_parts import sts3215_components
        cls.items = build_leg_items()
        cls.parameters = parameters()
        cls.servo = sts3215_components()["body"].val()

    def test_all_parts_are_valid_and_manufactured_plates_are_single_solids(self):
        for part in self.items:
            with self.subTest(part=part["name"]):
                self.assertTrue(part["wp"].val().isValid())
                self.assertGreater(part["wp"].val().Volume(), 0)
                if "flat" in part:
                    self.assertEqual(len(part["wp"].val().Solids()), 1)

    def test_clamps_belong_to_parent_link_and_outputs_to_child(self):
        for side in ("left", "right"):
            for segment in ("thigh", "shank"):
                jaws = [p for p in self.items if p["name"].startswith(f"case-{side}-{segment}-lower-jaw-")]
                self.assertEqual(len(jaws), 2)
                self.assertTrue(all(p["link"] == f"{side}_{segment}" for p in jaws))
                self.assertTrue(all("qualification" in p for p in jaws))

    def test_fixed_clamp_spacers_do_not_overlap_jaws(self):
        for jaw in self.items:
            if '-lower-jaw-' not in jaw['name']:continue
            for spacer in self.items:
                if spacer['link']!=jaw['link'] or '-clamp-spacer-' not in spacer['name']:continue
                with self.subTest(jaw=jaw['name'],spacer=spacer['name']):
                    self.assertLess(jaw['wp'].val().intersect(spacer['wp'].val()).Volume(),1e-6)

    def test_foot_sole_contact_and_height(self):
        for side in ("left", "right"):
            index = {p["name"]: p["wp"].val() for p in self.items}
            sole = index[f"leg-{side}-foot-sole"]
            plate = index[f"leg-{side}-foot-plate"]
            self.assertAlmostEqual(sole.BoundingBox().zmin, -self.parameters["foot_height_mm"], places=6)
            self.assertAlmostEqual(sole.BoundingBox().zmax, plate.BoundingBox().zmin, places=6)
            self.assertLess(sole.intersect(plate).Volume(), 1e-6)
            self.assertLessEqual(plate.BoundingBox().ylen, 70.0)

    def test_bolt_lengths_reach_clamp_nuts_without_using_case_threads(self):
        p = self.parameters
        for level in (0, 1):
            start = p["front_inner_mm"][level] + p["plate_t_mm"] + p["clamp_head_washer_mm"][level]
            tip = start - p["clamp_bolt_mm"][level]
            nut_far = p["rear_inner_mm"][level] - p["plate_t_mm"] - 2.4
            self.assertLessEqual(tip, nut_far + 0.01)
            self.assertLess(nut_far-tip, 3.0)

    def test_sampled_knee_and_ankle_rom_against_full_fixed_assembly(self):
        # All supplied fasteners are included. No collision whitelist or
        # case/output-disc overlap exemption is applied to moving pairs.
        for segment, previous, angles in (("shank", "thigh", range(0, 91, 5)),
                                         ("foot", "shank", range(-40, 41, 5))):
            fixed = [("servo", self.servo)] + [
                (p["name"], p["wp"].val().translate((0, 0, 78)))
                for p in self.items if p["link"] == "left_" + previous]
            moving = [(p["name"], p["wp"].val()) for p in self.items
                      if p["link"] == "left_" + segment]
            if segment == "shank":
                moving.append(("ankle-servo", self.servo.translate((0, 0, -78))))
            for angle in angles:
                for name, shape in moving:
                    rotated = shape.rotate((0, 0, 0), (0, 1, 0), angle)
                    a = rotated.BoundingBox()
                    for other, static in fixed:
                        b = static.BoundingBox()
                        if any(min(getattr(a, axis+"max"), getattr(b, axis+"max")) -
                               max(getattr(a, axis+"min"), getattr(b, axis+"min")) < 1e-6
                               for axis in "xyz"):
                            continue
                        with self.subTest(segment=segment, angle=angle, moving=name, fixed=other):
                            self.assertLess(rotated.intersect(static).Volume(), 0.01)

    def test_hip_pitch_sampled_clearance_includes_rear_case_protrusion(self):
        for part in self.items:
            if part['name'] != 'leg-left-thigh-rear': continue
            for angle in range(-60,61,5):
                with self.subTest(angle=angle):
                    moving=part['wp'].val().rotate((0,0,0),(0,1,0),angle)
                    self.assertLess(moving.intersect(self.servo).Volume(),.01)

    def test_foot_countersink_is_90_degrees_and_seats_without_overlap(self):
        # Inspect real B-reps: at 1.3 mm depth a diameter-6 90-degree
        # countersink has radius 1.7 mm, so r=1.8 is retained plate.
        p = self.parameters
        index = {part["name"]: part["wp"].val() for part in self.items}
        from v2.profile import K
        bottom = -p["foot_height_mm"] + K["sole_t"]
        for side in ("left", "right"):
            plate = index[f"leg-{side}-foot-plate"]
            for front, label in ((True, "front"), (False, "rear")):
                inner = p["front_inner_mm"][2] if front else p["rear_inner_mm"][2]
                y = inner - (1 if front else -1) * p["foot_angle_horizontal_hole_mm"]
                for n, x in enumerate(p["foot_angle_hole_x_mm"]):
                    self.assertTrue(plate.isInside(cq.Vector(x + 1.8, y, bottom + 1.3)))
                    bolt = index[f"leg-{side}-foot-{label}-base-bolt-{n}"]
                    self.assertLess(plate.intersect(bolt).Volume(), 1e-7)
                    nut = index[f"leg-{side}-foot-{label}-base-nut-{n}"]
                    self.assertGreaterEqual(bolt.BoundingBox().zmax, nut.BoundingBox().zmax)
