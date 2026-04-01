# Agent Guidelines for SFTP Client Project

This document provides guidelines for AI coding agents working on this PyQt6-based SFTP client application.

## Features Overview

- **Cross-platform**: Runs on Windows, macOS, and Linux with platform-specific paths
- **Multi-tabbed interface**: Connect to multiple SFTP servers simultaneously
- **SSH Terminal**: Interactive SSH shell sessions in addition to SFTP (Unix only; Windows shows placeholder)
- **Local Terminal**: Cross-platform local shell using QProcess (Windows, macOS, Linux)
- **Ephemeral connections**: Each operation creates a fresh connection for security
- **Threaded operations**: Uploads/downloads run in background threads
- **Dual-pane interface**: Local and remote file browsers side-by-side
- **File preview panel**: Collapsible side panel for text/image preview
- **Customizable toolbar**: Drag-and-drop reordering, visibility toggles
- **Bookmarks**: Per-host directory bookmarks
- **Tree view**: Directory tree panel (above or below list)
- **Progress tracking**: Real-time progress indicators for file transfers
- **Delete feedback**: Progress dialog and summary when deleting multiple items
- **Queue management**: Pause/cancel transfer operations
- **Transfer history**: Log of completed transfers with export capability
- **Persistent preferences**: User settings saved to home directory
- **Enhanced security**: Separate key storage, proper file permissions

## Session-Based API (2026-02-11) - MIGRATION COMPLETE

The project now uses a clean session-based API for SFTP operations. This provides a better alternative to the legacy 11-parameter `add_sftp_job()` calls.

> **Migration Status**: Complete as of 2026-02-27 - All production code now uses the session-based API

### Module Overview

| File | Purpose |
|------|---------|
| `sftp_hostdataeditor.py` | Connection data storage with atomic API functions |
| `sftp_session.py` | SessionManager and SFTPSession classes for isolated credential storage |
| `sftp_commands.py` | Typed command classes (DownloadCommand, UploadCommand, etc.) |
| `sftp_connection_pool.py` | Thread-safe SSH/SFTP connection pooling |
| `sftp_session_executor.py` | Command executor using sessions and pool |
| `sftp_operations.py` | High-level convenience functions |
| `sftp_terminal_widget.py` | SSH terminal widget with ANSI code stripping (Unix only) |
| `sftp_local_terminal_widget.py` | Local terminal widget (QProcess-based, cross-platform: Windows/macOS/Linux) |
| `sftp_preferences.py` | Persistent user preferences storage |
| `sftp_preview_widget.py` | File preview side panel (text/images) |
| `sftp_toolbar_customizer.py` | Toolbar customization dialog |
| `sftp_qt_compat.py` | Qt6 enum compatibility layer |
| `sftp_platform.py` | Cross-platform utilities (paths, permissions, shell detection) |
| `sftp_logging.py` | Application logging to file |
| `sftp_transfer_history.py` | Transfer history logging and export |
| `sftp_drag_drop.py` | Drag and drop infrastructure |

### Cross-Platform Support

The application runs on Windows, macOS, and Linux. Use `sftp_platform.py` for platform-specific operations:

```python
from sftp_platform import (
    is_windows, is_macos, is_linux,
    get_config_directory, get_key_file_path,
    secure_file_permissions, create_secure_directory,
    supports_local_terminal, get_default_shell
)

# Check platform
if is_windows():
    # Windows-specific code

# Get platform-appropriate paths
config_dir = get_config_directory()  # %APPDATA%/sftp_client on Windows
key_file = get_key_file_path()

# Secure file permissions (no-op on Windows)
secure_file_permissions('/path/to/file')

# Check if local terminal is supported (always True with QProcess-based terminal)
if supports_local_terminal():
    # Start local shell
```

### Quick Start

```python
from sftp_operations import SFTPOperations

# Create operations instance
ops = SFTPOperations('example.com', 'user', 'password')

# Download file
ops.download('/remote/file.txt', '/local/file.txt')

# Upload file
ops.upload('/local/other.txt', '/remote/other.txt')

# List directory
files = ops.list('/remote/directory')

# Change directory
ops.chdir('/remote/new/path')

# Cleanup
ops.close()
```

### Using Sessions Directly

```python
from sftp_session import SFTPCredentials, get_session_manager
from sftp_session_executor import SFTPSessionAPI

# Create credentials
creds = SFTPCredentials(
    hostname='example.com',
    username='user',
    password='password',
    port=22
)

# Create session and API
session = get_session_manager().create_session(creds)
api = SFTPSessionAPI(session)

# Use API for operations
api.download('/remote/file.csv', '/home/user/file.csv')
api.upload('/home/user/data.txt', '/remote/data.txt')

# Cleanup session
get_session_manager().remove_session(session.session_id)
```

