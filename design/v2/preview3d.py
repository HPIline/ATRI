"""自包含 WebGL 预览：零 CDN，浏览器打开即可转。"""
from __future__ import annotations

import base64
import gzip
import json
import sys
from array import array
from pathlib import Path
from typing import Dict


HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ATRI-v2 三维预览</title>
<style>
html,body{margin:0;height:100%;overflow:hidden;background:#0b1c2c;
  font:13px/1.45 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#e8eef7}
#c{display:block;width:100vw;height:100vh}
#hud{position:fixed;left:16px;top:14px;pointer-events:none}
#hud b{font-size:16px;letter-spacing:.4px}
#hud div{opacity:.72;margin-top:4px}
#panel{position:fixed;right:12px;top:12px;width:300px;max-height:calc(100vh - 24px);
  overflow:auto;background:rgba(8,24,40,.88);border:1px solid rgba(255,255,255,.16);
  border-radius:12px;padding:12px;backdrop-filter:blur(8px)}
#panel h4{margin:12px 0 6px;font-size:11px;opacity:.65;letter-spacing:.5px}
#panel h4:first-child{margin-top:0}
label{display:flex;align-items:center;gap:8px;padding:3px 0;cursor:pointer}
.sw{width:11px;height:11px;border-radius:3px;flex:none}
.row{display:flex;gap:6px;flex-wrap:wrap}
button{flex:1;background:rgba(255,255,255,.1);color:#e8eef7;border:1px solid rgba(255,255,255,.2);
  border-radius:7px;padding:6px 8px;cursor:pointer}
button:hover{background:rgba(255,255,255,.18)}
.jrow{display:grid;grid-template-columns:102px 1fr 36px;align-items:center;gap:4px;padding:1px 0}
.jrow span.n{font-size:11px;opacity:.88;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.jrow span.v{font-size:11px;text-align:right;opacity:.7;font-variant-numeric:tabular-nums}
input[type=range]{width:100%;height:16px;margin:0}
#tip{position:fixed;left:16px;bottom:12px;opacity:.55;font-size:12px}
@media (max-width:720px){
  #panel{left:8px;right:8px;top:auto;bottom:0;width:auto;max-height:42vh;
    border-radius:12px 12px 0 0}
  #hud{left:10px;top:8px}
  #tip{display:none}
}
</style>
</head>
<body>
<canvas id="c"></canvas>
<div id="hud"><b>ATRI-v2 A路线 · 铝夹层</b><div id="sub"></div></div>
<div id="panel">
  <h4>姿势</h4>
  <div class="row" id="presets"></div>
  <h4>关节 20 DOF</h4>
  <div id="sliders"></div>
  <div class="row" style="margin-top:8px"><button id="zero">全部归零</button></div>
  <h4>显示</h4>
  <div id="kinds"></div>
  <h4>视图</h4>
  <div class="row">
    <button id="reset">重置视角</button>
    <button id="wire">线框</button>
    <button id="spin">旋转</button>
  </div>
