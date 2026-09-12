"""Strict same-build STEP/STL/URDF/WebGL and manufacturing review export."""
from pathlib import Path
import json
import os
import shutil
import tempfile
from xml.etree import ElementTree as ET
import cadquery as cq
from .assembly3d import kinematic_tree, fk, preview_payload
from .pelvis_cad import mesh_payload
from .preview3d import write_html
from .urdf import write_urdf
from .manufacturing import _shape, GEOMETRY_KEYS


def canonical_items(items):
    """Validate every solid and link before exporting; preserve multi-solid items."""
    items=list(items);names=[i['name'] for i in items]
    if len(set(names))!=len(names):raise ValueError('Duplicate CAD part names')
    links={l['name'] for l in kinematic_tree()['links']}
    result=[]
    for item in items:
        if item['link'] not in links:raise ValueError(f"Unknown link: {item['name']} {item['link']}")
        if Path(item['name']).name!=item['name'] or item['name'] in ('.','..'):raise ValueError('Unsafe CAD part name')
        row={k:v for k,v in item.items() if k not in GEOMETRY_KEYS}
        json.dumps(row,allow_nan=False)
        copy=dict(item);copy['wp']=cq.Workplane('XY').newObject([_shape(item['wp'],item['name'])]);result.append(copy)
    return result


def export_subset(items, folder):
    """Export all selected items for a visible MCP update, with real metadata."""
    items=canonical_items(items);folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for item in items:
        filename=item['name']+'.stl'
        cq.exporters.export(item['wp'],str(folder/filename))
        row={k:v for k,v in item.items() if k not in GEOMETRY_KEYS}
        row['file']=filename;manifest.append(row)
    (folder/'parts.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return len(manifest)


def assembly_snapshot(items):
    from .cad_export import _moved
    items=canonical_items(items);world=fk(kinematic_tree());rows=[]
    for item in items:
        shape=item['wp'].val();bb=shape.BoundingBox();wb=_moved(item['wp'],world[item['link']]).val().BoundingBox()
        row={k:v for k,v in item.items() if k not in GEOMETRY_KEYS}
        row.update(volume_mm3=shape.Volume(),solid_count=len(shape.Solids()),
          bbox_mm=[getattr(bb,k) for k in ('xmin','ymin','zmin','xmax','ymax','zmax')],
          world_bbox_mm=[getattr(wb,k) for k in ('xmin','ymin','zmin','xmax','ymax','zmax')])
        rows.append(row)
    bounds=[min(p['world_bbox_mm'][i] for p in rows) for i in range(3)]+[max(p['world_bbox_mm'][i] for p in rows) for i in range(3,6)]
    return dict(parts=rows,part_count=len(rows),bbox_mm=bounds,release_ready=False)


def _same_mesh_collisions(path):
    tree=ET.parse(path,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    for link in tree.getroot().findall('link'):
        mesh=link.find('visual/geometry/mesh')
        if mesh is None:raise ValueError(f"Missing actual link mesh: {link.get('name')}")
        geometry=link.find('collision/geometry')
        geometry.clear();ET.SubElement(geometry,'mesh',dict(mesh.attrib))
    tree.write(path,encoding='utf-8',xml_declaration=True)


def export_review(out=None, items=None, manufacturing=True):
    """Build once or consume supplied items. Stage outputs before replacing them.

    Output directory may contain renders/reference material. Only managed CAD,
    sim, preview and manufacturing directories are replaced; old schematic dxf
    and drawings directories move into legacy-superseded, never remain active.
    """
    from .cad_export import build_items, _moved, _color
    from .manufacturing import export_manufacturing
    out=Path(out) if out else Path(__file__).parent/'out';out.mkdir(parents=True,exist_ok=True)
    items=canonical_items(build_items() if items is None else items)
    snapshot=assembly_snapshot(items);tree=kinematic_tree();world=fk(tree)
    with tempfile.TemporaryDirectory(prefix='.cad-export-',dir=out) as temp:
        stage=Path(temp)
        parts_dir=stage/'sim/parts';mesh_dir=stage/'sim/meshes';cad_dir=stage/'cad'
        for p in (parts_dir,mesh_dir,cad_dir):p.mkdir(parents=True,exist_ok=True)
        assembly=cq.Assembly(name='ATRI-v2-REVIEW-NOT-RELEASED');manifest=[];links={}
        for item in items:
            name,link,wp=item['name'],item['link'],item['wp']
            cq.exporters.export(wp,str(parts_dir/(name+'.stl')))
            row={k:v for k,v in item.items() if k not in GEOMETRY_KEYS}
            row['file']=name+'.stl';manifest.append(row)
            links.setdefault(link,[]).extend(wp.val().Solids())
            assembly.add(_moved(wp,world[link]),name=name,color=_color(item['kind']))
        missing={link['name'] for link in tree['links']}-set(links)
        if missing:raise ValueError(f'Links without geometry: {sorted(missing)}')
        for link,solids in links.items():cq.exporters.export(cq.Compound.makeCompound(solids),str(mesh_dir/(link+'.stl')))
        assembly.save(str(cad_dir/'ATRI-v2-review.step'))
        (stage/'sim/parts.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        write_urdf(stage/'sim/atri_v2.urdf',mesh_dir=mesh_dir)
        _same_mesh_collisions(stage/'sim/atri_v2.urdf')
        payload=preview_payload(parts=mesh_payload(items));payload['title']='ATRI-v2 实装审查 — 未放行打样'
        preview=write_html(stage/'preview/ATRI-v2.html',payload=payload)
        if manufacturing:export_manufacturing(items,stage/'manufacturing')
        (stage/'assembly-snapshot.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
        info=dict(parts=len(items),invalid=[],release_ready=False,manufacturing_exported=manufacturing,
                  geometry='one build_items for STEP/STL/URDF/WebGL'+('/manufacturing' if manufacturing else '; manufacturing not updated'),
                  step='cad/ATRI-v2-review.step',bbox_mm=snapshot['bbox_mm'],preview=preview)
        files=sorted(str(p.relative_to(stage)) for p in stage.rglob('*') if p.is_file())
        info['files']=files+['review-export.json']
        (stage/'review-export.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
        # Geometry/manufacturing failure above leaves all previous outputs intact.
        for name in ('cad','sim','preview')+(('manufacturing',) if manufacturing else ()):
            destination=out/name
            if destination.exists():shutil.rmtree(destination)
            os.replace(stage/name,destination)
        for name in ('assembly-snapshot.json','review-export.json'):os.replace(stage/name,out/name)
        for name in ('dxf','drawings'):
            if (out/name).exists():
                archive=out/'legacy-superseded';archive.mkdir(exist_ok=True)
                target=archive/name
                if target.exists():
                    import time
                    target=archive/(name+'-'+str(time.time_ns()))
                os.replace(out/name,target)
                (archive/'NOT-FOR-MANUFACTURING.txt').write_text('Superseded proxy output. Do not send to fabrication. Use current manufacturing/manifest.json.\n',encoding='utf-8')
    return info

if __name__=='__main__':print(json.dumps(export_review(),ensure_ascii=False))