### Context Manager Usage

```python
from sftp_operations import SFTPOperations

with SFTPOperations('example.com', 'user', 'password') as ops:
    ops.download('/remote/file.txt', '/local/file.txt')
    ops.upload('/local/other.txt', '/remote/other.txt')
# Session automatically closed on exit
```

### Available Operations

| Method | Description |
|--------|-------------|
| `download(remote, local)` | Download file from remote to local |
| `upload(local, remote)` | Upload file from local to remote |
| `list(path)` | List directory contents |
| `list_attr(path)` | List with file attributes |
| `stat(path)` | Get file attributes |
| `mkdir(path)` | Create directory |
| `rmdir(path)` | Remove directory |
| `remove(path)` | Remove file |
| `chdir(path)` | Change current directory |
| `exists(path)` | Check if path exists |
| `is_directory(path)` | Check if path is directory |
| `is_file(path)` | Check if path is file |

### Connection Data API (sftp_hostdataeditor.py)

The hostdataeditor module provides atomic API functions for managing connection data:

```python
from sftp_hostdataeditor import (
    load_connection_data,   # Load all connection data
    save_connection_data,   # Save all connection data (returns bool)
    get_site_names,         # Get list of configured hostnames
    get_site_data,          # Get dict with all fields for a site, or None
    get_setting,            # Get global setting (e.g., 'show_manager_on_startup')
    update_connection_data, # Atomic load-modify-save with callback
    delete_site,            # Atomically delete a site by hostname
    copy_site,              # Copy a site to a new hostname
    rename_site,            # Rename a site's hostname
)
```

**Atomic Updates:**

```python
# update_connection_data - thread-safe load-modify-save
def my_callback(host_data):
    host_data["hostnames"]["new_host"] = "new_host"
    host_data["usernames"]["new_host"] = "myuser"
    host_data["passwords"]["new_host"] = "mypass"
    host_data["ports"]["new_host"] = 22
    host_data["key"]["new_host"] = ""

update_connection_data(my_callback)

# Single-site operations
delete_site("hostname")
copy_site("source", "destination")
rename_site("old_name", "new_name")
```

**Reading Data:**

```python
# Get all hostnames
names = get_site_data("myserver.com")
# Returns: {'hostname': 'myserver.com', 'username': 'user', 'password': 'pass', 
#           'port': 22, 'key': '', 'connection_type': 'SFTP Browser', ...}

names = get_site_names()  # ['server1.com', 'server2.com']

# Get global setting
show_on_startup = get_setting("show_manager_on_startup", True)
```

### Legacy API Compatibility (DEPRECATED)

The old `add_sftp_job()` function is still available but **deprecated**. All production code has been migrated to the session-based API:

```python
# Old API (deprecated - DO NOT USE)
add_sftp_job(
    source_path, is_source_remote,
    destination_path, is_destination_remote,
    hostname, username, password, port,
    command, job_id, key
)
```

**Migration Status**: Complete (2026-02-27)

Migrated files:
- `sftp_browserclass.py` - upload, download, traverse_and_transfer, sftp_exists
- `sftp_remotefilebrowserclass.py` - change_directory, upload_download
- `sftp_remotefiletablemodel.py` - sftp_listdir_attr

```bash
# Run the application
python3 sftp.py

# Run with connection arguments
python3 sftp.py -H hostname -u username -p password -P 22

# Validate syntax
python3 -m py_compile sftp.py sftp_*.py

# Test single module
python3 -c "from sftp_creds import get_credentials; print('OK')"
```

## Code Style Guidelines

### Import Order (STRICT - Required)
Always order imports as follows with blank lines between groups:

```python
# 1. Standard library
import sys
import os
import json
import threading
import queue
import time

# 2. PyQt6 modules
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout,
    QTableWidget, QTableWidgetItem, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer

# 3. Third-party libraries
import paramiko
from cryptography.fernet import Fernet
from icecream import ic

# 4. Local project modules
from sftp_creds import get_credentials, set_credentials
from sftp_downloadworkerclass import add_sftp_job, put_response

# 5. Compatibility layer (for Qt enums)
from sftp_qt_compat import Qt
```

### Naming Conventions

