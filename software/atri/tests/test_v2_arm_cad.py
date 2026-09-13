"""Candidate arm assembly checks using exact CAD, not envelope whitelists."""
import unittest

from atri.optional_cadquery import HAS_CADQUERY, skip_without_cadquery

if HAS_CADQUERY:
    from v2.arm_cad import build_arm_items
    from v2.cad_parts import sts3215_components, orient_y_to_axis
    from v2.assembly3d import kinematic_tree, fk
    from v2.cad_export import _moved
    from v2.profile import CAD_INTERFACE
    from v2.arm_cad import parameters
    from v2.pelvis_cad import cyl


def collisions(parts, transforms, moving_only=False):
    moved = [(p, _moved(p['wp'], transforms[p['link']]).val()) for p in parts]
    boxes = [shape.BoundingBox() for _, shape in moved]
    result = []
    for index, (a, shape) in enumerate(moved):
        aa = boxes[index]
        for other_index, (b, other) in enumerate(moved[index + 1:],index+1):
            if moving_only and a['link'] == b['link']:
                continue
            if a['kind'] == 'fastener' and b['kind'] == 'fastener':
                names={a['name'],b['name']}
                regular=a['name'].replace('-bolt-','-thread-')==b['name'].replace('-nut-','-thread-') or b['name'].replace('-bolt-','-thread-')==a['name'].replace('-nut-','-thread-')
                p=parameters();special=[]
                for side in ('left','right'):
                    special.append({f'case-{side}-fore-nut-0',f"arm-{side}-gripper-fixed-bolt-{p['finger_case_bolt_z_mm'][0]}"})
                    special.append({f'arm-{side}-gripper-fixed-aux-nut',f"arm-{side}-gripper-fixed-bolt-{p['finger_case_bolt_z_mm'][1]}"})
                if regular or names in special:
                    continue  # Explicit matching male/female thread pair only.
            bb = boxes[other_index]
            if any(min(getattr(aa, axis+'max'), getattr(bb, axis+'max')) -
                   max(getattr(aa, axis+'min'), getattr(bb, axis+'min')) < 1e-6
                   for axis in 'xyz'):
                continue
            volume = shape.intersect(other).Volume()
            if volume > 1e-6:
                result.append((a['name'], b['name'], round(volume, 6)))
    return result


