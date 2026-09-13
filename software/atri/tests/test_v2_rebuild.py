"""ATRI-v2 A 路线：图纸 / BOM / 工程验证 / 能力验证。

运行：
    cd software/atri && python3 -m unittest tests.test_v2_rebuild -v
"""
from __future__ import annotations

import csv
import math
import json
import os
import subprocess
from functools import lru_cache
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "design"))

from v2 import bom as v2bom  # noqa: E402
from v2 import capability as v2cap  # noqa: E402
from v2 import generate as v2gen  # noqa: E402
from v2 import profile as P  # noqa: E402
from v2.assembly3d import fk, kinematic_tree, m_apply, preview_payload  # noqa: E402
from v2 import preview3d as v2prev  # noqa: E402


@lru_cache(maxsize=1)
def actual_snapshot():
    runtime=REPO/".venv-cad/bin/python"
    if not runtime.is_file():raise unittest.SkipTest("requires repository .venv-cad")
    with tempfile.TemporaryDirectory() as folder:
        dest=Path(folder)/"snapshot.json"
        code="from v2.cad_export import build_items; from v2.review_export import assembly_snapshot; import json,sys; open(sys.argv[1], 'w').write(json.dumps(assembly_snapshot(build_items())))"
        env=os.environ.copy();env["PYTHONPATH"]=str(REPO/"design")
        subprocess.run([str(runtime),"-c",code,str(dest)],cwd=REPO,env=env,check=True)
        return json.loads(dest.read_text())


class TestTopology(unittest.TestCase):
    def test_twenty_dof_and_contest_mins(self):
        c = P.dof_counts()
        self.assertEqual(c["total"], 20)
        self.assertGreaterEqual(c["total"], P.CONTEST["dof_min"])
        self.assertGreaterEqual(c["leg_l"], P.CONTEST["leg_dof_min"])
        self.assertGreaterEqual(c["leg_r"], P.CONTEST["leg_dof_min"])
        self.assertEqual(c["upper_torso"], 10)
        self.assertGreaterEqual(c["upper_torso"], P.CONTEST["upper_torso_min"])
        self.assertNotIn("left_hip_yaw", [j["name"] for j in P.JOINTS])
        self.assertEqual(P.DROPPED_VS_V1, ("left_hip_yaw", "right_hip_yaw"))

    def test_upper_torso_does_not_count_head(self):
        c = P.dof_counts()
        self.assertEqual(c["upper_torso"] + c["head"], c["total"] - c["leg_l"] - c["leg_r"])
        self.assertEqual(c["head"], 2)

    def test_group_dof_matches_joints(self):
        self.assertEqual(sum(P.GROUP_DOF.values()), 20)
        self.assertEqual(P.GROUP_DOF, {
            "head": 2, "trunk": 2, "leg_l": 4, "leg_r": 4, "arm_l": 4, "arm_r": 4,
        })


class TestEnvelope(unittest.TestCase):
    def test_inside_official_box(self):
        e = P.envelope_mm()
        self.assertLessEqual(e["height_mm"], P.CONTEST["height_max_mm"])
        self.assertLessEqual(e["width_mm"], P.CONTEST["width_max_mm"])
        self.assertLessEqual(e["depth_mm"], P.CONTEST["depth_max_mm"])
        self.assertGreater(e["height_mm"], 300.0)
        self.assertEqual(P.MASS["design_limit_g"], 2300.0)
        self.assertEqual(P.MASS["hard_limit_g"], 2450.0)

    def test_foot_size(self):
        self.assertEqual(P.K["foot_l"], 120.0)
        self.assertEqual(P.K["foot_w"], 70.0)