- **Functions & Variables:** `snake_case` (e.g., `get_credentials`, `host_data`)
- **Classes:** `PascalCase` (e.g., `MainWindow`, `DownloadWorker`, `SFTPJob`)
- **Constants:** `UPPER_CASE` (e.g., `MAX_TRANSFERS`, `response_queues`)
- **Private/Internal:** Leading underscore (e.g., `_creds_lock`, `_connection_pool`)
- **Global Shared State:** Module-level with locks (e.g., `response_queues`, `_pool_lock`)

### Thread Safety (CRITICAL)

This application uses extensive threading. Follow these rules:

1. **Always use locks for shared global state:**
```python
# CORRECT
with response_queues_lock:
    response_queues[job_id] = queue.Queue()

# INCORRECT - Race condition
response_queues[job_id] = queue.Queue()
```

2. **Use helper functions for queue operations:**
```python
# Use this helper instead of direct access
put_response(transfer_id, "success", data)

# Instead of:
response_queues[transfer_id].put("success")
```

3. **Required locks in the codebase:**
   - `response_queues_lock` - For response_queues dictionary
   - `_creds_lock` - For sftp_current_creds dictionary
   - `_pool_lock` - For SSH connection pool

### Error Handling

1. **Always use specific exception types:**
```python
# CORRECT
except (KeyError, RuntimeError) as e:
    ic(f"Expected error: {e}")

# INCORRECT - Catches everything including SystemExit
except:
    pass
```

2. **Always clean up resources in finally blocks:**
```python
# Use context managers for guaranteed cleanup
from sftp_downloadworkerclass import ResponseQueueContext

with ResponseQueueContext(job_id) as queue:
    # ... operations ...
    pass  # Automatically cleaned up

# Or manually with try/finally
try:
    queue = create_response_queue(job_id)
    # ... operations ...
finally:
    delete_response_queue(job_id)
```

3. **Use efficient blocking instead of busy-polling:**
```python
# CORRECT - Uses blocking get with timeout
try:
    response = queue.get(timeout=30)
except queue.Empty:
    handle_timeout()

# OLD PATTERN - Inefficient busy-polling (being phased out)
start_time = time.time()
while queue.empty() and (time.time() - start_time) < 30:
    self.non_blocking_sleep(100)
```

4. **Always close connections in finally blocks:**
```python
ssh = paramiko.SSHClient()
sftp = None
try:
    ssh.connect(...)
    sftp = ssh.open_sftp()
    # ... operations ...
finally:
    if sftp:
        try:
            sftp.close()
        except Exception as e:
            ic(f"Error closing SFTP: {e}")
    try:
        ssh.close()
    except Exception as e:
        ic(f"Error closing SSH: {e}")
```

5. **Always protect signal emissions in QRunnable workers:**
```python
# CORRECT - Signal emission won't crash if GC collected the QObject
def _safe_emit(self, signal, *args):
    try:
        signal.emit(*args)
    except RuntimeError:
        pass

# INCORRECT - Crashes if WorkerSignals was garbage collected
self.signals.finished.emit(self.transfer_id)
```
Workers store `self.signals = SomeQObject()` with no parent, so Python's GC can collect it while `run()` is still executing. Every `emit()` must be wrapped.

6. **Connection pool respects channel limits:**
The pool enforces `_max_channels_per_ssh` (default 8). Never destroy an SSH connection just because one channel open failed — it kills all other active transfers sharing that connection.

### Code Formatting

- **Line length:** Relaxed standard, max 120 characters
- **Indentation:** 4 spaces (no tabs)
- **Blank lines:** 
  - 2 lines between top-level functions/classes
  - 1 line between methods in a class
  - 1 line between import groups
- **Trailing whitespace:** Remove all trailing whitespace
- **Docstrings:** Add for public functions and classes

## Project Architecture

### File Organization
```
__init__.py                   # Package structure and public API exports
sftp.py                       # Main application entry point
sftp_creds.py                 # Thread-safe credential management
sftp_downloadworkerclass.py   # Background transfer workers
sftp_transfer_handler.py      # Directory traversal workers (TraversalWorker, DirectoryTransferTask)
sftp_backgroundthreadwindow.py # Transfer queue UI
sftp_hostdataeditor.py        # Connection data storage/encryption (functions only)
sftp_browserclass.py          # Base browser (uses mixins)
sftp_browser_mixins.py        # Browser mixins: TreeViewMixin, BookmarkMixin, FileOpsMixin
sftp_remotefilebrowserclass.py # Remote file browser
sftp_filebrowserclass.py      # Local file browser
sftp_*tablemodel.py           # Table models for file listings
sftp_editwindowclass.py       # Edit window dialog
sftp_session.py               # Session management
sftp_commands.py              # Typed command classes
sftp_connection_pool.py       # SSH connection pooling
sftp_session_executor.py      # Command executor
sftp_operations.py            # High-level SFTP operations
sftp_preferences.py           # Persistent user preferences
sftp_preview_widget.py        # File preview side panel
sftp_toolbar_customizer.py    # Toolbar customization dialog
sftp_terminal_widget.py       # SSH terminal widget
sftp_file_browser_panel.py    # Combined browser panel
sftp_transfer_queue_widget.py # Transfer queue widget
sftp_connections_widget.py    # Connection manager widget
sftp_qt_compat.py             # Qt6 enum compatibility layer
connection_data.json          # Site configurations (auto-generated)

archive/                      # Archived (unused) files
├── sftp_browser_actions.py   # Never integrated
├── sftp_navigation.py        # Never integrated
└── sftp_file_operations.py   # Never integrated
```

