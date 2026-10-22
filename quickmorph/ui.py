"""Tiny native dialogs - no GUI toolkit is loaded, so startup stays fast."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

MB_ICONERROR, MB_ICONINFO, MB_TOPMOST = 0x10, 0x40, 0x40000
OSASCRIPT = "/usr/bin/osascript"


def _headless() -> bool:
    return bool(os.environ.get("QUICKMORPH_NOUI"))


def _osascript(script: str, *args: str) -> None:
    # text goes in as argv, never spliced into the script, so file names can't inject AppleScript
    subprocess.run([OSASCRIPT, "-e", script, *args], capture_output=True)


def error(title: str, text: str) -> None:
    if _headless():
        print(f"{title}\n{text}", file=sys.__stderr__ or sys.stderr)
    elif sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, MB_ICONERROR | MB_TOPMOST)
    elif sys.platform == "darwin":
        _osascript("on run argv\ndisplay alert (item 1 of argv) message (item 2 of argv) as critical "
                   "giving up after 600\nend run", title, text)
    elif shutil.which("notify-send"):
        subprocess.run(["notify-send", "-u", "critical", title, text], capture_output=True)
    else:
        print(f"{title}\n{text}", file=sys.__stderr__ or sys.stderr)


def toast(title: str, text: str, seconds: float = 2.0) -> None:
    """Small self-closing confirmation. Silence it with env QUICKMORPH_QUIET=1."""
    if os.environ.get("QUICKMORPH_QUIET"):
        return
    if _headless():
        print(f"{title}: {text}")
    elif sys.platform == "win32":
        import ctypes
        # MessageBoxTimeoutW: undocumented but stable since XP; closes itself after the timeout
        ctypes.windll.user32.MessageBoxTimeoutW(0, text, title, MB_ICONINFO | MB_TOPMOST, 0, int(seconds * 1000))
    elif sys.platform == "darwin":
        _osascript("on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run",
                   title, text)
    elif shutil.which("notify-send"):
        subprocess.run(["notify-send", title, text], capture_output=True)
