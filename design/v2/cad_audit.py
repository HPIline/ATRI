"""B-rep intersection audit. No AABB overlap-ratio exemptions.

Fasteners are excluded from penetration testing: deliberate thread engagement
requires a separate connection-stack check, not Boolean collision suppression.
Touching faces (zero common volume) are allowed. Positive volume is reported.
"""
from __future__ import annotations
import json,itertools
from pathlib import Path
from .cad_export import build_items,_moved
from .assembly3d import kinematic_tree,fk,m_ident


def overlap(a,b):
 return all(getattr(a,k+'max')>getattr(b,k+'min')+1e-5 and getattr(b,k+'max')>getattr(a,k+'min')+1e-5 for k in 'xyz')


def intersections(items,angles=None,include_same_link=True):
 tree=kinematic_tree();W=fk(tree,angles)
 selected=[]
 for it in items:
  if it['kind'] not in ('servo','al','petg','pcb','elec','horn','optical','electronics_case','connector_metal','connector_white'):continue
  if it['kind']=='servo' and not it['name'].startswith('servo-'):continue
  shape=_moved(it['wp'],W.get(it['link'],m_ident())).val()
  selected.append((it,shape,shape.BoundingBox()))
 findings=[];checked=0;vendor_internal_pairs=0
 for (a,sa,ba),(b,sb,bb) in itertools.combinations(selected,2):
  if not include_same_link and a['link']==b['link']:continue
  if not overlap(ba,bb):continue
  if a.get('purchased_assembly') and a.get('purchased_assembly')==b.get('purchased_assembly'):
   vendor_internal_pairs+=1
   continue
  # Every selected structural pair is checked, including aluminium/aluminium.
  checked+=1
  common=sa.intersect(sb);v=common.Volume()
  if v>.01:findings.append({'a':a['name'],'b':b['name'],'volume_mm3':round(v,3),'same_link':a['link']==b['link']})
 return {'method':'B-rep common volume > 0.01 mm3; touching allowed; no AABB ratio whitelist','same_link_checked':include_same_link,'narrow_phase_pairs':checked,'purchased_internal_pairs_excluded':vendor_internal_pairs,'purchased_internal_scope':'Soldered vendor-board internals and conservative component envelopes are not separate ATRI mating interfaces; every vendor component is checked against external structural parts.','intersections':findings,'ok':not findings}


def report():
 items=build_items();r=intersections(items)
 r['n_items']=len(items)
 r['invalid_solids']=[i['name'] for i in items if not i['wp'].val().isValid()]
 r['mass_g_by_kind']={}
 density={'al':2.7,'petg':1.27,'fastener':7.85,'standoff':8.5,'tpu':1.21}
 for i in items:
  if i['kind'] in density:
   k=i['kind'];r['mass_g_by_kind'][k]=r['mass_g_by_kind'].get(k,0)+i['wp'].val().Volume()*density[k]/1000
 r['mass_g_by_kind']={k:round(v,2) for k,v in r['mass_g_by_kind'].items()}
 r['mass_scope']='Geometric modeled components only. Electronics use purchased-part masses; this is not whole robot mass.'
 r['release_ready']=False
 r['release_blockers']=['C018 connector revision and sample mating still unverified','Complete harness, power distribution and all BOM audio/IMU parts not modeled','Whole-robot mass and G0 shopping cart not closed','Continuous combined motion, assembly access and clamp strength remain unqualified']
 if r['intersections']:r['release_blockers'].append('Positive-volume intersections listed below')
 return r

if __name__=='__main__':
 p=Path(__file__).parent/'out'/'cad-audit.json'
 r=report();p.write_text(json.dumps(r,ensure_ascii=False,indent=2))
 print(json.dumps({'report':str(p),'n_items':r['n_items'],'intersections':len(r['intersections']),'invalid':r['invalid_solids'],'mass':r['mass_g_by_kind'],'release_ready':r['release_ready']},ensure_ascii=False))
