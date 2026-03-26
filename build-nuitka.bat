@echo off
setlocal enabledelayedexpansion

echo Building SFTP Client with Nuitka for Windows...

:: Check if Nuitka is installed
python -c "import nuitka" 2>nul
if %errorlevel% neq 0 (
    echo Installing Nuitka...
    pip install nuitka
)

:: Clean previous builds
echo Cleaning previous builds...
rd /s /q build 2>nul
rd /s /q dist 2>nul
rd /s /q *.build 2>nul
rd /s /q *.dist 2>nul
del /q sftp.exe 2>nul

:: Create dist directory
if not exist dist mkdir dist

:: Define modules to include
set INCLUDE_OPTS=^
 --include-module=sftp_about^
 --include-module=sftp_browserclass^
 --include-module=sftp_browser_mixins^
 --include-module=sftp_commands^
 --include-module=sftp_connection_pool^
 --include-module=sftp_connections_widget^
 --include-module=sftp_creds^
 --include-module=sftp_downloadworkerclass^
 --include-module=sftp_drag_drop^
 --include-module=sftp_file_browser_panel^
 --include-module=sftp_filebrowserclass^
 --include-module=sftp_filetablemodel^
 --include-module=sftp_hostdataeditor^
 --include-module=sftp_local_terminal_widget^
 --include-module=sftp_logging^
 --include-module=sftp_operations^
 --include-module=sftp_platform^
 --include-module=sftp_preferences^
 --include-module=sftp_preview_widget^
 --include-module=sftp_qt_compat^
 --include-module=sftp_remotefilebrowserclass^
 --include-module=sftp_remotefiletablemodel^
 --include-module=sftp_session^
 --include-module=sftp_session_executor^
 --include-module=sftp_sortfiltermodel^
 --include-module=sftp_terminal_widget^
 --include-module=sftp_textviewer^
 --include-module=sftp_theme^
 --include-module=sftp_toolbar_customizer^
 --include-module=sftp_transfer_handler^
 --include-module=sftp_transfer_history^
 --include-module=sftp_transfer_queue_widget

:: Run Nuitka
python -m nuitka ^
    --assume-yes-for-downloads ^
    --follow-imports ^
    --include-module=PySide6.QtCore ^
    --include-module=PySide6.QtGui ^
    --include-module=PySide6.QtWidgets ^
    --include-module=paramiko ^
    --include-module=cryptography ^
    --include-module=cryptography.fernet ^
    --include-module=cryptography.hazmat.primitives ^
    --include-module=cryptography.hazmat.backends ^
    --include-module=cryptography.hazmat.backends.openssl ^
    --include-data-file=sftp_theme.py=sftp_theme.py ^
    --include-data-file=sftp_qt_compat.py=sftp_qt_compat.py ^
    %INCLUDE_OPTS% ^
    --standalone ^
    --onefile ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=none ^
    --enable-plugin=pyside6 ^
    sftp.py

:: Move to dist directory
if exist sftp.exe (
    move sftp.exe "dist\SFTP Client.exe"
)

echo.
echo Build complete!
echo Windows executable: dist\SFTP Client.exe

endlocal
pause
