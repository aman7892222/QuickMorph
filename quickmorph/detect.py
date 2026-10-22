"""File-type detection: decides which rendering pipeline a file goes through."""
from __future__ import annotations

from pathlib import Path

MARKDOWN = {".md", ".markdown", ".mdown", ".mkd", ".mdx"}
RST = {".rst"}
HTML = {".html", ".htm", ".xhtml"}
NOTEBOOK = {".ipynb"}
DOCX = {".docx"}
CSV = {".csv", ".tsv"}
IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
# need Pandoc as a reader (no good pure-python reader exists)
PANDOC_READ = {".odt": "odt", ".rtf": "rtf", ".epub": "epub", ".org": "org", ".tex": "latex"}
TEXT = {".txt", ".log", ".text", ".nfo", ".ini", ".cfg", ".conf", ".env", ".properties"}
CODE = {
    ".json", ".jsonc", ".yaml", ".yml", ".toml", ".xml", ".py", ".pyw", ".js", ".mjs", ".ts", ".tsx",
    ".jsx", ".rs", ".go", ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".java", ".kt", ".swift", ".rb",
    ".php", ".sh", ".bash", ".bat", ".cmd", ".ps1", ".sql", ".css", ".scss", ".lua", ".r", ".m",
    ".dart", ".vue", ".svelte", ".tf", ".gradle", ".dockerfile", ".makefile", ".cmake", ".adoc",
    ".typ", ".tex",
}



def ext_of(path: Path) -> str:
    return (path.suffix or path.name).lower()


def all_extensions() -> list[str]:
    """Every extension that gets a right-click menu."""
    s = (MARKDOWN | RST | HTML | NOTEBOOK | DOCX | CSV | IMAGE | TEXT | CODE | set(PANDOC_READ))
    return sorted(s)


def category(path: Path) -> str:
    """markdown | rst | html | notebook | docx | csv | image | pandoc | text | code | (raises for binary)."""
    ext = ext_of(path)
    if ext in MARKDOWN:
        return "markdown"
    if ext in RST:
        return "rst"
    if ext in HTML:
        return "html"
    if ext in NOTEBOOK:
        return "notebook"
    if ext in DOCX:
        return "docx"
    if ext in CSV:
        return "csv"
    if ext in IMAGE:
        return "image"
    if ext in PANDOC_READ:
        return "pandoc"
    if ext in TEXT:
        return "text"
    if ext in CODE:
        return "code"
    # unknown extension: accept it if it looks like text
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
    except OSError as e:
        raise ValueError(f"Cannot read file: {e}") from e
    if b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise ValueError(f"'{path.name}' looks like a binary file - not supported.")
    return "text"


def read_text(path: Path) -> str:
    """Read any text file robustly (BOMs, UTF-16, legacy Windows encodings) without losing characters."""
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")
