#!/usr/bin/env python3
"""生成"零安装"交互式 3D 预览：一个自包含 HTML + 一个标准 GLB。

为什么自研 HTML 预览（而不是只依赖某个查看器）：
    - **零安装**：任何浏览器双击就开，不需要 vtk / Blender / 任何插件；
    - **可自动化**：由脚本从 CAD 实体直接生成，改完模型重跑一条命令即可；
    - **断网可用**：几何数据以 base64 内嵌，不依赖 CDN（比赛现场没网也能给评委看）。

同时导出 `.glb`（glTF 2.0 二进制，需 vtk）：这是**标准交换格式**，
VS Code 的 glTF 扩展、Blender、在线查看器都能直接读——用于"要给别人看/要二次加工"的场合。

用法：
    .venv-cad/bin/python design/cad/preview.py --all
    .venv-cad/bin/python design/cad/preview.py --part joint_cage   # 只看单件
产出：
    out/preview/ATRI-preview.html     自包含交互预览（旋转/缩放/平移/显隐）
    out/preview/ATRI-assembly.glb     标准 glTF 二进制（可选，需 vtk）
"""
from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

import numpy as np
import cadquery as cq

import assembly as A
import render3d as R
import skeleton as sk
from kit import MATERIALS

OUT = HERE / "out"
PREVIEW = OUT / "preview"

# 与渲染图一致的配色（同一套视觉语言，PPT 里能混用）
KIND_COLORS = {
    "bulk":    (140, 158, 184),
    "cage":    (33, 76, 133),
    "fork":    (51, 115, 173),
    "adapter": (77, 140, 140),
    "tube":    (115, 148, 115),
    "servo":   (64, 69, 82),
    "elec":    (217, 140, 51),
    "ground":  (90, 140, 110),
}
KIND_LABEL = {
    "bulk": "结构框架/大件", "cage": "关节笼", "fork": "连杆叉",
    "adapter": "紧凑转接块", "tube": "连杆管", "servo": "舵机（占位）",
    "elec": "电子件（占位）", "ground": "地平面（垫高）",
}

PREVIEW_POSE_DEG = A.DISPLAY_POSE_DEG


# --------------------------------------------------------------------------
# 几何：按"类别"打包成批次（HTML 里可按类别显隐）
# --------------------------------------------------------------------------
def build_batches(items: Sequence[Tuple[str, cq.Workplane]], tol: float
                  ) -> Tuple[Dict[str, np.ndarray], List[Dict[str, Any]]]:
    """返回 ({类别: {'pos':(N,9) float32, 'nrm':(N,9) float32, 'col':(N,3) uint8}}, 统计)。"""
    meshes = R.tessellate(items, tol=tol)
    merged: Dict[str, List[Tuple[np.ndarray, np.ndarray]]] = {}
    for name, verts, tris in meshes:
        k = R.kind_of(name)
        v = verts[tris]                                   # (M,3,3)
        n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        ln = np.linalg.norm(n, axis=1, keepdims=True)
        ln[ln < 1e-12] = 1.0
        n = n / ln
        merged.setdefault(k, []).append((v.reshape(-1, 3), n.repeat(3, axis=0)))

    batches: Dict[str, np.ndarray] = {}
    stats: List[Dict[str, Any]] = []
    for k, chunks in merged.items():
        pos = np.concatenate([c[0] for c in chunks]).astype(np.float32)
        nrm = np.concatenate([c[1] for c in chunks]).astype(np.float32)
        col = np.tile(np.array(KIND_COLORS[k], dtype=np.uint8),
                      (len(pos), 1))
        batches[k] = {"pos": pos, "nrm": nrm, "col": col}
        stats.append({"kind": k, "label": KIND_LABEL[k],
                      "triangles": int(len(pos) // 3),
                      "color": KIND_COLORS[k]})
    stats.sort(key=lambda s: -s["triangles"])
    return batches, stats


def ground_batch(bbox: Sequence[float], margin: float = 40.0) -> Dict[str, np.ndarray]:
    """垫高处一张薄地平面，不计入装配零件。"""
    z = float(bbox[2])
    x0, y0 = float(bbox[0]) - margin, float(bbox[1]) - margin
    x1, y1 = float(bbox[3]) + margin, float(bbox[4]) + margin
    pos = np.array(
        [[x0, y0, z], [x1, y0, z], [x1, y1, z],
         [x0, y0, z], [x1, y1, z], [x0, y1, z]],
        dtype=np.float32,
    )
    nrm = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (6, 1))
    col = np.tile(np.array(KIND_COLORS["ground"], dtype=np.uint8), (6, 1))
    return {"pos": pos, "nrm": nrm, "col": col}


