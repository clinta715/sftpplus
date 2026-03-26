# Changelog

All notable changes to the SFTP Client application will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Cross-Platform Support**: Application now runs on Windows, macOS, and Linux
  - Platform-specific config directories (`%APPDATA%/sftp_client` on Windows)
  - Local terminal now fully supported on all platforms (QProcess-based, no PTY dependency)
  - File permissions handled gracefully on all platforms
- **Delete Progress Feedback**: Deleting multiple items now shows progress dialog and summary
- **Logging System**: New `sftp_logging.py` module with file logging to platform-specific log directory
- **Transfer History**: New `sftp_transfer_history.py` module for logging completed transfers
- **Drag & Drop Infrastructure**: New `sftp_drag_drop.py` module with `DragDropInfo` class
- **Platform Utility Module**: New `sftp_platform.py` with cross-platform utilities
- **Keyboard Shortcuts Help**: Press F1 to see all available keyboard shortcuts
- **Test Framework**: 123 tests in `tests/` directory
- **Local Terminal Tests**: 34 tests for `sftp_local_terminal_widget.py` covering ANSI stripping, architecture verification, line editor, history, and tab completion
- **Filename Truncation**: Long filenames now show beginning instead of end (elide left)
- **Tree View Context Menu**: Added Rename and Delete options to tree view right-click menu

### Fixed
- **Local Terminal Redesign**: Complete rewrite from PTY-based to QProcess-based architecture. Fixes prompt-redraw bug caused by `TERM=dumb` with fish/bash shells. The new design uses `QProcess` with pipes, built-in line editing, command history, and file path tab completion. Cross-platform (Windows, macOS, Linux).
- **Active Browser Detection**: Toolbar buttons now correctly detect which browser (local/remote) was last clicked
- **Tree Download Path**: Tree view downloads now create subfolders instead of flattening directory structure
- **Permission Error Handling**: Delete operations now handle permission errors gracefully instead of retrying forever
- **Rename Dialog**: Rename dialog now pre-populates with current filename
- **Toolbar Delete**: Delete button works for both local and remote browsers
- **Connection Pool**: Changed from RejectPolicy to WarningPolicy to allow connections to new hosts

### Security
- **Credential Encryption**: Transfer queue passwords now encrypted with Fernet (not base64)
- **Debug Output Cleanup**: Removed all `icecream` debug statements (269 calls across 23 files)

### Changed
- **Toolbar Tooltips**: Now display keyboard shortcuts for each button
- **Default Browser**: Remote browser is now default active browser instead of local
- **Config Paths**: All config files now use platform-appropriate directories

## [2.0.1] - 2026-03-03

### Fixed
- **Auto-clear bug**: `get_bool()` in preferences was returning `True` for string "false" (non-empty strings are truthy). Now properly parses string values.
- **Progress display**: Added `signal_transfer_progress` signal to show transfer progress in status bar
- **Browser refresh on error**: Added `notify_observees()` call in `transfer_error()` to refresh browsers even when transfers fail
- **Error feedback**: Transfers tab now focuses when transfers fail so users can see error messages
- **Case-insensitive sorting**: Already implemented in `DirectoryFirstSortProxyModel` and `FileTableModel`

### Changed
- Status bar now shows transfer progress, speed (KB/s or MB/s), and ETA during active transfers

## [2.0.0] - 2026-02-27

### Added
- **Session-Based API**: Complete migration from legacy `add_sftp_job()` to new session-based API
  - New `SFTPOperations` class for high-level SFTP operations
  - New `SFTPSessionAPI` class with progress signals
  - New `CommandExecutor` with progress tracking
  - Connection pooling for improved performance
- **Progress Signals**: Added `progress`, `message`, and `finished` signals to executor classes
- **Unit Tests**: New test classes for `SFTPOperations`, `SFTPSessionAPI`, and `CommandExecutor`

### Changed
- **Transfers**: Upload/download operations now use `SFTPOperations` API
- **Directory Operations**: `chdir`, `list_attr`, `exists` now use session-based API
- **Import Cleanup**: Removed unused `add_sftp_job` imports from migrated files

### Migrated Files

| File | Operation |
|------|-----------|
| `sftp_browserclass.py` | upload, download, traverse_and_transfer, sftp_exists |
| `sftp_remotefilebrowserclass.py` | change_directory, upload_download |
| `sftp_remotefiletablemodel.py` | sftp_listdir_attr |

### Deprecated
- `add_sftp_job()` function kept for backward compatibility but no longer used in production code

### Removed
- Dead code in `sftp_transfer_handler.py` (orphaned, never integrated)

## [1.x.x] - Previous Versions

### 1.0.0 - Initial Release
- Multi-tabbed SFTP client
- SSH Terminal support
- File preview panel
- Customizable toolbar
- Bookmarks and tree view
- Transfer queue with persistence
- Enhanced security features

---

## Migration Guide

### Upgrading to 2.0.0

The session-based API provides a cleaner interface:

```python
# Old API (deprecated but still works)
add_sftp_job(source, True, dest, False, host, user, pass, port, "upload", job_id, key)

# New API
from sftp_operations import SFTPOperations

ops = SFTPOperations(hostname=host, username=user, password=pass, port=port)
ops.upload(source, dest, job_id=str(job_id))
ops.close()
```

### Context Manager Usage

```python
from sftp_operations import SFTPOperations

with SFTPOperations('example.com', 'user', 'password') as ops:
    ops.download('/remote/file.txt', '/local/file.txt')
    ops.upload('/local/other.txt', '/remote/other.txt')
# Session automatically closed
```

### Available Operations

| Method | Description |
|--------|-------------|
| `download(remote, local)` | Download file |
| `upload(local, remote)` | Upload file |
| `list(path)` | List directory |
| `list_attr(path)` | List with attributes |
| `stat(path)` | Get file info |
| `mkdir(path)` | Create directory |
| `rmdir(path)` | Remove directory |
| `remove(path)` | Delete file |
| `chdir(path)` | Change directory |
| `exists(path)` | Check if path exists |
| `is_directory(path)` | Check if directory |
| `is_file(path)` | Check if file |
