@echo off
setlocal enabledelayedexpansion

echo Building SFTP Client for Windows...

:: Check for PyInstaller
python -c "import PyInstaller" 2>nul
if %errorlevel% neq 0 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

:: Clean previous builds
echo Cleaning previous builds...
rd /s /q build 2>nul
rd /s /q dist 2>nul
rd /s /q __pycache__ 2>nul
del /q *.spec 2>nul

:: Define hidden imports
set HIDDEN_IMPORTS=^
 --hidden-import "PySide6.QtCore"^
 --hidden-import "PySide6.QtGui"^
 --hidden-import "PySide6.QtWidgets"^
 --hidden-import "paramiko"^
 --hidden-import "cryptography"^
 --hidden-import "cryptography.fernet"^
 --hidden-import "cryptography.hazmat.primitives"^
 --hidden-import "cryptography.hazmat.backends"^
 --hidden-import "cryptography.hazmat.backends.openssl"^
 --hidden-import "sftp_about"^
 --hidden-import "sftp_browser_mixins"^
 --hidden-import "sftp_browserclass"^
 --hidden-import "sftp_commands"^
 --hidden-import "sftp_connection_pool"^
 --hidden-import "sftp_connections_widget"^
 --hidden-import "sftp_creds"^
 --hidden-import "sftp_drag_drop"^
 --hidden-import "sftp_file_browser_panel"^
 --hidden-import "sftp_filebrowserclass"^
 --hidden-import "sftp_filetablemodel"^
 --hidden-import "sftp_hostdataeditor"^
 --hidden-import "sftp_local_terminal_widget"^
 --hidden-import "sftp_logging"^
 --hidden-import "sftp_operations"^
 --hidden-import "sftp_platform"^
 --hidden-import "sftp_preferences"^
 --hidden-import "sftp_preview_widget"^
 --hidden-import "sftp_qt_compat"^
 --hidden-import "sftp_remotefilebrowserclass"^
 --hidden-import "sftp_remotefiletablemodel"^
 --hidden-import "sftp_session"^
 --hidden-import "sftp_session_executor"^
 --hidden-import "sftp_sortfiltermodel"^
 --hidden-import "sftp_terminal_widget"^
 --hidden-import "sftp_textviewer"^
 --hidden-import "sftp_theme"^
 --hidden-import "sftp_toolbar_customizer"^
 --hidden-import "sftp_transfer_handler"^
 --hidden-import "sftp_transfer_history"^
 --hidden-import "sftp_transfer_queue_widget"

:: Run PyInstaller
pyinstaller --windowed ^
            --onedir ^
            --name "SFTP Client" ^
            --paths "." ^
            --add-data "sftp_theme.py;." ^
            --add-data "sftp_qt_compat.py;." ^
            --collect-all "PySide6" ^
            --collect-all "paramiko" ^
            --collect-all "cryptography" ^
            --collect-all "encodings" ^
            --hidden-import "encodings" ^
            --hidden-import "encodings.ascii" ^
            --hidden-import "encodings.utf_8" ^
            --hidden-import "encodings.latin_1" ^
            --hidden-import "encodings.charmap" ^
            --hidden-import "paramiko.win_openssh" ^
            %HIDDEN_IMPORTS% ^
            --exclude-module "tkinter" ^
            --exclude-module "matplotlib" ^
            --exclude-module "numpy" ^
            --exclude-module "pandas" ^
            --exclude-module "scipy" ^
            --exclude-module "PIL" ^
            --exclude-module "cv2" ^
            --exclude-module "pytest" ^
            --exclude-module "icecream" ^
            sftp.py

echo.
echo Build complete!
echo Windows folder: dist/SFTP Client/
echo Run: dist/SFTP Client/SFTP Client.exe

endlocal
pause
