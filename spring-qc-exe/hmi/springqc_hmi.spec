# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Spring QC HMI kiosk shell.

No ML/GPU dependencies at all (pywebview + keyboard only) - a completely
separate, lightweight build from the server. Runs on the admin PC and every
operator touch panel.
"""
from pathlib import Path

block_cipher = None
THIS_DIR = Path(SPECPATH).resolve()  # noqa: F821

a = Analysis(
    ["springqc_hmi.py"],
    pathex=[str(THIS_DIR)],
    hiddenimports=["win32timezone"],
    excludes=["tkinter"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="SpringQCHMI",
    console=False,
    icon=str(THIS_DIR / "installer" / "springqc.ico") if (THIS_DIR / "installer" / "springqc.ico").exists() else None,
)

COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="SpringQCHMI")
