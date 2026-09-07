"""Entry point for the packaged macOS app.

The Studio runs as a normal desktop window: a WKWebView showing a local server
that only ever binds 127.0.0.1. A browser tab was the cheaper option and the
wrong one -- it puts a research tool behind whatever else is open, gives it a
URL bar and a browser's cache and extensions, and leaves the app running with
no window when the tab is closed. A window is also the only way the icon in the
Dock means anything.

Double-clicking a `.app` gives no terminal and no way to read a traceback, so
this logs somewhere findable, picks its own port, and puts a dialog on screen if
it cannot start at all.
"""

from pathlib import Path
from typing import Optional
import logging
import os
import socket
import sys
import threading
import time
import webbrowser

from . import config

LOG_DIR = Path.home() / "Library" / "Logs" / config.APP_NAME if sys.platform == "darwin" else config.support_dir()
PREFERRED_PORT = 8765
WINDOW_TITLE = "SpatialMind Studio"
WINDOW_BACKGROUND = "#080D0F"   # --paper from the UI's palette
DEFAULT_SIZE = (1440, 920)
MIN_SIZE = (1080, 700)


def setup_logging() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / "studio.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(str(path)), logging.StreamHandler(sys.stdout)],
    )
    return path


def headless() -> bool:
    """Server only, no window. Used by the smoke test and by --no-browser."""
    return bool(os.environ.get("SPATIALMIND_HEADLESS") or os.environ.get("SPATIALMIND_NO_BROWSER"))


def port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def choose_port() -> int:
    forced = os.environ.get("SPATIALMIND_PORT")
    if forced:
        return int(forced)
    if port_is_free(PREFERRED_PORT):
        return PREFERRED_PORT
    for port in range(PREFERRED_PORT + 1, PREFERRED_PORT + 40):
        if port_is_free(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until_ready(url: str, timeout: float = 60.0) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "api/health", timeout=1.0):
                return True
        except Exception:
            time.sleep(0.25)
    return False


def _load_window_state() -> dict:
    saved = config.load().get("window") or {}
    width = int(saved.get("width") or DEFAULT_SIZE[0])
    height = int(saved.get("height") or DEFAULT_SIZE[1])
    return {"width": max(width, MIN_SIZE[0]), "height": max(height, MIN_SIZE[1])}