</div>
<div id="tip">左键旋转 · 滚轮缩放 · 右键/Shift 平移 · 拖滑条摆姿势</div>
<script id="meta" type="application/json">__META__</script>
<script id="geo" type="application/octet-stream">__B64__</script>
<script>
"use strict";
(async function startPreview(){
document.getElementById("sub").textContent="正在解压实装模型…";
const META=JSON.parse(document.getElementById("meta").textContent);
function b64(s){const b=atob(s);const u=new Uint8Array(b.length);for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);return u;}
if(typeof DecompressionStream!=="function") throw new Error("此浏览器不支持 gzip 解压，请使用新版 Chrome / Edge / Firefox / Safari。");
const compressed=b64(document.getElementById("geo").textContent.trim());
const stream=new Blob([compressed]).stream().pipeThrough(new DecompressionStream("gzip"));
const raw=await new Response(stream).arrayBuffer();
if(raw.byteLength!==META.geometryBytes) throw new Error("模型数据长度校验失败");
const F32=new Float32Array(raw);
const canvas=document.getElementById("c");
const gl=canvas.getContext("webgl",{antialias:true,alpha:false});
if(!gl) throw new Error("需要 WebGL，请启用浏览器硬件加速。");

function mI(){const o=new Array(16).fill(0);o[0]=o[5]=o[10]=o[15]=1;return o;}
function mT(x,y,z){const o=mI();o[12]=x;o[13]=y;o[14]=z;return o;}
function mMul(a,b){const o=new Array(16);
  for(let i=0;i<4;i++)for(let j=0;j<4;j++){let s=0;for(let k=0;k<4;k++)s+=a[k*4+j]*b[i*4+k];o[i*4+j]=s;}return o;}
function mAA(ax,th){const n=Math.hypot(ax[0],ax[1],ax[2])||1,x=ax[0]/n,y=ax[1]/n,z=ax[2]/n,c=Math.cos(th),s=Math.sin(th),C=1-c;
  return [x*x*C+c,y*x*C+z*s,z*x*C-y*s,0, x*y*C-z*s,y*y*C+c,z*y*C+x*s,0, x*z*C+y*s,y*z*C-x*s,z*z*C+c,0, 0,0,0,1];}
function persp(fov,asp,n,f){const t=1/Math.tan(fov/2),o=new Array(16).fill(0);
  o[0]=t/asp;o[5]=t;o[10]=(f+n)/(n-f);o[11]=-1;o[14]=2*f*n/(n-f);return o;}
function lookAt(e,c,u){
  let z=[e[0]-c[0],e[1]-c[1],e[2]-c[2]];let l=Math.hypot(z[0],z[1],z[2]);z=z.map(v=>v/l);
  let x=[u[1]*z[2]-u[2]*z[1],u[2]*z[0]-u[0]*z[2],u[0]*z[1]-u[1]*z[0]];l=Math.hypot(x[0],x[1],x[2])||1;x=x.map(v=>v/l);
  const y=[z[1]*x[2]-z[2]*x[1],z[2]*x[0]-z[0]*x[2],z[0]*x[1]-z[1]*x[0]];
  return [x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,
    -(x[0]*e[0]+x[1]*e[1]+x[2]*e[2]),-(y[0]*e[0]+y[1]*e[1]+y[2]*e[2]),-(z[0]*e[0]+z[1]*e[1]+z[2]*e[2]),1];}

const LIDX={};META.links.forEach((l,i)=>LIDX[l.name]=i);
const NJ=META.joints.length, NL=META.links.length;
const ANG=new Float64Array(NJ);
const W=new Array(NL), M=new Array(NL);
const ORIG=META.joints.map(j=>mT(j.xyz[0],j.xyz[1],j.xyz[2]));
function fk(){
  W[LIDX[META.root]]=mT(META.root_xyz[0],META.root_xyz[1],META.root_xyz[2]);
  META.fkOrder.forEach(k=>{
    const j=META.joints[k], th=ANG[k]*Math.PI/180;
    let o=ORIG[k]; if(Math.abs(th)>1e-12) o=mMul(o,mAA(j.axis,th));
    W[LIDX[j.child]]=mMul(W[LIDX[j.parent]],o);
  });
  for(let i=0;i<NL;i++) M[i]=W[i]||mI();
}

const VS="attribute vec3 aP;attribute vec3 aN;uniform mat4 uMVP;uniform mat4 uM;uniform mat3 uN;varying vec3 vN;varying vec3 vW;void main(){vN=uN*aN;vW=(uM*vec4(aP,1.0)).xyz;gl_Position=uMVP*vec4(aP,1.0);}";
const FS="precision mediump float;varying vec3 vN;varying vec3 vW;uniform vec3 uC;uniform vec3 uEye;uniform float uA;uniform float uMetal;uniform float uRough;void main(){vec3 n=normalize(vN);vec3 V=normalize(uEye-vW);vec3 L=normalize(vec3(.55,.22,.82));vec3 H=normalize(L+V);float ndl=max(dot(n,L),0.0);float ndh=max(dot(n,H),0.0);float ndv=max(dot(n,V),0.0);float hemi=.22+.28*max(n.z,0.0)+.12*max(-n.z,0.0);float specPow=mix(8.0,96.0,1.0-uRough);vec3 f0=mix(vec3(.04),uC,uMetal);vec3 spec=f0*pow(ndh,specPow)*mix(.25,.9,1.0-uRough);vec3 diff=uC*(1.0-uMetal)*(hemi+.62*ndl);float rim=pow(1.0-ndv,3.0)*(.18+.35*uMetal);float shadow=smoothstep(6.0,28.0,vW.z)*.22;vec3 c=diff+spec+uC*rim-vec3(shadow);gl_FragColor=vec4(c,uA);}";
function mkSh(t,s){const o=gl.createShader(t);gl.shaderSource(o,s);gl.compileShader(o);return o;}
const prog=gl.createProgram();
const _vs=mkSh(gl.VERTEX_SHADER,VS),_fs=mkSh(gl.FRAGMENT_SHADER,FS);
gl.attachShader(prog,_vs);gl.attachShader(prog,_fs);
gl.linkProgram(prog);
if(!gl.getProgramParameter(prog,gl.LINK_STATUS)){
  document.getElementById("sub").textContent="WebGL "+(gl.getProgramInfoLog(prog)||gl.getShaderInfoLog(_fs)||"fail");
}
gl.useProgram(prog);
const aP=gl.getAttribLocation(prog,"aP"),aN=gl.getAttribLocation(prog,"aN");
const uMVP=gl.getUniformLocation(prog,"uMVP"),uN=gl.getUniformLocation(prog,"uN");
const uM=gl.getUniformLocation(prog,"uM"),uEye=gl.getUniformLocation(prog,"uEye");
const uC=gl.getUniformLocation(prog,"uC"),uA=gl.getUniformLocation(prog,"uA");
const uMetal=gl.getUniformLocation(prog,"uMetal"),uRough=gl.getUniformLocation(prog,"uRough");
const KMET={}; META.kinds.forEach(k=>KMET[k.kind]=k.metal||0);
const KRU={}; META.kinds.forEach(k=>KRU[k.kind]=k.rough==null?.45:k.rough);
const vbo=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,vbo);
gl.bufferData(gl.ARRAY_BUFFER,F32,gl.STATIC_DRAW);
gl.enableVertexAttribArray(aP);gl.enableVertexAttribArray(aN);

