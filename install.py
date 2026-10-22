"""QuickMorph installer - adds "View as PDF" and "Convert to PDF" to the right-click menu.

    python install.py                  install / update        (no admin rights needed, current user only)
    python install.py --uninstall      remove everything
    python install.py --with-pandoc    also fetch portable Pandoc (~35 MB) for .odt/.rtf/.epub/.org/.tex
  Windows 11 only (optional):
    python install.py --classic-menu      show the full classic right-click menu (no "Show more options")
    python install.py --no-classic-menu   undo that - only if QuickMorph was the one that turned it on

What it does:
  1. copies the app into your user folder (Windows: %LOCALAPPDATA%\\QuickMorph,
     macOS: ~/Library/Application Support/QuickMorph, Linux: ~/.local/share/quickmorph)
  2. pip-installs a few pure-Python libraries into ...\\app\\libs (isolated: never touches your global Python)
  3. Windows: registers two verbs under HKCU\\Software\\Classes\\*\\shell
     macOS:   adds two Finder Quick Actions to ~/Library/Services (right-click > Quick Actions)
     Linux:   nothing to register - use the `quickmorph` command (see README)
  4. converts a tiny test file to prove everything works

It NEVER restarts Explorer or Finder: Windows is notified with SHChangeNotify, macOS with `pbs -update`.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if sys.version_info < (3, 9):
    sys.exit("QuickMorph needs Python 3.9 or newer.")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from quickmorph import detect  # noqa: E402
from quickmorph.env import APP_DIR, MACOS, WINDOWS  # noqa: E402

APP = APP_DIR / "app"
BIN = APP_DIR / "bin"
ACTIONS = {"view": "View as PDF", "save": "Convert to PDF"}

# --------------------------------------------------------------------------- Windows registry
STAR_SHELL_ROOT = r"Software\Classes\*\shell"
LEGACY_SFA_ROOT = r"Software\Classes\SystemFileAssociations"
WIN11_CLASSIC_CLSID = r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}"
QM_MARKER_VALUE = "AddedByQuickMorph"
VERB_KEYS = {"view": "QuickMorph.View", "save": "QuickMorph.Save"}
SHCNE_ASSOCCHANGED, SHCNF_IDLIST = 0x08000000, 0
CLASSIC_MENU_NOTE = ('Note: the Windows 11 classic-menu change takes effect after you sign out and back in '
                     '(QuickMorph never restarts Explorer for you).')

# --------------------------------------------------------------------------- macOS Quick Actions
SERVICES = Path.home() / "Library" / "Services"


def mac_workflow(action: str) -> Path:
    return SERVICES / f"QuickMorph - {ACTIONS[action]}.workflow"


# --------------------------------------------------------------------------- shared steps
def interpreter() -> Path:
    """The real Python (not a venv shim). On Windows prefer pythonw.exe -> no console window flashes."""
    base = Path(getattr(sys, "_base_executable", None) or sys.executable)
    if WINDOWS:
        for cand in (base.with_name("pythonw.exe"), Path(sys.executable).with_name("pythonw.exe")):
            if cand.is_file():
                return cand
        sys.exit("pythonw.exe not found next to your Python install.")
    return base if base.is_file() else Path(sys.executable)


def launch_command(action: str) -> list[str]:
    return [str(interpreter()), str(APP / "run.pyw"), "--queue", "--action", action, "--"]


def copy_app() -> None:
    print(f"-> copying app to {APP}")
    shutil.rmtree(APP / "quickmorph", ignore_errors=True)
    APP.mkdir(parents=True, exist_ok=True)
    shutil.copytree(HERE / "quickmorph", APP / "quickmorph", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(HERE / "run.pyw", APP / "run.pyw")
    if not (APP / "quickmorph" / "vendor" / "katex" / "katex.min.js").is_file():
        print("   ! vendor/ missing - math & mermaid won't render. Run: python tools/fetch_vendor.py")


def install_deps() -> None:
    libs = APP / "libs"
    req = HERE / "requirements.txt"
    stamp_text = f"{sys.version_info[:2]}\n{req.read_text(encoding='utf-8')}"
    stamp = libs / ".requirements.stamp"
    if stamp.is_file() and stamp.read_text(encoding="utf-8") == stamp_text:
        return
    print(f"-> installing dependencies into {libs} (one-time, ~10 MB)")
    shutil.rmtree(libs, ignore_errors=True)
    # wheels only: no package gets to run setup.py code on your machine
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                    "--no-warn-script-location", "--only-binary=:all:", "--target", str(libs), "-r", str(req)],
                   check=True)
    stamp.write_text(stamp_text, encoding="utf-8")
    # pre-compile so the first right-click is as fast as the rest
    subprocess.run([sys.executable, "-m", "compileall", "-q", str(APP)], check=False)


def fetch_pandoc() -> None:
    import hashlib
    import platform
    import urllib.request
    import zipfile
    suffix = {"win32": "windows-x86_64.zip",
              "darwin": "arm64-macOS.zip" if platform.machine() == "arm64" else "x86_64-macOS.zip"}.get(sys.platform)
    if not suffix:
        print("-> Pandoc: install it with your package manager, e.g.  sudo apt install pandoc")
        return
    exe = "pandoc.exe" if WINDOWS else "pandoc"
    print("-> downloading portable Pandoc ...")
    try:
        with urllib.request.urlopen("https://api.github.com/repos/jgm/pandoc/releases/latest", timeout=30) as r:
            rel = json.load(r)
        asset = next(a for a in rel["assets"] if a["name"].endswith(suffix))
        with tempfile.TemporaryFile() as tmp:
            h = hashlib.sha256()
            with urllib.request.urlopen(asset["browser_download_url"], timeout=300) as r:
                for chunk in iter(lambda: r.read(1 << 20), b""):  # streamed: never holds 35 MB in RAM
                    h.update(chunk)
                    tmp.write(chunk)
            digest = asset.get("digest") or ""
            if digest.startswith("sha256:") and digest[7:].lower() != h.hexdigest():
                sys.exit("Pandoc download failed its SHA-256 check - nothing was installed.")
            tmp.seek(0)
            with zipfile.ZipFile(tmp) as z:
                member = next(n for n in z.namelist() if n.endswith("/" + exe))
                BIN.mkdir(parents=True, exist_ok=True)
                with z.open(member) as s, open(BIN / exe, "wb") as d:
                    shutil.copyfileobj(s, d)
    except Exception as e:  # noqa: BLE001
        print(f"   ! could not download Pandoc ({e}). Install it yourself instead "
              f"({'winget install pandoc' if WINDOWS else 'brew install pandoc'}).")
        return
    if not WINDOWS:
        (BIN / exe).chmod(0o755)
    print(f"   pandoc {rel['tag_name']} -> {BIN / exe}")


def self_test() -> None:
    """Convert a tiny file with the INSTALLED copy, exactly like a right-click would (minus the queue)."""
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "quickmorph-selftest.md"
        src.write_text("# QuickMorph self-test\n\nIf you can read this, it works.\n", encoding="utf-8")
        t0 = time.time()
        env = {**os.environ, "QUICKMORPH_NOUI": "1"}
        r = subprocess.run([sys.executable, str(APP / "run.pyw"), "--action", "save", str(src)],
                           capture_output=True, text=True, env=env, timeout=180)
        if r.returncode == 0 and src.with_suffix(".pdf").is_file():
            print(f"-> self-test passed ({time.time() - t0:.1f}s)")
        else:
            print("-> ! self-test FAILED - right-click conversions will not work yet:\n   "
                  + (r.stderr or r.stdout).strip().replace("\n", "\n   "))


# --------------------------------------------------------------------------- Windows
def _delete_tree(root, path: str) -> None:
    import winreg
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as k:
            while True:
                try:
                    _delete_tree(root, path + "\\" + winreg.EnumKey(k, 0))
                except OSError:
                    break
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        pass


def classic_menu_state() -> tuple[bool, bool]:
    """(exists, added_by_quickmorph). Only a key carrying QuickMorph's own marker counts as ours -
    a classic-menu tweak you (or another tool) added is never removed."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WIN11_CLASSIC_CLSID + r"\InprocServer32"):
            pass
    except FileNotFoundError:
        return False, False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WIN11_CLASSIC_CLSID) as k:
            return True, winreg.QueryValueEx(k, QM_MARKER_VALUE)[0] == "1"
    except FileNotFoundError:
        return True, False


