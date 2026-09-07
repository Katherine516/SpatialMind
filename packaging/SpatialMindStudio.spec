# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SpatialMind Studio.

Bundles only what the Studio imports. requirements.txt installs the whole
workstation stack -- napari, vitessce, chromadb, celery, torch -- and none of it
is on the Studio's import path; pulling it in would add gigabytes and a much
larger surface for a broken hidden import.
"""

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
APP_NAME = "SpatialMind Studio"
ICON = os.path.join(SPECPATH, "SpatialMindStudio.icns")

# Packages whose data files, dylibs and submodules must all come along. Each is
# on the Studio's real import path.
BUNDLE_PACKAGES = [
    "scanpy", "squidpy", "anndata", "sklearn", "scipy", "pandas", "numpy",
    "numba", "llvmlite", "h5py", "pyarrow", "matplotlib", "igraph", "leidenalg",
    "tifffile", "reportlab", "PIL", "networkx", "statsmodels", "pynndescent",
    "umap", "natsort", "joblib", "threadpoolctl", "session_info", "legacy_api_wrap",
    "uvicorn", "fastapi", "starlette", "pydantic", "pydantic_core", "anyio", "click", "h11",
    # The native window: pywebview drives a WKWebView through pyobjc.
    "webview", "objc", "Foundation", "AppKit", "WebKit", "Quartz",
]

datas, binaries, hiddenimports = [], [], []
for package in BUNDLE_PACKAGES:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception:
        continue  # optional in some environments; the build verifies imports later
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# spatialmind.batch.celery_app imports celery, which the Studio never uses and
# which is excluded below. Collecting it would drag the whole broker stack in.
hiddenimports += [
    module for module in collect_submodules("spatialmind")
    if not module.startswith("spatialmind.batch")
]
hiddenimports += [
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
    "encodings.idna", "pkg_resources",
    # pywebview picks its backend at runtime, so the Cocoa one is never seen as
    # an import and has to be named explicitly.
    "webview.platforms.cocoa", "webview.window", "webview.util",
]

# The web UI ships inside the bundle.
datas += [(os.path.join(ROOT, "spatialmind", "app", "static"), os.path.join("spatialmind", "app", "static"))]

EXCLUDES = [
    "napari", "vitessce", "chromadb", "celery", "redis", "kombu", "flower",
    "torch", "torchvision", "tensorflow", "jax",
    "cv2", "bokeh", "plotly", "altair", "datashader", "dask", "distributed",
    "s3fs", "fsspec.implementations.http", "spatialdata", "spatialdata_io",
    "napari_plugin_engine", "PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter",
    "IPython", "jupyter", "notebook", "jupyterlab", "ipykernel", "ipywidgets",
    "pytest", "PyInstaller", "openai", "anthropic",
]

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SpatialMindStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,   # host architecture; see scripts/build_macos_app.py
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON if os.path.exists(ICON) else None,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, upx_exclude=[], name="SpatialMindStudio",
)

app = BUNDLE(
    coll,
    name="%s.app" % APP_NAME,
    icon=ICON if os.path.exists(ICON) else None,
    bundle_identifier="com.spatialmind.studio",
    version="1.0.0",
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "NSHighResolutionCapable": True,
        # The window loads http://127.0.0.1; App Transport Security blocks plain
        # HTTP unless local networking is allowed explicitly.
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        # The UI is a browser tab; the app itself shows no window.
        "LSBackgroundOnly": False,
        "LSMinimumSystemVersion": "11.0",
        "NSHumanReadableCopyright": "SpatialMind",
        # macOS asks before letting the app read these folders. Without a reason
        # string the prompt is bare and easy to refuse by accident, and a refused
        # or unanswered prompt looks exactly like the app hanging.
        "NSDocumentsFolderUsageDescription":
            "SpatialMind Studio reads Xenium output bundles from the folder you choose.",
        "NSDesktopFolderUsageDescription":
            "SpatialMind Studio reads Xenium output bundles from the folder you choose.",
        "NSDownloadsFolderUsageDescription":
            "SpatialMind Studio reads Xenium output bundles from the folder you choose.",
        "NSRemovableVolumesUsageDescription":
            "SpatialMind Studio reads Xenium output bundles from external drives you choose.",
    },
)
