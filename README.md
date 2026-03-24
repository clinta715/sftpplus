# Multi-threaded SFTP Client

A multi-tabbed, ephemeral-connection based graphical SFTP client written in Python and PyQt6 with integrated SSH terminal support.

## Features

- **Cross-platform**: Runs on Windows, macOS, and Linux
- **Multi-tabbed interface**: Connect to multiple SFTP servers simultaneously
- **SSH Terminal**: Interactive SSH shell sessions alongside SFTP file transfers (Unix only)
- **Connection types**: Choose between SFTP Browser or SSH Terminal per saved site
- **Ephemeral connections**: Each operation creates a fresh connection for security
- **Threaded operations**: Uploads/downloads run in background threads
- **Dual-pane interface**: Local and remote file browsers side-by-side
- **File preview panel**: Preview text files and images in a collapsible side panel
- **Customizable toolbar**: Drag to reorder buttons, toggle visibility, right-click for quick access
- **Bookmarks**: Save frequently used directories per-host
- **Directory tree view**: Toggle tree panel above or below file list
- **Progress tracking**: Real-time progress indicators for file transfers
- **Delete feedback**: Progress dialog and summary when deleting multiple items
- **Queue management**: Pause/cancel transfer operations
- **Persistent transfer queue**: Unfinished transfers saved and restored between sessions
- **Persistent preferences**: User settings saved to platform-appropriate directory
- **Enhanced security**: Separate key storage, proper file permissions, secure temp file handling
- **Transfer history**: Log of completed transfers with export capability

## Requirements

- Python 3.7+
- PyQt6
- paramiko
- cryptography
- humanize (optional, for file size formatting)

## Installation

```bash
pip install PyQt6 paramiko cryptography humanize
```

## Platform Notes

### Windows
- Config files stored in `%APPDATA%/sftp_client/`
- Local terminal not available (PTY not supported on Windows)
- File permissions use Windows ACLs

### macOS / Linux
- Config files stored in `~/.sftp_client/`
- Local terminal fully supported
- File permissions use Unix mode bits (0o600)

## Usage

### Basic Operations

1. **Connect to server**:
   - Enter hostname/IP, username, password, and optionally port (default: 22)
   - Press Enter in password or port field to connect
   - Additional connections open in new tabs

2. **File operations**:
   - **Right-click**: Context menu for upload/download operations
   - **Double-click remote file**: Download and prompt for save location
   - **Double-click remote directory**: Navigate into directory
   - **Drag & drop**: Supported between local and remote panes
   - **Preview**: Select a file to preview in the side panel (Ctrl+P)

3. **Navigation**:
   - Use `..` to navigate up directory levels
   - Bookmarks available via ⭐ button in browser toolbar
   - Tree view (🌲) shows directory structure

