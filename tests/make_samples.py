"""Generates a stress-test corpus in tests/samples (images, md with every feature, csv, ipynb, ...)."""
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).parent / "samples"


def png(path: Path, w: int, h: int, rgb: tuple[int, int, int]) -> None:
    """Minimal valid PNG with a gradient, no Pillow needed."""
    rows = b""
    for y in range(h):
        row = b"".join(bytes((min(255, rgb[0] + x * 80 // w), min(255, rgb[1] + y * 80 // h), rgb[2])) for x in range(w))
        rows += b"\x00" + row
    def chunk(t: bytes, d: bytes) -> bytes:
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    path.write_bytes(data)


MD = r"""---
title: Stress Test Document
author: QuickMorph
---

# Stress Test Document

Plain paragraph with **bold**, *italic*, ~~strike~~, `inline code`, a [link](https://example.com) and a bare URL https://example.org/page.
Unicode: café ünïcödé — 日本語 — Привет — emoji 🚀✅

## Local images (relative paths, spaces, subfolder)

![Relative image](images/pic one.png)

![Parent-relative](./images/wide.png)

Obsidian embed: ![[obsidian_pic.png|200]]

## Table (wide)

| Id | Name | Description | Col D | Col E | Col F | Col G | Col H | Notes |
|----|------|-------------|-------|-------|-------|-------|-------|-------|
| 1 | Alpha | A very long description that must wrap rather than run off the right edge of the page margin | d | e | f | g | h | LONG_TABLE_CELL_SENTINEL |
| 2 | Beta | short | d | e | f | g | h | ok |

## Code

```python
def fibonacci(n: int) -> int:
    # a very long line that must wrap and never be clipped by the page: ........................................................................................ END_OF_LONG_LINE
    return n if n < 2 else fibonacci(n - 1) + fibonacci(n - 2)
```

```
no language block
```

## Alerts, tasks, footnotes

> [!NOTE]
> This is a GitHub alert about ALERT_SENTINEL.

> [!WARNING]
> Careful here.

- [x] done task
- [ ] open task
  - nested item

Footnote reference[^1].

[^1]: FOOTNOTE_SENTINEL text.

<details>
<summary>Collapsed section</summary>

HIDDEN_DETAILS_SENTINEL should still appear in the PDF.

</details>

## Math

Inline $E = mc^2$ and currency $5 and $10 stay literal.

$$
\int_0^\infty e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}
$$

## Mermaid

```mermaid
graph TD
    A[Right click] --> B{QuickMorph}
    B --> C[PDF]
    B --> D[DOCX]
```

## Definition list

Term
: DEFLIST_SENTINEL definition

---

END_OF_DOCUMENT_SENTINEL
"""


def main() -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "images").mkdir(exist_ok=True)
    png(OUT / "images" / "pic one.png", 320, 180, (40, 90, 200))
    png(OUT / "images" / "wide.png", 2400, 400, (200, 60, 60))   # far wider than the page
    png(OUT / "obsidian_pic.png", 160, 160, (30, 160, 80))
    (OUT / "stress.md").write_text(MD, encoding="utf-8")

    (OUT / "wide.csv").write_text(
        "id,name,a,b,c,d,e,f,g,h,i,CSV_SENTINEL\n" + "\n".join(f"{i},name{i},1,2,3,4,5,6,7,8,9,x{i}" for i in range(1, 80)),
        encoding="utf-8")
    (OUT / "data.json").write_text(json.dumps({"name": "x", "items": [1, 2, {"deep": "JSON_SENTINEL"}]}), encoding="utf-8")
    (OUT / "script.py").write_text("import os\n\ndef main():\n    print('PY_SENTINEL')\n", encoding="utf-8")
    (OUT / "notes.txt").write_text("Plain text file\nline two TXT_SENTINEL\n" + "word " * 400, encoding="utf-8")
    (OUT / "utf16.txt").write_text("UTF16_SENTINEL ünï", encoding="utf-16")
    (OUT / "legacy.txt").write_bytes("CP1252_SENTINEL caf\xe9".encode("cp1252"))
    (OUT / "page.html").write_text(
        '<html><body><h1>HTML Page</h1><p>HTML_SENTINEL</p><img src="images/pic one.png"></body></html>', encoding="utf-8")
    (OUT / "doc.rst").write_text("RST Title\n=========\n\nParagraph RST_SENTINEL.\n\n* item one\n* item two\n", encoding="utf-8")

    png_b64 = __import__("base64").b64encode((OUT / "obsidian_pic.png").read_bytes()).decode()
    nb = {"nbformat": 4, "nbformat_minor": 5,
          "metadata": {"kernelspec": {"language": "python", "name": "python3"}, "language_info": {"name": "python"}},
          "cells": [
              {"cell_type": "markdown", "metadata": {}, "source": ["# Notebook\n", "NB_MD_SENTINEL $x^2$"]},
              {"cell_type": "code", "execution_count": 1, "metadata": {}, "source": ["print('hi')\n", "1+1"],
               "outputs": [{"output_type": "stream", "name": "stdout", "text": ["NB_STREAM_SENTINEL\n"]},
                           {"output_type": "display_data", "data": {"image/png": png_b64, "text/plain": "<img>"}, "metadata": {}}]},
              {"cell_type": "code", "execution_count": 2, "metadata": {}, "source": ["1/0"],
               "outputs": [{"output_type": "error", "ename": "ZeroDivisionError", "evalue": "x",
                            "traceback": ["\u001b[31mZeroDivisionError\u001b[0m: NB_ERR_SENTINEL"]}]}]}
    (OUT / "book.ipynb").write_text(json.dumps(nb), encoding="utf-8")

    try:  # real .docx with heading, table and picture
        import docx  # python-docx (dev only)
        d = docx.Document()
        d.add_heading("Word Document", 1)
        d.add_paragraph("DOCX_SENTINEL paragraph with text.")
        t = d.add_table(rows=2, cols=2)
        t.cell(0, 0).text, t.cell(1, 1).text = "H1", "DOCX_TABLE_SENTINEL"
        d.add_picture(str(OUT / "obsidian_pic.png"))
        d.save(OUT / "word.docx")
    except ImportError:
        pass
    print("samples ready:", OUT)


if __name__ == "__main__":
    main()
