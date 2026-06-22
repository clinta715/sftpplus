#!/bin/bash
# Build script for SFTP Client standalone executables
# Usage: ./build.sh [platform]
#   platform: macos, windows, linux (default: current platform)

set -e

# Detect current platform
detect_platform() {
    case "$(uname -s)" in
        Darwin*)    echo "macos";;
        CYGWIN*|MINGW*|MSYS*)    echo "windows";;
        Linux*)     echo "linux";;
        *)          echo "unknown";;
    esac
}

# Get target platform
PLATFORM="${1:-$(detect_platform)}"

echo "Building SFTP Client for $PLATFORM..."

# Install PyInstaller if not present
if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "Installing PyInstaller..."
    pip3 install pyinstaller
fi

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build/ dist/ __pycache__/ *.spec 2>/dev/null || true

# Common hidden imports for all platforms
HIDDEN_IMPORTS=(
    --hidden-import "PySide6.QtCore"
    --hidden-import "PySide6.QtGui"
    --hidden-import "PySide6.QtWidgets"
    --hidden-import "paramiko"
    --hidden-import "cryptography"
    --hidden-import "cryptography.fernet"
    --hidden-import "cryptography.hazmat.primitives"
    --hidden-import "cryptography.hazmat.backends"
    --hidden-import "cryptography.hazmat.backends.openssl"
    --hidden-import "sftp_about"
    --hidden-import "sftp_browser_mixins"
    --hidden-import "sftp_browserclass"
    --hidden-import "sftp_commands"
    --hidden-import "sftp_connection_pool"
    --hidden-import "sftp_connections_widget"
    --hidden-import "sftp_creds"
    --hidden-import "sftp_drag_drop"
    --hidden-import "sftp_file_browser_panel"
    --hidden-import "sftp_filebrowserclass"
    --hidden-import "sftp_filetablemodel"
    --hidden-import "sftp_hostdataeditor"
    --hidden-import "sftp_local_terminal_widget"
    --hidden-import "sftp_logging"
    --hidden-import "sftp_operations"
    --hidden-import "sftp_platform"
    --hidden-import "sftp_preferences"
    --hidden-import "sftp_preview_widget"
    --hidden-import "sftp_qt_compat"
    --hidden-import "sftp_remotefilebrowserclass"
    --hidden-import "sftp_remotefiletablemodel"
    --hidden-import "sftp_session"
    --hidden-import "sftp_session_executor"
    --hidden-import "sftp_sortfiltermodel"
    --hidden-import "sftp_terminal_widget"
    --hidden-import "sftp_textviewer"
    --hidden-import "sftp_theme"
    --hidden-import "sftp_toolbar_customizer"
    --hidden-import "sftp_transfer_handler"
    --hidden-import "sftp_transfer_history"
    --hidden-import "sftp_transfer_queue_widget"
)

# Build based on platform
case "$PLATFORM" in
    macos)
        echo "Building macOS .app bundle..."
        pyinstaller --windowed \
                    --onedir \
                    --name "SFTP Client" \
                    --paths "." \
                    --add-data "sftp_theme.py:." \
                    --add-data "sftp_qt_compat.py:." \
                    "${HIDDEN_IMPORTS[@]}" \
                    --exclude-module "tkinter" \
                    --exclude-module "matplotlib" \
                    --exclude-module "numpy" \
                    --exclude-module "pandas" \
                    --exclude-module "scipy" \
                    --exclude-module "PIL" \
                    --exclude-module "cv2" \
                    --exclude-module "pytest" \
                    --exclude-module "icecream" \
                    sftp.py
        
        echo ""
        echo "Build complete!"
        echo "macOS .app bundle: dist/SFTP Client.app"
        ;;

    windows)
        echo "Building Windows executable..."
        pyinstaller --windowed \
                    --onedir \
                    --name "SFTP Client" \
                    --paths "." \
                    --add-data "sftp_theme.py;." \
                    --add-data "sftp_qt_compat.py;." \
                    --collect-all "PySide6" \
                    --collect-all "paramiko" \
                    --collect-all "cryptography" \
                    --collect-all "encodings" \
                    --hidden-import "encodings" \
                    --hidden-import "encodings.ascii" \
                    --hidden-import "encodings.utf_8" \
                    --hidden-import "encodings.latin_1" \
                    --hidden-import "encodings.charmap" \
                    "${HIDDEN_IMPORTS[@]}" \
                    --hidden-import "paramiko.win_openssh" \
                    --exclude-module "tkinter" \
                    --exclude-module "matplotlib" \
                    --exclude-module "numpy" \
                    --exclude-module "pandas" \
                    --exclude-module "scipy" \
                    --exclude-module "PIL" \
                    --exclude-module "cv2" \
                    --exclude-module "pytest" \
                    --exclude-module "icecream" \
                    sftp.py
        
        echo ""
        echo "Build complete!"
        echo "Windows folder: dist/SFTP Client/"
        echo "Run: dist/SFTP Client/SFTP Client.exe"
        ;;

    linux)
        echo "Building Linux executable..."
        pyinstaller --windowed \
                    --onefile \
                    --name "sftp-client" \
                    --paths "." \
                    --add-data "sftp_theme.py:." \
                    --add-data "sftp_qt_compat.py:." \
                    "${HIDDEN_IMPORTS[@]}" \
                    --hidden-import "pty" \
                    --hidden-import "fcntl" \
                    --hidden-import "termios" \
                    --exclude-module "tkinter" \
                    --exclude-module "matplotlib" \
                    --exclude-module "numpy" \
                    --exclude-module "pandas" \
                    --exclude-module "scipy" \
                    --exclude-module "PIL" \
                    --exclude-module "cv2" \
                    --exclude-module "pytest" \
                    --exclude-module "icecream" \
                    sftp.py
        
        echo ""
        echo "Build complete!"
        echo "Linux executable: dist/sftp-client"
        ;;

    *)
        echo "Unknown platform: $PLATFORM"
        echo "Usage: ./build.sh [macos|windows|linux]"
        exit 1
        ;;
esac

echo ""
echo "Build artifacts are in: dist/"