class TestTorque(unittest.TestCase):
    def test_v1_formula_reproduces_authoritative_ankle(self):
        tau = P.ankle_torque_nm(P.V1["mass_g"], P.ANKLE["k_hold"])
        self.assertAlmostEqual(tau, P.V1["ankle_nm"], delta=0.02)

    def test_walk_at_design_mass_under_util_cap(self):
        tau = P.ankle_torque_nm(P.MASS["design_limit_g"], P.ANKLE["k_walk"])
        util = tau / P.SERVO["rated_nm"]
        self.assertLessEqual(util, P.ANKLE["util_walk_max"])

    def test_hold_at_design_mass_still_over_rated_is_documented(self):
        tau = P.ankle_torque_nm(P.MASS["design_limit_g"], P.ANKLE["k_hold"])
        self.assertGreater(tau, P.SERVO["rated_nm"])

    def test_does_not_revive_wrong_trunk_roll(self):
        self.assertLess(P.V1["trunk_roll_nm"], 0.5)
        scaled = P.scale_from_v1(P.V1["trunk_roll_nm"], P.V1["mass_g"], P.MASS["design_limit_g"])
        self.assertLess(scaled / P.SERVO["rated_nm"], 0.50)


class TestPlates(unittest.TestCase):
    def test_pcd_is_fourteen_and_no_mounting_ears(self):
        self.assertAlmostEqual(P.SERVO["horn_hole_square_mm"]*math.sqrt(2),14.,places=2)
        self.assertEqual(P.SERVO["horn_hole_thread"],"M3")
        self.assertAlmostEqual(P.CASE_MOUNT["hole_mm"],3.2)

    def test_actual_aluminum_volume_within_budget(self):
        rows=actual_snapshot()["parts"]
        mass=sum(p["volume_mm3"]*.0027 for p in rows if p["kind"]=="al")
        self.assertGreater(mass,100.)
        self.assertLessEqual(mass,P.MASS["structure_al_budget_g"])


class TestBom(unittest.TestCase):
    def test_retail_cart_exceeds_budget(self):
        r = v2bom.cart("retail")
        self.assertGreater(r["total_cny"], 3200)

    def test_cart_totals_are_honest_and_g0_stays_open(self):
        r=v2bom.cart("close")
        self.assertAlmostEqual(r["total_cny"],sum(i["subtotal_cny"] for i in r["items"] if i["in_budget"]))
        self.assertAlmostEqual(r["contingency_cny"],3200-r["total_cny"])
        self.assertIn("3000",v2gen.GATES["G0"])
        self.assertIn("截图",v2gen.GATES["G0"])

    def test_twenty_bus_servos_12v(self):
        r = v2bom.cart("close")
        servo = next(i for i in r["items"] if i["sku"].startswith("STS3215"))
        self.assertEqual(servo["qty"], 20)
        self.assertIn("12V", servo["spec"])
        self.assertNotIn("7.4V", servo["spec"])

    def test_charger_excluded_from_3200(self):
        r = v2bom.cart("close")
        names = [i["name"] for i in r["items"]]
        self.assertTrue(any("平衡充" in n for n in names))
        charged = [i for i in r["items"] if "平衡充" in i["name"]][0]
        self.assertFalse(charged["in_budget"])


class TestCapability(unittest.TestCase):
    def test_no_fake_thirty_minute_runtime(self):
        rows = v2cap.matrix()
        runtime = next(r for r in rows if r["id"] == "runtime")
        self.assertNotEqual(runtime["verdict"], "PASS")
        self.assertIn("待测", runtime["evidence"])

    def test_t01_to_t05_present(self):
        ids = {r["id"] for r in v2cap.matrix()}
        for t in ("T-01", "T-02", "T-03", "T-04", "T-05"):
            self.assertIn(t, ids)

    def test_t02_conditional_on_turn_gate(self):
        t02 = next(r for r in v2cap.matrix() if r["id"] == "T-02")
        self.assertEqual(t02["verdict"], "CONDITIONAL")
        self.assertIn("G4", t02["gates"])


