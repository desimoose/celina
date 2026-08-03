# -*- mode: python ; coding: utf-8 -*-
# Build: powershell -File build.ps1   (or: python -m PyInstaller celina.spec)
import os
from PyInstaller.utils.hooks import collect_all

datas = [("web", "web")]          # bundle the UI; resource_path("web") finds it
binaries = []

# Obscura ships bundled so "install, add a key, search" works with no separate
# download - see scripts/fetch-obscura.ps1 (pinned + hash-verified) and
# third_party/obscura/ for the manifest + redistributed Apache-2.0 license.
# build.ps1 always runs the fetch first; fail loud here rather than silently
# shipping an exe whose central search/privacy path is missing.
_obscura_exe = os.path.join("vendor", "obscura", "obscura.exe")
if not os.path.exists(_obscura_exe):
    raise SystemExit(
        f"{_obscura_exe} not found - run scripts\\fetch-obscura.ps1 before building "
        "(build.ps1 does this automatically)."
    )
datas += [
    (_obscura_exe, "vendor/obscura"),
    ("third_party/obscura/LICENSE", "third_party/obscura"),
]
hiddenimports = [
    "finder", "gateway", "tools", "pdf", "paths", "app", "scanner",
    "sessions", "events", "redaction", "tokens", "traffic", "evidence",
    "orchestrator", "verification", "memory",
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
    name="Celina",
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
