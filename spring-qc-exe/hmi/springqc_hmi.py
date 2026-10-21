"""
Spring QC HMI - kiosk shell for the operator touchscreen / admin PC.

This deliberately contains none of the product's actual logic - it is a
thin, native window (using Windows' built-in WebView2 runtime via
pywebview, not a bundled Chromium) pointed at whichever Spring QC server
the site's edge box is running. It replaces "open Chrome in --kiosk mode"
with something purpose-built:

  * a one-time setup screen (server address + which page: Operator, Admin,
    Monitor, Reports) instead of editing a .bat file,
  * a friendly "reconnecting..." screen instead of a raw browser error page
    if the edge box is rebooting or the network blips,
  * a hardware-independent exit/settings gesture (Ctrl+Alt+S / Ctrl+Alt+Q)
    that works no matter what page is currently loaded, so a supervisor can
    always get back to Windows without hunting for a keyboard shortcut the
    web page itself would have to implement.

Packaged separately from the server (see hmi/springqc_hmi.spec) - it carries
no ML/GPU dependencies at all, so it's a ~10 MB install on the admin PC and
every operator panel, independent of whatever the edge box is doing.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import keyboard
import webview

APP_NAME = "SpringQC"
CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
CONFIG_PATH = CONFIG_DIR / "hmi.json"

DEFAULT_CFG = {"host": "192.168.1.50", "port": 8001, "page": "/operator"}

PAGES = {
    "Operator (touch panel)": "/operator",
    "Admin": "/admin",
    "Monitor": "/monitor",
    "Reports": "/reports",
}


def load_cfg() -> dict:
    if CONFIG_PATH.exists():
        try:
            return {**DEFAULT_CFG, **json.loads(CONFIG_PATH.read_text(encoding="utf-8"))}
        except Exception:
            pass
    return dict(DEFAULT_CFG)


def save_cfg(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def target_url(cfg: dict) -> str:
    return f"http://{cfg['host']}:{cfg['port']}{cfg['page']}"


# ---------------------------------------------------------------- shells --

SETTINGS_HTML = """<!doctype html><html><head><meta charset="utf-8">
<style>
  body {{ margin:0; height:100vh; display:flex; align-items:center; justify-content:center;
         background:#0e141a; font-family:'Segoe UI',Arial,sans-serif; color:#eef3f7; }}
  .card {{ width:420px; background:#17212b; border:1px solid #2a3946; border-radius:14px; padding:28px; }}
  h1 {{ font-size:18px; margin:0 0 4px; }}
  p {{ color:#a7b7c4; font-size:13px; margin:0 0 20px; }}
  label {{ display:block; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.05em;
           color:#7c8f9c; margin-bottom:6px; }}
  .field {{ margin-bottom:16px; }}
  input, select {{ width:100%; height:42px; border-radius:9px; border:1px solid #2a3946; background:#0e141a;
           color:#eef3f7; padding:0 12px; font-size:14px; box-sizing:border-box; }}
  button {{ width:100%; height:46px; border:none; border-radius:9px; background:#4a9eea; color:#0e141a;
            font-weight:700; font-size:15px; cursor:pointer; margin-top:6px; }}
  .hint {{ margin-top:18px; font-size:11.5px; color:#7c8f9c; text-align:center; }}
</style></head>
<body>
  <div class="card">
    <h1>Spring QC &mdash; Station setup</h1>
    <p>Point this panel at the Spring QC edge server on your local network.</p>
    <div class="field"><label>Server address (edge box IP or hostname)</label>
      <input id="host" value="{host}"></div>
    <div class="field"><label>Port</label><input id="port" value="{port}"></div>
    <div class="field"><label>Screen</label>
      <select id="page">{page_options}</select></div>
    <button onclick="save()">Connect</button>
    <div class="hint">Ctrl+Alt+S reopens this screen &middot; Ctrl+Alt+Q exits to Windows</div>
  </div>
<script>
function save() {{
  var host = document.getElementById('host').value.trim();
  var port = document.getElementById('port').value.trim();
  var page = document.getElementById('page').value;
  pywebview.api.save_settings(host, port, page);
}}
</script>
</body></html>"""


SHELL_HTML = """<!doctype html><html><head><meta charset="utf-8">
<style>
  body {{ margin:0; height:100vh; display:flex; align-items:center; justify-content:center; flex-direction:column;
         background:#0e141a; font-family:'Segoe UI',Arial,sans-serif; color:#eef3f7; gap:18px; }}
  .spinner {{ width:40px; height:40px; border-radius:50%; border:4px solid #2a3946; border-top-color:#4a9eea;
              animation:spin 0.9s linear infinite; }}
  @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
  .msg {{ font-size:14px; color:#a7b7c4; }}
  .target {{ font-size:12px; color:#5b6b7a; font-family:'Consolas',monospace; }}
  .hint {{ position:fixed; bottom:16px; font-size:11px; color:#3a4a58; }}
</style></head>
<body>
  <div class="spinner"></div>
  <div class="msg" id="msg">Connecting to Spring QC server&hellip;</div>
  <div class="target">{target}</div>
  <div class="hint">Ctrl+Alt+S for setup &middot; Ctrl+Alt+Q to exit</div>
<script>
var target = {target_json};
var attempt = 0;
function poll() {{
  attempt++;
  fetch(target, {{ mode: 'no-cors', cache: 'no-store' }})
    .then(function () {{ window.location.href = target; }})
    .catch(function () {{
      document.getElementById('msg').textContent =
        'Waiting for the server at ' + target + ' (attempt ' + attempt + ')…';
      setTimeout(poll, 2000);
    }});
}}
poll();
</script>
</body></html>"""


def render_settings_html(cfg: dict) -> str:
    options = "".join(
        f'<option value="{path}"{" selected" if path == cfg["page"] else ""}>{label}</option>'
        for label, path in PAGES.items()
    )
    return SETTINGS_HTML.format(host=cfg["host"], port=cfg["port"], page_options=options)


def render_shell_html(cfg: dict) -> str:
    url = target_url(cfg)
    return SHELL_HTML.format(target=url, target_json=json.dumps(url))


# --------------------------------------------------------------------- api --

class Api:
    """Exposed to the settings page as `pywebview.api.*`."""

    def __init__(self):
        self.window: webview.Window | None = None

    def save_settings(self, host: str, port: str, page: str) -> bool:
        try:
            cfg = {"host": host.strip(), "port": int(port), "page": page}
        except ValueError:
            return False
        save_cfg(cfg)
        if self.window:
            self.window.load_html(render_shell_html(cfg))
        return True

    def get_settings(self) -> dict:
        return load_cfg()


def main() -> None:
    api = Api()
    cfg = load_cfg()
    first_run = not CONFIG_PATH.exists()
    initial_html = render_settings_html(cfg) if first_run else render_shell_html(cfg)

    window = webview.create_window(
        "Spring QC",
        html=initial_html,
        js_api=api,
        fullscreen=True,
        confirm_close=False,
        text_select=False,
    )
    api.window = window

    def register_hotkeys():
        # A physical-keyboard exit/settings gesture that works no matter what
        # page is currently loaded (the operator/admin pages are a different
        # origin than this shell, so in-page JS shortcuts can't reach here
        # once we've navigated to the real app) - this is why it's a global
        # OS-level hook rather than a JS keydown handler.
        keyboard.add_hotkey("ctrl+alt+s", lambda: window.load_html(render_settings_html(load_cfg())))
        keyboard.add_hotkey("ctrl+alt+q", lambda: window.destroy())

    threading.Thread(target=register_hotkeys, daemon=True).start()

    webview.start(gui="edgechromium")  # Windows' built-in WebView2 - no bundled browser


if __name__ == "__main__":
    main()
