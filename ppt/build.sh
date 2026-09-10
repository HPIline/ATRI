#!/usr/bin/env bash
# 构建 → 导出 PDF（PowerPoint）→ 栅格化校验
# 用法： bash ppt/build.sh ppt/build_sample.py
set -euo pipefail

ROOT="/Users/hpi/Documents/搞机器人"
PY="$ROOT/.venv-ppt/bin/python"
SCRIPT="${1:-ppt/build_sample.py}"
NAME="${2:-$(basename "$SCRIPT" .py)}"
PPTX="$ROOT/ppt/out/$NAME.pptx"
PDF="$ROOT/ppt/out/$NAME.pdf"

cd "$ROOT"

echo "── 1/4 生成 PPTX ─────────────────────────────"
"$PY" "$SCRIPT" "$NAME"

echo "── 2/4 释放 PowerPoint 中可能残留的旧文档 ────"
osascript -e 'tell application "Microsoft PowerPoint" to close every presentation saving no' \
  >/dev/null 2>&1 || true
sleep 1
rm -f "$ROOT/ppt/out/~\$"*.pptx "$PDF"

echo "── 3/4 导出 PDF ──────────────────────────────"
osascript "$ROOT/ppt/export_pdf.applescript" "$PPTX" "$PDF"
# 防止 PowerPoint 从内存里导出旧版本：PDF 必须比 PPTX 新
[ "$PDF" -nt "$PPTX" ] || { echo "!! PDF 比 PPTX 旧，导出无效"; exit 1; }

echo "── 4/4 栅格化 ────────────────────────────────"
"$PY" - "$PDF" "$ROOT/ppt/out/pdf" <<'PYEOF'
import sys, pymupdf
doc = pymupdf.open(sys.argv[1])
for i, page in enumerate(doc):
    pix = page.get_pixmap(dpi=150)
    pix.save(f"{sys.argv[2]}_p{i+1:02d}.png")
print(f"  {doc.page_count} 页 -> {sys.argv[2]}_pNN.png")
PYEOF
echo "完成：$PDF"
