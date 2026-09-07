# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the SpendSlicer desktop builds.

Build from the repo root, after the frontend has been built:

    cd frontend && npm ci && npm run build && cd ..
    python packaging/make_icons.py
    pyinstaller packaging/spendslicer.spec --noconfirm

Produces dist/SpendSlicer.app on macOS and dist/SpendSlicer/SpendSlicer.exe on
Windows. The wrapper scripts in this directory turn those into a .dmg and a
.zip respectively.

Why one-dir rather than --onefile: a onefile build unpacks ~200MB to a temp
directory on every launch, which adds seconds of startup and trips endpoint
security tooling. One-dir starts immediately and is what both installers want
anyway.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

REPO = Path(SPECPATH).resolve().parent
ICONS = REPO / "packaging" / "icons"

datas = []
binaries = []
hiddenimports = []

# The dashboard bundle. Without this the app starts and serves a 404 at /app.
static_dir = REPO / "spendslicer" / "web" / "static"
if not (static_dir / "index.html").is_file():
    raise SystemExit(
        "spendslicer/web/static/index.html is missing — run `cd frontend && npm run build` first."
    )
datas.append((str(static_dir), "spendslicer/web/static"))

# botocore ships its entire service model as JSON data files; without them
# every client() call fails with "Unknown service".
datas += collect_data_files("botocore")
datas += collect_data_files("boto3")

# CUR warehouse. duckdb is a compiled extension with its own shared library,
# so collect_all is required, not just a hidden import. PyArrow used to be
# collected here too and was 118MB of a 254MB bundle — nothing imported it,
# duckdb reads and writes Parquet natively.
for pkg in ("duckdb",):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception as exc:  # pragma: no cover
        print(f"warning: could not collect {pkg}: {exc}")

# uvicorn resolves its protocol/loop/lifespan implementations by string at
# runtime, so PyInstaller's import graph never sees them.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += [
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "anyio._backends._asyncio",
]

# pywebview picks its GUI backend at runtime.
try:
    wv_datas, wv_binaries, wv_hidden = collect_all("webview")
    datas += wv_datas
    binaries += wv_binaries
    hiddenimports += wv_hidden
except Exception as exc:  # pragma: no cover
    print(f"warning: could not collect webview: {exc}")

hiddenimports += collect_submodules("spendslicer")

# Test-only and plotting stacks that would otherwise ride along via transitive
# imports and add tens of megabytes.
excludes = [
    # duckdb.polars_io imports pyarrow for optional Arrow/Polars interop we
    # never touch, and collect_all("duckdb") drags it in — 117MB of a 253MB
    # bundle. Verified duckdb reads and writes Parquet with pyarrow absent
    # entirely (tests/test_cur_*.py pass in a venv without it).
    "pyarrow",
    "polars",
    "tkinter",
    "matplotlib",
    "PIL",
    "pytest",
    "moto",
    "mypy",
    "ruff",
    "IPython",
    "notebook",
    "pandas.tests",
    "numpy.distutils",
]

a = Analysis(
    [str(REPO / "packaging" / "entry.py")],
    pathex=[str(REPO)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SpendSlicer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-packed binaries trip antivirus heuristics on Windows.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICONS / "icon.ico") if sys.platform == "win32" else str(ICONS / "icon.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SpendSlicer",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="SpendSlicer.app",
        icon=str(ICONS / "icon.icns"),
        bundle_identifier="io.spendslicer.desktop",
        info_plist={
            "CFBundleName": "SpendSlicer",
            "CFBundleDisplayName": "SpendSlicer",
            "CFBundleShortVersionString": os.environ.get("SPENDSLICER_VERSION", "0.3.0"),
            "CFBundleVersion": os.environ.get("SPENDSLICER_VERSION", "0.3.0"),
            "NSHighResolutionCapable": True,
            # No server, no inbound listener beyond loopback, no camera/mic.
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "MIT licensed. © SpendSlicer contributors.",
        },
    )
