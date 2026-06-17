"""
Tray launcher — the PyInstaller entry point for the packaged Windows app.

Runs the FastAPI backend (which also serves the built React UI) on
http://127.0.0.1:8000 inside this process, shows a system-tray icon, and opens the
browser once on first start. A tray app (rather than a console window) keeps the
server alive in the background for manual syncs without anything visible to close
by accident.

Tray menu: Open · Run sync now · Quit.
"""
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser


def _ensure_std_streams():
    """In a windowed PyInstaller build (console=False) sys.stdout/stderr are None,
    which crashes libraries that probe them (e.g. uvicorn's log formatter calls
    sys.stdout.isatty()). Point them at a real, writable stream — a log file under
    the app's data dir when possible, otherwise the null device."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    stream = None
    try:
        log_dir = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
            "sHaRe-sync", "logs",
        )
        os.makedirs(log_dir, exist_ok=True)
        stream = open(os.path.join(log_dir, "launcher.log"), "a", buffering=1, encoding="utf-8")
    except Exception:
        stream = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


_ensure_std_streams()

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _error_box(message: str):
    """Show a native message box on Windows; fall back to stderr elsewhere."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "sHaRe sync", 0x10)
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def _wait_until_up(timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{URL}/api/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def _trigger_sync():
    try:
        req = urllib.request.Request(f"{URL}/api/sync/trigger", method="POST")
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:  # noqa: BLE001
        _error_box(f"Could not start a sync:\n{e}")


def _make_icon_image():
    from PIL import Image, ImageDraw

    # Prefer the bundled cloud-sync mark (app.ico). In a PyInstaller one-dir build
    # data files live under sys._MEIPASS; in dev it sits next to this file.
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(base, "app.ico"),
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")):
        try:
            return Image.open(cand).convert("RGBA")
        except Exception:
            pass

    # Fallback: simple blue disc with a play glyph (rarely needed).
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), fill=(37, 99, 235, 255))
    d.polygon([(26, 20), (26, 44), (46, 32)], fill=(255, 255, 255, 255))
    return img


def main():
    if _port_in_use(HOST, PORT):
        # Most likely the app (or its dev server) is already running — just open it.
        webbrowser.open(URL)
        _error_box(
            f"Port {PORT} is already in use.\n\n"
            "sHaRe sync may already be running — opening it in your browser. "
            "If something else is using the port, close it and relaunch."
        )
        return

    import uvicorn

    config = uvicorn.Config("backend.main:app", host=HOST, port=PORT, log_level="info")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    server_thread.start()

    if _wait_until_up():
        webbrowser.open(URL)
    else:
        _error_box("The backend did not start in time. Check the logs and relaunch.")

    import pystray
    from pystray import MenuItem as Item

    def on_open(icon, item):
        webbrowser.open(URL)

    def on_sync(icon, item):
        threading.Thread(target=_trigger_sync, daemon=True).start()

    def on_quit(icon, item):
        server.should_exit = True
        icon.stop()

    icon = pystray.Icon(
        "share_sync",
        _make_icon_image(),
        "sHaRe sync",
        menu=pystray.Menu(
            Item("Open", on_open, default=True),
            Item("Run sync now", on_sync),
            Item("Quit", on_quit),
        ),
    )
    icon.run()  # blocks until on_quit -> icon.stop()


if __name__ == "__main__":
    main()
