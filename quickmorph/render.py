"""Turn any supported file into a self-contained, print-ready HTML document."""
from __future__ import annotations

import csv
import glob
import html as _html
import io
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from markdown_it.token import Token

from . import detect
from .env import CREATE_NO_WINDOW, find_pandoc, paper_size

PKG = Path(__file__).resolve().parent
ASSETS = PKG / "assets"
VENDOR = PKG / "vendor"
esc = _html.escape
# Text-like files bigger than this would become thousands of pages and freeze a 4 GB laptop.
MAX_TEXT_MB = float(os.environ.get("QUICKMORPH_MAX_MB", 10))
HIGHLIGHT_MAX_CHARS = 400_000  # bigger source files are shown as plain text: same content, far faster


@dataclass
class Doc:
    html: str = ""            # complete HTML document (empty when `direct` is used)
    direct: Path | None = None  # print this HTML file as-is (original .html input)
    title: str = ""
    landscape: bool = False
    needs_js: bool = False    # math / mermaid present -> give the browser time to run scripts


# --------------------------------------------------------------------------- assets
_ASSET_RE = re.compile(r"""(<(?:img|source|video|audio|embed)\b[^>]*?\ssrc\s*=\s*)(["'])(.+?)\2""", re.I | re.S)
_WIN_ABS = re.compile(r"^[A-Za-z]:[\\/]")


def _local_path(url: str, base: Path) -> Path | None:
    url = url.strip()
    if _WIN_ABS.match(url):
        p = Path(url)
    else:
        parsed = urlparse(url)
        if parsed.scheme == "file":
            p = Path(url2pathname(parsed.path))
        elif parsed.scheme or url.startswith(("//", "#")):
            return None  # http(s), data:, mailto:, in-page anchor ...
        else:
            p = Path(unquote(url.split("#", 1)[0].split("?", 1)[0]))
            if not p.is_absolute():
                p = base / p
    return p if p.is_file() else None


def resolve_assets(html: str, base: Path) -> str:
    """Rewrite every local image to an absolute file:// URI so it resolves from the temp render folder.

    (Deliberately NOT using <base href>: that would break in-page #anchor links in the PDF.)
    """
    def fix(m: re.Match) -> str:
        p = _local_path(m.group(3), base)
        if p is None:
            return m.group(0)
        return f"{m.group(1)}{m.group(2)}{p.resolve().as_uri()}{m.group(2)}"

    return _ASSET_RE.sub(fix, html)


# --------------------------------------------------------------------------- code highlighting
_pyg_css: str | None = None


def pygments_css() -> str:
    global _pyg_css
    if _pyg_css is None:
        from pygments.formatters import HtmlFormatter
        _pyg_css = HtmlFormatter(style="default").get_style_defs(".highlight")
    return _pyg_css


def _lexer(name: str | None, filename: str | None = None, code: str = ""):
    from pygments.lexers import TextLexer, get_lexer_by_name, get_lexer_for_filename
    from pygments.util import ClassNotFound
    try:
        if name:
            return get_lexer_by_name(name)
        if filename:
            return get_lexer_for_filename(filename, code)
    except ClassNotFound:
        pass
    return TextLexer()


def highlight_block(code: str, lang: str) -> str:
    """For fenced blocks inside markdown: <pre> with token spans (or '' = let markdown-it escape it)."""
    if not lang:
        return ""
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import get_lexer_by_name
    from pygments.util import ClassNotFound
    try:
        lx = get_lexer_by_name(lang)
    except ClassNotFound:
        return ""
    body = highlight(code, lx, HtmlFormatter(nowrap=True))
    return f'<pre class="highlight"><code>{body}</code></pre>'


