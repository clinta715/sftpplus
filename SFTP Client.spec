# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['sftp.py'],
    pathex=[],
    binaries=[],
    datas=[('sftp_theme.py', '.'), ('sftp_qt_compat.py', '.')],
    hiddenimports=['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 'paramiko', 'cryptography', 'cryptography.fernet', 'cryptography.hazmat.primitives', 'cryptography.hazmat.backends', 'cryptography.hazmat.backends.openssl'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy', 'PIL', 'cv2', 'pytest', 'icecream'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SFTP Client',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SFTP Client',
)
app = BUNDLE(
    coll,
    name='SFTP Client.app',
    icon=None,
    bundle_identifier=None,
)
