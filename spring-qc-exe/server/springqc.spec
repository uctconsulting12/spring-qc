# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the Spring QC Server (the GPU inference box).

Produces one onedir bundle (dist/SpringQCServer/) with two entry points:
    SpringQCServer.exe   - console app: double-click to run in the foreground,
                            opens the admin page in the default browser.
    SpringQCService.exe  - the same server, wrapped as a Windows Service for
                            unattended production use (no console window).

Both share every dependency (torch, ultralytics, opencv, the app itself) so
they don't duplicate several GB of CUDA binaries between two separate builds.

Build with:  pyinstaller springqc.spec --distpath <distpath> --workpath <workpath>
(server/build.bat sets sensible, disk-safe defaults - see that file.)
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None

THIS_DIR = Path(SPECPATH).resolve()  # noqa: F821  (SPECPATH is injected by PyInstaller)
APP_SRC = (THIS_DIR / ".." / ".." / "spring-qc-app").resolve()

if not APP_SRC.exists():
    raise SystemExit(
        f"Expected the Spring QC app source at {APP_SRC} - this spec packages "
        f"spring-qc-app as-is, it does not contain a copy of the app's logic."
    )

# ultralytics ships yaml configs, fonts, etc. as package data that PyInstaller's
# default import analysis won't pick up on its own.
ul_datas, ul_binaries, ul_hidden = collect_all("ultralytics")

vendor_pg = THIS_DIR / "vendor" / "postgres"

datas = [
    (str(APP_SRC / "static"), "static"),
    (str(APP_SRC / "model"), "model"),
    (str(APP_SRC / "trackers"), "trackers"),
    (str(APP_SRC / "config.yaml"), "."),
    (str(THIS_DIR / "springqc.ini"), "."),
] + ul_datas

if vendor_pg.exists():
    # Bundled Postgres runtime (bin/lib/share only - initdb/pg_ctl/postgres
    # and what they need; the dev headers, docs, and pgAdmin that EDB's zip
    # also ships are stripped out at vendor-population time, not here).
    datas.append((str(vendor_pg), "vendor/postgres"))

hiddenimports = [
    "app",        # spring-qc-app/app.py, resolved via pathex below
    "detector",   # spring-qc-app/detector.py
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "psycopg", "psycopg.rows", "psycopg_binary",
    "PIL", "openpyxl",
] + ul_hidden

common_excludes = ["tkinter", "matplotlib.tests", "torch.utils.tensorboard"]

launcher_a = Analysis(
    ["springqc_launcher.py"],
    pathex=[str(THIS_DIR), str(APP_SRC)],
    binaries=ul_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=common_excludes,
    cipher=block_cipher,
)

service_a = Analysis(
    ["springqc_service.py"],
    pathex=[str(THIS_DIR), str(APP_SRC)],
    binaries=ul_binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["win32timezone", "servicemanager"],
    excludes=common_excludes,
    cipher=block_cipher,
)

MERGE(
    (launcher_a, "springqc_launcher", "SpringQCServer"),
    (service_a, "springqc_service", "SpringQCService"),
)

launcher_pyz = PYZ(launcher_a.pure, launcher_a.zipped_data, cipher=block_cipher)
service_pyz = PYZ(service_a.pure, service_a.zipped_data, cipher=block_cipher)

launcher_exe = EXE(
    launcher_pyz, launcher_a.scripts, [],
    exclude_binaries=True,
    name="SpringQCServer",
    console=True,          # foreground / first-run use - operator sees log output
    icon=str(THIS_DIR / "installer" / "springqc.ico") if (THIS_DIR / "installer" / "springqc.ico").exists() else None,
)

service_exe = EXE(
    service_pyz, service_a.scripts, [],
    exclude_binaries=True,
    name="SpringQCService",
    console=False,         # runs headless under the Service Control Manager
    icon=str(THIS_DIR / "installer" / "springqc.ico") if (THIS_DIR / "installer" / "springqc.ico").exists() else None,
)

COLLECT(
    launcher_exe, launcher_a.binaries, launcher_a.zipfiles, launcher_a.datas,
    service_exe, service_a.binaries, service_a.zipfiles, service_a.datas,
    strip=False,
    upx=False,   # UPX on a multi-GB CUDA payload buys little and can trip AV heuristics
    name="SpringQCServer",
)
