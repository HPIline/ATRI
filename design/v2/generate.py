#!/usr/bin/python3
"""Generate the current assembly once, then derive every delivery from it.

Run from the repository: PYTHONPATH=design python3 -m v2.generate [output].
System Python delegates CAD work to the repository .venv-cad interpreter.
"""
from __future__ import annotations
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
from . import bom, capability, profile as P

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[1]
DEFAULT_OUT=ROOT/'out'
CAD_PYTHON=REPO/'.venv-cad/bin/python'
GATES={
 'G0':'12V C018 SKU 截图及真实购物车 close ≤¥3000；零售 ¥109×20 不通过，不一次购买20只。',
 'G1':'一只 C018：0.8/1.0/1.2 N·m 各循环30分钟，壳温≤65°C。',
 'G2':'单腿铝骡机称重与夹具滑移/蠕变测试；外推整机≤2300g，硬顶2450g。',
 'G3':'赛方书面确认头部、夹爪是否计入上肢躯干及尺寸量法。',
 'G4':'无 hip_yaw 转向误差实测；未关闭不得加回 yaw 或修改现机22DOF软件。',
}


def _bom_md(cart):
    lines=[f"# BOM：{cart['kind']}（估价日期 {cart['price_date']}）",'',
      '> 估算不代表现货、锁价或购物车验收。数量是设计需求，不是采购授权。G0 未关闭。','',
      '| SKU | 名称 | 规格 | 数量 | 单价¥ | 小计¥ | 计入预算 | 来源 |',
      '|---|---|---|---:|---:|---:|---|---|']
    for i in cart['items']:
        lines.append(f"| {i['sku']} | {i['name']} | {i['spec']} | {i['qty']} | {i['unit_cny']:.1f} | {i['subtotal_cny']:.1f} | {'是' if i['in_budget'] else '否'} | {i['source']} |")
    lines+=['',f"预算内估算 ¥{cart['total_cny']:.0f}；整机预算上限 ¥{cart['budget_cny']:.0f}；G0 close 门槛 ¥3000。",'']
    return '\n'.join(lines)


def _part_table(rows):
    lines=['| 实装零件名 | 材料 | 工艺/文件 | 未决项 |','|---|---|---|---|']
    for p in rows:
        links='、'.join(f"[{k}](manufacturing/{v})" for k,v in p['files'].items() if k!='review_stl') or '仅审查网格'
        hold='；'.join(p['unresolved']) or '文件级检查无未决项；整机门禁仍开放'
        lines.append(f"| {p['name']} | {p['material']} | {p['process']}；{links} | {hold} |")
    return '\n'.join(lines)


