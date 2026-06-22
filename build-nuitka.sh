#!/bin/bash
# Build script for SFTP Client using Nuitka
# Nuitka compiles Python to C for better performance and smaller binaries
# Usage: ./build-nuitka.sh [platform]
#   platform: macos, windows, linux (default: current platform)
#
# NOTE: PySide6 support in Nuitka is limited on macOS.
# For macOS builds, consider using PyInstaller instead (./build.sh macos)

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

echo "Building SFTP Client with Nuitka for $PLATFORM..."

# Check if Nuitka is installed
if ! python3 -c "import nuitka" 2>/dev/null; then
    echo "Installing Nuitka..."
    pip3 install nuitka
fi

# Platform-specific warnings
case "$PLATFORM" in
    macos)
        echo ""
        echo "WARNING: PySide6 support in Nuitka is limited on macOS."
        echo "Consider using PyInstaller for macOS builds instead:"
        echo "  ./build.sh macos"
        echo ""
        echo "Continuing with Nuitka build (may fail)..."
        echo ""
        ;;
esac

# Check if C compiler is available
check_compiler() {
    case "$PLATFORM" in
        macos)
            if ! command -v clang &> /dev/null && ! command -v gcc &> /dev/null; then
                echo "Error: No C compiler found. Install Xcode CLI: xcode-select --install"
                exit 1
            fi
            ;;
        linux)
            if ! command -v gcc &> /dev/null; then
                echo "Error: No C compiler found. Install gcc."
                exit 1
            fi
            ;;
        windows)
            if ! command -v gcc &> /dev/null && ! command -v cl &> /dev/null; then
                echo "Error: No C compiler found. Install MinGW or Visual Studio."
                exit 1
            fi
            ;;
    esac
}

check_compiler

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build/ dist/ *.build/ *.dist/ sftp.app 2>/dev/null || true

# Create dist directory
mkdir -p dist

# Common Nuitka options
NUITKA_OPTS=(
    --assume-yes-for-downloads
    --follow-imports
    --include-module=PySide6.QtCore
    --include-module=PySide6.QtGui
    --include-module=PySide6.QtWidgets
    --include-module=paramiko
    --include-module=cryptography
    --include-module=cryptography.fernet
    --include-module=cryptography.hazmat.primitives
    --include-module=cryptography.hazmat.backends
    --include-module=cryptography.hazmat.backends.openssl
    --include-data-file=sftp_theme.py=sftp_theme.py
    --include-data-file=sftp_qt_compat.py=sftp_qt_compat.py
)

# Modules to include
INCLUDE_MODULES=(
    sftp_about
    sftp_browserclass
    sftp_browser_mixins
    sftp_commands
    sftp_connection_pool
    sftp_connections_widget
    sftp_creds
    sftp_drag_drop
    sftp_file_browser_panel
    sftp_filebrowserclass
    sftp_filetablemodel
    sftp_hostdataeditor
    sftp_local_terminal_widget
    sftp_logging
    sftp_operations
    sftp_platform
    sftp_preferences
    sftp_preview_widget
    sftp_qt_compat
    sftp_remotefilebrowserclass
    sftp_remotefiletablemodel
    sftp_session
    sftp_session_executor
    sftp_sortfiltermodel
    sftp_terminal_widget
    sftp_textviewer
    sftp_theme
    sftp_toolbar_customizer
    sftp_transfer_handler
    sftp_transfer_history
    sftp_transfer_queue_widget
)

# Add include options
for module in "${INCLUDE_MODULES[@]}"; do
    NUITKA_OPTS+=(--include-module="$module")
done

# Build based on platform
case "$PLATFORM" in
    macos)
        echo "Building macOS .app bundle with Nuitka..."
        echo "Note: This may fail due to PySide6 limitations. Use ./build.sh macos if it does."
        echo ""
        
        # Try build, fallback to PyInstaller recommendation on failure
        if python3 -m nuitka \
            "${NUITKA_OPTS[@]}" \
            --standalone \
            --macos-create-app-bundle \
            --macos-app-name="SFTP Client" \
            --macos-app-version="2.1.0" \
            --macos-signed-app-name="com.sftpclient.app" \
            --macos-app-icon=none \
            --enable-plugin=pyside6 \
            sftp.py 2>&1; then
            
            # Move to dist directory
            if [ -d "sftp.app" ]; then
                mv sftp.app "dist/SFTP Client.app"
            fi
            if [ -d "sftp.dist" ]; then
                mv sftp.dist/* dist/ 2>/dev/null || true
            fi
            
            echo ""
            echo "Build complete!"
            echo "macOS .app bundle: dist/SFTP Client.app/"
        else
            echo ""
            echo "Nuitka build failed (PySide6 on macOS has limited support)."
            echo "Falling back to PyInstaller..."
            echo ""
            ./build.sh macos
        fi
        ;;

    windows)
        echo "Building Windows executable with Nuitka..."
        python3 -m nuitka \
            "${NUITKA_OPTS[@]}" \
            --standalone \
            --onefile \
            --windows-console-mode=disable \
            --windows-icon-from-ico=none \
            --enable-plugin=pyside6 \
            sftp.py
        
        # Move to dist directory
        if [ -f "sftp.exe" ]; then
            mv sftp.exe "dist/SFTP Client.exe"
        fi
        
        echo ""
        echo "Build complete!"
        echo "Windows executable: dist/SFTP Client.exe"
        ;;

    linux)
        echo "Building Linux executable with Nuitka..."
        python3 -m nuitka \
            "${NUITKA_OPTS[@]}" \
            --standalone \
            --onefile \
            --enable-plugin=pyside6 \
            sftp.py
        
        # Move to dist directory
        if [ -f "sftp.bin" ]; then
            mv sftp.bin dist/sftp-client
            chmod +x dist/sftp-client
        fi
        
        echo ""
        echo "Build complete!"
        echo "Linux executable: dist/sftp-client"
        ;;

    *)
        echo "Unknown platform: $PLATFORM"
        echo "Usage: ./build-nuitka.sh [macos|windows|linux]"
        exit 1
        ;;
esac

echo ""
echo "Note: Nuitka build may take several minutes on first run."
echo "Subsequent builds will be faster due to caching."