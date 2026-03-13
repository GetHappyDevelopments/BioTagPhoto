# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project_dir = Path.cwd()
datas = [
    (str(project_dir / "ui" / "BioTagPhotoIcon.png"), "ui"),
    (str(project_dir / "ui" / "BioTagPhotoStart.png"), "ui"),
    (str(project_dir / "LICENSE"), "."),
    (str(project_dir / "NOTICE"), "."),
    (str(project_dir / "THIRD_PARTY_NOTICES.md"), "."),
    (str(project_dir / "PRIVACY.md"), "."),
    (str(project_dir / "LEGAL.md"), "."),
]

binaries = []
hiddenimports = []

for package_name in ("PySide6", "cv2", "insightface", "onnxruntime", "skimage", "sklearn", "scipy"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package_name)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        pass

a = Analysis(
    [str(project_dir / "main.py")],
    pathex=[str(project_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="BioTagPhoto",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_dir / "ui" / "BioTagPhotoIcon.png"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BioTagPhoto",
)