### Browser Mixin Architecture (2026-02-22)

The `Browser` class in `sftp_browserclass.py` now uses mixins for modularity:

```python
class Browser(TreeViewMixin, BookmarkMixin, FileOpsMixin, QWidget):
    ...
```

| Mixin | Purpose |
|-------|---------|
| `TreeViewMixin` | Directory tree population, expansion, navigation |
| `BookmarkMixin` | Per-host directory bookmarks |
| `FileOpsMixin` | SFTP operations with cached `SFTPOperations` instance |

**FileOpsMixin Caching:**

The `FileOpsMixin` caches `SFTPOperations` instances for performance:

```python
class FileOpsMixin:
    _sftp_ops_cache: dict = {}
    
    def get_sftp_operations(self):
        # Returns cached instance or creates new one
        ...
    
    def clear_sftp_cache(self):
        # Call when credentials change
        ...
```

All SFTP operations in the mixin use the cached instance:
- `sftp_listdir()`, `sftp_listdir_attr()`
- `sftp_mkdir()`, `sftp_rmdir()`, `sftp_remove()`, `sftp_rename()`
- `sftp_exists()`, `is_remote_directory()`, `is_remote_file()`

### Key Patterns

1. **Qt Signals/Slots for UI updates:**
```python
class WorkerSignals(QObject):
    progress = pyqtSignal(int, int, float, float)
    finished = pyqtSignal(int)
    message = pyqtSignal(int, str)
```

2. **Background work with QRunnable:**
```python
class DownloadWorker(QRunnable):
    def run(self):
        # Background operations here
        pass
```

3. **Session-based state:**
```python
session_id = create_random_integer()
set_credentials(session_id, 'hostname', hostname)
set_credentials(session_id, 'current_remote_directory', '.')
```

## Testing Strategy

### Automated Tests

Run the test suite:
```bash
# Run all tests
python3 test_sftp.py

# Run with pytest (if installed)
python3 -m pytest test_sftp.py -v

# Run quick smoke tests only
python3 -c "from test_sftp import run_quick_tests; run_quick_tests()"
```

### Manual Testing

1. **Launch test:** `python3 sftp.py`
2. **Connection test:** Connect to configured host
3. **File operations:** Upload, download, delete files
4. **Directory navigation:** Browse remote directories
5. **Concurrent transfers:** Start multiple transfers simultaneously
6. **Thread safety:** Verify no crashes with rapid operations

### Testing a Single Component

Test individual modules manually:
```python
python3 -c "
from sftp_creds import get_credentials, set_credentials
set_credentials(123, 'hostname', 'test.example.com')
creds = get_credentials(123)
print(f'Host: {creds[\"hostname\"]}')
"
```

## Security Best Practices

### SSH Host Key Verification
Always verify host keys to prevent man-in-the-middle attacks:
```python
# Load known hosts
ssh.load_host_keys(os.path.expanduser('~/.ssh/known_hosts'))

# Use WarningPolicy or implement interactive policy
ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
```

### Input Sanitization
Always sanitize user input before using in commands:
```python
import shlex
safe_path = shlex.quote(user_path)
stdin, stdout, stderr = ssh.exec_command(f'cd {safe_path}')
```

### Input Validation
Validate all user inputs:
```python
# Port validation
port = int(port_str)
if not (1 <= port <= 65535):
    raise ValueError("Port must be between 1 and 65535")

# Hostname validation
if not hostname or not isinstance(hostname, str):
    raise ValueError("Valid hostname required")
```

## Critical Bugs & Lessons Learned

### Directory Transfer Prompts (2026-03-19) - CRITICAL FIX

Directory uploads and downloads now properly handle file conflict prompts. This was a major bug where prompts would not work or files would not transfer.