# --------------------------------------------------------------------------
# 自包含 HTML（内嵌几何 + 手写 WebGL 查看器，无外部依赖）
# --------------------------------------------------------------------------
_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  html,body{margin:0;height:100%;overflow:hidden;background:#0a2540;
            font:13px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#e8eef7}
  #c{display:block;width:100vw;height:100vh}
  #hud{position:fixed;left:14px;top:12px;pointer-events:none}
  #hud b{font-size:15px;letter-spacing:.5px}
  #hud div{opacity:.75;font-size:12px}
  #panel{position:fixed;right:14px;top:12px;background:rgba(10,37,64,.82);
         border:1px solid rgba(255,255,255,.16);border-radius:10px;padding:10px 12px;
         backdrop-filter:blur(6px);min-width:168px}
  #panel h4{margin:0 0 6px;font-size:12px;opacity:.7;font-weight:600}
  #panel label{display:flex;align-items:center;gap:7px;padding:3px 0;cursor:pointer}
  #panel .sw{width:11px;height:11px;border-radius:3px;flex:none}
  #panel .n{margin-left:auto;opacity:.55;font-size:11px}
  #tip{position:fixed;left:14px;bottom:12px;opacity:.6;font-size:12px}
  #panel button{margin-top:8px;width:100%;background:rgba(255,255,255,.1);color:#e8eef7;
                border:1px solid rgba(255,255,255,.2);border-radius:6px;padding:5px;cursor:pointer}
  #panel button:hover{background:rgba(255,255,255,.18)}
</style>
</head>
<body>
<canvas id="c"></canvas>
<div id="hud"><b>__TITLE__</b><div>__SUBTITLE__</div></div>
<div id="panel">
  <h4>显示</h4>
  <div id="kinds"></div>
  <button id="reset">重置视角 (R)</button>
  <button id="wire">线框 (W)</button>
  <button id="spin">自动旋转 (空格)</button>
</div>
<div id="tip">左键拖拽旋转 · 滚轮缩放 · 右键/Shift 拖拽平移</div>
<script id="geo" type="application/octet-stream">__B64__</script>
<script id="meta" type="application/json">__META__</script>
<script>
"use strict";
const META = JSON.parse(document.getElementById("meta").textContent);
function b64(s){const bin=atob(s);const n=bin.length;const u=new Uint8Array(n);
  for(let i=0;i<n;i++)u[i]=bin.charCodeAt(i);return u.buffer;}
const BUF = b64(document.getElementById("geo").textContent.trim());

const canvas=document.getElementById("c");
const gl=canvas.getContext("webgl",{antialias:true,alpha:false})||canvas.getContext("experimental-webgl");
if(!gl){document.body.innerHTML="<p style='padding:2em'>此浏览器不支持 WebGL，请用 Safari/Chrome/Edge 打开。</p>";}

// ---------- 矩阵 ----------
function mul(a,b){const o=new Float32Array(16);
  for(let i=0;i<4;i++)for(let j=0;j<4;j++){let s=0;
    for(let k=0;k<4;k++)s+=a[k*4+j]*b[i*4+k];o[i*4+j]=s;}return o;}
function persp(fov,asp,n,f){const t=1/Math.tan(fov/2),o=new Float32Array(16);
  o[0]=t/asp;o[5]=t;o[10]=(f+n)/(n-f);o[11]=-1;o[14]=2*f*n/(n-f);return o;}
