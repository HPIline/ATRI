import unittest
import cadquery as cq
from v2.profile import ELECTRONICS as E


class ElectronicsMountTests(unittest.TestCase):
    def test_official_board_holes_are_open_at_transformed_datums(self):
        from v2.electronics_cad import build_electronics
        board=next(p['wp'].val() for p in build_electronics() if p['name']=='sbc')
        x,y,z=E['sbc']['position_mm'];w,h,t=E['sbc']['pcb_mm']
        for hx,hy in E['sbc']['hole_xy_mm']:
            probe=cq.Workplane('YZ').center(y+hx-w/2,z-(hy-h/2)).circle(1.3).extrude(4).translate((x-2,0,0))
            self.assertLess(board.intersect(probe.val()).Volume(),1e-8)

    def test_mounts_are_single_solids_and_clear_board(self):
        from v2.electronics_mount import build_sbc_mount
        from v2.electronics_cad import build_electronics
        board=next(p['wp'].val() for p in build_electronics() if p['name']=='sbc')
        parts=build_sbc_mount()
        self.assertEqual(sum(p['kind']=='petg' for p in parts),2)
        for p in parts:
            with self.subTest(part=p['name']):
                solid=p['wp'].val()
                self.assertTrue(solid.isValid())
                self.assertEqual(len(solid.Solids()),1)
                self.assertLess(solid.intersect(board).Volume(),1e-7)

    def test_carrier_and_fasteners_clear_torso_frame(self):
        from v2.electronics_mount import build_sbc_mount
        from v2.torso_cad import build_torso_items
        frame=build_torso_items()
        for p in build_sbc_mount():
            for q in frame:
                with self.subTest(mount=p['name'],frame=q['name']):
                    self.assertLess(p['wp'].val().intersect(q['wp'].val()).Volume(),1e-6)
