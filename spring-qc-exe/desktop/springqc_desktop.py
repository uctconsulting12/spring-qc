"""
Spring QC Desktop - a windowed front-end for the same server the console
(SpringQCServer.exe) and service (SpringQCService.exe) exes run, replacing
the black cmd console with a small status window and a system tray icon,
so closing the window doesn't have to mean stopping the server.

This is a *packaging and presentation* layer only, exactly like
springqc_launcher.py itself: it imports SpringQCServer from
springqc_launcher unmodified and just gives it a different front end. No
detection/tracking/API logic lives here, and nothing in ../server or
../../spring-qc-app is touched.
"""
from __future__ import annotations

import logging
import queue
import socket
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, scrolledtext

# springqc_launcher.py lives in ../server relative to this file in dev mode
# (running this script directly with `python`, for iterating without a
# rebuild); springqc_desktop.spec bundles it alongside this script when
# built, so the same bare `import springqc_launcher` resolves in both.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str((Path(__file__).resolve().parent / ".." / "server").resolve()))

from springqc_launcher import FROZEN, SpringQCServer, _setup_logging  # noqa: E402

log = logging.getLogger("springqc.desktop")

try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False


class LogTailHandler(logging.Handler):
    """Feeds log records into a thread-safe queue the Tk window polls on its
    own thread - the server runs on a background thread, and touching Tk
    widgets directly from there is not safe."""

    def __init__(self, q: "queue.Queue[str]"):
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        self.q.put(self.format(record))


