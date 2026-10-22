"""HTML -> PDF with a headless Chromium browser that is already installed (Edge ships with Windows).

Kept deliberately lean for low-end PCs: one short-lived browser per file with background services,
component extensions, the spare renderer and the separate GPU process switched off (~7 processes and
~275 MB peak instead of ~16 / ~450 MB), plus a reusable profile so nothing is re-initialised each time.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from . import __version__, render
from .env import (APP_DIR, CREATE_NO_WINDOW, MACOS, WINDOWS, find_browser, paper_inches, paper_size, try_lock,
                  unlock)

TIMEOUT = float(os.environ.get("QUICKMORPH_TIMEOUT", 120))
PROFILE = APP_DIR / "browser-profile"
FLAGS = [
    "--headless=new", "--disable-gpu", "--in-process-gpu", "--no-first-run", "--no-default-browser-check",
    "--disable-extensions", "--disable-component-extensions-with-background-pages", "--disable-sync",
    "--disable-background-networking", "--disable-component-update", "--disable-default-apps",
    "--disable-breakpad", "--disable-crash-reporter", "--no-service-autorun", "--metrics-recording-only",
    "--mute-audio", "--hide-scrollbars", "--incognito", "--password-store=basic", "--use-mock-keychain",
    "--disable-features=Translate,OptimizationHints,MediaRouter,AutofillServerCommunication,SpareRendererForSitePerProcess",
    "--no-pdf-header-footer", "--print-to-pdf-no-header", "--generate-pdf-document-outline",
]
NO_ENGINE = ("No browser engine was found to draw the PDF. Install any one of these free browsers: "
             "Microsoft Edge, Google Chrome, Brave, Chromium, Vivaldi or Firefox"
             + (" (on a Mac the built-in WebKit engine is used automatically)." if MACOS else ".")
             + " Or point the environment variable QUICKMORPH_BROWSER at a Chromium-based browser.")


def engines() -> list[tuple[str, str]]:
    """Usable engines, best first: Chromium (fastest, page numbers, bookmarks) -> WebKit (Mac) -> Firefox.

    Env QUICKMORPH_ENGINE=chromium|webkit|firefox forces one (handy for testing).
    """
    from . import fallback
    forced = os.environ.get("QUICKMORPH_ENGINE", "").strip().lower()
    found = []
    if forced in ("", "chromium") and (b := find_browser()):
        found.append(("chromium", b))
    if forced in ("", "webkit") and fallback.webkit_available():
        found.append(("webkit", fallback.OSASCRIPT))
    if forced in ("", "firefox") and (ff := fallback.find_firefox()):
        found.append(("firefox", ff))
    return found


def file_to_pdf(src: Path, out_pdf: Path) -> Path:
    """Render `src` into `out_pdf` (atomic, and never overwrites a PDF that QuickMorph did not make itself)."""
    available = engines()
    if not available:
        raise RuntimeError(NO_ENGINE)
    doc = render.build(src)

    work = Path(tempfile.mkdtemp(prefix="qm_", dir=_work_root()))
    try:
        tmp_pdf, errors = work / "out.pdf", []
        for name, exe in available:  # normally just one; a failing engine falls through to the next
            ok, err = _render(name, exe, doc, tmp_pdf, work)
            if ok:
                break
            errors.append(f"[{name}] {err.strip()[-400:]}")
        else:
            raise RuntimeError("The browser produced no PDF.\n" + "\n".join(errors))
        tag = source_tag(src)
        _stamp(tmp_pdf, tag)
        return _move_into_place(tmp_pdf, out_pdf, tag)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _work_root() -> str | None:
    """Scratch space inside QuickMorph's own folder (not /tmp, which sandboxed browsers such as snap Firefox can't
    read). Leftovers from a crash are swept after a day."""
    root = APP_DIR / "work"
    try:
        root.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - 86400
        for d in root.iterdir():
            if d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        return str(root)
    except OSError:
        return None


def _render(engine: str, exe: str, doc: render.Doc, pdf: Path, work: Path) -> tuple[bool, str]:
    wait = doc.needs_js or bool(doc.direct)
    if engine == "chromium":
        url = doc.direct.as_uri() if doc.direct else _write_page(doc.html, work)
        lock = try_lock(APP_DIR / "browser.lock")  # holder may use the warm profile; others get a throwaway one
        try:
            ok, err = _print(exe, url, pdf, PROFILE if lock else work / "profile", wait_for_js=wait, work=work)
            if not ok and lock:
                shutil.rmtree(PROFILE, ignore_errors=True)  # a damaged profile must never break the next run
            return ok, err
        finally:
            if lock:
                unlock(lock)

    from . import fallback
    if doc.direct:
        url = doc.direct.as_uri()
    else:  # these engines apply the page margin themselves
        html = doc.html.replace("</head>", "<style>@page { margin: 0 !important; }</style></head>", 1)
        if engine == "firefox":
            html = _inline_katex(html)
        url = _write_page(html, work)
    size = paper_inches(paper_size(), doc.landscape)
    if engine == "webkit":
        ok, err = fallback.webkit_print(url, pdf, size, wait, TIMEOUT)
    else:
        ok, err = fallback.firefox_print(exe, url, pdf, size, wait, TIMEOUT, work)
    return ok and _complete(pdf), err


def _inline_katex(html: str) -> str:
    """Firefox's file:// rules block web fonts from other folders, so embed KaTeX's CSS and woff2 fonts in the page
    (only for documents with math; ~300 KB)."""
    import base64
    css_file = render.VENDOR / "katex" / "katex.min.css"
    link = f'<link rel="stylesheet" href="{css_file.as_uri()}">'
    if link not in html:
        return html

    def font(m: re.Match) -> str:
        f = css_file.parent / "fonts" / m.group(1)
        return f"url(data:font/woff2;base64,{base64.b64encode(f.read_bytes()).decode()})" if f.is_file() else m.group(0)

    css = re.sub(r"url\(fonts/([\w-]+\.woff2)\)", font, css_file.read_text(encoding="utf-8"))
    css = re.sub(r',url\(fonts/[\w-]+\.(?:woff|ttf)\) format\("(?:woff|truetype)"\)', "", css)
    return html.replace(link, f"<style>{css}</style>", 1)


def _write_page(html: str, work: Path) -> str:
    page = work / "render.html"
    page.write_text(html, encoding="utf-8")
    return page.as_uri()


def _print(browser: str, url: str, pdf: Path, profile: Path, wait_for_js: bool, work: Path) -> tuple[bool, str]:
    cmd = [browser, *FLAGS, f"--user-data-dir={profile}", f"--print-to-pdf={pdf}"]
    if wait_for_js:
        cmd.append("--virtual-time-budget=10000")  # let KaTeX / Mermaid / page scripts finish
    cmd.append(url)
    log = work / "browser.log"  # a file, not a pipe: a chatty browser can never fill a pipe and hang us
    with open(log, "wb") as err:
        kw = {"creationflags": CREATE_NO_WINDOW} if WINDOWS else {"start_new_session": True}
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err, **kw)
        deadline, done_at = time.monotonic() + TIMEOUT, None
        while p.poll() is None:
            now = time.monotonic()
            if done_at is None and _complete(pdf):
                done_at = now
            if now > deadline or (done_at is not None and now - done_at > 1.0):  # Edge sometimes lingers
                _kill_tree(p)
                break
            time.sleep(0.05)
    if _complete(pdf):
        return True, ""
    return False, log.read_text(encoding="utf-8", errors="replace")


def _complete(pdf: Path) -> bool:
    """True once the whole file is on disk (ends with %%EOF), so a slow disk never yields a truncated PDF."""
    try:
        with open(pdf, "rb") as f:
            f.seek(0, 2)
            if f.tell() < 64:
                return False
            f.seek(-64, 2)
            return b"%%EOF" in f.read()
    except OSError:
        return False


def _kill_tree(p: subprocess.Popen) -> None:
    try:
        if WINDOWS:
            taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
            subprocess.run([str(taskkill), "/F", "/T", "/PID", str(p.pid)], capture_output=True,
                           creationflags=CREATE_NO_WINDOW)
        else:
            os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


# --------------------------------------------------------------------------- "made by QuickMorph" stamp
def source_tag(src: Path) -> str:
    return hashlib.sha1(os.path.normcase(str(src)).encode("utf-8", "replace")).hexdigest()[:12]


def _stamp(pdf: Path, tag: str) -> None:
    """Mark the PDF as QuickMorph output: in Chromium's /Creator when possible, else a comment after %%EOF
    (Firefox/WebKit lay their files out differently; PDF readers ignore a trailing comment)."""
    if not _stamp_creator(pdf, tag):
        try:
            with open(pdf, "ab") as f:
                f.write(f"\n%QuickMorph src={tag}\n".encode())
        except OSError:
            pass


def _stamp_creator(pdf: Path, tag: str) -> bool:
    """Replace Chromium's /Creator text with 'QuickMorph <ver> src=<tag>' of the SAME length (no offsets move)."""
    try:
        with open(pdf, "r+b") as f:
            head = f.read(4096)
            start = head.find(b"/Creator (")
            if start < 0:
                return False
            start += len(b"/Creator (")
            i, depth, end = start, 0, -1
            while i < len(head):
                c = head[i]
                if c == 0x5C:  # backslash escape
                    i += 2
                    continue
                if c == 0x28:
                    depth += 1
                elif c == 0x29:
                    if depth == 0:
                        end = i
                        break
                    depth -= 1
                i += 1
            mark = f"QuickMorph {__version__} src={tag}".encode()
            if end < 0 or len(mark) > end - start:
                return False
            f.seek(start)
            f.write(mark.ljust(end - start))
            return True
    except OSError:
        return False