def generate_documents(out, manifest, review):
    """Write inventories from current manufacturing rows, never proxy part names."""
    out=Path(out);out.mkdir(parents=True,exist_ok=True);written=[]
    def put(name,text):
        path=out/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(text,encoding='utf-8');written.append(name)
    rows=manifest['parts']
    put('ATRI-v2-BOM.md',_bom_md(bom.cart('close'))+'\n---\n\n'+_bom_md(bom.cart('retail')))
    with (out/'ATRI-v2-BOM.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=['sku','name','spec','qty','unit_close','unit_retail','in_budget','source','note'],extrasaction='ignore',lineterminator='\n')
        writer.writeheader();writer.writerows(bom.ITEMS)
    written.append('ATRI-v2-BOM.csv')
    put('gates.json',json.dumps({key:dict(status='OPEN',requirement=value) for key,value in GATES.items()},ensure_ascii=False,indent=2))
    put('PETG-打印清单.md','# PETG / TPU 实装打印清单\n\n以下条目直接来自 manufacturing/manifest.json；未指定朝向不提供打印3MF。哑光白PETG壁厚2.4mm；切片支撑、配合与蠕变须试样。\n\n'+_part_table([p for p in rows if p['kind'] in ('petg','tpu')])+'\n')
    put('铝件-加工清单.md','# 铝件加工清单\n\n只使用 manufacturing/laser 中的实际等厚毛坯DXF；尚未排版或添加割缝补偿。角铝参考模板不是展开毛坯；沉孔、钻孔及标准型材须逐项核对。\n\n'+_part_table([p for p in rows if p['kind']=='al'])+'\n')
    order=['# 实装顺序与零件索引','','> 当前审查版本，G0–G4 均未关闭。此索引不替代逐颗紧固件作业指导书。','',
      '1. 仅购一只 STS3215-C018 12V 做接口和温升试验；核对25T、PCD Φ14、4×M3。量产装配前写入ID和零位。',
      '2. 先装激光板、角铝与外部舵机壳体夹具；螺钉长度、垫片堆叠和螺母按下方实装条目核对。足底为粘接TPU，不从鞋底穿旧示意螺钉。',
      '3. 肢体先穿线，再封连接框架；保持过关节余量，手动逐段检查限位。',
      '4. 骨盆使用开放框架及三个输出转接座，禁止恢复两片大夹板和旧M3×35铜柱布局。',
      '5. 胸腔先装管内螺母、载架和电池托盘，再装电子板；内部紧固件必须在外壳封闭前可达。',
      '6. 安装颈、头部输出臂与USB摄像头；镜头朝+X，USB线向下进入脖子，不使用旧CSI路线。',
      '7. 最后装不透明哑光白分件PETG；逐项执行下表中的 assembly、manufacturing 与 qualification。','',
      '| 实装零件 | link | 装配/工艺备注 |','|---|---|---|']
    for p in rows:
        meta=p.get('metadata',{})
        note='；'.join(str(meta[k]) for k in ('assembly','manufacturing','spec','qualification') if meta.get(k)) or '见实装清单及紧固件核验；无详细工序声明'
        order.append(f"| {p['name']} | {p['link']} | {note} |")
    put('ATRI-v2-装配顺序.md','\n'.join(order)+'\n')
    m=P.MASS['design_limit_g'];walk=P.ankle_torque_nm(m,P.ANKLE['k_walk']);hold=P.ankle_torque_nm(m,P.ANKLE['k_hold'])
    aluminum=sum(p['volume_mm3'] for p in rows if p['kind']=='al')*.00270
    bbox=review.get('bbox_mm');dims=[bbox[i+3]-bbox[i] for i in range(3)] if bbox else None
    report=['# 当前实装工程核验','','所有几何来自同一次 build_items；BRep模型与厂家/标准文件的差异仍以未决项记录。',
      f"零位外包络 XYZ：{dims} mm（实际几何，不是旧示意盒）。",
      f"铝件实体体积按2.70g/cm³换算：{aluminum:.1f} g；不代表整机称重。",
      f"设计质量{m:g}g；硬顶{P.MASS['hard_limit_g']:g}g；20×STS3215-C018 12V，连续额定0.98 N·m。",
      f"walk k=1.4：{walk:.3f} N·m，利用率{walk/P.SERVO['rated_nm']:.1%}；hold k=2：{hold:.3f} N·m，仍超额定。",
      'URDF几何与实装一致；惯量仍是分配估算，Webots尚未真实导入运行。','']
    report += [f"- **{k} OPEN**：{v}" for k,v in GATES.items()]
    put('ATRI-v2-工程验证.md','\n'.join(report)+'\n')
    put('ATRI-v2-能力验证.md',capability.markdown())
    put('sim/README.md','# 仿真入口\n\nURDF为20个revolute，m/rad，实际link网格来自同一次build_items。碰撞网格同源；惯量仍为分配估算，未完成Webots导入运行。\n')
    put('preview/index.html',"<!DOCTYPE html><meta charset=utf-8><meta http-equiv=refresh content='0;url=ATRI-v2.html'><a href='ATRI-v2.html'>打开实装审查模型</a>\n")
    return sorted(written)


def generate(out):
    out=Path(out).resolve()
    if Path(sys.prefix).resolve()!=CAD_PYTHON.parent.parent.resolve():
        if not CAD_PYTHON.is_file():raise RuntimeError(f'CAD interpreter missing: {CAD_PYTHON}')
        env=os.environ.copy();env['PYTHONPATH']=str(REPO/'design')
        subprocess.run([str(CAD_PYTHON),'-m','v2.generate','--cad-worker',str(out)],cwd=REPO,env=env,check=True)
        return json.loads((out/'generated-files.json').read_text())
    from .review_export import export_review
    info=export_review(out,manufacturing=True)
    manifest=json.loads((out/'manufacturing/manifest.json').read_text())
    files=generate_documents(out,manifest,info)
    from .mass_ledger import write as write_mass
    write_mass(out)
    files += ['mass-ledger.json','质量账.md']
    files+=info['files']
    files=sorted(set(files+['generated-files.json']))
    (out/'generated-files.json').write_text(json.dumps(files,ensure_ascii=False,indent=2),encoding='utf-8')
    return files


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if args and args[0]=='--cad-worker':
        args.pop(0)
        if Path(sys.prefix).resolve()!=CAD_PYTHON.parent.parent.resolve():raise RuntimeError('CAD worker must run inside repository .venv-cad')
    if len(args)>1:raise ValueError('Usage: python3 -m v2.generate [output]')
    out=Path(args[0]) if args else DEFAULT_OUT
    files=generate(out)
    print(f'Generated {len(files)} current-assembly files in {out}; G0–G4 OPEN')
    return 0

if __name__=='__main__':raise SystemExit(main())