function lookAt(e,c,u){
  let z=[e[0]-c[0],e[1]-c[1],e[2]-c[2]];let l=Math.hypot(...z);z=z.map(v=>v/l);
  let x=[u[1]*z[2]-u[2]*z[1],u[2]*z[0]-u[0]*z[2],u[0]*z[1]-u[1]*z[0]];
  l=Math.hypot(...x)||1;x=x.map(v=>v/l);
  const y=[z[1]*x[2]-z[2]*x[1],z[2]*x[0]-z[0]*x[2],z[0]*x[1]-z[1]*x[0]];
  return new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,
    -(x[0]*e[0]+x[1]*e[1]+x[2]*e[2]),-(y[0]*e[0]+y[1]*e[1]+y[2]*e[2]),
    -(z[0]*e[0]+z[1]*e[1]+z[2]*e[2]),1]);}

// ---------- 着色器 ----------
const VS=`attribute vec3 aPos;attribute vec3 aNrm;attribute vec3 aCol;
uniform mat4 uMVP;varying vec3 vN;varying vec3 vC;varying float vD;
void main(){vN=aNrm;vC=aCol;gl_Position=uMVP*vec4(aPos,1.0);
vD=gl_Position.z;}`;
const FS=`precision mediump float;varying vec3 vN;varying vec3 vC;uniform float uAlpha;
void main(){vec3 L=normalize(vec3(0.42,-0.62,0.66));
float d=max(dot(normalize(vN),L),0.0);
vec3 c=vC*(0.46+0.58*d);
gl_FragColor=vec4(c,uAlpha);}`;
function sh(t,s){const o=gl.createShader(t);gl.shaderSource(o,s);gl.compileShader(o);
  if(!gl.getShaderParameter(o,gl.COMPILE_STATUS))console.error(gl.getShaderInfoLog(o));return o;}
const prog=gl.createProgram();
gl.attachShader(prog,sh(gl.VERTEX_SHADER,VS));
gl.attachShader(prog,sh(gl.FRAGMENT_SHADER,FS));
gl.linkProgram(prog);gl.useProgram(prog);
const aPos=gl.getAttribLocation(prog,"aPos"),aNrm=gl.getAttribLocation(prog,"aNrm"),
      aCol=gl.getAttribLocation(prog,"aCol"),uMVP=gl.getUniformLocation(prog,"uMVP"),
      uAlpha=gl.getUniformLocation(prog,"uAlpha");

// ---------- 上传几何 ----------
const F32=new Float32Array(BUF,0,META.floatCount);
const groups=[];
for(const b of META.batches){
  const pos=gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER,pos);
  gl.bufferData(gl.ARRAY_BUFFER,F32.subarray(b.fOffset,b.fOffset+b.verts*6),gl.STATIC_DRAW);
  const col=gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER,col);
  gl.bufferData(gl.ARRAY_BUFFER,new Uint8Array(BUF,META.floatCount*4+b.cOffset,b.verts*3),gl.STATIC_DRAW);
  groups.push({meta:b,pos,col,visible:true});
}

// ---------- 相机 ----------
const bbox=META.bbox, ctr=[(bbox[0]+bbox[3])/2,(bbox[1]+bbox[4])/2,(bbox[2]+bbox[5])/2];
const radius=Math.max(bbox[3]-bbox[0],bbox[4]-bbox[1],bbox[5]-bbox[2])/2;
let theta=0.9,phi=1.15,dist=radius*3.4,target=ctr.slice(),spin=false,wire=false;