**Root Cause:**
`DirectoryTransferTask` created a `TraversalWorker` but never called `QThreadPool.globalInstance().start(worker)` to execute it. The worker never ran.

**The Fix:**
Replace the broken `DirectoryTransferTask` + `QThread` pattern with direct `TraversalWorker` + `QThreadPool`:

```python
# CORRECT - Worker is actually started
worker = TraversalWorker(...)
worker.signals.prompt_overwrite.connect(
    lambda path: self._handle_worker_prompt(worker, path),
    type=Qt.QueuedConnection  # CRITICAL: Must be QueuedConnection
)
QThreadPool.globalInstance().start(worker)

# WRONG - Worker created but never started
task = DirectoryTransferTask(...)
task.moveToThread(thread)
thread.started.connect(task.run)  # run() creates worker but doesn't start it!
```

**Key Points:**

1. **Use `QThreadPool.globalInstance().start(worker)`:** `TraversalWorker` is a `QRunnable` that must be started in a thread pool.

2. **Use `Qt.QueuedConnection` for prompts:** With `DirectConnection`, the slot runs in the worker thread which has no event loop. Use `QueuedConnection` so the prompt dialog runs in the UI thread.

3. **Remove `auto_overwrite=True`:** This flag bypassed prompts entirely, not because it was working correctly, but because the worker was never running.

**Files Modified:**
- `sftp_browserclass.py` - `upload_directory()` fixed to use `TraversalWorker` + `QThreadPool`
- `sftp_remotefilebrowserclass.py` - `download_directory()` fixed to use `TraversalWorker` + `QThreadPool`
- `sftp_transfer_handler.py` - `DirectoryTransferTask.run()` fixed to use `QueuedConnection`; added explicit `"overwrite"` action handling

**Prompt Flow (Now Working):**
1. `TraversalWorker._traverse()` detects file conflict
2. Emits `prompt_overwrite` signal with `QueuedConnection`
3. Signal queued to browser's UI thread event loop
4. `_handle_worker_prompt()` runs in UI thread, shows dialog
5. User clicks Overwrite → `set_prompt_result("overwrite")` called
6. `QWaitCondition` wakes worker thread with result
7. Worker continues with correct action

**Action Handling in `TraversalWorker._traverse()`:**
```python
if action == "cancel":
    return
elif action == "skip":
    continue
elif action == "skip_all":
    self.skip_all = True
    continue
elif action == "overwrite_all":
    self.overwrite_all = True
    # Falls through to add job
elif action == "resume_all":
    self.resume_all = True
    # Falls through to add job
elif action == "resume":
    command = "resume"
elif action == "overwrite":
    # Falls through to add job with original command
    pass
```

### Signal Source Deleted & Connection Pool Cascading Failure (2026-03-29) - CRITICAL FIX

Multiple transfers would fail mid-run with `RuntimeError: Signal source has been deleted`, and once one transfer failed it would cascade to kill all other transfers sharing the same SSH connection.

**Root Cause 1 — Signal GC:**
Workers store `self.signals = WorkerSignals()` (a QObject with no parent). When the transfer queue's `cleanup_transfer()` removes a `Transfer` from the list, the last Python reference to the worker drops, and Python's GC collects the `WorkerSignals` QObject while the worker's `run()` is still executing in the thread pool.

**Root Cause 2 — Connection pool cascading failure:**
The pool never enforced `_max_channels_per_ssh` (set to 8). When the Nth transfer tried to open one channel too many, the `except` block called `_close_conn_info()` which **destroyed the SSH connection for all other active transfers sharing it**.

**Fix 1 — `_safe_emit()` pattern:**
All QRunnable workers must wrap every `signal.emit()` call in a try/except RuntimeError. Both `DownloadWorker` and all workers in `sftp_transfer_handler.py` now use a `_safe_emit()` helper:

```python
# In DownloadWorker (instance method)
def _safe_emit(self, signal, *args):
    try:
        signal.emit(*args)
    except RuntimeError:
        pass

# In sftp_transfer_handler.py (module-level function)
def _safe_emit(signal, *args):
    try:
        signal.emit(*args)
    except RuntimeError:
        pass
```

**Fix 2 — Worker reference retention:**
`TransferQueueWidget` now maintains a `_running_workers` set holding strong references to active workers. Workers are added on start and removed in `cleanup_transfer()`.

**Fix 3 — Connection pool channel limits:**
`sftp_connection_pool.py` now checks `total_channels >= _max_channels_per_ssh` *before* attempting to open a new channel. Connections at capacity are kept alive (not destroyed) and a new SSH connection is created instead.