def _tag_of(pdf: Path) -> str | None:
    """Source tag of a QuickMorph PDF; 'legacy' for headless-browser output (QuickMorph 1.0 did not stamp); else None."""
    try:
        with open(pdf, "rb") as f:
            head = f.read(4096)
            f.seek(max(0, f.seek(0, 2) - 512))
            tail = f.read()
    except OSError:
        return None
    m = re.search(rb"/Creator \(QuickMorph \S+ src=([0-9a-f]+)", head) or re.search(rb"%QuickMorph src=([0-9a-f]+)", tail)
    if m:
        return m.group(1).decode()
    return "legacy" if b"HeadlessChrome/" in head else None


def _move_into_place(tmp: Path, dest: Path, tag: str) -> Path:
    """Save as `dest`, else 'name (1).pdf', 'name (2).pdf' ...

    Only replaces a PDF that QuickMorph made earlier from the same source file. A PDF you made yourself
    (or one from a different file with the same name) is never touched; one that is locked open in a
    viewer is skipped. Works across drives (USB sticks, D:, network shares).
    """
    try:
        staged = dest.with_name(f".~{dest.stem}.{os.getpid()}.qmpart")
        shutil.move(str(tmp), str(staged))  # same folder as dest -> the final rename below is atomic
    except OSError as e:
        raise RuntimeError(f"Cannot write to '{dest.parent}' ({e.strerror or e}). Use 'View as PDF' instead.") from e
    try:
        for i in range(1000):
            cand = dest if i == 0 else dest.with_name(f"{dest.stem} ({i}){dest.suffix}")
            if cand.exists() and _tag_of(cand) not in (tag, "legacy"):
                continue
            try:
                os.replace(staged, cand)
                return cand
            except PermissionError:
                continue  # open in a PDF viewer
        raise RuntimeError("Too many existing copies.")
    finally:
        if staged.exists():
            staged.unlink()