class TestGenerate(unittest.TestCase):
    def test_manifest_drives_generated_inventory(self):
        rows=[]
        for p in actual_snapshot()["parts"]:
            rows.append(dict(name=p["name"],link=p["link"],kind=p["kind"],material=p.get("material",p["kind"]),
                volume_mm3=p["volume_mm3"],process=p.get("manufacturing",p.get("spec","pending")),
                files={},unresolved=["review only"],metadata=p))
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)
            files=v2gen.generate_documents(out,dict(parts=rows),actual_snapshot())
            self.assertIn("ATRI-v2-BOM.csv",files)
            self.assertFalse((out/"dxf").exists())
            self.assertFalse((out/"drawings").exists())
            printed=(out/"PETG-打印清单.md").read_text()
            for p in rows:
                if p["kind"] in ("petg","tpu"):self.assertIn(p["name"],printed)
            self.assertNotIn("cable-csi",printed)
            report=(out/"ATRI-v2-工程验证.md").read_text()
            self.assertIn("仍超额定",report)
            gates=json.loads((out/"gates.json").read_text())
            self.assertTrue(all(g["status"]=="OPEN" for g in gates.values()))


class TestPreview3D(unittest.TestCase):
    def test_zero_pose_left_foot_on_ground(self):
        W=fk(kinematic_tree())
        x,y,z=m_apply(W["left_foot"],(0,0,0))
        self.assertAlmostEqual(z,P.K["foot_to_ankle_z"],delta=.01)
        self.assertAlmostEqual(y,P.K["hip_width"]/2,delta=.01)

    def test_payload_preserves_explicit_parts_and_twenty_joints(self):
        part=dict(name="test",link="pelvis",kind="al",alpha=1,verts=[0,0,0,0,0,1,1,0,0,0,0,1,0,1,0,0,0,1])
        payload=preview_payload(parts=[part])
        self.assertEqual(len(payload["joints"]),20)
        self.assertEqual(payload["parts"],[part])
        self.assertEqual(payload["nTri"],1)


class TestFinishedLook(unittest.TestCase):
    """Actual BRep inventory and bounds; local detailed CAD tests cover interfaces."""
    @classmethod
    def setUpClass(cls):
        cls.snapshot=actual_snapshot()
        cls.parts={p["name"]:p for p in cls.snapshot["parts"]}

    def test_complete_servo_inventory(self):
        names={"servo-"+j["name"] for j in P.JOINTS}
        self.assertEqual({n for n in self.parts if n.startswith("servo-")},names)

    def test_soles_touch_ground_and_have_no_underfoot_bolts(self):
        for side in ("left","right"):
            sole=self.parts[f"leg-{side}-foot-sole"]
            self.assertAlmostEqual(sole["world_bbox_mm"][2],0,delta=.001)
            self.assertEqual(sole["kind"],"tpu")
        for p in self.parts.values():
            if p["kind"]=="fastener":self.assertGreater(p["world_bbox_mm"][2],0)

    def test_shells_are_split_opaque_parts_with_print_orientation(self):
        for name in ("shell-torso-front","shell-torso-rear","cover-head-f","cover-head-b"):
            p=self.parts[name]
            self.assertEqual(p["kind"],"petg")
            self.assertEqual(p["solid_count"],1)
            self.assertIn(p["print_face"],("+X","-X"))
            self.assertEqual(p["wall_mm"],2.4)
        self.assertNotIn("cover-pelvis",self.parts)

    def test_gripper_has_fixed_and_moving_fingers_on_distinct_links(self):
        for side in ("left","right"):
            fixed=self.parts[f"arm-{side}-gripper-fixed-finger"]
            moving=self.parts[f"arm-{side}-gripper-moving-finger"]
            self.assertEqual(fixed["link"],side+"_hand")
            self.assertEqual(moving["link"],side+"_grip")

    def test_neck_and_torso_have_real_frames(self):
        self.assertEqual(self.parts["neck-base"]["link"],"head_yaw_link")
        self.assertIn("neck-cheek-front",self.parts)
        self.assertIn("neck-cheek-rear",self.parts)
        self.assertTrue(any(n.startswith("torso-beam-") for n in self.parts))
        for old in ("neck-column","head-bracket","torso-floor","torso-post-l"):
            self.assertNotIn(old,self.parts)

    def test_pelvis_open_frame_replaces_large_sandwich(self):
        for old in ("pelvis-front","pelvis-back","standoff-pelvis-0"):
            self.assertNotIn(old,self.parts)
        box=self.parts["pelvis-open-frame"]["bbox_mm"]
        self.assertLess(box[3]-box[0],3.)
        for tag,link in (("left","left_hip_roll_link"),("right","right_hip_roll_link"),("trunk","trunk_roll_link")):
            self.assertEqual(self.parts[f"pelvis-output-adapter-{tag}"]["link"],link)

    def test_actual_world_envelope_uses_contest_limits(self):
        box=self.snapshot["bbox_mm"]
        for axis,key in ((0,"depth_max_mm"),(1,"width_max_mm"),(2,"height_max_mm")):
            self.assertLessEqual(box[axis+3]-box[axis],P.CONTEST[key]+.001)

    def test_every_part_is_valid_nonempty_inventory(self):
        self.assertEqual(len(self.parts),self.snapshot["part_count"])
        self.assertTrue(all(p["solid_count"]>0 and p["volume_mm3"]>0 for p in self.parts.values()))
        self.assertFalse(self.snapshot["release_ready"])

    def test_camera_is_usb_and_battery_uses_selected_real_envelope(self):
        self.assertFalse(any("csi" in n.lower() for n in self.parts))
        p=self.parts["battery"];b=p["bbox_mm"]
        for i,size in enumerate(P.ELECTRONICS["battery"]["body_mm"]):
            self.assertAlmostEqual(b[i+3]-b[i],size,delta=.001)

    def test_knee_flexion_lifts_foot_within_limits(self):
        tree=kinematic_tree();i=next(i for i,j in enumerate(tree["joints"]) if j["name"]=="left_knee_pitch")
        self.assertEqual(tuple(tree["joints"][i]["limit_deg"]),(0,90))
        angles=[0.]*20;angles[i]=90
        z0=m_apply(fk(tree)["left_foot"],(0,0,0))[2]
        z1=m_apply(fk(tree,angles)["left_foot"],(0,0,0))[2]
        self.assertGreater(z1-z0,40)


