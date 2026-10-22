"""End-to-end tests: convert real files and verify nothing was lost - and nothing unsafe happened.

    python -m pytest tests -q          (needs: pip install -r requirements.txt -r requirements-dev.txt)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = Path(__file__).parent / "samples"
sys.path.insert(0, str(ROOT))
os.environ["QUICKMORPH_NOUI"] = "1"
os.environ.setdefault("QUICKMORPH_HOME", str(Path(tempfile.gettempdir()) / "quickmorph-test-home"))

import pytest  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from quickmorph import render  # noqa: E402
from quickmorph.cli import process  # noqa: E402
from quickmorph.env import find_pandoc  # noqa: E402

EXPECT = {  # file -> strings that MUST survive into the PDF text layer
    "stress.md": ["Stress Test Document", "LONG_TABLE_CELL_SENTINEL", "END_OF_LONG_LINE", "ALERT_SENTINEL",
                  "FOOTNOTE_SENTINEL", "HIDDEN_DETAILS_SENTINEL", "DEFLIST_SENTINEL", "END_OF_DOCUMENT_SENTINEL",
                  "café", "日本語", "Привет", "Right click", "QuickMorph"],   # last two = mermaid labels
    "wide.csv": ["CSV_SENTINEL", "name1", "name79", "x79"],
    "data.json": ["JSON_SENTINEL"],
    "script.py": ["PY_SENTINEL"],
    "notes.txt": ["TXT_SENTINEL"],
    "utf16.txt": ["UTF16_SENTINEL", "ünï"],
    "legacy.txt": ["CP1252_SENTINEL", "café"],
    "page.html": ["HTML_SENTINEL"],
    "doc.rst": ["RST Title", "RST_SENTINEL", "item two"],
    "book.ipynb": ["NB_MD_SENTINEL", "NB_STREAM_SENTINEL", "NB_ERR_SENTINEL"],
    "word.docx": ["Word Document", "DOCX_SENTINEL", "DOCX_TABLE_SENTINEL"],
    "obsidian_pic.png": [],
}
ABSENT = {"stress.md": ["-->", r"\int_0"]}  # raw Mermaid / TeX source must be gone = they really rendered
MIN_IMAGES = {"stress.md": 3, "book.ipynb": 1, "word.docx": 1, "page.html": 1, "obsidian_pic.png": 1}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _text(pdf: Path) -> str:
    return _norm("".join(p.extract_text() or "" for p in PdfReader(pdf).pages))


@pytest.fixture(scope="session", autouse=True)
def samples():
    subprocess.run([sys.executable, str(Path(__file__).parent / "make_samples.py")], check=True, capture_output=True)


@pytest.mark.parametrize("name", sorted(EXPECT))
def test_converts_without_loss(name):
    if name == "word.docx" and not (SAMPLES / name).exists():
        pytest.skip("python-docx not installed")
    out = process("save", SAMPLES / name)
    assert out.is_file() and out.stat().st_size > 1000
    text = _text(out)
    missing = [s for s in EXPECT[name] if _norm(s) not in text]
    assert not missing, f"lost content in {name}: {missing}\n--- extracted text (start) ---\n{text[:1500]}"
    leftover = [s for s in ABSENT.get(name, []) if _norm(s) in text]
    assert not leftover, f"{name}: not rendered: {leftover}"
    if name in MIN_IMAGES:
        n = sum(_count_images(p.get("/Resources")) for p in PdfReader(out).pages)
        assert n >= MIN_IMAGES[name], f"{name}: expected >= {MIN_IMAGES[name]} images, got {n}"


def _count_images(resources, depth: int = 0) -> int:
    """Image XObjects on a page, including those nested in Form XObjects (Firefox and WebKit nest them)."""
    n = 0
    for ref in ((resources or {}).get("/XObject") or {}).values():
        obj = ref.get_object()
        if obj.get("/Subtype") == "/Image":
            n += 1
        elif obj.get("/Subtype") == "/Form" and depth < 8:
            n += _count_images(obj.get("/Resources"), depth + 1)
    return n


def test_math_fonts_embedded_and_currency_kept():
    html = render.build(SAMPLES / "stress.md").html
    assert "katex.min.js" in html and "mermaid.min.js" in html
    assert "$5 and $10" in html.replace("&#36;", "$")  # currency not mistaken for math
    out = process("save", SAMPLES / "stress.md")
    fonts = {str(f.get_object().get("/BaseFont")) for p in PdfReader(out).pages
             for f in ((p.get("/Resources") or {}).get("/Font") or {}).values()}
    assert any("KaTeX" in f for f in fonts), fonts


def test_wide_csv_is_landscape():
    page = PdfReader(process("save", SAMPLES / "wide.csv")).pages[0]
    assert page.mediabox.width > page.mediabox.height


def test_view_writes_to_temp_not_source_dir():
    out = process("view", SAMPLES / "notes.txt", open_after=False)
    assert out.parent != SAMPLES and out.is_file()


def test_rejects_binary_and_pdf(tmp_path):
    b = tmp_path / "blob.bin"
    b.write_bytes(b"\x00\x01\x02" * 100)
    with pytest.raises(ValueError):
        process("save", b)
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4")
    with pytest.raises(ValueError):
        process("save", p)


# --------------------------------------------------------------------------- safety
def test_document_scripts_never_run(tmp_path):
    md = tmp_path / "evil.md"
    md.write_text("# Doc\n\nSAFE_TEXT_SENTINEL\n\n<script>document.write('SCRIPT_RAN_SENTINEL')</script>\n\n"
                  "<img src=\"missing.png\" onerror=\"document.body.insertAdjacentHTML('beforeend','ONERROR_SENTINEL')\">\n\n"
                  "Math still works: $x^2$\n", encoding="utf-8")
    text = _text(process("save", md))
    assert "SAFE_TEXT_SENTINEL" in text
    assert "SCRIPT_RAN_SENTINEL" not in text and "ONERROR_SENTINEL" not in text


def test_html_file_cannot_read_other_local_files(tmp_path):
    (tmp_path / "secret.txt").write_text("SECRET_SENTINEL", encoding="utf-8")
    page = tmp_path / "page.html"
    page.write_text("<html><body><p>PAGE_SENTINEL</p><script>"
                    "try{var x=new XMLHttpRequest();x.open('GET','secret.txt',false);x.send();"
                    "document.body.insertAdjacentHTML('beforeend','<p>'+x.responseText+'</p>')}catch(e){}"
                    "fetch('secret.txt').then(function(r){return r.text()}).then(function(t)"
                    "{document.body.insertAdjacentHTML('beforeend','<p>'+t+'</p>')}).catch(function(){});"
                    "</script></body></html>", encoding="utf-8")
    text = _text(process("save", page))
    assert "PAGE_SENTINEL" in text and "SECRET_SENTINEL" not in text


def test_never_overwrites_a_pdf_it_did_not_make(tmp_path):
    src = tmp_path / "report.md"
    src.write_text("# Report\n\nNEW_CONTENT\n", encoding="utf-8")
    mine = tmp_path / "report.pdf"
    mine.write_bytes(b"%PDF-1.4 the user's own precious PDF")
    out1 = process("save", src)
    assert mine.read_bytes() == b"%PDF-1.4 the user's own precious PDF"
    assert out1.name == "report (1).pdf"
    assert process("save", src) == out1  # our own earlier output is refreshed, not duplicated
    other = tmp_path / "report.txt"
    other.write_text("OTHER", encoding="utf-8")
    assert process("save", other).name == "report (2).pdf"  # same name, different source: kept apart


def test_huge_text_files_are_refused_quickly(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "MAX_TEXT_MB", 0.001)
    big = tmp_path / "big.log"
    big.write_text("x" * 5000, encoding="utf-8")
    with pytest.raises(ValueError, match="too large"):
        process("save", big)


def test_multi_select_queue_converts_everything(tmp_path):
    files = []
    for i in range(4):
        f = tmp_path / f"multi{i}.txt"
        f.write_text(f"QUEUE_SENTINEL_{i}", encoding="utf-8")
        files.append(f)
    env = {**os.environ, "QUICKMORPH_HOME": str(tmp_path / "home")}
    procs = [subprocess.Popen([sys.executable, "-m", "quickmorph", "--queue", "--action", "save", "--", str(f)],
                              cwd=ROOT, env=env) for f in files]
    for p in procs:
        p.wait(timeout=300)
    for i, f in enumerate(files):
        assert f"QUEUE_SENTINEL_{i}" in _text(f.with_suffix(".pdf"))
    assert not list((tmp_path / "home" / "queue").glob("*.job"))


@pytest.mark.skipif(not find_pandoc(), reason="pandoc not installed")
def test_pandoc_formats_are_sandboxed(tmp_path):
    (tmp_path / "secret.txt").write_text("PANDOCSECRETSENTINEL", encoding="utf-8")
    org = tmp_path / "notes.org"
    org.write_text('* Heading\n\nORGSENTINEL text\n\n#+INCLUDE: "secret.txt"\n', encoding="utf-8")  # x_y = subscript in Org
    try:
        text = _text(process("save", org))
    except RuntimeError:
        return  # refusing the include outright is fine too - what matters is that nothing leaks
    assert "ORGSENTINEL" in text and "PANDOCSECRETSENTINEL" not in text
    rtf = tmp_path / "letter.rtf"
    rtf.write_text(r"{\rtf1\ansi {\b RTF_SENTINEL} plain text\par}", encoding="ascii")
    assert "RTF_SENTINEL" in _text(process("save", rtf))


def test_installer_never_restarts_explorer_or_finder():
    src = (ROOT / "install.py").read_text(encoding="utf-8").lower()
    for bad in ("taskkill", "explorer.exe", "killall", "stop-process"):
        assert bad not in src, bad
    assert "shchangenotify" in src and "pbs" in src