# --------------------------------------------------------------------------- markdown
_ALERT_RE = re.compile(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*(?:\n|$)", re.I)
_ALERT_ICON = {"note": "\u2139\ufe0f", "tip": "\U0001f4a1", "important": "\u2757", "warning": "\u26a0\ufe0f", "caution": "\U0001f6d1"}
_WIKI_RE = re.compile(r"(!?)\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")


def _alerts_rule(state) -> None:
    toks, i = state.tokens, 0
    while i < len(toks) - 2:
        t = toks[i]
        if t.type == "blockquote_open" and toks[i + 1].type == "paragraph_open" and toks[i + 2].type == "inline":
            inline = toks[i + 2]
            m = _ALERT_RE.match(inline.content)
            if m:
                kind = m.group(1).lower()
                t.attrSet("class", f"alert alert-{kind}")
                inline.content = inline.content[m.end():]
                inline.children = []
                if inline.content.strip():
                    state.md.inline.parse(inline.content, state.md, state.env, inline.children)
                title = Token("html_block", "", 0)
                title.content = f'<p class="alert-title">{_ALERT_ICON[kind]} {kind.capitalize()}</p>\n'
                toks.insert(i + 1, title)
                i += 1
        i += 1


def find_attachment(name: str, base: Path) -> Path | None:
    """Locate an Obsidian-style attachment: beside the note, else anywhere in the vault."""
    p = base / name
    if p.is_file():
        return p
    root = next((d for d in [base, *base.parents] if (d / ".obsidian").is_dir()), None)
    if root:
        return next(root.rglob(glob.escape(Path(name).name)), None)
    return None


def _wiki_rule(state) -> None:
    base: Path = state.env.get("dir") or Path(".")

    def text(content: str):
        t = Token("text", "", 0)
        t.content = content
        return t

    for blk in state.tokens:
        if blk.type != "inline" or not blk.children:
            continue
        out = []
        for ch in blk.children:
            if ch.type != "text" or "[[" not in ch.content:
                out.append(ch)
                continue
            pos = 0
            for m in _WIKI_RE.finditer(ch.content):
                if m.start() > pos:
                    out.append(text(ch.content[pos:m.start()]))
                pos = m.end()
                bang, target, alias = m.group(1), m.group(2).strip(), m.group(3)
                is_img = Path(target).suffix.lower() in detect.IMAGE
                if bang and is_img:
                    found = find_attachment(target, base)
                    img = Token("image", "img", 0)
                    img.attrSet("src", found.resolve().as_uri() if found else target)
                    img.content = target
                    img.children = [text(target)]
                    if alias and alias.strip().isdigit():
                        img.attrSet("width", alias.strip())
                    out.append(img)
                else:
                    out.append(text(alias if alias and not alias.strip().isdigit() else target))
            if pos < len(ch.content):
                out.append(text(ch.content[pos:]))
        blk.children = out


_md = None


def _markdown_it():
    global _md
    if _md is not None:
        return _md
    from markdown_it import MarkdownIt
    from mdit_py_plugins.anchors import anchors_plugin
    from mdit_py_plugins.deflist import deflist_plugin
    from mdit_py_plugins.dollarmath import dollarmath_plugin
    from mdit_py_plugins.footnote import footnote_plugin
    from mdit_py_plugins.front_matter import front_matter_plugin
    from mdit_py_plugins.tasklists import tasklists_plugin

    md = MarkdownIt("gfm-like", {"html": True, "highlight": lambda c, l, a: highlight_block(c, l)})
    md.use(front_matter_plugin).use(footnote_plugin).use(deflist_plugin).use(tasklists_plugin)
    md.use(dollarmath_plugin, allow_space=False, allow_digits=False)  # Pandoc rules: "$5 and $10" stays text
    md.use(anchors_plugin, max_level=6)
    md.core.ruler.push("gfm_alerts", _alerts_rule)
    md.core.ruler.push("wikilinks", _wiki_rule)

    default_fence = md.renderer.rules["fence"]

    def fence(tokens, idx, options, env):
        tok = tokens[idx]
        info = tok.info.strip().split()
        if info and info[0] == "mermaid":
            return f'<pre class="mermaid">{esc(tok.content)}</pre>\n'
        return default_fence(tokens, idx, options, env)

    def front_matter(tokens, idx, options, env):
        return f'<details class="frontmatter" open><summary>metadata</summary><pre>{esc(tokens[idx].content)}</pre></details>\n'

    md.renderer.rules["fence"] = fence
    md.renderer.rules["front_matter"] = front_matter
    _md = md
    return md


_SPACED_LINK = re.compile(r"(!?\[[^\]\n]*\]\()([^)<>\n]*\s[^)<>\n]*)\)")


def _fix_spaced_paths(text: str, base: Path) -> str:
    """`![x](my pic.png)` is invalid CommonMark but common in the wild: wrap in <> when that file exists."""
    def fix(m: re.Match) -> str:
        target = m.group(2).strip()
        if (base / unquote(target)).is_file():
            return f"{m.group(1)}<{target}>)"
        return m.group(0)
    return _SPACED_LINK.sub(fix, text)


def render_markdown(text: str, base: Path) -> str:
    return _markdown_it().render(_fix_spaced_paths(text, base), {"dir": base})


_CELL = re.compile(r"(<t[dh]\b[^>]*>)(.*?)(</t[dh]>)", re.S)
_LONG = re.compile(r"(?:&[#\w]+;|[^\s<>&])+")


def _soft_break_cells(html: str, n: int = 18) -> str:
    """Insert invisible <wbr> break points into very long tokens inside table cells only.

    Lets CSS use `overflow-wrap: break-word` (normal words never split into 'Na|me') while
    40-char IDs / URLs still wrap instead of pushing the table off the page.
    """
    def chunk(m: re.Match) -> str:
        w = m.group(0)
        if len(w) <= 24:
            return w
        atoms = re.findall(r"&[#\w]+;|.", w)
        return "<wbr>".join("".join(atoms[i:i + n]) for i in range(0, len(atoms), n))

    def cell(m: re.Match) -> str:
        parts = re.split(r"(<[^>]+>)", m.group(2))
        return m.group(1) + "".join(p if p.startswith("<") else _LONG.sub(chunk, p) for p in parts) + m.group(3)

    return _CELL.sub(cell, html)


# --------------------------------------------------------------------------- other categories
def _csv_html(text: str, ext: str) -> tuple[str, bool]:
    sample = text[:8192]
    if ext == ".tsv":
        delim = "\t"
    else:
        try:
            delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delim = ","
    csv.field_size_limit(1 << 30)
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delim))
    rows = [r for r in rows if r]
    if not rows:
        return "<p><em>(empty file)</em></p>", False
    ncol = max(len(r) for r in rows)
    pad = lambda r: r + [""] * (ncol - len(r))  # noqa: E731
    head, body = pad(rows[0]), [pad(r) for r in rows[1:]]
    cls = "csv dense" if ncol > 14 else "csv"
    out = [f'<div class="csv-meta">{len(body)} rows \u00d7 {ncol} columns</div>', f'<table class="{cls}"><thead><tr>']
    out += [f"<th>{esc(c)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for r in body:
        out.append("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out), ncol > 8


def _code_html(text: str, path: Path) -> str:
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    if path.suffix.lower() in (".json", ".jsonc"):
        try:
            text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except ValueError:
            pass  # JSON with comments etc. -> show as-is
    if len(text) > HIGHLIGHT_MAX_CHARS:
        return f'<div class="file-header">{esc(path.name)}</div><pre class="plain">{esc(text)}</pre>'
    lx = _lexer(None, path.name, text)
    body = highlight(text, lx, HtmlFormatter(linenos="inline", cssclass="highlight", wrapcode=True))
    return f'<div class="file-header">{esc(path.name)}</div>{body}'


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _join(v) -> str:
    return "".join(v) if isinstance(v, list) else (v or "")


def _notebook_html(text: str, base: Path) -> str:
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    nb = json.loads(text)
    if "cells" not in nb:
        raise ValueError("Only nbformat v4 notebooks are supported.")
    meta = nb.get("metadata", {})
    lang = (meta.get("language_info") or {}).get("name") or (meta.get("kernelspec") or {}).get("language") or "python"
    lx = _lexer(lang)
    parts: list[str] = []
    for cell in nb["cells"]:
        src = _join(cell.get("source"))
        kind = cell.get("cell_type")
        if kind == "markdown":
            for name, bundle in (cell.get("attachments") or {}).items():
                for mime, b64 in bundle.items():
                    src = src.replace(f"attachment:{name}", f"data:{mime};base64,{_join(b64).strip()}")
            parts.append(f'<div class="nb-cell">{render_markdown(src, base)}</div>')
        elif kind == "code":
            n = cell.get("execution_count")
            label = f'<div class="nb-label">In [{n if n is not None else " "}]:</div>'
            code = highlight(src, lx, HtmlFormatter(cssclass="highlight", wrapcode=True))
            parts.append(f'<div class="nb-cell">{label}<div class="nb-in">{code}</div>')
            for o in cell.get("outputs", []):
                parts.append(_nb_output(o))
            parts.append("</div>")
        elif src.strip():
            parts.append(f'<div class="nb-cell"><pre class="plain">{esc(src)}</pre></div>')
    return "\n".join(parts)


def _nb_output(o: dict) -> str:
    t = o.get("output_type")
    if t == "stream":
        return f'<div class="nb-out"><pre>{esc(_join(o.get("text")))}</pre></div>'
    if t == "error":
        tb = _ANSI.sub("", "\n".join(o.get("traceback") or []))
        return f'<div class="nb-out nb-err"><pre>{esc(tb)}</pre></div>'
    data = o.get("data") or {}
    for mime in ("image/png", "image/jpeg", "image/gif"):
        if mime in data:
            return f'<div class="nb-out"><img src="data:{mime};base64,{_join(data[mime]).strip()}"></div>'
    if "image/svg+xml" in data:
        return f'<div class="nb-out">{_join(data["image/svg+xml"])}</div>'
    if "text/html" in data:
        return f'<div class="nb-out">{_join(data["text/html"])}</div>'
    if "text/plain" in data:
        return f'<div class="nb-out"><pre>{esc(_join(data["text/plain"]))}</pre></div>'
    return ""


def _docx_html(path: Path) -> str:
    import mammoth
    with open(path, "rb") as f:
        return f'<div class="docx-body">{mammoth.convert_to_html(f).value}</div>'


def _rst_html(text: str) -> str:
    import docutils
    from docutils.core import publish_parts
    writer = {"writer": "html5"} if docutils.__version_info__ >= (0, 22) else {"writer_name": "html5"}
    return publish_parts(
        text, **writer,
        settings_overrides={"report_level": 5, "halt_level": 5, "file_insertion_enabled": False,
                            "_disable_config": True,  # never read a docutils.conf planted next to the file
                            "initial_header_level": 1, "syntax_highlight": "short"},
    )["html_body"]


def _pandoc_html(path: Path) -> str:
    pandoc = find_pandoc()
    if not pandoc:
        raise RuntimeError(
            f"'{path.suffix}' files need Pandoc, which is not installed.\n"
            "Run:  python install.py --with-pandoc"
        )
    fmt = detect.PANDOC_READ[path.suffix.lower()]
    # --sandbox: the document may only read itself, so an .org/.tex file can't pull other local files into the PDF
    cmd = [pandoc, "--sandbox", "-f", fmt, "-t", "html5", "--standalone", "--embed-resources", "--mathml",
           "--metadata", "pagetitle=doc", str(path)]
    r = subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError("Pandoc failed:\n" + r.stderr.decode("utf-8", "replace")[-800:])
    out = r.stdout.decode("utf-8", "replace")
    m = re.search(r"<body[^>]*>(.*)</body>", out, re.S | re.I)
    return m.group(1) if m else out


# --------------------------------------------------------------------------- assembly
_META_REFRESH = re.compile(r"""<meta\b[^>]*http-equiv\s*=\s*["']?\s*refresh[^>]*>""", re.I)

def _title_of(body: str, fallback: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S | re.I)
    if m:
        t = _html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
        if t:
            return t
    return fallback


def _head_scripts(body: str, nonce: str) -> tuple[str, str, bool]:
    """(head_html, tail_html, needs_js) - offline KaTeX / Mermaid, loaded ONLY when the document uses them."""
    head, tail, js = "", "", False
    if 'class="math ' in body:
        js = True
        css, src = (VENDOR / "katex" / "katex.min.css").as_uri(), (VENDOR / "katex" / "katex.min.js").as_uri()
        head += f'<link rel="stylesheet" href="{css}">'
        tail += (f'<script nonce="{nonce}" src="{src}"></script><script nonce="{nonce}">'
                 'document.querySelectorAll(".math").forEach(function(el)'
                 '{try{katex.render(el.textContent,el,{displayMode:el.classList.contains("block"),throwOnError:false})}'
                 'catch(e){}});</script>')
    if 'class="mermaid"' in body:
        js = True
        src = (VENDOR / "mermaid" / "mermaid.min.js").as_uri()
        tail += (f'<script nonce="{nonce}" src="{src}"></script><script nonce="{nonce}">mermaid.initialize('
                 '{startOnLoad:false,securityLevel:"strict",theme:"default"});</script>')
    if js:  # "#qm-ready" tells the Firefox/WebKit engines that math & diagrams are drawn
        tail += (f'<script nonce="{nonce}">(window.mermaid?mermaid.run():Promise.resolve()).catch(function(){{}})'
                 '.then(function(){location.hash="qm-ready"});</script>')
    return head, tail, js


def _csp(nonce: str) -> str:
    """Documents are untrusted: only OUR vendored scripts may run (no <script> or onerror=... from the file),
    and nothing can be fetched, framed or submitted. Images (local and web) and styles still render normally."""
    return ("default-src 'none'; img-src file: data: blob: https: http:; media-src file: data: https: http:; "
            "style-src 'unsafe-inline' file:; font-src file: data:; "
            f"script-src 'nonce-{nonce}'; base-uri 'none'; form-action 'none'")


def wrap(body: str, title: str, *, landscape: bool = False) -> Doc:
    nonce = os.urandom(12).hex()
    head, tail, js = _head_scripts(body, nonce)
    css = (ASSETS / "print.css").read_text(encoding="utf-8")
    if "highlight" in body:
        css += pygments_css()
    page = f"@page {{ size: {paper_size()} {'landscape' if landscape else 'portrait'}; }}"
    html = (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<meta http-equiv="Content-Security-Policy" content="{_csp(nonce)}"><title>{esc(title)}</title>'
            f"<style>{page}\n{css}</style>{head}</head><body><main>{body}</main>{tail}</body></html>")
    return Doc(html=html, title=title, landscape=landscape, needs_js=js)


def build(path: Path) -> Doc:
    """Any supported file -> print-ready HTML document (or the original .html file to print directly)."""
    path = Path(path).resolve()
    cat = detect.category(path)
    base = path.parent
    landscape = False
    if cat in ("markdown", "rst", "csv", "code", "text") and path.stat().st_size > MAX_TEXT_MB * 1e6:
        raise ValueError(f"'{path.name}' is {path.stat().st_size / 1e6:.0f} MB - too large to turn into a readable "
                         f"PDF (limit {MAX_TEXT_MB:g} MB; raise it with the environment variable QUICKMORPH_MAX_MB).")

    if cat == "html":
        return Doc(direct=path, title=path.stem)

    if cat == "markdown":
        body = render_markdown(detect.read_text(path), base)
    elif cat == "rst":
        body = _rst_html(detect.read_text(path))
    elif cat == "notebook":
        body = _notebook_html(detect.read_text(path), base)
    elif cat == "docx":
        body = _docx_html(path)
    elif cat == "csv":
        body, landscape = _csv_html(detect.read_text(path), path.suffix.lower())
    elif cat == "image":
        body = f'<div class="image-page"><img src="{path.as_uri()}"></div>'
    elif cat == "pandoc":
        if not find_pandoc() and path.suffix.lower() in (".tex", ".org"):
            body = _code_html(detect.read_text(path), path)  # readable source beats an error
        else:
            body = _pandoc_html(path)
    elif cat == "code":
        body = _code_html(detect.read_text(path), path)
    else:  # text / logs
        body = f'<pre class="plain">{esc(detect.read_text(path))}</pre>'

    body = resolve_assets(body, base)
    body = _soft_break_cells(body)
    body = re.sub(r"<details(?![^>]*\bopen\b)", "<details open", body)  # collapsed = hidden content in a PDF
    body = _META_REFRESH.sub("", body)  # a document must not send the renderer to another page
    return wrap(body, _title_of(body, path.stem), landscape=landscape)
