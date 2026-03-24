# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for SFTP Client

Build commands:
    pyinstaller sftp_client.spec
    
For platform-specific builds:
    macOS: pyinstaller --windowed --onefile --name "SFTP Client" sftp_client.spec
    Windows: pyinstaller --windowed --onefile --name "SFTP Client" sftp_client.spec
    Linux: pyinstaller --onefile --name "sftp-client" sftp_client.spec
"""

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect all PySide6 data files (plugins, translations, etc.)
datas = []
datas += collect_data_files('PySide6')
datas += collect_data_files('paramiko')

# Hidden imports that PyInstaller might miss
hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'paramiko',
    'cryptography',
    'cryptography.fernet',
    'cryptography.hazmat.primitives',
    'cryptography.hazmat.backends',
    'cryptography.hazmat.backends.openssl',
]

# Platform-specific hidden imports
if sys.platform == 'win32':
    hiddenimports.extend([
        'paramiko.win_openssh',
    ])
elif sys.platform == 'darwin':
    hiddenimports.extend([
        'paramiko.win_openssh',  # Sometimes needed on macOS too
    ])
else:
    hiddenimports.extend([
        'pty',
        'fcntl',
        'termios',
    ])

# All modules from the sftp package
sftp_modules = [
    'sftp',
    'sftp_browserclass',
    'sftp_browser_mixins',
    'sftp_commands',
    'sftp_connection_pool',
    'sftp_connections_widget',
    'sftp_creds',
    'sftp_downloadworkerclass',
    'sftp_drag_drop',
    'sftp_file_browser_panel',
    'sftp_filebrowserclass',
    'sftp_filetablemodel',
    'sftp_hostdataeditor',
    'sftp_local_terminal_widget',
    'sftp_logging',
    'sftp_operations',
    'sftp_platform',
    'sftp_preferences',
    'sftp_preview_widget',
    'sftp_qt_compat',
    'sftp_remotefilebrowserclass',
    'sftp_remotefiletablemodel',
    'sftp_session',
    'sftp_session_executor',
    'sftp_sortfiltermodel',
    'sftp_terminal_widget',
    'sftp_textviewer',
    'sftp_theme',
    'sftp_toolbar_customizer',
    'sftp_transfer_handler',
    'sftp_transfer_history',
    'sftp_transfer_queue_widget',
]
hiddenimports.extend(sftp_modules)

a = Analysis(
    ['sftp.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'cv2',
        'pytest',
        'icecream',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Platform-specific bundle
if sys.platform == 'darwin':
    # macOS .app bundle
    pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
    
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
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='SFTP Client',
    )
    
    app = BUNDLE(
        coll,
        name='SFTP Client.app',
        icon=None,  # Add .icns file path here if you have an icon
        bundle_identifier='com.sftpclient.app',
        info_plist={
            'CFBundleName': 'SFTP Client',
            'CFBundleDisplayName': 'SFTP Client',
            'CFBundleVersion': '2.1.0',
            'CFBundleShortVersionString': '2.1.0',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '10.13.0',
        },
    )

elif sys.platform == 'win32':
    # Windows executable
    pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
    
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='SFTP Client',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,  # GUI application
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=None,  # Add .ico file path here if you have an icon
    )

else:
    # Linux executable
    pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
    
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='sftp-client',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,  # GUI application
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )