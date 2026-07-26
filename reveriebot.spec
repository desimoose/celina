# -*- mode: python ; coding: utf-8 -*-
# Build: powershell -File build.ps1   (or: python -m PyInstaller reveriebot.spec)
from PyInstaller.utils.hooks import collect_all

datas = [("web", "web")]          # bundle the UI; resource_path("web") finds it
binaries = []
hiddenimports = [
    "finder", "gateway", "studio", "tools", "pdf", "paths", "app", "scanner",
]

# pywebview + its .NET bridge need their data/binaries/submodules collected.
for pkg in ("webview", "clr_loader", "pythonnet"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass  # pythonnet metadata name differs from import name; webview covers it

a = Analysis(
    ["server/desktop.py"],
    pathex=["server"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Reveriebot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,           # no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
)