def set_classic_menu(enable: bool) -> None:
    import winreg
    exists, ours = classic_menu_state()
    if enable and not exists:
        print("-> enabling the Windows 11 classic context menu")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, WIN11_CLASSIC_CLSID) as k:
            winreg.SetValueEx(k, QM_MARKER_VALUE, 0, winreg.REG_SZ, "1")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, WIN11_CLASSIC_CLSID + r"\InprocServer32") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "")
        print(CLASSIC_MENU_NOTE)
    elif not enable and exists:
        if ours:
            print("-> removing the Windows 11 classic context menu tweak QuickMorph added")
            _delete_tree(winreg.HKEY_CURRENT_USER, WIN11_CLASSIC_CLSID)
            print(CLASSIC_MENU_NOTE)
        else:
            print("-> classic context menu was not turned on by QuickMorph - left exactly as it is")


def win_register() -> None:
    import winreg
    icon = os.path.expandvars(r"%SystemRoot%\System32\imageres.dll") + ",-68"  # stock document icon
    print("-> registering right-click menu under HKCU\\Software\\Classes\\*\\shell")
    for action, key in VERB_KEYS.items():
        path = rf"{STAR_SHELL_ROOT}\{key}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, ACTIONS[action])
            winreg.SetValueEx(k, "MUIVerb", 0, winreg.REG_SZ, ACTIONS[action])
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_EXPAND_SZ, icon)
            winreg.SetValueEx(k, "Position", 0, winreg.REG_SZ, "Top")
            # no 15-file limit on multi-select; the --queue worker converts them one at a time
            winreg.SetValueEx(k, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path + r"\command") as k:
            cmd = " ".join(f'"{a}"' if " " in a or "\\" in a else a for a in launch_command(action)) + ' "%1"'
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)


