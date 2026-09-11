#!/usr/bin/env bash
# 构建 → 导出 PDF → 栅格化校验
# Linux 优先：soffice / libreoffice；macOS 可退回 PowerPoint。
# 用法： bash ppt/build.sh [脚本] [产物名]
# 例：   bash ppt/build.sh ppt/build_deck.py ATRI-答辩PPT-v4
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ -x "$ROOT/.venv-ppt/bin/python" ]]; then
  PY="$ROOT/.venv-ppt/bin/python"
else
  PY="${PYTHON:-python3}"
fi
SCRIPT="${1:-ppt/build_deck.py}"
NAME="${2:-$(basename "$SCRIPT" .py)}"
PPTX="$ROOT/ppt/out/$NAME.pptx"
PDF="$ROOT/ppt/out/$NAME.pdf"

cd "$ROOT"
mkdir -p "$ROOT/ppt/out"

echo "── 1/3 生成 PPTX ─────────────────────────────"
"$PY" "$SCRIPT" "$NAME"

export_pdf() {
  rm -f "$PDF"
  local so=""
  if command -v soffice >/dev/null 2>&1; then
    so="$(command -v soffice)"
  elif command -v libreoffice >/dev/null 2>&1; then
    so="$(command -v libreoffice)"
  fi
  if [[ -n "$so" ]]; then
    "$so" --headless --convert-to pdf --outdir "$ROOT/ppt/out" "$PPTX"
    return 0
  fi
  if command -v osascript >/dev/null 2>&1 && [[ -f "$ROOT/ppt/export_pdf.applescript" ]]; then
    osascript -e 'tell application "Microsoft PowerPoint" to close every presentation saving no' \
      >/dev/null 2>&1 || true
    sleep 1
    rm -f "$ROOT/ppt/out/~\$"*.pptx
    osascript "$ROOT/ppt/export_pdf.applescript" "$PPTX" "$PDF"
    return 0
  fi
  echo "!! 未找到 soffice / LibreOffice / PowerPoint，跳过 PDF"
  return 1
}

echo "── 2/3 导出 PDF ──────────────────────────────"
if export_pdf && [[ -f "$PDF" ]]; then
  echo "── 3/3 栅格化 ────────────────────────────────"
  if "$PY" -c "import pymupdf" >/dev/null 2>&1; then
    "$PY" - "$PDF" "$ROOT/ppt/out/pdf" <<'PYEOF'
import sys, pymupdf
doc = pymupdf.open(sys.argv[1])
for i, page in enumerate(doc):
    pix = page.get_pixmap(dpi=150)
    pix.save(f"{sys.argv[2]}_p{i+1:02d}.png")
print(f"  {doc.page_count} 页 -> {sys.argv[2]}_pNN.png")
PYEOF
  else
    echo "未安装 pymupdf，跳过栅格化"
  fi
  echo "完成：$PDF"
else
  echo "完成：$PPTX（无 PDF）"
fi