**Files Modified:**
- `sftp_downloadworkerclass.py` — `_safe_emit()` added; all 15 signal emissions protected
- `sftp_transfer_handler.py` — `_safe_emit()` module function; all 20+ emissions protected across 5 worker classes
- `sftp_transfer_queue_widget.py` — `_running_workers` set added
- `sftp_connection_pool.py` — Channel limit enforced; cascading failure prevented

### File Browser UI Fixes (2026-03-29)

Several long-standing display issues were fixed:

**1. Text elision direction:**
The base `Browser.init_ui()` had `setTextElideMode(Qt.TextElideMode_Left)` which showed `...long_filename.txt`. Changed to `TextElideMode_Right` so filenames show `long_file...`.

**2. Directory prefix removal:**
The `[DIR]`, `[LINK]`, `[LINK→DIR]` text prefixes were removed from `DisplayRole` in both `FileTableModel` and `RemoteFileTableModel`. Directories are still visually distinguished by **bold** font (`FontRole`) and **blue** color (`ForegroundRole`). The sort proxy model now uses `FontRole.bold()` to detect directories instead of text prefix matching.

**3. Column layout:**
- Name column (0) uses `Stretch` mode — fills remaining space, elides from right
- Size (1) and Modified (3) are `Interactive` (user-resizable)
- Permissions (2) is **hidden by default** (`hideSection(2)`)
- `setWordWrap(False)` prevents text from wrapping to a second line
- Fixed row height (22px) in both local and remote browsers

**4. Status bar resizing:**
Long pathnames in the status bar would expand the entire window. Both `status_path` and `status_message` labels now use `QSizePolicy.Ignored` so they never drive the window size.

**5. Tree view button labels:**
Local browser tree view buttons now show "Upload" / "Upload All" instead of "Download" / "Download All". Both tree views already use the same `upload_directory()` / `download_directory()` methods as the browser right-click actions.

**Files Modified:**
- `sftp_browserclass.py` — Text elide mode, word wrap, row height
- `sftp_filetablemodel.py` — Removed [DIR]/[LINK] prefixes, added TextAlignmentRole
- `sftp_remotefiletablemodel.py` — Removed [DIR]/[LINK] prefixes, added TextAlignmentRole
- `sftp_sortfiltermodel.py` — Directory detection via FontRole instead of text prefix
- `sftp_filebrowserclass.py` — Column layout, hidden permissions, upload button labels
- `sftp_remotefilebrowserclass.py` — Column layout, hidden permissions
- `sftp_qt_compat.py` — Added `TextAlignmentRole`, `AlignLeft`, `ScrollBarAlwaysOff`
- `sftp.py` — Status bar size policy

### Transfer Directory Creation & Concurrent Connection Limits (2026-04-01)

**1. Missing directory creation during transfers:**

`DirectTransferWorker` in `sftp_transfer_handler.py` was missing parent directory creation logic that the legacy `DownloadWorker` had. This caused transfers to fail when the destination path contained directories that didn't exist yet.

**Fix:**
- Downloads: Added `os.makedirs(local_parent, exist_ok=True)` before downloading (`sftp_transfer_handler.py:785-788`)
- Uploads: Added `_ensure_remote_dir()` call before uploading (`sftp_transfer_handler.py:753`)
- New method `_ensure_remote_dir()` walks path components and creates each missing remote directory (`sftp_transfer_handler.py:848-861`)

**2. Per-host SSH connection limits with blocking:**

The connection pool previously created unlimited SSH connections, which could overwhelm servers that limit concurrent connections per user.

**Fix:**
- Added `_max_connections_per_host` dict to track per-host limits (default 8)
- Added `_pending_connections` dict to prevent race conditions during SSH creation
- Added `_connection_condition` (threading.Condition) for blocking/waiting
- `get_connection()` now loops: reuse existing → create new if under limit → block waiting for release
- `release_connection()` now calls `notify_all()` to wake waiting threads
- `set_max_connections()` / `get_max_connections()` API for configuring limits

**3. Removed dead `max_concurrent_transfers` spinner:**

The old "Concurrent:" spinner controlled `max_concurrent_transfers` which only gated the legacy `sftp_queue` path. Since `check_and_start_transfers()` no longer enforces this limit (transfers now start immediately via `DirectTransferWorker`), the spinner was dead UI.

**Fix:**
- Removed `self.spinBox` and `on_value_changed()` from `sftp.py`
- Replaced with single "SSH Conn:" spinner (`self.ssh_conn_spinbox`) backed by `max_ssh_connections_per_host` preference
- `on_ssh_conn_value_changed()` persists the setting
- `connect()` reads the preference and calls `pool.set_max_connections()` on each connection