def win_unregister() -> None:
    import winreg
    for key in VERB_KEYS.values():
        _delete_tree(winreg.HKEY_CURRENT_USER, rf"{STAR_SHELL_ROOT}\{key}")
    # per-extension keys written by very old versions
    exts = set(detect.all_extensions())
    try:
        exts |= set(json.loads((APP_DIR / "registered.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    for ext in exts:
        for key in VERB_KEYS.values():
            _delete_tree(winreg.HKEY_CURRENT_USER, rf"{LEGACY_SFA_ROOT}\{ext}\shell\{key}")


def win_refresh_shell() -> None:
    import ctypes
    ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)


# --------------------------------------------------------------------------- macOS
def _mac_plists(action: str) -> tuple[dict, dict]:
    import uuid
    label = ACTIONS[action]
    script = " ".join(shlex.quote(a) for a in launch_command(action)) + ' "$@"'
    info = {"NSServices": [{
        "NSBackgroundColorName": "background", "NSIconName": "NSActionTemplate",
        "NSMenuItem": {"default": label}, "NSMessage": "runWorkflowAsService",
        "NSRequiredContext": {"NSApplicationIdentifier": "com.apple.finder"},
        "NSSendFileTypes": ["public.item"],
    }], "QuickMorph": True}  # marker: --uninstall only ever deletes workflows carrying it
    arg = lambda n, name, default: {"default value": default, "name": name, "required": "0", "type": "0", "uuid": n}  # noqa: E731
    action_dict = {
        "AMAccepts": {"Container": "List", "Optional": True, "Types": ["com.apple.cocoa.string"]},
        "AMActionVersion": "2.0.3", "AMApplication": ["Automator"],
        "AMParameterProperties": {k: {} for k in ("COMMAND_STRING", "CheckedForUserDefaultShell", "inputMethod",
                                                  "shell", "source")},
        "AMProvides": {"Container": "List", "Types": ["com.apple.cocoa.string"]},
        "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
        "ActionName": "Run Shell Script",
        "ActionParameters": {"COMMAND_STRING": script, "CheckedForUserDefaultShell": True, "inputMethod": 1,
                             "shell": "/bin/bash", "source": ""},
        "BundleIdentifier": "com.apple.RunShellScript", "CFBundleVersion": "2.0.3",
        "CanShowSelectedItemsWhenRun": False, "CanShowWhenRun": True, "Category": ["AMCategoryUtilities"],
        "Class Name": "RunShellScriptAction",
        "InputUUID": str(uuid.uuid4()).upper(), "OutputUUID": str(uuid.uuid4()).upper(), "UUID": str(uuid.uuid4()).upper(),
        "Keywords": ["Shell", "Script", "Command", "Run", "Unix"], "UnlocalizedApplications": ["Automator"],
        "arguments": {"0": arg("0", "inputMethod", 0), "1": arg("1", "CheckedForUserDefaultShell", False),
                      "2": arg("2", "source", ""), "3": arg("3", "COMMAND_STRING", ""), "4": arg("4", "shell", "/bin/sh")},
        "isViewVisible": 1, "location": "309.000000:253.000000",
        "nibPath": "/System/Library/Automator/Run Shell Script.action/Contents/Resources/Base.lproj/main.nib",
    }
    wflow = {
        "AMApplicationBuild": "523", "AMApplicationVersion": "2.10", "AMDocumentVersion": "2",
        "actions": [{"action": action_dict, "isViewVisible": 1}],
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleIDsByPath": {}, "applicationPaths": [],
            "inputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "outputTypeIdentifier": "com.apple.Automator.nothing",
            "presentationMode": 15, "processesInput": 0,
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": 0, "systemImageName": "NSActionTemplate", "useAutomaticInputType": 0,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }
    return info, wflow


def mac_register() -> None:
    import plistlib
    print(f"-> adding Finder Quick Actions to {SERVICES}")
    for action in ACTIONS:
        wf = mac_workflow(action)
        shutil.rmtree(wf, ignore_errors=True)
        (wf / "Contents").mkdir(parents=True)
        info, wflow = _mac_plists(action)
        with open(wf / "Contents" / "Info.plist", "wb") as f:
            plistlib.dump(info, f)
        with open(wf / "Contents" / "document.wflow", "wb") as f:
            plistlib.dump(wflow, f)
    mac_refresh_services()


def mac_unregister() -> None:
    import plistlib
    for action in ACTIONS:
        wf = mac_workflow(action)
        try:
            with open(wf / "Contents" / "Info.plist", "rb") as f:
                if plistlib.load(f).get("QuickMorph"):
                    shutil.rmtree(wf, ignore_errors=True)
        except (OSError, plistlib.InvalidFileException):
            pass
    mac_refresh_services()


def mac_refresh_services() -> None:
    pbs = "/System/Library/CoreServices/pbs"  # re-reads the Services list; Finder is NOT restarted
    if os.path.exists(pbs):
        subprocess.run([pbs, "-update"], capture_output=True)


# --------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uninstall", action="store_true", help="remove QuickMorph and its right-click entries")
    ap.add_argument("--with-pandoc", action="store_true", help="also download Pandoc for .odt/.rtf/.epub/.org/.tex")
    ap.add_argument("--classic-menu", action="store_true", help="Windows 11: show the full classic right-click menu")
    ap.add_argument("--no-classic-menu", action="store_true", help="Windows 11: undo --classic-menu")
    ap.add_argument("--skip-self-test", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()

    if a.uninstall:
        if WINDOWS:
            win_unregister()
            set_classic_menu(False)
            win_refresh_shell()
        elif MACOS:
            mac_unregister()
        shutil.rmtree(APP_DIR, ignore_errors=True)
        print("QuickMorph removed.")
        return

    if WINDOWS:
        win_unregister()  # clean slate: also removes keys from older versions
    copy_app()
    install_deps()
    if a.with_pandoc:
        fetch_pandoc()
    if WINDOWS:
        win_register()
        if a.classic_menu or a.no_classic_menu:
            set_classic_menu(a.classic_menu)
        win_refresh_shell()
    elif MACOS:
        mac_register()
    if not a.skip_self_test:
        self_test()

    print()
    if WINDOWS:
        print("Done! Right-click any file -> 'View as PDF' or 'Convert to PDF'.")
        if not classic_menu_state()[0]:
            print("Windows 11: they are under 'Show more options' (or Shift+Right-click). "
                  "Run with --classic-menu to show them directly.")
    elif MACOS:
        print("Done! In Finder, right-click any file -> Quick Actions -> 'View as PDF' or 'Convert to PDF'.")
        print("(Not listed? System Settings > Privacy & Security > Extensions > Finder - tick both.)")
    else:
        print(f"Done! Convert from a terminal:  {shlex.quote(str(interpreter()))} "
              f"{shlex.quote(str(APP / 'run.pyw'))} --action view FILE")


if __name__ == "__main__":
    main()
