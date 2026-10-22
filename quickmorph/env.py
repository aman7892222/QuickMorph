"""Environment helpers: app folders, finding a browser/Pandoc, paper size, opening files, file locks."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

WINDOWS, MACOS = sys.platform == "win32", sys.platform == "darwin"
CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0


def _app_dir() -> Path:
    if os.environ.get("QUICKMORPH_HOME"):
        return Path(os.environ["QUICKMORPH_HOME"])
    if WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "QuickMorph"
    if MACOS:
        return Path.home() / "Library" / "Application Support" / "QuickMorph"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "quickmorph"


APP_DIR = _app_dir()
LOG_FILE = APP_DIR / "quickmorph.log"


def harden_process() -> None:
    """Never run helper programs (taskkill, pandoc, ...) planted next to the file that was right-clicked.

    Explorer/Finder start us *inside* that folder, and Windows looks for executables in the current
    directory first - so move out of it and tell Windows to skip the current directory.
    """
    os.environ["NoDefaultCurrentDirectoryInExePath"] = "1"
    for d in (APP_DIR, Path.home()):
        try:
            os.chdir(d)
            return
        except OSError:
            pass


# --------------------------------------------------------------------------- paper size
_LETTER_COUNTRIES = {"US", "CA", "MX", "PH", "CL", "CO", "VE", "CR", "GT", "PA", "DO", "PR", "SV", "NI", "BZ"}


def paper_size() -> str:
    """Letter in the US/Canada/..., A4 everywhere else. Override with env QUICKMORPH_PAPER=A4|Letter|Legal|A3 ..."""
    env = os.environ.get("QUICKMORPH_PAPER")
    if env:
        return env
    if WINDOWS:
        import ctypes
        buf = ctypes.create_unicode_buffer(8)
        if ctypes.windll.kernel32.GetLocaleInfoEx(None, 0x100A, buf, 8):  # LOCALE_IPAPERSIZE: 1=Letter 5=Legal 9=A4
            return "Letter" if buf.value.strip() in ("1", "5") else "A4"
        return "A4"
    loc = os.environ.get("LC_PAPER") or os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
    if not loc and MACOS:
        try:
            import plistlib
            with open(Path.home() / "Library" / "Preferences" / ".GlobalPreferences.plist", "rb") as f:
                loc = str(plistlib.load(f).get("AppleLocale", ""))
        except Exception:  # noqa: BLE001 - unreadable prefs just mean "use A4"
            pass
    m = re.search(r"_([A-Z]{2})", loc)
    return "Letter" if m and m.group(1) in _LETTER_COUNTRIES else "A4"


_PAPER_INCHES = {"a3": (11.69, 16.54), "a4": (8.27, 11.69), "a5": (5.83, 8.27), "b5": (6.93, 9.84),
                 "letter": (8.5, 11.0), "legal": (8.5, 14.0), "tabloid": (11.0, 17.0), "ledger": (17.0, 11.0)}


def paper_inches(name: str, landscape: bool = False) -> tuple[float, float]:
    """(width, height) in inches for engines that need numbers instead of a CSS page size."""
    w, h = _PAPER_INCHES.get(name.strip().lower(), _PAPER_INCHES["a4"])
    return (h, w) if landscape else (w, h)


# --------------------------------------------------------------------------- external programs
def find_pandoc() -> str | None:
    exe = "pandoc.exe" if WINDOWS else "pandoc"
    for cand in (APP_DIR / "bin" / exe, Path(__file__).resolve().parent.parent / "bin" / exe):
        if cand.is_file():
            return str(cand)
    return shutil.which("pandoc")


# Any Chromium-based browser can print to PDF headlessly. Edge comes first on Windows (it ships with the OS).
_WIN_BROWSERS = [
    r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe",
    r"BraveSoftware\Brave-Browser\Application\brave.exe", r"Chromium\Application\chrome.exe",
    r"Vivaldi\Application\vivaldi.exe", r"Microsoft\Edge Beta\Application\msedge.exe",
    r"Microsoft\Edge Dev\Application\msedge.exe", r"Google\Chrome Beta\Application\chrome.exe",
]
_MAC_BROWSERS = ["Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium", "Vivaldi", "Google Chrome Canary",
                 "Microsoft Edge Beta", "Google Chrome Beta"]
_LINUX_BROWSERS = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
                   "microsoft-edge-stable", "brave-browser", "vivaldi-stable"]


def find_browser() -> str | None:
    env = os.environ.get("QUICKMORPH_BROWSER")
    if env and Path(env).is_file():
        return env
    if WINDOWS:
        roots = [os.environ.get(v) for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
        for rel in _WIN_BROWSERS:
            for root in roots:
                if root and (Path(root) / rel).is_file():
                    return str(Path(root) / rel)
        import winreg
        for exe in ("msedge.exe", "chrome.exe", "brave.exe"):
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                        p = winreg.QueryValue(k, None).strip('"')
                    if p and Path(p).is_file():
                        return p
                except OSError:
                    pass
        return None
    if MACOS:
        for app in _MAC_BROWSERS:
            for root in (Path("/Applications"), Path.home() / "Applications"):
                exe = root / f"{app}.app" / "Contents" / "MacOS" / app
                if exe.is_file():
                    return str(exe)
        return None
    return next((p for p in map(shutil.which, _LINUX_BROWSERS) if p), None)


def open_path(path: Path) -> None:
    """Open a file with its default app (the PDF viewer)."""
    if WINDOWS:
        os.startfile(path)  # noqa: S606 - our own freshly written PDF
    elif MACOS:
        subprocess.Popen(["/usr/bin/open", str(path)])
    else:
        opener = shutil.which("xdg-open")
        if opener:
            subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------------------- cross-process lock
def try_lock(path: Path):
    """Non-blocking exclusive lock. Returns a handle (pass to unlock) or None if another process holds it.

    The OS drops the lock automatically if the holder crashes, so it can never get stuck.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        f = open(path, "a+b")
    except OSError:
        return None
    try:
        if WINDOWS:
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def unlock(handle) -> None:
    try:
        if WINDOWS:
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    handle.close()
