"""Command-line entry point.

    quickmorph [--action save|view] FILE [FILE ...]
      save -> write <name>.pdf next to each file (default)
      view -> render to the temp folder and open it in the default PDF viewer (no clutter)

The right-click menu adds --queue: each click only drops its file(s) into a tiny job queue and exits;
the first instance becomes the worker and converts the queue one file at a time. Selecting 50 files
therefore runs ONE browser at a time instead of 50 at once, so even a 4 GB laptop stays responsive.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .env import APP_DIR, LOG_FILE, harden_process, open_path, try_lock, unlock

QUEUE_DIR = APP_DIR / "queue"
RUN_LOCK = APP_DIR / "run.lock"
STALE_JOB_SECONDS = 3600


def _setup() -> None:
    # pythonw.exe has no console: stdout/stderr are None
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w"))
    import logging
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 200_000:
            LOG_FILE.unlink()
        logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s %(message)s")
    except OSError:
        pass


def _temp_dir() -> Path:
    import tempfile
    d = Path(tempfile.gettempdir()) / "QuickMorph"
    d.mkdir(exist_ok=True)
    cutoff = time.time() - 86400  # tidy previews older than a day
    for f in d.glob("*.pdf"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass  # still open in a viewer
    return d


def process(action: str, src: Path, open_after: bool = True) -> Path:
    """Convert one file. Returns the PDF path. Raises on any failure."""
    from .pdf import file_to_pdf, source_tag
    src = Path(src).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"File not found: {src}")
    if src.suffix.lower() == ".pdf":
        raise ValueError("This file is already a PDF.")
    if action == "view":
        out = file_to_pdf(src, _temp_dir() / f"{src.stem}_{source_tag(src)[:6]}_{int(time.time())}.pdf")
        if open_after:
            open_path(out)
        return out
    return file_to_pdf(src, src.with_suffix(".pdf"))


def _convert(jobs: list[tuple[str, str]], open_after: bool) -> tuple[list[str], list[str]]:
    import logging
    import traceback
    saved, failures = [], []
    for action, f in jobs:
        src = Path(f)
        try:
            t0 = time.time()
            out = process(action, src, open_after=open_after)
            logging.info("OK  %s %s -> %s (%.2fs)", action, src, out, time.time() - t0)
            if action == "save":
                saved.append(out.name)
        except Exception as e:  # noqa: BLE001 - surface every problem to the user, never fail silently
            logging.error("ERR %s %s\n%s", action, src, traceback.format_exc())
            failures.append(f"{src.name}: {e}")
    return saved, failures


def _report(saved: list[str], failures: list[str]) -> None:
    from . import ui
    if failures:
        ui.error("QuickMorph - PDF conversion failed", "\n\n".join(failures[:15]) +
                 (f"\n\n... and {len(failures) - 15} more" if len(failures) > 15 else "") + f"\n\n(details: {LOG_FILE})")
    if saved:
        names = ", ".join(saved[:5]) + (f" and {len(saved) - 5} more" if len(saved) > 5 else "")
        ui.toast("QuickMorph", f"Saved {len(saved)} PDF{'s' * (len(saved) > 1)}: {names}")


# --------------------------------------------------------------------------- right-click queue
def _enqueue(action: str, files: list[str]) -> None:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns()}-{os.getpid()}"
    tmp = QUEUE_DIR / f"{name}.tmp"
    tmp.write_text("\n".join([action, *files]), encoding="utf-8")
    os.replace(tmp, QUEUE_DIR / f"{name}.job")  # appears atomically: the worker never reads half a job


def _take_jobs() -> list[tuple[str, str]]:
    jobs = []
    for j in sorted(QUEUE_DIR.glob("*.job")):
        try:
            fresh = time.time() - j.stat().st_mtime < STALE_JOB_SECONDS
            lines = j.read_text(encoding="utf-8").splitlines()
            j.unlink()
        except OSError:
            continue
        if fresh and lines and lines[0] in ("view", "save"):
            jobs += [(lines[0], f) for f in lines[1:] if f]
    return jobs


def _run_queued(action: str, files: list[str]) -> int:
    _enqueue(action, files)
    saved, failures = [], []
    while True:
        lock = try_lock(RUN_LOCK)
        if lock is None:
            break  # another instance is already converting - it will pick our files up
        try:
            _setup()
            while True:
                jobs = _take_jobs()
                if not jobs:
                    break
                s, f = _convert(jobs, open_after=True)
                saved += s
                failures += f
        finally:
            unlock(lock)
        if not any(QUEUE_DIR.glob("*.job")):  # nothing slipped in while we were releasing the lock
            break
    if saved or failures:
        _report(saved, failures)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="quickmorph", description="Any text/document/code/image file -> PDF")
    ap.add_argument("--action", choices=["view", "save"], default="save",
                    help="save: <name>.pdf next to the file (default); view: open a temporary PDF")
    ap.add_argument("--no-open", action="store_true", help="view: don't launch the PDF viewer")
    ap.add_argument("--queue", action="store_true", help=argparse.SUPPRESS)  # used by the right-click menu
    ap.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    files = [os.path.abspath(f) for f in args.files]
    harden_process()

    if args.queue:
        return _run_queued(args.action, files)

    _setup()
    saved, failures = _convert([(args.action, f) for f in files], open_after=not args.no_open)
    for name in saved:
        print("saved:", name)
    for msg in failures:
        print("error:", msg, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
