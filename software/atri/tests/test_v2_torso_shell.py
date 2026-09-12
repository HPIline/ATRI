import tempfile
import unittest

try:
    import cadquery as cq
except ImportError:
    cq = None


@unittest.skipUnless(cq, 'requires repository .venv-cad')
class TorsoShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from v2.electronics_mount import build_sbc_mount, build_bus_mount
        from v2.torso_shell import add_torso_shell
        cls.anchors = build_sbc_mount()+build_bus_mount()
        cls.items = add_torso_shell(cls.anchors)

    def test_shells_and_integrated_anchors_are_single_valid_solids(self):
        selected = [p for p in self.items if p['kind']=='petg']
        for p in selected:
            with self.subTest(p=p['name']):
                self.assertTrue(p['wp'].val().isValid())
                self.assertEqual(len(p['wp'].val().Solids()), 1)
        self.assertEqual(len(self.items),len(self.anchors)+10)

    def test_three_mf_is_closed_for_all_modified_printed_parts(self):
        from v2.manufacturing import _shape, orient_for_print, write_3mf
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            for p in self.items:
                if p['kind']=='petg':
                    with self.subTest(p=p['name']):
                        shape=orient_for_print(_shape(p['wp'],p['name']),p['print_face'])
                        write_3mf(shape,Path(folder)/(p['name']+'.3mf'))

    def test_shells_do_not_penetrate_supports_or_each_other(self):
        shells=[p for p in self.items if p['name'].startswith('shell-torso-') and p['kind']=='petg']
        supports=[p for p in self.items if p['name'] in ('bus-bridge','sbc-carrier-0','sbc-carrier-1')]
        for shell in shells:
            for other in supports+shells:
                if shell is other:continue
                with self.subTest(shell=shell['name'],other=other['name']):
                    self.assertLess(shell['wp'].val().intersect(other['wp'].val()).Volume(),1e-5)

    def test_missing_anchor_rejected_and_input_not_modified(self):
        from v2.torso_shell import add_torso_shell
        with self.assertRaises(ValueError):add_torso_shell([])
        self.assertTrue(all('shell_mount' not in p for p in self.anchors))

    def test_shell_hardware_does_not_penetrate_any_printed_part(self):
        hardware=[p for p in self.items if p['name'].startswith('shell-torso-') and p['kind']=='fastener']
        printed=[p for p in self.items if p['kind']=='petg']
        for bolt in hardware:
            for plastic in printed:
                with self.subTest(hardware=bolt['name'],plastic=plastic['name']):
                    self.assertLess(bolt['wp'].val().intersect(plastic['wp'].val()).Volume(),1e-5)
