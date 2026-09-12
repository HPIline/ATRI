"""Conservative mass accounting; unknown purchased items never count as zero."""
from pathlib import Path
import json
from .profile import MASS,ELECTRONICS,SERVO

DENSITY_G_MM3={'al':.00270,'petg':.00127,'tpu':.00121,'fastener':.00785,'standoff':.0085}


def report(snapshot):
    parts=snapshot['parts'];rows=[]
    for kind,density in DENSITY_G_MM3.items():
        selected=[p for p in parts if p['kind']==kind]
        rows.append(dict(item=kind,count=len(selected),mass_g=round(sum(p['volume_mm3'] for p in selected)*density,3),
             basis='nominal solid volume × assumed material density',
             caveat='Major-diameter thread envelopes, not measured screw masses' if kind=='fastener' else 'Material grade/density and finished mass require sample'))
    rows.extend([
      dict(item='20 C018 servos',count=20,mass_g=1100.,basis='manufacturer nominal 55±1g each',caveat='Accessory/cable inclusion in supplier weight must be established before adding them separately'),
      dict(item=ELECTRONICS['battery']['sku'],count=1,mass_g=ELECTRONICS['battery']['mass_g'],basis='published battery mass',caveat='Check adapter and lead inclusion'),
      dict(item=ELECTRONICS['sbc']['sku'],count=1,mass_g=ELECTRONICS['sbc']['mass_g'],basis='design allocation, not sample measurement',caveat='Board revision, heatsink and card not weighed')])
    unknown=['camera and lens','bus adapter','regulator','IMU','microphone/audio/speaker',
             'wires, plugs, distribution, protection and strain relief','battery straps and adhesives',
             'servo discs, shafts and supplied cable mass scope','SBC cooling and storage']
    subtotal=round(sum(r['mass_g'] for r in rows),3)
    return dict(schema=1,rows=rows,accounted_estimate_g=subtotal,unknown_items=unknown,
       whole_robot_mass_g=None,design_target_g=MASS['design_limit_g'],hard_limit_g=MASS['hard_limit_g'],
       allowance_to_design_g=round(MASS['design_limit_g']-subtotal,3),
       allowance_to_hard_limit_g=round(MASS['hard_limit_g']-subtotal,3),
       design_mass_closed=False,physical_mass_verified=False,
       statement='This is an incomplete conservative design ledger, neither measured mass nor a certified lower bound. Unknown entries cannot be silently assigned zero. No arbitrary thread-volume discount is applied.')


def write(out):
    out=Path(out);r=report(json.loads((out/'assembly-snapshot.json').read_text()))
    (out/'mass-ledger.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
    lines=['# 当前质量账（未闭合）','',r['statement'],'',
      '| 项目 | 数量 | 质量估算g | 依据/限制 |','|---|---:|---:|---|']
    for x in r['rows']:lines.append(f"| {x['item']} | {x['count']} | {x['mass_g']:.1f} | {x['basis']}; {x['caveat']} |")
    lines += ['',f"已计项目约 **{r['accounted_estimate_g']:.1f}g**；设计目标余量 **{r['allowance_to_design_g']:.1f}g**，硬顶余量 **{r['allowance_to_hard_limit_g']:.1f}g**。完整整机质量未知，不能据此放行。",'',
              '以下未计齐，必须补齐采购/实测质量；舵机配件须先避免重复计入：','']
    lines += ['- '+x for x in r['unknown_items']]
    (out/'质量账.md').write_text('\n'.join(lines)+'\n')
    return r


if __name__=='__main__':print(json.dumps(write(Path(__file__).parent/'out'),ensure_ascii=False))