@skip_without_cadquery
class ArmAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = kinematic_tree()
        cls.parts = build_arm_items()
        body = sts3215_components()['body'].union(cyl(3,4.1,'y',(0,-18.5,0)))
        for joint in cls.tree['joints']:
            if joint['group'] not in ('arm_l', 'arm_r'):
                continue
            wp = orient_y_to_axis(body,joint['axis'])
            wp = wp.rotate((0,0,0),tuple(joint['axis']),CAD_INTERFACE['housing_clock_deg'].get(joint['name'],0)).translate(joint['xyz'])
            cls.parts.append(dict(name='servo-'+joint['name'],link=joint['parent'],kind='servo',wp=wp))

    def test_zero_pose(self):
        self.assertEqual(collisions(self.parts, fk(self.tree)), [])

    def test_single_joint_ranges(self):
        for index,joint in enumerate(self.tree['joints']):
            if joint['group'] not in ('arm_l','arm_r'):
                continue
            side=joint['name'].split('_')[0]
            local=[p for p in self.parts if side in p['name']]
            for angle in range(joint['limit_deg'][0],joint['limit_deg'][1]+1,5):
                angles=[0.]*len(self.tree['joints']);angles[index]=angle
                with self.subTest(joint=joint['name'],angle=angle):
                    self.assertEqual(collisions(local,fk(self.tree,angles),moving_only=True),[])
        for side,roll in (('left',90.),('right',-90.)):
            local=[p for p in self.parts if side in p['name']]
            for pitch in (-90.,0.,90.):
                for grip in (0.,60.):
                    angles=[0.]*len(self.tree['joints'])
                    for suffix,value in (('shoulder_pitch',pitch),('shoulder_roll',roll),('elbow_pitch',-120.),('gripper',grip)):
                        index=next(i for i,j in enumerate(self.tree['joints']) if j['name']==side+'_'+suffix)
                        angles[index]=value
                    with self.subTest(side=side,corner_pitch=pitch,corner_grip=grip):
                        self.assertEqual(collisions(local,fk(self.tree,angles),moving_only=True),[])

    def test_manufacturing_solids(self):
        for part in self.parts:
            with self.subTest(part=part['name']):
                self.assertTrue(part['wp'].val().isValid())
                self.assertEqual(len(part['wp'].solids().vals()),1)
                for key in ('flat','side_flat','output_flat'):
                    if key in part:
                        self.assertAlmostEqual(part[key].val().BoundingBox().zmin,0.,places=6)
        transforms=fk(self.tree)
        boxes=[_moved(p['wp'],transforms[p['link']]).val().BoundingBox() for p in self.parts]
        self.assertLessEqual(max(b.ymax for b in boxes)-min(b.ymin for b in boxes),295.)
        right_joint=next(j for j in self.tree['joints'] if j['name']=='right_shoulder_pitch')
        self.assertEqual(right_joint['axis'],[0.,-1.,0.])
        for part in self.parts:
            if 'right-shoulder' in part['name'] and part['kind']!='fastener':
                self.assertLessEqual(part['wp'].val().BoundingBox().ymax,-19.2+1e-6)
        self.assertFalse(any(p.get('stock_angle_mm',(0,))[0]>=100 for p in self.parts))

    def test_fixed_pad_has_metal_support_across_contact_width(self):
        parts={p['name']:p for p in self.parts}
        for side in ('left','right'):
            shoe=parts[f'arm-{side}-gripper-pad-support-1']['wp'].val()
            pad=parts[f'arm-{side}-gripper-fixed-pad']['wp'].val()
            self.assertLess(shoe.distance(pad),1e-6)
            a,b=shoe.BoundingBox(),pad.BoundingBox()
            self.assertGreaterEqual(a.xmax,b.xmax-.3)
            self.assertGreaterEqual(len(shoe.Solids()),1)

    def test_gripper_35mm_opening_retains_contact_height(self):
        from v2.profile import K
        parts={p['name']:p for p in self.parts}
        for side in ('left','right'):
            fixed=parts[f'arm-{side}-gripper-fixed-pad']['wp'].translate((0,0,K['forearm'])).val()
            moving=parts[f'arm-{side}-gripper-moving-pad']['wp'].val().rotate((0,0,0),(1,0,0),60)
            self.assertGreaterEqual(fixed.distance(moving),35.)
            a,b=fixed.BoundingBox(),moving.BoundingBox()
            self.assertGreaterEqual(min(a.zmax,b.zmax)-max(a.zmin,b.zmin),4.)
            self.assertGreaterEqual(min(a.xmax,b.xmax)-max(a.xmin,b.xmin),1.9)

    def test_gripper_pads_bond_to_separate_fingers_and_open(self):
        parts={p['name']:p for p in self.parts}
        for side in ('left','right'):
            for kind in ('fixed','moving'):
                finger=parts[f'arm-{side}-gripper-{kind}-finger']
                pad=parts[f'arm-{side}-gripper-{kind}-pad']
                self.assertEqual(finger['link'],side+('_hand' if kind=='fixed' else '_grip'))
                self.assertLess(finger['wp'].val().distance(pad['wp'].val()),1e-6)
            index=next(i for i,j in enumerate(self.tree['joints']) if j['name']==side+'_gripper')
            gaps=[]
            for angle in (0.,60.):
                angles=[0.]*len(self.tree['joints']);angles[index]=angle;transforms=fk(self.tree,angles)
                fixed=parts[f'arm-{side}-gripper-fixed-pad'];moving=parts[f'arm-{side}-gripper-moving-pad']
                gaps.append(_moved(fixed['wp'],transforms[fixed['link']]).val().distance(_moved(moving['wp'],transforms[moving['link']]).val()))
            self.assertGreater(gaps[1],gaps[0]+20.)


if __name__ == '__main__':unittest.main()