**Files Modified:**
- `sftp_transfer_handler.py` — Directory creation for uploads/downloads
- `sftp_connection_pool.py` — Per-host connection limits with blocking
- `sftp_preferences.py` — Added `max_ssh_connections_per_host` default
- `sftp.py` — Replaced dead spinner with SSH Conn spinner; applied limits on connect
- `sftp_transfer_queue_widget.py` — Removed `max_concurrent_transfers` check

### Remote Directory Tracking (CRITICAL)

This has been a recurring source of bugs. Follow these rules:

**1. Credentials are the source of truth for current directory:**
```python
# CORRECT - Use credentials
from sftp_creds import get_credentials
creds = get_credentials(self.session_id)
current_dir = creds.get('current_remote_directory', '.')

# INCORRECT - Creating new SSH session returns HOME directory
ssh = paramiko.SSHClient()
ssh.connect(...)
stdin, stdout, stderr = ssh.exec_command('pwd')  # Always returns /home/user!
```

**2. NEVER use `get_remote_cwd_direct()` for path construction:**
- This function creates a **new SSH session** which always starts in the home directory
- It returns `/home/user` NOT the current SFTP working directory
- Only use for initial connection when credentials are empty

**3. Initialization Order Matters:**
```python
# CORRECT ORDER in sftp.py:
1. set_credentials_async()           # Set initial connection info
2. test_connection()                  # Verify SFTP works
3. navigate_to_initial_directories()  # Set current_remote_directory
4. prepare_container_widget()         # Creates browser, calls initialize_model()

# INCORRECT - Browser initializes before initial directory is set:
prepare_container_widget()  # Uses /home/user
navigate_to_initial_directories()  # Too late! Browser already initialized
```

**4. Complete path detection:**
```python
def is_complete_path(self, path):
    # ONLY absolute paths starting with '/' are complete
    # Hidden files like '.mozilla' are NOT complete paths
    return path.startswith('/')
```

**5. Path construction:**
```python
# For complete paths (start with '/')
remote_path = path  # Already absolute

# For incomplete paths (filenames like '.mozilla')
remote_path = self.get_normalized_remote_path(current_dir, filename)
# Results in: /mnt/.mozilla (correct)
# NOT: /home/user/.mozilla (wrong)
```

### Common Navigation Error Messages

- **"It's neither a directory nor a file"** - Usually means:
  - Path was constructed incorrectly (using wrong base directory)
  - Stat failed because path doesn't exist
  - Check that `current_remote_directory` credential is correct

- **"No such file or directory"** - Path is malformed or file really doesn't exist

## Interface Structure

### Integrated Tab Layout

The application now uses a single main window with permanent tabs:

```
Main Window Tabs:
├── Tab 0: 📋 Transfers (permanent, non-closable)
├── Tab 1: 🔗 Connections (permanent, non-closable)  
└── Tab 2+: Connection tabs (SFTP browser or SSH terminal)
```

### Widget Classes

**Transfer Queue:**
- File: `sftp_transfer_queue_widget.py`
- Class: `TransferQueueWidget(QWidget)`
- Features: Transfer list, progress bars, pause/cancel controls, preferences checkboxes
- Signals: `signal_transfer_started`, `signal_transfer_completed`, `signal_transfer_error`

**Connections (Site Manager):**
- File: `sftp_connections_widget.py`
- Class: `ConnectionsWidget(QWidget)`
- Features: Site list, connection details, connection type selection (SFTP/SSH Terminal)

**File Browser Panel:**
- File: `sftp_file_browser_panel.py`
- Class: `FileBrowserPanel(QWidget)`
- Features: Collapsible local browser, QSplitter resizing, toggle button

**SSH Terminal:**
- File: `sftp_terminal_widget.py`
- Class: `SSHTerminalWidget(QWidget)`
- Features: Interactive SSH shell, ANSI code stripping, dark theme
- Uses paramiko `invoke_shell()` for interactive sessions

**Local Terminal:**
- File: `sftp_local_terminal_widget.py`
- Class: `LocalTerminalWidget(QWidget)`
- Architecture: QProcess-based with pipes (no PTY dependency)
- Cross-platform: Works on Windows, macOS, and Linux
- Features: Built-in line editor, command history (up/down), file path tab completion, prompt display
- Shell runs in non-interactive mode; widget handles all line editing
- Uses `strip_ansi_codes()` for output cleaning (same as SSH terminal)
- Marker-based command completion detection (`echo ___SFTP_PROMPT_READY___`)
- Limitations: No job control (Ctrl+Z), no interactive programs (vim, top, less)

