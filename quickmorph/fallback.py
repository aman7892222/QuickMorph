"""Fallback PDF engines for machines that have no Chromium browser (Edge/Chrome/Brave/...).

  webkit  - macOS: the WebKit engine built into every Mac (what Safari uses), driven through osascript
  firefox - any OS: Firefox's built-in remote protocol (Marionette) over a local socket

Nothing here is imported unless it is needed, so the normal (Chromium) path pays nothing for it.
Both write a PDF to `out` and return (ok, error_text).
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

from .env import CREATE_NO_WINDOW, MACOS, WINDOWS

MARGIN_IN = 0.6  # page margin these engines apply natively (CSS @page margins are zeroed for them)
OSASCRIPT = "/usr/bin/osascript"


# --------------------------------------------------------------------------- discovery
def find_firefox() -> str | None:
    env = os.environ.get("QUICKMORPH_FIREFOX")
    if env and Path(env).is_file():
        return env
    if WINDOWS:
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
            if root and (Path(root) / "Mozilla Firefox" / "firefox.exe").is_file():
                return str(Path(root) / "Mozilla Firefox" / "firefox.exe")
        return None
    if MACOS:
        for root in (Path("/Applications"), Path.home() / "Applications"):
            if (root / "Firefox.app/Contents/MacOS/firefox").is_file():
                return str(root / "Firefox.app/Contents/MacOS/firefox")
        return None
    return shutil.which("firefox") or shutil.which("firefox-esr")


def webkit_available() -> bool:
    return MACOS and os.path.exists(OSASCRIPT)


# --------------------------------------------------------------------------- macOS WebKit
_JXA = r"""
ObjC.import('Cocoa');
ObjC.import('WebKit');
function spin(s) { $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(s)); }
function run(argv) {
  var url = argv[0], out = argv[1], w = Number(argv[2]) * 72, h = Number(argv[3]) * 72, m = Number(argv[4]) * 72;
  var waitReady = argv[5] === '1', end = Date.now() + Number(argv[6]) * 1000;
  $.NSApplication.sharedApplication.setActivationPolicy(1);  // accessory: no Dock icon, no menu bar
  var view = $.WKWebView.alloc.initWithFrameConfiguration($.NSMakeRect(0, 0, w - 2 * m, h - 2 * m),
                                                          $.WKWebViewConfiguration.alloc.init);
  var win = $.NSWindow.alloc.initWithContentRectStyleMaskBackingDefer($.NSMakeRect(-20000, -20000, w, h), 0, 2, false);
  win.contentView = view;
  view.loadFileURLAllowingReadAccessToURL($.NSURL.URLWithString(url), $.NSURL.fileURLWithPath('/'));
  while (view.isLoading && Date.now() < end) spin(0.05);
  var ready = Math.min(end, Date.now() + (waitReady ? 10000 : 300));
  while (Date.now() < ready) {
    var u = view.URL;
    if (waitReady && u && u.fragment && u.fragment.js === 'qm-ready') break;
    spin(0.05);
  }
  var info = $.NSPrintInfo.sharedPrintInfo.copy;
  info.paperSize = $.NSMakeSize(w, h);
  info.topMargin = m; info.bottomMargin = m; info.leftMargin = m; info.rightMargin = m;
  info.horizontalPagination = 1;  // fit width
  info.verticalPagination = 0;    // automatic page breaks
  info.horizontallyCentered = false; info.verticallyCentered = false;
  info.jobDisposition = $.NSPrintSaveJob;
  info.dictionary.setObjectForKey($.NSURL.fileURLWithPath(out), $.NSPrintJobSavingURL);
  var op = view.printOperationWithPrintInfo(info);
  op.showsPrintPanel = false;
  op.showsProgressPanel = false;
  op.view.frame = $.NSMakeRect(0, 0, w - 2 * m, h - 2 * m);
  op.runOperationModalForWindowDelegateDidRunSelectorContextInfo(win, $(), $(), $());
  var fm = $.NSFileManager.defaultManager, last = -1, stable = 0;
  while (Date.now() < end && stable < 4) {
    spin(0.1);
    if (!fm.fileExistsAtPath(out)) continue;
    var size = fm.attributesOfItemAtPathError(out, $()).fileSize;
    stable = (size > 0 && size === last) ? stable + 1 : 0;
    last = size;
  }
  return fm.fileExistsAtPath(out) ? 'ok' : 'no output';
}
"""


def webkit_print(url: str, out: Path, size_in: tuple[float, float], wait_for_ready: bool,
                 timeout: float) -> tuple[bool, str]:
    w, h = size_in
    try:
        r = subprocess.run([OSASCRIPT, "-l", "JavaScript", "-e", _JXA, url, str(out), str(w), str(h), str(MARGIN_IN),
                            "1" if wait_for_ready else "0", str(int(timeout))],
                           capture_output=True, text=True, timeout=timeout + 15)
    except subprocess.TimeoutExpired:
        return False, "WebKit timed out"
    return out.is_file() and out.stat().st_size > 0, (r.stderr or r.stdout).strip()


# --------------------------------------------------------------------------- Firefox (Marionette)
class _Marionette:
    """Minimal client for Firefox's built-in remote protocol: length-prefixed JSON over a local TCP socket."""

    def __init__(self, sock: socket.socket):
        self.sock, self.buf, self.msg_id = sock, b"", 0
        self._recv()  # server hello

    def _recv(self):
        while b":" not in self.buf:
            self._fill()
        size, _, rest = self.buf.partition(b":")
        self.buf = rest
        while len(self.buf) < int(size):
            self._fill()
        data, self.buf = self.buf[:int(size)], self.buf[int(size):]
        return json.loads(data)

    def _fill(self) -> None:
        chunk = self.sock.recv(1 << 16)
        if not chunk:
            raise ConnectionError("Firefox closed the connection")
        self.buf += chunk

    def cmd(self, name: str, params: dict):
        self.msg_id += 1
        data = json.dumps([0, self.msg_id, name, params]).encode()
        self.sock.sendall(str(len(data)).encode() + b":" + data)
        while True:
            msg = self._recv()
            if msg[0] == 1 and msg[1] == self.msg_id:
                if msg[2]:
                    raise RuntimeError((msg[2] or {}).get("message") or str(msg[2]))
                return msg[3]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def firefox_print(firefox: str, url: str, out: Path, size_in: tuple[float, float], wait_for_ready: bool,
                  timeout: float, work: Path) -> tuple[bool, str]:
    profile = work / "ff-profile"
    profile.mkdir()
    port = _free_port()
    prefs = {
        "marionette.port": port, "browser.shell.checkDefaultBrowser": False,
        "browser.startup.homepage_override.mstone": "ignore", "browser.aboutwelcome.enabled": False,
        "datareporting.policy.dataSubmissionEnabled": False, "toolkit.telemetry.reportingpolicy.firstRun": False,
        "app.update.disabledForTesting": True, "browser.safebrowsing.update.enabled": False,
        # Marionette's automation defaults relax these; a document must never read its neighbouring files
        "security.fileuri.strict_origin_policy": True, "privacy.file_unique_origin": True,
    }
    (profile / "user.js").write_text("".join(f'user_pref("{k}", {json.dumps(v)});\n' for k, v in prefs.items()),
                                     encoding="utf-8")
    env = {**os.environ, "MOZ_HEADLESS": "1", "MOZ_CRASHREPORTER_DISABLE": "1"}
    kw = {"creationflags": CREATE_NO_WINDOW} if WINDOWS else {"start_new_session": True}
    p = subprocess.Popen([firefox, "--headless", "--marionette", "--no-remote", "--profile", str(profile)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, **kw)
    deadline = time.monotonic() + timeout
    sock = None
    try:
        while sock is None:
            if p.poll() is not None or time.monotonic() > deadline:
                return False, "Firefox did not start its remote protocol"
            try:
                sock = socket.create_connection(("127.0.0.1", port), timeout=1)
            except OSError:
                time.sleep(0.2)
        sock.settimeout(max(5.0, deadline - time.monotonic()))
        ff = _Marionette(sock)
        ff.cmd("WebDriver:NewSession", {"capabilities": {"alwaysMatch": {"pageLoadStrategy": "normal"}}})
        ff.cmd("WebDriver:Navigate", {"url": url})
        ready = time.monotonic() + (10 if wait_for_ready else 0.3)
        while time.monotonic() < ready:
            if wait_for_ready and str(ff.cmd("WebDriver:GetCurrentURL", {}).get("value", "")).endswith("#qm-ready"):
                break
            time.sleep(0.1)
        cm = lambda inches: round(inches * 2.54, 3)  # noqa: E731
        res = ff.cmd("WebDriver:Print", {
            "page": {"width": cm(size_in[0]), "height": cm(size_in[1])}, "orientation": "portrait",
            "margin": {k: cm(MARGIN_IN) for k in ("top", "bottom", "left", "right")},
            "background": True, "shrinkToFit": True, "scale": 1.0, "pageRanges": []})
        out.write_bytes(base64.b64decode(res["value"]))
        try:
            ff.cmd("Marionette:Quit", {"flags": ["eForceQuit"]})
        except (OSError, RuntimeError, ValueError):
            pass
        return True, ""
    except (OSError, RuntimeError, ValueError, KeyError) as e:
        return False, f"Firefox: {e}"
    finally:
        if sock is not None:
            sock.close()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            from .pdf import _kill_tree
            _kill_tree(p)
