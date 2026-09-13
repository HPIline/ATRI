"""Known-mass CAD centroid and static gravity moments; NOT dynamic balance."""
import json, math
from pathlib import Path
from .cad_export import build_items, _moved
from .assembly3d import kinematic_tree, fk, m_apply
from .mass_ledger import DENSITY_G_MM3
from .profile import ELECTRONICS, SERVO


def report():
    items=build_items();tree=kinematic_tree();w=fk(tree);rows=[];missing=[]
    for it in items:
        kind=it['kind'];name=it['name'];s=_moved(it['wp'],w[it['link']]).val()
        if kind in DENSITY_G_MM3:mass=s.Volume()*DENSITY_G_MM3[kind]
        elif name.startswith('servo-'):mass=55.
        elif name in ('battery','battery-secondary','battery2-pack-envelope'):mass=ELECTRONICS['battery']['mass_g']
        elif name=='sbc':mass=ELECTRONICS['sbc']['mass_g']
        else:missing.append(name);continue
        rows.append(dict(name=name,link=it['link'],mass_g=mass,centroid_mm=s.Center().toTuple()))
    total=sum(x['mass_g'] for x in rows)
    com=[sum(x['mass_g']*x['centroid_mm'][k] for x in rows)/total for k in range(3)]
    parent={x['name']:x['parent'] for x in tree['links']}
    def descendant(link,root):
        while link:
            if link==root:return True
            link=parent[link]
        return False
    moments=[]
    for j in tree['joints']:
        center=m_apply(w[j['child']],(0,0,0))
        ap=m_apply(w[j['parent']],j['axis']);a0=m_apply(w[j['parent']],(0,0,0))
        axis=[ap[i]-a0[i] for i in range(3)]
        leg=j['name'].startswith(('left_hip','right_hip','left_knee','right_knee','left_ankle','right_ankle'))
        carried=[x for x in rows if descendant(x['link'],j['child']) != leg]
        # r(mm) × gravity(N); only the world Z gravity component is nonzero.
        torque=sum((-(x['centroid_mm'][1]-center[1])*axis[0]+(x['centroid_mm'][0]-center[0])*axis[1])*x['mass_g']*9.81/1e6 for x in carried)
        moments.append(dict(joint=j['name'],gravity_nm=torque,absolute_nm=abs(torque),utilization=abs(torque)/SERVO['rated_nm'],
          scope='single supporting leg upper-side free body' if leg else 'downstream free body',known_mass_only=True))
    soles=[_moved(x['wp'],w[x['link']]).val().BoundingBox() for x in items if x['name'].endswith('foot-sole')]
    support=[]
    for b in soles:
        support.append(dict(rectangle_mm=[b.xmin,b.ymin,b.xmax,b.ymax],
          com_rectangle_margin_mm=min(com[0]-b.xmin,b.xmax-com[0],com[1]-b.ymin,b.ymax-com[1]),
          caveat='bounding rectangle only, not measured contact patch'))
    return dict(release_ready=False,pose='zero',known_mass_g=total,known_mass_centroid_mm=com,
      whole_robot_com_verified=False,missing_cad_mass_items=missing,
      additional_missing='unmodeled harness, IMU/audio, cooling, straps and payload; servo internal CoM approximated by uniform body geometry',
      joint_static_moments=moments,single_foot_rectangle_screen=support,
      limitations='Gravity only; no accelerations, no contact/friction solve, no dynamic ZMP, no complete purchase mass. Do not infer stable walking from this report.')

if __name__=='__main__':
    r=report();p=Path(__file__).parent/'out/gravity-audit.json';p.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:r[k] for k in ('known_mass_g','known_mass_centroid_mm','single_foot_rectangle_screen')},ensure_ascii=False))