### Key Implementation Notes

1. **Permanent Tabs:**
   - Index 0: Transfers tab (cannot be closed)
   - Index 1: Connections tab (cannot be closed)
   - Index 2+: Connection tabs (can be SFTP browser or SSH terminal)

2. **closeTab() Protection:**
   ```python
   def closeTab(self, index):
       if index <= 1:  # Protect transfers and connections tabs
           return
   ```

3. **Signal Handling:**
   - `ConnectionsWidget.connect_requested` → `MainWindow.handle_connection_request()`
   - Auto-switches to connection form tab after connecting
   - TransferQueueWidget signals for status bar updates

4. **Connection Types:**
   - Sites can be configured as "SFTP Browser" or "SSH Terminal"
   - Connection type is persisted per-site in connection data

5. **Preferences:**
   - File: `sftp_preferences.py`
   - Stored in: `~/.sftp_client_preferences.json`
   - Includes: `clear_completed_on_complete`, `overwrite_on_transfer`, `confirm_exit`, `focus_transfers_on_start`, `tree_view_position`, `toolbar_buttons`

6. **Keyboard Shortcuts:**
   - Global shortcuts registered in `MainWindow.setup_keyboard_shortcuts()`
   - Browser shortcuts handled in `Browser.keyPressEvent()`
   - See README.md for complete shortcut list

7. **Backward Compatibility:**
   - Original `sftp_backgroundthreadwindow.py` preserved
   - `sftp_hostdataeditor.py` - HostDataEditor class removed (replaced by ConnectionsWidget), functions retained
   - Original `FileBrowser` and `RemoteFileBrowser` classes preserved
   - Old dialog-based code still exists but not used

### Old vs New Structure

**OLD (Separate Windows):**
```
Main Window
├── Transfer Queue (separate window)
├── Site Manager (modal dialog)
└── Connection tabs
```

**NEW (Integrated):**
```
Main Window (single window)
├── 📋 Transfers tab (integrated)
├── 🔗 Connections tab (integrated)  
└── Connection tabs (closable, with collapsible local browser)
```

## Common Pitfalls

1. **Never access global queues without locks**
2. **Always set timeout on blocking waits**
3. **Check if items exist before accessing table/model indices**
4. **Use `.get()` with defaults for dictionary access**
5. **Clean up response queues even on errors**
6. **Test UI responsiveness with QApplication.processEvents()**

## Dependencies

Core dependencies (install with pip):
- PyQt6
- paramiko
- cryptography
- icecream
- humanize (optional, for file size formatting)

No formal requirements.txt exists - install manually as needed.

## New Features (2026-02-22)

### File Preview Panel

The preview panel (`sftp_preview_widget.py`) provides:
- Text file preview (up to 100KB)
- Image preview (PNG, JPG, GIF, BMP, SVG up to 5MB)
- File info display (size, permissions, modified date)
- Toggle with `Ctrl+P` or 👁 button
- Automatic cleanup of temp files via `atexit`

### Customizable Toolbar

Toolbar buttons can be customized via `sftp_toolbar_customizer.py`:
- Drag to reorder in the dialog
- Double-click to show/hide
- Right-click toolbar for quick toggle menu
- Settings persist in preferences

### Tree View Position

The directory tree panel can be positioned:
- Above or below the file list
- Toggle with ↕ button when tree is visible
- Position saved in `tree_view_position` preference

### Bookmarks

Per-host directory bookmarks:
- Add with `Ctrl+D` or ⭐ button
- Stored in connection data per-hostname
- Quick jump from bookmarks menu

### Tab Management

- Double-click tab to rename
- Right-click for context menu
- Connection manager has copy function for sites

### Persistent Transfer Queue

Unfinished transfers are saved and restored between sessions:
- Queued transfers saved to `~/.sftp_client_transfer_queue.json`
- File uses mode 0o600 (owner read/write only)
- Credentials included (encrypted when possible)
- Auto-deleted after successful restoration
- Restored transfers re-added to queue on startup
- Message displayed in console showing count of restored transfers

### Security Enhancements

Key security improvements:
1. **Separate key storage**: `~/.sftp_client_key` with mode 0o600
2. **Secure file permissions**: All credential files use restrictive permissions
3. **No hardcoded defaults**: Removed guest/guest credentials
4. **Secure temp handling**: atexit cleanup, hidden files, proper permissions
5. **Sanitized logging**: Private key data removed from debug output
