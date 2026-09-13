"""Run with PYTHONPATH=design .venv-cad/bin/python -m unittest ... ."""
import unittest
try:
 import cadquery
except ImportError:
 cadquery=None

@unittest.skipUnless(cadquery, 'CadQuery checks require repository .venv-cad')
class TestCadInterfaces(unittest.TestCase):
 def test_soles_touch_ground_without_overlapping_foot_plates(self):
  from v2.cad_export import build_items,_moved
  from v2.assembly3d import kinematic_tree,fk
  items={i['name']:i for i in build_items()};w=fk(kinematic_tree())
  mass=0
  for tag in ('left','right'):
   sole,foot=items[f'leg-{tag}-foot-sole'],items[f'leg-{tag}-foot-plate']
   s=_moved(sole['wp'],w[sole['link']]).val()
   f=_moved(foot['wp'],w[foot['link']]).val()
   self.assertAlmostEqual(s.BoundingBox().zmin,0,places=4)
   self.assertAlmostEqual(s.BoundingBox().zmax,f.BoundingBox().zmin,places=4)
   self.assertLess(s.intersect(f).Volume(),.01)
   mass+=s.Volume()*1.21/1000
  self.assertLessEqual(mass,40)

 def test_m3_hex_socket_is_open_at_external_head_face(self):
  import cadquery as cq
  from v2.pelvis_cad import screw
  shape=screw(6,'z',(0,0,0)).val()
  probe=cq.Workplane('XY').circle(.5).extrude(.1).translate((0,0,-3)).val()
  self.assertLess(shape.intersect(probe).Volume(),1e-9)

 def test_missing_vendor_model_cannot_silently_become_a_placeholder(self):
  from unittest.mock import patch
  from pathlib import Path
  from v2.cad_parts import sts3215
  with patch("v2.cad_parts.VENDOR_STEP",Path("work/nonexistent-servo-model.step")):
   with self.assertRaises(FileNotFoundError):sts3215()

 def test_shoulder_motor_housings_do_not_intersect(self):
  from v2.cad_export import build_items,_moved
  from v2.assembly3d import kinematic_tree,fk
  items={i['name']:i for i in build_items()};w=fk(kinematic_tree())
  for side in ('left','right'):
   a,b=[items[f'servo-{side}_shoulder_{axis}'] for axis in ('pitch','roll')]
   sa,sb=[_moved(i['wp'],w[i['link']]).val() for i in (a,b)]
   self.assertLess(sa.intersect(sb).Volume(),.01,side)

 def test_vendor_accessories_are_partitioned_without_lost_geometry(self):
  from v2.cad_parts import sts3215,sts3215_components
  parts=sts3215_components()
  self.assertEqual(set(parts),{'body','drive','passive'})
  self.assertAlmostEqual(sum(p.val().Volume() for p in parts.values()),sts3215().val().Volume(),places=3)
  for name,p in parts.items():
   self.assertTrue(p.val().isValid(),name)
   self.assertGreater(p.val().Volume(),0)
  for a,b in (('body','drive'),('body','passive'),('drive','passive')):
   self.assertLess(parts[a].val().intersect(parts[b].val()).Volume(),.001)

 def test_c018_accessory_dimensions_match_official_page7(self):
  from v2.cad_parts import c018_horn
  from OCP.BRepAdaptor import BRepAdaptor_Surface
  from OCP.GeomAbs import GeomAbs_Cylinder
  for passive,total,bore in ((False,4.5,1.6),(True,3.1,3.025)):
   shape=c018_horn(passive).val()
   self.assertAlmostEqual(shape.BoundingBox().ylen,total,places=4)
   holes=[]
   for f in shape.Faces():
    a=BRepAdaptor_Surface(f.wrapped)
    if a.GetType()==GeomAbs_Cylinder:
     c=a.Cylinder()
     if abs(c.Radius()-1.5)<1e-5:holes.append(c)
   self.assertEqual(len(holes),4)
   for c in holes:
    p=c.Location()
    self.assertAlmostEqual((p.X()**2+p.Z()**2)**.5,7,places=2)

 def test_c018_accessory_dimensions_follow_official_page_seven(self):
  from v2.cad_parts import c018_accessories
  from OCP.BRepAdaptor import BRepAdaptor_Surface
  from OCP.GeomAbs import GeomAbs_Cylinder
  for name,wp in c018_accessories().items():
   b=wp.val().BoundingBox()
   self.assertAlmostEqual(b.ylen,4.5 if name=='drive' else 3.1,places=3)
   holes=[]
   for f in wp.val().Faces():
    a=BRepAdaptor_Surface(f.wrapped)
    if a.GetType()==GeomAbs_Cylinder:
     c=a.Cylinder();p=c.Location()
     if abs(c.Radius()-1.5)<.001 and (p.X()**2+p.Z()**2)**.5>6.9:holes.append(c)
   self.assertEqual(len(holes),4,name)

 def test_vendor_axis_is_joint_origin(self):
  from v2.cad_parts import sts3215
  from OCP.BRepAdaptor import BRepAdaptor_Surface
  from OCP.GeomAbs import GeomAbs_Cylinder
  axes=[]
  for f in sts3215().val().Faces():
   a=BRepAdaptor_Surface(f.wrapped)
   if a.GetType()==GeomAbs_Cylinder:
    c=a.Cylinder()
    if abs(c.Radius()-10)<.01 and abs(c.Axis().Direction().Y())>.99:
     p=c.Location();axes.append((p.X(),p.Z()))
  self.assertGreaterEqual(len(axes),2)
  for x,z in axes:self.assertAlmostEqual(x,0,places=3);self.assertAlmostEqual(z,0,places=3)

 def test_pelvis_has_no_large_sandwich_and_mounts_are_drilled(self):
  from v2.pelvis_cad import build_pelvis_items
  items=build_pelvis_items()
  names={i['name'] for i in items}
  self.assertNotIn('pelvis-front',names)
  self.assertNotIn('pelvis-back',names)
  self.assertIn('pelvis-open-frame',names)
  for i in items:
   self.assertTrue(i['wp'].val().isValid(),i['name'])
   self.assertGreater(i['wp'].val().Volume(),0,i['name'])
  frame=next(i for i in items if i['name']=='pelvis-open-frame')
  self.assertEqual(len(frame['mount_holes']),6)
  self.assertLess(frame['wp'].val().Volume()*2.7/1000,45)

if __name__=='__main__':unittest.main()
