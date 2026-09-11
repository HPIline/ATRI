"""把厂商 PDF（规格书/图纸）逐页转成 PNG 并抽出文字。

用途：厂商 PDF 往往只有第 1 页能被 `sips` 转图；本脚本用 pypdfium2 渲染全部页面，
再用 pypdf 抽文字，便于**逐页目视核验官方图纸数值**。

    .venv-cad/bin/python design/cad/read_vendor_pdf.py <file.pdf> [--out DIR] [--scale 2.0]
"""
from __future__ import annotations

import sys
from pathlib import Path

import pypdf
import pypdfium2 as pdfium


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = Path(argv[1])
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else \
        Path(__file__).parent / "out" / "vendor_pdf"
    scale = float(argv[argv.index("--scale") + 1]) if "--scale" in argv else 2.0
    out.mkdir(parents=True, exist_ok=True)

    doc = pdfium.PdfDocument(str(src))
    print(f"# {src.name}: {len(doc)} 页")
    for i in range(len(doc)):
        page = doc[i]
        img = page.render(scale=scale).to_pil()
        dst = out / f"{src.stem}_p{i + 1}.png"
        img.save(dst)
        print(f"✓ {dst}  ({img.width}×{img.height})")

    print("\n" + "=" * 70 + "\n## 文字\n")
    reader = pypdf.PdfReader(str(src))
    for i, page in enumerate(reader.pages):
        txt = (page.extract_text() or "").strip()
        print(f"\n----- 第 {i + 1} 页 -----\n{txt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
