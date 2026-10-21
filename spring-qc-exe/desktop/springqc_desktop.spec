# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Spring QC Desktop - a windowed alternative to
SpringQCServer.exe (no console box), with a system tray icon so closing
the window doesn't have to mean stopping the server.

Reuses springqc_launcher.py from ../server unmodified (same GPU check,
same bundled/external Postgres handling, same uvicorn server) and the same
vendor/postgres runtime - this is a presentation layer only, not a second
implementation.

Build with:  pyinstaller springqc_desktop.spec --distpath <distpath> --workpath <workpath>
(build.bat sets sensible, disk-safe defaults - see that file.)
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None

THIS_DIR = Path(SPECPATH).resolve()  # noqa: F821  (SPECPATH is injected by PyInstaller)
SERVER_DIR = (THIS_DIR / ".." / "server").resolve()
APP_SRC = (THIS_DIR / ".." / ".." / "spring-qc-app").resolve()

if not APP_SRC.exists():
    raise SystemExit(
        f"Expected the Spring QC app source at {APP_SRC} - this spec packages "
        f"spring-qc-app as-is, it does not contain a copy of the app's logic."
    )
if not SERVER_DIR.exists():
    raise SystemExit(
        f"Expected ../server at {SERVER_DIR} - Desktop reuses springqc_launcher.py "
        f"from there instead of duplicating server lifecycle logic."
    )

ul_datas, ul_binaries, ul_hidden = collect_all("ultralytics")

vendor_pg = SERVER_DIR / "vendor" / "postgres"

datas = [
    (str(APP_SRC / "static"), "static"),
    (str(APP_SRC / "model"), "model"),
    (str(APP_SRC / "trackers"), "trackers"),
    (str(APP_SRC / "config.yaml"), "."),
    (str(SERVER_DIR / "springqc.ini"), "."),
] + ul_datas

if vendor_pg.exists():
    datas.append((str(vendor_pg), "vendor/postgres"))

icon_file = THIS_DIR / "springqc.ico"
if not icon_file.exists():
    icon_file = SERVER_DIR / "installer" / "springqc.ico"

hiddenimports = [
    "springqc_launcher",  # ../server/springqc_launcher.py, resolved via pathex below
    "app",                # spring-qc-app/app.py
    "detector",            # spring-qc-app/detector.py
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "psycopg", "psycopg.rows", "psycopg_binary",
    "PIL", "PIL._tkinter_finder", "openpyxl",
    "pystray", "pystray._win32",
] + ul_hidden

a = Analysis(
    ["springqc_desktop.py"],
    pathex=[str(THIS_DIR), str(SERVER_DIR), str(APP_SRC)],
    binaries=ul_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["matplotlib.tests", "torch.utils.tensorboard"],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="SpringQCDesktop",
    console=False,  # the whole point - a proper window, no black cmd box
    icon=str(icon_file) if icon_file.exists() else None,
)

COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False,
    upx=False,  # UPX on a multi-GB CUDA payload buys little and can trip AV heuristics
    name="SpringQCDesktop",
)
