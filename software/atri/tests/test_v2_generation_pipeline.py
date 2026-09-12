"""Small real fixtures validate packaging without exporting the whole robot."""
import base64
import gzip
import json
import re
import struct
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

try:
    import cadquery as cq
except ImportError:
    cq=None

from v2.assembly3d import preview_payload
from v2.preview3d import write_html


class CompressedPreviewTests(unittest.TestCase):
    def test_gzip_preserves_geometry_and_does_not_mutate_input(self):
        verts=[0.,0.,0.,0.,0.,1., 7.,0.,0.,0.,0.,1., 0.,11.,0.,0.,0.,1.]
        payload=preview_payload(parts=[dict(name='fixture',link='pelvis',kind='al',alpha=1.,verts=verts)])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'model.html'
            write_html(path,payload)
            html=path.read_text()
            packed=re.search(r'<script id="geo"[^>]*>(.*?)</script>',html,re.S).group(1)
            self.assertEqual(struct.unpack('<18f',gzip.decompress(base64.b64decode(packed))),tuple(verts))
            self.assertEqual(payload['parts'][0]['verts'],verts)
            self.assertIn('DecompressionStream',html)
            self.assertIn('previewReady',html)

    def test_no_implicit_legacy_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'payload'):
                write_html(Path(tmp)/'model.html')


class ManifestDocumentTests(unittest.TestCase):
    def test_documents_list_actual_print_and_laser_items_with_open_gates(self):
        from v2.generate import generate_documents
        manifest=dict(part_count=2,release_ready=False,parts=[
            dict(name='actual-shell',kind='petg',link='head',material='PETG',volume_mm3=125.,
                 process='FDM',files={'3mf':'print/actual-shell.3mf'},unresolved=['sample required']),
            dict(name='actual-plate',kind='al',link='pelvis',material='6061',volume_mm3=100.,
                 process='laser',files={'laser_dxf':'laser/actual-plate.dxf'},unresolved=[]),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            files=generate_documents(Path(tmp),manifest,{'parts':2,'bbox_mm':[0,0,0,100,80,450]})
            self.assertIn('PETG-打印清单.md',files)
            text=(Path(tmp)/'PETG-打印清单.md').read_text()
            self.assertIn('actual-shell',text)
            self.assertNotIn('cover-pelvis',text)
            gates=json.loads((Path(tmp)/'gates.json').read_text())
            self.assertEqual(set(gates),{'G0','G1','G2','G3','G4'})
            self.assertTrue(all(g['status']=='OPEN' for g in gates.values()))
            report=(Path(tmp)/'ATRI-v2-工程验证.md').read_text()
            self.assertIn('0.98',report)
            self.assertIn('0.3',report)  # 100 mm3 aluminum = 0.27 g, rounded.


@unittest.skipUnless(cq,'requires repository .venv-cad')
class SameBuildExportTests(unittest.TestCase):
    def test_missing_link_geometry_preserves_previous_delivery(self):
        from v2.review_export import export_review
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);(out/'cad').mkdir()
            previous=out/'cad/previous.step';previous.write_text('keep prior review')
            with self.assertRaisesRegex(ValueError,'Links without geometry'):
                export_review(out,items=[dict(name='only-pelvis',link='pelvis',kind='al',wp=cq.Workplane('XY').box(1,2,3))])
            self.assertEqual(previous.read_text(),'keep prior review')

    def test_small_complete_tree_exports_identical_inventory_and_real_collision_meshes(self):
        from v2.assembly3d import kinematic_tree
        from v2.review_export import export_review
        items=[dict(name='fixture-'+link['name'],link=link['name'],kind='al',
                    wp=cq.Workplane('XY').box(2,3,1)) for link in kinematic_tree()['links']]
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            (out/'dxf').mkdir();(out/'dxf/old-proxy.dxf').write_text('obsolete')
            report=export_review(out,items=items)
            self.assertEqual(report['parts'],len(items))
            manifest=json.loads((out/'manufacturing/manifest.json').read_text())
            self.assertEqual({p['name'] for p in manifest['parts']},{p['name'] for p in items})
            self.assertEqual(len(list((out/'sim/parts').glob('*.stl'))),len(items))
            self.assertEqual(len(cq.importers.importStep(str(out/report['step'])).solids().vals()),len(items))
            self.assertIn('target-mass allocations',(out/'sim/atri_v2.urdf').read_text())
            root=ET.parse(out/'sim/atri_v2.urdf').getroot()
            for link in root.findall('link'):
                self.assertEqual(link.find('visual/geometry/mesh').attrib,link.find('collision/geometry/mesh').attrib)
            self.assertFalse((out/'dxf').exists())
            self.assertTrue((out/'legacy-superseded/dxf/old-proxy.dxf').is_file())
            self.assertFalse(report['release_ready'])
