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

# Build based on platform
case "$PLATFORM" in
    macos)
        echo "Building macOS .app bundle..."
        pyinstaller --windowed \
                    --onedir \
                    --name "SFTP Client" \
                    --bundle-identifier "com.sftpclient.app" \
                    --osx-bundle-identifier "com.sftpclient.app" \
                    --add-data "sftp_theme.py:." \
                    --add-data "sftp_qt_compat.py:." \
                    --hidden-import "PySide6.QtCore" \
                    --hidden-import "PySide6.QtGui" \
                    --hidden-import "PySide6.QtWidgets" \
                    --hidden-import "PySide6.sip" \
                    --hidden-import "paramiko" \
                    --hidden-import "cryptography" \
                    --hidden-import "cryptography.fernet" \
                    --hidden-import "cryptography.hazmat.primitives" \
                    --hidden-import "cryptography.hazmat.backends" \
                    --hidden-import "cryptography.hazmat.backends.openssl" \
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
                    --onefile \
                    --name "SFTP Client" \
                    --add-data "sftp_theme.py;." \
                    --add-data "sftp_qt_compat.py;." \
                    --hidden-import "PySide6.QtCore" \
                    --hidden-import "PySide6.QtGui" \
                    --hidden-import "PySide6.QtWidgets" \
                    --hidden-import "PySide6.sip" \
                    --hidden-import "paramiko" \
                    --hidden-import "cryptography" \
                    --hidden-import "cryptography.fernet" \
                    --hidden-import "cryptography.hazmat.primitives" \
                    --hidden-import "cryptography.hazmat.backends" \
                    --hidden-import "cryptography.hazmat.backends.openssl" \
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
        echo "Windows executable: dist/SFTP Client.exe"
        ;;

    linux)
        echo "Building Linux executable..."
        pyinstaller --windowed \
                    --onefile \
                    --name "sftp-client" \
                    --add-data "sftp_theme.py:." \
                    --add-data "sftp_qt_compat.py:." \
                    --hidden-import "PySide6.QtCore" \
                    --hidden-import "PySide6.QtGui" \
                    --hidden-import "PySide6.QtWidgets" \
                    --hidden-import "PySide6.sip" \
                    --hidden-import "paramiko" \
                    --hidden-import "cryptography" \
                    --hidden-import "cryptography.fernet" \
                    --hidden-import "cryptography.hazmat.primitives" \
                    --hidden-import "cryptography.hazmat.backends" \
                    --hidden-import "cryptography.hazmat.backends.openssl" \
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