#!/usr/bin/env bash
# A.T.R.I. CAD 全链一键构建：零件 → 装配 → 渲染/图纸 → 交互预览（+ 自检截图）
#
# 用法：bash design/cad/build.sh [--fast]
#   --fast  跳过渲染/图纸（只出 STEP/STL/质量报告与预览），改参数时反复跑用这个
#
# 纪律：产物一律重新生成，不手改 out/ 里任何文件。
set -euo pipefail

cd "$(dirname "$0")/../.."          # → 仓库根
PY=".venv-cad/bin/python"
FAST=0
[ "${1:-}" = "--fast" ] && FAST=1

if [ ! -x "$PY" ]; then
  echo "找不到 $PY —— 先建 CAD 环境："
  echo "  python3 -m venv .venv-cad && .venv-cad/bin/pip install -r design/cad/requirements.txt"
  exit 3
fi

echo "== 0/5 环境冒烟 =="
$PY -c "import cadquery as cq; from cadquery import vis; \
print('cadquery', cq.__version__, '/ cq.vis', callable(vis.show))"

echo "== 1/5 零件：STEP / STL / 质量审计 =="
$PY design/cad/build_all.py --all

echo "== 2/5 整机装配：ATRI-assembly.step =="
$PY design/cad/assembly.py --all

if [ "$FAST" -eq 0 ]; then
  echo "== 3/5 渲染图 + 工程图 =="
  $PY design/cad/render3d.py --all
else
  echo "== 3/5 渲染图（--fast 跳过）=="
fi

echo "== 4/5 交互预览：自包含 HTML + GLB =="
$PY design/cad/preview.py --all

echo "== 5/5 离屏自检出图（VTK，无 GUI）=="
$PY design/cad/view.py --assembly --edges \
  --screenshot design/cad/out/view/ATRI-整机等轴测.png

echo
echo "全部完成。产物："
echo "  design/cad/out/report.md                     质量审计与零件表"
echo "  design/cad/out/step/ATRI-assembly.step       整机装配（进 SolidWorks）"
echo "  design/cad/out/renders/                      渲染图（SVG+PNG）"
echo "  design/cad/out/drawings/                     工程图（HLR 三视图 + 零件图）"
echo "  design/cad/out/preview/ATRI-preview.html     零安装交互预览（浏览器打开）"
echo "  design/cad/out/view/ATRI-整机等轴测.png      离屏自检图"