def _lan_ip() -> str:
    """Best-effort LAN-facing IP address - the one other PCs on the network
    would actually use to reach this machine, as opposed to 127.0.0.1 which
    only ever works from this PC itself. Opens no real connection (UDP
    "connect" just picks the outbound interface/route); falls back to
    localhost if there's no network at all."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _tray_image() -> "Image.Image":
    img = Image.new("RGB", (64, 64), "#16294a")
    d = ImageDraw.Draw(img)
    d.ellipse((14, 14, 50, 50), fill="#2e6bff")
    return img


class DesktopApp:
    BG = "#0f1c33"
    PANEL = "#16294a"
    FG = "#e7ecf7"
    ACCENT = "#2e6bff"
    OK = "#9fd8a8"
    WARN = "#e2b25c"

    def __init__(self) -> None:
        self.server = SpringQCServer()
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.server_thread: threading.Thread | None = None
        self.tray_icon: "pystray.Icon | None" = None
        self.running = False
        self.lan_ip = _lan_ip()

        self.root = tk.Tk()
        self.root.title("Spring QC Server")
        self.root.geometry("680x440")
        self.root.minsize(600, 360)
        self.root.configure(bg=self.BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._set_icon()
        self._build_ui()
        self._poll_log_queue()

    def _set_icon(self) -> None:
        try:
            base = Path(sys._MEIPASS) if FROZEN else Path(__file__).resolve().parent  # type: ignore[attr-defined]
            icon_path = base / "springqc.ico"
            if icon_path.exists():
                self.root.iconbitmap(str(icon_path))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=self.PANEL)
        header.pack(fill="x")
        tk.Label(
            header, text="Spring QC Server", bg=self.PANEL, fg=self.FG,
            font=("Segoe UI", 14, "bold"), pady=12,
        ).pack(side="left", padx=16)

        status_frame = tk.Frame(self.root, bg=self.BG)
        status_frame.pack(fill="x", padx=16, pady=12)

        self.status_var = tk.StringVar(value="Starting...")
        self.url_var = tk.StringVar(value="")

        tk.Label(
            status_frame, textvariable=self.status_var, bg=self.BG, fg=self.WARN,
            font=("Segoe UI", 11, "bold"), anchor="w",
        ).pack(fill="x")
        tk.Label(
            status_frame, textvariable=self.url_var, bg=self.BG, fg=self.FG,
            font=("Consolas", 10), anchor="w",
        ).pack(fill="x", pady=(4, 0))

        btn_frame = tk.Frame(self.root, bg=self.BG)
        btn_frame.pack(fill="x", padx=16, pady=(0, 12))

        self.open_btn = tk.Button(
            btn_frame, text="Open Dashboard", command=self._open_dashboard,
            bg=self.ACCENT, fg="white", relief="flat", padx=14, pady=7,
            state="disabled", cursor="hand2",
        )
        self.open_btn.pack(side="left")

        self.open_hmi_btn = tk.Button(
            btn_frame, text="Open Operator (HMI)", command=self._open_hmi,
            bg="#2a3550", fg=self.FG, relief="flat", padx=14, pady=7,
            state="disabled", cursor="hand2",
        )
        self.open_hmi_btn.pack(side="left", padx=(8, 0))

        self.stop_btn = tk.Button(
            btn_frame, text="Stop Server", command=self._stop_server,
            bg="#5a2e2e", fg="white", relief="flat", padx=14, pady=7,
            state="disabled", cursor="hand2",
        )
        self.stop_btn.pack(side="left", padx=(8, 0))

        if TRAY_AVAILABLE:
            tk.Button(
                btn_frame, text="Minimize to Tray", command=self._minimize_to_tray,
                bg="#2a3550", fg=self.FG, relief="flat", padx=14, pady=7, cursor="hand2",
            ).pack(side="right")

        tk.Label(
            self.root, text="Log", bg=self.BG, fg="#7f8cae",
            font=("Segoe UI", 9), anchor="w",
        ).pack(fill="x", padx=16)

        self.log_box = scrolledtext.ScrolledText(
            self.root, bg="#0a1420", fg="#c9d4ea", insertbackground="#c9d4ea",
            font=("Consolas", 9), relief="flat", height=14, borderwidth=0,
        )
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(2, 16))
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        handler = LogTailHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

        self.running = True
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()
        self.root.after(400, self._poll_server_ready)
        self.root.mainloop()

    def _run_server(self) -> None:
        try:
            # We handle opening the browser ourselves once /poll confirms the
            # server answered, so the window and the browser tab appear in
            # sync instead of racing each other.
            self.server.start(open_browser=False)
        except Exception:
            log.exception("Spring QC server failed to start")
        finally:
            self.running = False

    def _poll_server_ready(self) -> None:
        port = self.server.cfg.getint("server", "port", fallback=8001)
        import urllib.request
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.5)
            self.status_var.set("● Running")
            self.url_var.set(f"http://{self.lan_ip}:{port}   (this is the address to share with other PCs)")
            self.open_btn.config(state="normal")
            self.open_hmi_btn.config(state="normal")
            self.stop_btn.config(state="normal")
            webbrowser.open(f"http://{self.lan_ip}:{port}/admin")
            return
        except Exception:
            pass
        if self.running:
            self.root.after(500, self._poll_server_ready)
        else:
            self.status_var.set("● Failed to start - see log below")

    def _open_dashboard(self) -> None:
        port = self.server.cfg.getint("server", "port", fallback=8001)
        webbrowser.open(f"http://{self.lan_ip}:{port}/admin")

    def _open_hmi(self) -> None:
        # "HMI" here is exactly what it means for this product: a normal web
        # page (the Operator station) opened in a normal browser - there is
        # no separate app to launch. See ../client-shortcuts/README.md.
        port = self.server.cfg.getint("server", "port", fallback=8001)
        webbrowser.open(f"http://{self.lan_ip}:{port}/operator")

    def _stop_server(self) -> None:
        if messagebox.askyesno(
            "Stop Spring QC Server",
            "This stops inference and takes every connected browser offline. Continue?",
        ):
            self.status_var.set("● Stopping...")
            self.stop_btn.config(state="disabled")
            self.open_btn.config(state="disabled")
            self.open_hmi_btn.config(state="disabled")
            self.server.request_stop()

    # ------------------------------------------------------------------
    # Window / tray
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        if TRAY_AVAILABLE:
            self._minimize_to_tray()
        else:
            self._confirm_exit()

    def _confirm_exit(self) -> None:
        if messagebox.askyesno(
            "Exit Spring QC Server",
            "Closing this will stop the server and take every connected browser offline. Exit anyway?",
        ):
            self.server.request_stop()
            self.root.after(300, self._shutdown)

    def _shutdown(self) -> None:
        if self.tray_icon is not None:
            self.tray_icon.stop()
        self.root.destroy()

    def _minimize_to_tray(self) -> None:
        self.root.withdraw()
        if self.tray_icon is None:
            menu = pystray.Menu(
                pystray.MenuItem("Open Dashboard", lambda: self._open_dashboard()),
                pystray.MenuItem("Open Operator (HMI)", lambda: self._open_hmi()),
                pystray.MenuItem("Show Window", lambda: self.root.after(0, self.root.deiconify)),
                pystray.MenuItem("Stop && Exit", lambda: self.root.after(0, self._exit_from_tray)),
            )
            self.tray_icon = pystray.Icon("springqc", _tray_image(), "Spring QC Server", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _exit_from_tray(self) -> None:
        self.root.deiconify()
        self._confirm_exit()

    # ------------------------------------------------------------------
    # Log polling
    # ------------------------------------------------------------------

    def _poll_log_queue(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_box.configure(state="normal")
            self.log_box.insert("end", line + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.root.after(200, self._poll_log_queue)


def main() -> None:
    _setup_logging()
    log.info("Spring QC Desktop starting (frozen=%s)", FROZEN)
    app = DesktopApp()
    app.start()


if __name__ == "__main__":
    main()