const bb=META.bbox, ctr=[(bb[0]+bb[3])/2,(bb[1]+bb[4])/2,(bb[2]+bb[5])/2];
const rad=Math.max(bb[3]-bb[0],bb[4]-bb[1],bb[5]-bb[2])/2;
let th=0.85, ph=1.12, dist=rad*3.6, tgt=ctr.slice(), spin=false, wire=false;
const kindOn={}; META.kinds.forEach(k=>kindOn[k.kind]=true);
const KCOL={}; META.kinds.forEach(k=>KCOL[k.kind]=k.color.map(x=>x/255));

function eye(){
  const e=[tgt[0]+dist*Math.sin(ph)*Math.cos(th), tgt[1]+dist*Math.sin(ph)*Math.sin(th), tgt[2]+dist*Math.cos(ph)];
  return e;
}
function mvpOf(model){
  const e=eye(); const V=lookAt(e,tgt,[0,0,1]);
  const P=persp(Math.PI/4, canvas.width/canvas.height, 2, dist*20);
  return mMul(P, mMul(V, model||mI()));
}
function nrmOf(m){return [m[0],m[1],m[2], m[4],m[5],m[6], m[8],m[9],m[10]];}

function draw(){
  const dpr=window.devicePixelRatio||1;
  const w=canvas.clientWidth,h=canvas.clientHeight;
  if(canvas.width!==w*dpr||canvas.height!==h*dpr){canvas.width=w*dpr;canvas.height=h*dpr;gl.viewport(0,0,canvas.width,canvas.height);}
  gl.enable(gl.DEPTH_TEST); gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  gl.clearColor(0.043,0.11,0.173,1); gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
  gl.bindBuffer(gl.ARRAY_BUFFER,vbo);
  gl.vertexAttribPointer(aP,3,gl.FLOAT,false,24,0);
  gl.vertexAttribPointer(aN,3,gl.FLOAT,false,24,12);
  gl.polygonOffset(1,1);
  if(wire) gl.enable(gl.POLYGON_OFFSET_FILL);
  fk();
  function pass(transparent){
    META.parts.forEach(p=>{
      if(!kindOn[p.kind]) return;
      const a=p.alpha||1;
      if(transparent!==(a<0.99)) return;
      const model=(p.link && LIDX[p.link]!==undefined)?M[LIDX[p.link]]:mI();
      gl.uniformMatrix4fv(uMVP,false,mvpOf(model));
      gl.uniformMatrix4fv(uM,false,model);
      gl.uniformMatrix3fv(uN,false,nrmOf(model));
      const epos=eye(); gl.uniform3f(uEye,epos[0],epos[1],epos[2]);
      const c=KCOL[p.kind]; gl.uniform3f(uC,c[0],c[1],c[2]); gl.uniform1f(uA,a);
      gl.uniform1f(uMetal,KMET[p.kind]||0); gl.uniform1f(uRough,KRU[p.kind]||.45);
      gl.drawArrays(gl.TRIANGLES, p.v0, p.vn);
    });
  }
  gl.depthMask(true); pass(false);
  gl.depthMask(false); pass(true); gl.depthMask(true);
  if(wire){
    gl.disable(gl.POLYGON_OFFSET_FILL);
    gl.enable(gl.BLEND);
    META.parts.forEach(p=>{
      if(!kindOn[p.kind]) return;
      const model=(p.link && LIDX[p.link]!==undefined)?M[LIDX[p.link]]:mI();
      gl.uniformMatrix4fv(uMVP,false,mvpOf(model));
      gl.uniformMatrix3fv(uN,false,nrmOf(model));
      gl.uniform3f(uC,.85,.9,1); gl.uniform1f(uA,.35);
      gl.drawArrays(gl.LINE_LOOP, p.v0, p.vn);
    });
  }
  document.getElementById("sub").textContent=META.nTri+" 三角面 · 20 DOF · 左键转";
}