function draw(){
  const w=canvas.clientWidth,h=canvas.clientHeight;
  if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
  gl.viewport(0,0,w,h);
  gl.clearColor(0.039,0.145,0.251,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
  gl.enable(gl.DEPTH_TEST);gl.enable(gl.CULL_FACE);gl.cullFace(gl.BACK);
  gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
  const eye=[target[0]+dist*Math.sin(phi)*Math.cos(theta),
             target[1]+dist*Math.sin(phi)*Math.sin(theta),
             target[2]+dist*Math.cos(phi)];
  const mvp=mul(persp(Math.PI/4,w/h,radius*0.02,radius*40),
                lookAt(eye,target,[0,0,1]));
  gl.uniformMatrix4fv(uMVP,false,mvp);
  for(const g of groups){
    if(!g.visible)continue;
    gl.bindBuffer(gl.ARRAY_BUFFER,g.pos);
    gl.enableVertexAttribArray(aPos);gl.vertexAttribPointer(aPos,3,gl.FLOAT,false,24,0);
    gl.enableVertexAttribArray(aNrm);gl.vertexAttribPointer(aNrm,3,gl.FLOAT,false,24,12);
    gl.bindBuffer(gl.ARRAY_BUFFER,g.col);
    gl.enableVertexAttribArray(aCol);gl.vertexAttribPointer(aCol,3,gl.UNSIGNED_BYTE,true,3,0);
    const mate=g.meta.kind==="fork"||g.meta.kind==="cage";
    gl.uniform1f(uAlpha,mate?0.55:1.0);
    gl.depthMask(!mate);
    gl.drawArrays(wire?gl.LINES:gl.TRIANGLES,0,g.meta.verts);
  }
  gl.depthMask(true);
}

// ---------- 交互 ----------
let drag=null;
canvas.addEventListener("contextmenu",e=>e.preventDefault());
canvas.addEventListener("mousedown",e=>{drag={x:e.clientX,y:e.clientY,
  pan:(e.button===2||e.shiftKey)};});
window.addEventListener("mouseup",()=>drag=null);
window.addEventListener("mousemove",e=>{
  if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;
  if(drag.pan){
    const k=dist*0.0016;
    const right=[-Math.sin(theta),Math.cos(theta),0];
    const up=[-Math.cos(theta)*Math.cos(phi),-Math.sin(theta)*Math.cos(phi),Math.sin(phi)];
    for(let i=0;i<3;i++)target[i]+=(-right[i]*dx+up[i]*dy)*k;
  }else{theta-=dx*0.008;phi=Math.max(0.05,Math.min(Math.PI-0.05,phi-dy*0.008));}
  draw();});
canvas.addEventListener("wheel",e=>{e.preventDefault();
  dist*=Math.exp(e.deltaY*0.0011);
  dist=Math.max(radius*0.35,Math.min(radius*30,dist));draw();},{passive:false});
window.addEventListener("keydown",e=>{
  const k=e.key.toLowerCase();
  if(k==="r"){theta=0.9;phi=1.15;dist=radius*3.4;target=ctr.slice();draw();}
  else if(k==="w"){wire=!wire;draw();}
  else if(e.code==="Space"){spin=!spin;e.preventDefault();}});
(function loop(){if(spin){theta+=0.006;draw();}requestAnimationFrame(loop);})();
window.addEventListener("resize",draw);

// ---------- 类别开关 ----------
const kinds=document.getElementById("kinds");
for(const g of groups){
  const m=g.meta;
  const el=document.createElement("label");
  el.innerHTML=`<input type="checkbox" checked>
    <span class="sw" style="background:rgb(${m.color.join(",")})"></span>
    <span>${m.label}</span><span class="n">${(m.triangles/1000).toFixed(0)}k</span>`;
  el.querySelector("input").addEventListener("change",ev=>{
    g.visible=ev.target.checked;draw();});
  kinds.appendChild(el);
}
document.getElementById("reset").onclick=()=>{theta=0.9;phi=1.15;dist=radius*3.4;
  target=ctr.slice();draw();};
document.getElementById("wire").onclick=()=>{wire=!wire;draw();};
document.getElementById("spin").onclick=()=>{spin=!spin;};
draw();
</script>
</body>
</html>
"""


def write_html(batches: Dict[str, np.ndarray], stats: List[Dict[str, Any]],
               bbox: Sequence[float], path: Path, title: str,
               subtitle: str) -> Dict[str, Any]:
    """把几何打包进一个自包含 HTML。"""
    floats: List[np.ndarray] = []
    uints: List[bytes] = []
    f_off = u_off = 0
    meta_batches = []
    for s in stats:
        k = s["kind"]
        b = batches[k]
        pos_nrm = np.concatenate([b["pos"], b["nrm"]], axis=1).astype(np.float32)
        floats.append(pos_nrm.reshape(-1))
        uints.append(b["col"].astype(np.uint8).tobytes())
        verts = int(len(b["pos"]))
        meta_batches.append({
            "kind": k, "label": s["label"], "color": list(s["color"]),
            "verts": verts, "triangles": s["triangles"],
            "fOffset": f_off, "cOffset": u_off,
        })
        f_off += verts * 6
        u_off += verts * 3

    blob = np.concatenate(floats).astype(np.float32).tobytes() + b"".join(uints)
    meta = {"floatCount": f_off, "batches": meta_batches,
            "bbox": [round(v, 2) for v in bbox]}
    html = (_HTML.replace("__TITLE__", title)
            .replace("__SUBTITLE__", subtitle)
            .replace("__B64__", base64.b64encode(blob).decode("ascii"))
            .replace("__META__", json.dumps(meta, ensure_ascii=False)))
    path.write_text(html, encoding="utf-8")
    return {"html_bytes": path.stat().st_size,
            "geo_bytes": len(blob),
            "triangles": sum(b["triangles"] for b in meta_batches)}


def export_glb(items: Sequence[Tuple[str, cq.Workplane]], path: Path
               ) -> Optional[str]:
    """用 CadQuery 官方导出器出标准 glTF 二进制（需要 vtk）。"""
    try:
        asm = cq.Assembly()
        for name, wp in items:
            k = R.kind_of(name)
            c = KIND_COLORS[k]
            asm.add(wp.val(), name=name,
                    color=cq.Color(c[0] / 255, c[1] / 255, c[2] / 255))
        # 注意：必须调 exportGLTF 本体；走 cq.exporters.export(..., exportType="GLTF")
        # 会在 dispatch 上抛 DispatchError（cadquery 2.5.2 的已知路由问题）
        from cadquery.occ_impl.exporters.assembly import exportGLTF
        exportGLTF(asm, str(path), binary=True, tolerance=0.4,
                   angularTolerance=0.4)
        return f"{path.stat().st_size/1e6:.1f} MB"
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] GLB 导出跳过（{type(exc).__name__}: {exc}）")
        print("         装 vtk 后可用：.venv-cad/bin/pip install -i "
              "https://mirrors.aliyun.com/pypi/simple/ vtk")
        return None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="生成交互式 3D 预览")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--zero", action="store_true",
                    help="用机械零位（默认是展示姿态；零位零件本身不得穿髋）")
    ap.add_argument("--part", type=str, default=None, help="只看单个零件")
    ap.add_argument("--tol", type=float, default=1.2, help="网格容差 mm")
    args = ap.parse_args(argv)

    PREVIEW.mkdir(parents=True, exist_ok=True)

    if args.part:
        items = [(args.part, sk.build(args.part))]
        title = f"ATRI · {args.part}"
        subtitle = "单件预览"
    else:
        pose = {} if args.zero else PREVIEW_POSE_DEG
        kin = A.Kin(A.DESIGN / "atri.urdf", pose_deg=pose)
        placements = json.loads((A.DESIGN / "placements.json").read_text(encoding="utf-8"))
        items, log = A.build_assembly(kin, placements)
        bad = [l for l in log if not l.get("ok")]
        bb0 = None
        for _, wp in items:
            b0 = wp.val().BoundingBox()
            bb0 = b0 if bb0 is None else bb0.add(b0)
        title = "A.T.R.I. 骨架装配预览"
        pose_label = "机械零位" if args.zero else "展示姿态"
        subtitle = (f"{len(items)} 个零件 · 22 DOF · {pose_label} · 包络 "
                    f"{bb0.xlen:.0f}×{bb0.ylen:.0f}×{bb0.zlen:.0f} mm")
        if bad:
            print(f"  [WARN] {len(bad)} 个件装配失败")

    print(f"三角化（tol={args.tol}）…")
    batches, stats = build_batches(items, tol=args.tol)
    bb = None
    for _, wp in items:
        b = wp.val().BoundingBox()
        bb = b if bb is None else bb.add(b)
    bbox = [bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax]
    if not args.part:
        batches["ground"] = ground_batch(bbox)
        stats.append({"kind": "ground", "label": KIND_LABEL["ground"],
                      "triangles": 2, "color": KIND_COLORS["ground"]})

    html = PREVIEW / "ATRI-preview.html"
    info = write_html(batches, stats, bbox, html, title, subtitle)
    print(f"已生成 {html}")
    print(f"  {info['triangles']} 三角面 · 几何 {info['geo_bytes']/1e6:.1f} MB · "
          f"HTML {info['html_bytes']/1e6:.1f} MB（自包含，双击即可用）")

    glb_mb = export_glb(items, PREVIEW / "ATRI-assembly.glb")
    if glb_mb:
        print(f"已生成 {PREVIEW/'ATRI-assembly.glb'}（{glb_mb}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
