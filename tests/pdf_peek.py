"""Dev helper: render PDF pages to PNG to eyeball layout.   usage: python tests/pdf_peek.py file.pdf [outdir]

Needs:  pip install pypdfium2 pillow   (not part of the normal test requirements)
"""
import sys
from pathlib import Path

import pypdfium2 as pdfium

pdf = pdfium.PdfDocument(sys.argv[1])
out = Path(sys.argv[2] if len(sys.argv) > 2 else Path(sys.argv[1]).with_suffix("")).resolve()
out.mkdir(parents=True, exist_ok=True)
print("pages:", len(pdf))
for i, page in enumerate(pdf):
    w, h = page.get_size()
    print(f"  page {i+1}: {w:.0f}x{h:.0f}pt")
    bm = page.render(scale=1.1)
    bm.to_pil().save(out / f"p{i+1}.png")
print("images in", out)