class TestUrdfV2(unittest.TestCase):
    """Webots 入口：20 个 revolute、限位与 profile 一致、单位 m/rad。"""

    def test_twenty_revolute_joints_match_profile(self):
        from v2 import urdf as v2urdf
        xml = v2urdf.build_urdf()
        root = ET.fromstring(xml)
        joints = [j for j in root.findall("joint") if j.get("type") == "revolute"]
        self.assertEqual(len(joints), 20)
        by_name = {j.get("name"): j for j in joints}
        for spec in P.JOINTS:
            self.assertIn(spec["name"], by_name)
            lim = by_name[spec["name"]].find("limit")
            lo = math.degrees(float(lim.get("lower")))
            hi = math.degrees(float(lim.get("upper")))
            self.assertAlmostEqual(lo, spec["limit_deg"][0], places=3)
            self.assertAlmostEqual(hi, spec["limit_deg"][1], places=3)

    def test_root_is_pelvis_and_mesh_paths_relative(self):
        from v2 import urdf as v2urdf
        xml = v2urdf.build_urdf()
        root = ET.fromstring(xml)
        self.assertEqual(root.get("name"), "atri_v2")
        links = {lk.get("name") for lk in root.findall("link")}
        self.assertIn("pelvis", links)
        self.assertNotIn("://", xml)
        self.assertNotIn("C:\\", xml)
        if "<mesh" in xml:
            self.assertIn("meshes/", xml)

    def test_write_urdf_file(self):
        from v2 import urdf as v2urdf
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "atri_v2.urdf"
            info = v2urdf.write_urdf(path)
            self.assertTrue(path.is_file())
            self.assertEqual(info["n_revolute"], 20)
            text = path.read_text(encoding="utf-8")
            self.assertIn("mm -> m", text)


class TestEngineeringReport(unittest.TestCase):
    def test_five_physical_gates_remain_explicit(self):
        self.assertEqual(set(v2gen.GATES),{"G0","G1","G2","G3","G4"})
        self.assertIn("22DOF",v2gen.GATES["G4"])
        self.assertGreater(P.ankle_torque_nm(P.MASS["design_limit_g"],P.ANKLE["k_hold"]),P.SERVO["rated_nm"])