4. **Tab management**:
   - Double-click tab to rename
   - Right-click tab for context menu (rename, close, close others)
   - Ctrl+W closes current tab

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+R` / `F5` | Refresh directory |
| `Ctrl+N` | New connection (switch to Connections tab) |
| `Ctrl+W` | Close current tab |
| `Ctrl+Shift+N` | New folder |
| `Ctrl+U` / `F7` | Upload selected |
| `Ctrl+D` / `F6` | Download selected |
| `F2` | Rename selected |
| `Delete` | Delete selected |
| `Ctrl+Enter` | View/edit selected file |
| `Backspace` | Go to parent directory |
| `Ctrl+L` | Focus address bar |
| `Ctrl+B` | Add bookmark for current directory |
| `Ctrl+P` | Toggle preview panel |
| `Ctrl+T` | Toggle Transfers tab |
| `Ctrl+Shift+T` | Customize toolbar |
| `F1` | Show keyboard shortcuts help |

### Toolbar Customization

- Click **⚙** gear button to open customization dialog
- **Drag** items to reorder
- **Double-click** to show/hide
- **Right-click** toolbar for quick toggle menu
- Settings persist between sessions

### Connection Manager

- **📋 Copy** button duplicates selected site with all settings
- Auto-generates unique name (e.g., `hostname (copy)`)
- Immediately selects copy for editing

### Transfer Queue

- Unfinished transfers are automatically saved on exit
- Queued and active transfers are restored on next launch
- Saved in `~/.sftp_client_transfer_queue.json` (encrypted credentials)
- Transfers resume automatically when application starts

## Architecture

### Core Components

| File | Purpose |
|------|---------|
| `sftp.py` | Main application window and orchestration |
| `sftp_browserclass.py` | Base browser (uses mixins for modular functionality) |
| `sftp_browser_mixins.py` | Browser mixins: TreeViewMixin, BookmarkMixin, FileOpsMixin |
| `sftp_remotefilebrowserclass.py` | Remote SFTP browser implementation |
| `sftp_downloadworkerclass.py` | Background transfer worker threads |
| `sftp_creds.py` | Session credential management |
| `sftp_hostdataeditor.py` | Connection data storage/encryption (functions only) |
| `sftp_preferences.py` | Persistent user preferences |
| `sftp_preview_widget.py` | File preview side panel |
| `sftp_toolbar_customizer.py` | Toolbar button customization dialog |
| `sftp_connections_widget.py` | Connection manager widget |
| `sftp_file_browser_panel.py` | Combined local/remote browser panel |
| `sftp_transfer_queue_widget.py` | Transfer queue widget |
| `sftp_operations.py` | High-level SFTP operations API |
| `__init__.py` | Package structure and public API exports |

### Session-Based API (2026-02)

The session-based API provides a cleaner alternative to legacy `add_sftp_job()` calls:

| File | Purpose |
|------|---------|
| `sftp_session.py` | SessionManager and SFTPSession classes |
| `sftp_commands.py` | Typed command classes (DownloadCommand, UploadCommand, etc.) |
| `sftp_connection_pool.py` | Thread-safe SSH/SFTP connection pooling |
| `sftp_session_executor.py` | Command executor with progress signals |
| `sftp_operations.py` | High-level convenience functions |

**Migration Status**: Complete - all production code now uses session-based API

### Archived Files

These files are preserved in `archive/` but no longer used:
- `sftp_browser_actions.py` - Never integrated
- `sftp_navigation.py` - Never integrated
- `sftp_file_operations.py` - Never integrated

### Preferences

User preferences stored in `~/.sftp_client_preferences.json`:

| Setting | Description |
|---------|-------------|
| `clear_completed_on_complete` | Auto-clear completed transfers |
| `overwrite_on_transfer` | Skip overwrite prompts |
| `confirm_exit` | Confirm before exiting with active transfers |
| `focus_transfers_on_start` | Focus Transfers tab when transfers start |
| `tree_view_position` | Tree panel position: "above" or "below" list |
| `toolbar_buttons` | Customized toolbar button order and visibility |

### Security Features

- **Separate key storage**: Encryption key stored in `~/.sftp_client_key` (mode 0o600)
- **Secure file permissions**: Credential files created with restricted permissions
- **No hardcoded defaults**: Removed guest/guest fallback credentials
- **Secure temp files**: Preview files cleaned up via atexit handlers
- **Sanitized logging**: Private key data removed from debug output

### File Storage Locations

**Unix (macOS/Linux):**

| File | Purpose |
|------|---------|
| `~/.sftp_client/preferences.json` | User preferences |
| `~/.sftp_client/connections.json` | Encrypted site configurations |
| `~/.sftp_client/history.json` | Transfer history |
| `~/.sftp_client/logs/sftp.log` | Application logs |
| `~/.sftp_client_key` | Encryption key (separate from data) |
| `~/.sftp_client_transfer_queue.json` | Pending transfers (auto-deleted after restore) |
| `/tmp/.sftp_preview_*` | Temporary preview files (auto-cleaned) |

**Windows:**

| File | Purpose |
|------|---------|
| `%APPDATA%/sftp_client/preferences.json` | User preferences |
| `%APPDATA%/sftp_client/connections.json` | Encrypted site configurations |
| `%APPDATA%/sftp_client/history.json` | Transfer history |
| `%APPDATA%/sftp_client/logs/sftp.log` | Application logs |
| `%APPDATA%/sftp_client/key.bin` | Encryption key |
| `%APPDATA%/sftp_client/transfer_queue.json` | Pending transfers |

## Development History

### 2026-02-22: Usability & Security Updates

**New Features:**
- Keyboard shortcuts for all common operations
- Tab renaming (double-click or right-click)
- Per-host bookmarks system
- Enhanced status bar with connection status, path (click to copy)
- File preview side panel (text files, images)
- Customizable toolbar with drag-and-drop reordering
- Connection manager copy function
- Tree view position toggle (above/below list, persistent)
- Persistent transfer queue (unfinished transfers saved/restored between sessions)

**Security Fixes:**
- Encryption key stored separately from encrypted data
- Credential files created with proper permissions (0o600)
- Removed hardcoded default credentials
- Secure temp file handling with atexit cleanup
- Removed sensitive data from debug logs

**Bug Fixes:**
- Fixed column header sorting (was double-toggling)
- Fixed toolbar layout after customization
- Fixed connection manager data synchronization

### 2026-02-20: SSH Terminal & Interface Updates

- Added SSH Terminal support (interactive shell sessions)
- Added persistent preferences system
- Added connection type selection (SFTP Browser vs SSH Terminal)
- Added focus transfers preference
- Added status bar feedback for transfer events
- Fixed crash on exit and session cleanup issues
- Added ANSI code stripping for terminal output
- Updated to integrated tabbed interface

### Earlier Updates

See git history for complete changelog.

## Contributing

### Code Quality Priorities

1. Maintain thread safety for all shared state
2. Use specific exception types (avoid bare `except`)
3. Clean up resources in finally blocks
4. Follow import ordering conventions
5. Add docstrings for public functions

### Development Commands

```bash
# Run the application
python3 sftp.py

# Validate syntax
python3 -m py_compile sftp.py sftp_*.py

# Test single module
python3 -c "from sftp_creds import get_credentials; print('OK')"

# Run all tests
python3 -m pytest tests/ -v
```

## Building Standalone Executables

### PyInstaller (Recommended)

PyInstaller is the easiest way to create standalone executables.

```bash
# Install dependencies
pip install -r requirements-dev.txt

# Build for current platform
./build.sh

# Build for specific platform
./build.sh macos    # Creates dist/SFTP Client.app
./build.sh windows  # Creates dist/SFTP Client.exe
./build.sh linux    # Creates dist/sftp-client
```

### Nuitka (Alternative)

Nuitka compiles Python to C for potentially smaller, faster executables.

```bash
# Install Nuitka
pip install nuitka

# Build for current platform
./build-nuitka.sh

# Build for specific platform
./build-nuitka.sh macos    # Creates dist/SFTP Client.app
./build-nuitka.sh windows  # Creates dist/SFTP Client.exe
./build-nuitka.sh linux    # Creates dist/sftp-client
```

**Nuitka Requirements:**
- **macOS**: Xcode CLI (`xcode-select --install`)
- **Linux**: GCC (`apt install gcc` or `dnf install gcc`)
- **Windows**: MinGW or Visual Studio

### Build Comparison

| Feature | PyInstaller | Nuitka |
|---------|-------------|--------|
| Build time | Fast (1-2 min) | Slow (5-15 min) |
| Executable size | Larger | Smaller |
| Startup speed | Normal | Faster |
| Complexity | Simple | Requires C compiler |
