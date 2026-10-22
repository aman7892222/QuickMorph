"""Dev-time script: vendor KaTeX + Mermaid locally so PDFs render math/diagrams OFFLINE.

Usage:  python tools/fetch_vendor.py
Needs Node's `npm` (dev machine only; end users never need it).
Only the files actually required are kept (~6 MB total); they are loaded
by the HTML renderer ONLY when a document actually contains math/mermaid.
"""
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / "quickmorph" / "vendor"


def npm_pack(pkg: str, tmp: Path) -> Path:
    out = subprocess.run(
        ["npm", "pack", pkg, "--silent"], cwd=tmp, capture_output=True, text=True, shell=True, check=True
    ).stdout.strip().splitlines()[-1]
    dest = tmp / pkg
    dest.mkdir()
    with tarfile.open(tmp / out) as tf:
        if hasattr(tarfile, "data_filter"):
            tf.extractall(dest, filter="data")  # refuse absolute paths / ../ tricks in the tarball
        else:
            tf.extractall(dest)  # noqa: S202 - npm registry tarball, older Python
    return dest / "package"


def main() -> int:
    VENDOR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        katex = npm_pack("katex", tmp)
        (VENDOR / "katex" / "fonts").mkdir(parents=True, exist_ok=True)
        shutil.copy(katex / "dist" / "katex.min.js", VENDOR / "katex" / "katex.min.js")
        shutil.copy(katex / "dist" / "katex.min.css", VENDOR / "katex" / "katex.min.css")
        shutil.copy(katex / "LICENSE", VENDOR / "katex" / "LICENSE")
        for f in (katex / "dist" / "fonts").glob("*.woff2"):
            shutil.copy(f, VENDOR / "katex" / "fonts" / f.name)
        mermaid = npm_pack("mermaid", tmp)
        (VENDOR / "mermaid").mkdir(exist_ok=True)
        shutil.copy(mermaid / "dist" / "mermaid.min.js", VENDOR / "mermaid" / "mermaid.min.js")
        shutil.copy(mermaid / "LICENSE", VENDOR / "mermaid" / "LICENSE")
    total = sum(f.stat().st_size for f in VENDOR.rglob("*") if f.is_file())
    print(f"vendored OK: {total / 1e6:.1f} MB in {VENDOR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