let drag=null,lx=0,ly=0;
canvas.addEventListener("pointerdown",e=>{drag=e.button;lx=e.clientX;ly=e.clientY;canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener("pointerup",()=>drag=null);
canvas.addEventListener("pointermove",e=>{
  if(drag===null) return;
  const dx=e.clientX-lx, dy=e.clientY-ly; lx=e.clientX; ly=e.clientY;
  if(drag===2||e.shiftKey){ tgt[0]-=dx*dist*0.0015; tgt[2]+=dy*dist*0.0015; }
  else { th+=dx*0.008; ph=Math.min(Math.max(ph-dy*0.008,0.12),Math.PI-0.12); }
});
canvas.addEventListener("contextmenu",e=>e.preventDefault());
canvas.addEventListener("wheel",e=>{e.preventDefault(); dist*=e.deltaY>0?1.08:0.92; dist=Math.min(Math.max(dist,rad*0.6),rad*12);},{passive:false});

const PRE={
  "零位": new Array(NJ).fill(0),
  "稍蹲": (function(){const a=new Array(NJ).fill(0); META.joints.forEach((j,i)=>{
    if(j.name.indexOf("knee")>=0) a[i]=35; if(j.name.indexOf("hip_pitch")>=0) a[i]=-18;
    if(j.name.indexOf("ankle")>=0) a[i]=-16; if(j.name==="trunk_pitch") a[i]=8;}); return a;})(),
  "挥手": (function(){const a=new Array(NJ).fill(0); META.joints.forEach((j,i)=>{
    if(j.name==="left_shoulder_pitch") a[i]=-70; if(j.name==="left_elbow_pitch") a[i]=-50;
    if(j.name==="head_yaw") a[i]=18;}); return a;})(),
  "抬腿": (function(){const a=new Array(NJ).fill(0); META.joints.forEach((j,i)=>{
    if(j.name==="left_hip_pitch") a[i]=-45; if(j.name==="left_knee_pitch") a[i]=70;
    if(j.name==="trunk_roll") a[i]=6;}); return a;})()
};
const pbox=document.getElementById("presets");
Object.keys(PRE).forEach(name=>{
  const b=document.createElement("button"); b.textContent=name;
  b.onclick=()=>{PRE[name].forEach((v,i)=>{ANG[i]=v; const el=document.getElementById("j"+i); if(el){el.value=v; document.getElementById("v"+i).textContent=Math.round(v)+"°";}});};
  pbox.appendChild(b);
});
const sl=document.getElementById("sliders");
META.joints.forEach((j,i)=>{
  const row=document.createElement("div"); row.className="jrow";
  row.innerHTML='<span class="n" title="'+j.name+'">'+j.name.replace("left_","L ").replace("right_","R ")+'</span>'+
    '<input id="j'+i+'" type="range" min="'+j.limit_deg[0]+'" max="'+j.limit_deg[1]+'" step="1" value="0">'+
    '<span class="v" id="v'+i+'">0°</span>';
  sl.appendChild(row);
  row.querySelector("input").oninput=e=>{ANG[i]=+e.target.value; document.getElementById("v"+i).textContent=Math.round(ANG[i])+"°";};
});
document.getElementById("zero").onclick=()=>{for(let i=0;i<NJ;i++){ANG[i]=0; const el=document.getElementById("j"+i); if(el){el.value=0; document.getElementById("v"+i).textContent="0°";}}};
const kb=document.getElementById("kinds");
META.kinds.forEach(k=>{
  const lab=document.createElement("label");
  lab.innerHTML='<span class="sw" style="background:rgb('+k.color.join(',')+')"></span><input type="checkbox" checked> '+k.label;
  lab.querySelector("input").onchange=e=>{kindOn[k.kind]=e.target.checked;};
  kb.appendChild(lab);
});
document.getElementById("reset").onclick=()=>{th=0.85;ph=1.12;dist=rad*3.6;tgt=ctr.slice();};
document.getElementById("wire").onclick=()=>{wire=!wire;};
document.getElementById("spin").onclick=()=>{spin=!spin;};
addEventListener("keydown",e=>{
  if(e.key===" ") {spin=!spin; e.preventDefault();}
  if(e.key==="w"||e.key==="W") wire=!wire;
  if(e.key==="0") document.getElementById("zero").click();
  if(e.key==="r"||e.key==="R") document.getElementById("reset").click();
});

function loop(){ if(spin) th+=0.004; draw(); requestAnimationFrame(loop); }
fk(); loop();
document.body.dataset.previewReady="true";
})().catch(error=>{document.body.dataset.previewError=error.message;document.getElementById("sub").textContent="模型加载失败："+error.message;console.error(error);});
</script>
</body></html>
"""


def write_html(path: Path, payload=None) -> Dict[str, int]:
    if payload is None:
        raise ValueError("Explicit canonical CAD payload required; use v2.generate")
    payload = dict(payload)
    buf = array('f')
    packed = []
    for p in payload["parts"]:
        v0 = len(buf) // 6
        vn = len(p["verts"]) // 6
        buf.extend(p["verts"])
        packed.append({k: p[k] for k in ("name", "link", "kind", "alpha")})
        packed[-1]["v0"] = v0
        packed[-1]["vn"] = vn
    payload["parts"] = packed
    if sys.byteorder!='little':buf.byteswap()
    raw = buf.tobytes()
    b64 = base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode("ascii")
    payload["geometryBytes"] = len(raw)
    meta = json.dumps(
        {k: payload[k] for k in ("title", "root", "root_xyz", "links", "joints", "fkOrder", "parts", "kinds", "bbox", "nTri", "geometryBytes")},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    html = HTML.replace("__META__", meta.replace("<", "\\u003c")).replace("__B64__", b64)
    if len(html.encode("utf-8")) >= 100_000_000:
        raise ValueError("Compressed standalone HTML exceeds 100 MB; do not publish incomplete geometry")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return {"bytes": path.stat().st_size, "tris": payload["nTri"], "parts": len(packed)}