def _make_window_dark(window) -> None:
    """Extend the page under the title bar and force the dark system appearance.

    A stock macOS title bar paints in the *system* appearance, so on a light-mode
    Mac the app showed a white band above a near-black UI. Making the title bar
    transparent and letting the content view run full height removes the band
    entirely; the strip stays draggable because a transparent title bar is still
    a title bar. The explicit dark appearance keeps the traffic lights and any
    system menus in the right register.
    """
    native = getattr(window, "native", None)
    if native is None:
        return

    def apply() -> None:
        try:
            import AppKit

            native.setTitlebarAppearsTransparent_(True)
            native.setTitleVisibility_(AppKit.NSWindowTitleHidden)
            native.setStyleMask_(native.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView)
            native.setAppearance_(AppKit.NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
            red, green, blue = (int(WINDOW_BACKGROUND[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
            native.setBackgroundColor_(AppKit.NSColor.colorWithRed_green_blue_alpha_(red, green, blue, 1.0))
            logging.info("window chrome set to dark, full-height content")
        except Exception:
            # A light title bar is ugly, not fatal; never take the app down for it.
            logging.exception("could not restyle the window chrome")

    try:
        # `shown` fires on pywebview's thread, and Cocoa raises on any window
        # geometry change off the main thread. Hand it to the main run loop.
        from PyObjCTools import AppHelper

        AppHelper.callAfter(apply)
    except Exception:
        logging.exception("could not schedule the window restyle")


class WindowBridge:
    """The few things the page cannot do for itself inside a WKWebView."""

    def open_external(self, target: str) -> bool:
        """Open a report or file in the user's real browser.

        A WKWebView silently drops `target="_blank"`, so a report link inside the
        window would do nothing at all. Reports are standalone HTML meant to be
        kept, mailed and printed; the browser is the right place for them.
        """
        if not isinstance(target, str) or not target.startswith(("http://127.0.0.1", "http://localhost")):
            logging.warning("refusing to open a non-local URL from the page: %r", target)
            return False
        webbrowser.open(target)
        return True


def run_windowed(app, port: int, url: str) -> int:
    """Serve on a worker thread and own the main thread with the window.

    Cocoa requires its run loop on the main thread, so the server is the thing
    that moves, not the UI. `log_config=None` keeps uvicorn from installing its
    own handlers: a windowed app has no stdout, and without this its request log
    goes to /dev/null instead of the file a user can actually send you.
    """
    import uvicorn
    import webview

    try:
        app.state.studio.window_mode = True
    except AttributeError:
        pass
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info", log_config=None))
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()

    if not wait_until_ready(url):
        logging.error("Server did not become ready; opening the window anyway.")

    state = _load_window_state()
    window = webview.create_window(
        WINDOW_TITLE,
        url,
        width=state["width"],
        height=state["height"],
        min_size=MIN_SIZE,
        resizable=True,
        text_select=True,
        confirm_close=False,
        js_api=WindowBridge(),
        # Without this the window paints white until the first frame arrives,
        # which on a dark UI reads as a flash of the wrong app.
        background_color=WINDOW_BACKGROUND,
    )
    window.events.shown += lambda: _make_window_dark(window)

    def remember_size():
        try:
            config.save({"window": {"width": int(window.width), "height": int(window.height)}})
        except Exception:
            pass  # a window that will not report its size is not worth failing over

    window.events.closing += remember_size
    logging.info("window open on %s", url)
    webview.start()  # blocks until the window closes

    logging.info("window closed; shutting the server down")
    server.should_exit = True
    thread.join(timeout=10)
    return 0


def run_headless(app, port: int, url: str) -> int:
    """No window: serve on the main thread. The smoke test drives this."""
    import uvicorn

    logging.info("headless mode; no window will open")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info", log_config=None)
    return 0


def run_browser(app, port: int, url: str) -> int:
    """Fallback when the native window is unavailable."""
    import uvicorn

    threading.Thread(target=lambda: wait_until_ready(url) and webbrowser.open(url), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info", log_config=None)
    return 0


def create_app_for(data_root: Optional[str] = None, output_root: Optional[str] = None):
    """Build the ASGI app, logging the roots it resolved."""
    from .server import create_studio_app

    resolved_data = data_root or config.default_data_root()
    resolved_output = output_root or config.default_output_root()
    logging.info("data root   : %s", resolved_data)
    logging.info("output root : %s", resolved_output)
    return create_studio_app(data_root=resolved_data, output_root=resolved_output)


def main() -> int:
    log_path = setup_logging()
    logging.info("SpatialMind Studio starting (frozen=%s, python=%s)", config.is_frozen(), sys.version.split()[0])

    try:
        app = create_app_for()
        port = choose_port()
        url = "http://localhost:%d/" % port
        logging.info("serving on %s (log: %s)", url, log_path)

        if headless():
            return run_headless(app, port, url)
        try:
            import webview  # noqa: F401
        except ImportError:
            logging.warning("pywebview is unavailable; falling back to the default browser")
            return run_browser(app, port, url)
        return run_windowed(app, port, url)
    except Exception:
        logging.exception("SpatialMind Studio failed to start")
        _report_failure(log_path)
        return 1


def _report_failure(log_path: Path) -> None:
    """With no terminal attached, a dialog is the only way to say what broke."""
    if sys.platform != "darwin":
        return
    try:
        import subprocess

        message = "SpatialMind Studio could not start.\\n\\nThe log is at:\\n%s" % log_path
        subprocess.run(
            ["osascript", "-e",
             'display dialog "%s" with title "SpatialMind Studio" buttons {"OK"} with icon stop' % message],
            check=False, timeout=30,
        )
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
