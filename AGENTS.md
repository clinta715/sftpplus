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
- **Customizable context menus**: Toggle visibility of right-click menu items per menu
- **Bookmarks**: Per-host directory bookmarks
- **Tree view**: Directory tree panel (above or below list)
- **Progress tracking**: Real-time progress indicators for file transfers
- **Connection progress dialog**: Step-by-step progress dialog during SSH/SFTP connection
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
| `sftp_context_menu_customizer.py` | Context menu customization dialog |
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

### Nickname Lookup Bug (2026-04-03)

**Bug:** When a site has a nickname configured, selecting it in the Connections widget showed empty fields instead of the saved data.

**Root Cause:**
- The table displayed nicknames (e.g., "My Server") but stored them as the lookup key
- The connection data was keyed by actual hostname (e.g., "server.com"), not the nickname
- Lookup failed because "My Server" didn't exist in the `hostnames` dict

**Fix:**
- Store actual hostname in `Qt.UserRole` data when populating the table
- All lookups now read from `UserRole` instead of table display text
- Falls back to table text if `UserRole` is missing (backward compatibility)

**Files Modified:**
- `sftp_connections_widget.py` — `_update_table()` stores hostname in UserRole; all lookup methods use UserRole

### Connection Data Storage & Delete Bug (2026-04-04)

Multiple bugs fixed across `sftp_hostdataeditor.py` and `sftp_connections_widget.py`.

#### sftp_hostdataeditor.py — 10 bugs fixed

**1. Non-atomic file writes (CRITICAL):**
`save_connection_data()` wrote directly to the data file. A crash mid-write corrupted the entire file (partial JSON).

**Fix:** New `_atomic_write_json()` helper writes to a temp file, flushes+fsyncs, then `os.replace()` for atomic replacement. Also removed the process-wide `os.umask()` hack (replaced by `secure_file_permissions()`).

**2. `_ensure_keys()` defined but never called:**
The function guarantees all expected dict keys exist, but was never invoked. Callers assuming keys like `nicknames` existed could get `KeyError`.

**Fix:** `_ensure_keys()` now called at the end of every `load_connection_data()` return path.

**3. Silent password loss on decryption failure:**
If the key file was deleted but the data file remained, all passwords silently became empty strings with no warning.

**Fix:** Decryption failures are counted and logged as a single prominent warning suggesting the key file was lost.

**4. Key regeneration on transient errors:**
`JSONDecodeError` and `OSError` error paths generated a new encryption key, permanently destroying the old one. A transient file-lock error would make all passwords unrecoverable.

**Fix:** Only `FileNotFoundError` regenerates the key (correct: no data file = no passwords to lose). `JSONDecodeError` and `OSError` preserve the existing key.

**5. `save_connection_data()` drops unknown keys:**
Constructed a new dict with only known keys, silently discarding any keys added by a newer version.

**Fix:** Reads existing file before save and preserves unknown top-level keys via `_KNOWN_TOP_LEVEL_KEYS` set.

**6. `copy_site()`/`rename_site()` silently overwrite:**
Neither checked if the target hostname already existed, silently destroying an existing site.

**Fix:** Both return `False` if target exists (rename allows same-as-source no-op). Uses mutable list flag to propagate guard through `update_connection_data`.

**7. Read functions not thread-safe:**
`get_site_names()`, `get_site_data()`, `get_setting()` called `load_connection_data()` without `_data_lock`, reading partially-written data during concurrent writes.

**Fix:** All three wrapped with `_data_lock`.

**8. Redundant exception catch:**
`except (InvalidToken, Exception)` — `InvalidToken` is a subclass of `Exception`.

**Fix:** Narrowed to `(InvalidToken, ValueError, UnicodeDecodeError)`.

**9. Module-level init crashes on unwritable config dir:**
`_load_encryption_key()` at import time would crash the entire app.

**Fix:** Wrapped in try/except with error logging.

#### sftp_connections_widget.py — Delete display bugs

**1. TOCTOU race in `_update_table()` causing blank rows:**
Called `get_site_names()` (1 load), then `get_site_data()` per hostname (N loads), then `get_setting()` (1 load). If the file changed between calls, a hostname could return `None`, allocating a row that was never populated — visible as a blank row.

**Fix:** Single `load_connection_data()` call reads all data at once.

**2. Stale visual state after deleting second-to-last item:**
Deleting row 5 of 7 left a blank row 6 and the last item (G) appeared missing. `QTableWidget.setRowCount(6)` on a 7-row table didn't fully clear the removed row's geometry. `_clear_details()` fired `textChanged` signals that cascaded into `_update_selected_row()`.

**Fix:**
- `setRowCount(0)` before `setRowCount(N)` fully tears down all rows, items, and header labels
- `setUpdatesEnabled(False/True)` wraps the rebuild to prevent intermediate paints
- `_clear_details()` blocks signals on each widget before clearing
- `show_on_startup_checkbox` blocks signals during rebuild to prevent spurious saves

**Files Modified:**
- `sftp_hostdataeditor.py` — Atomic writes, `_ensure_keys`, key regeneration guards, overwrite guards, thread-safe reads
- `sftp_connections_widget.py` — `_update_table()`, `delete_row()`, `_clear_details()`

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

### Customizable Context Menus

Context menus can be customized via `sftp_context_menu_customizer.py`:
- Toggle visibility of individual menu items
- Separate configs for: file table, remote tree, local tree, transfer queue, tab bar
- Access via right-click menu → "Customize Context Menus..." or toolbar right-click
- Settings persist in `context_menu_items` preference

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

### Browser & Transfer Bug Fixes (2026-04-05)

Multiple bugs fixed across the browser subsystem, transfer queue, and file preview panel.

#### Duplicate Transfer Workers (CRITICAL)

**Bug:** Directory upload/download progress bars flickered between two values.

**Root Cause:** `_add_files_to_queue()` in both `sftp_browserclass.py` and `sftp_remotefilebrowserclass.py` created two `DirectTransferWorker` instances per file:
1. **Path A:** `signal_add_transfer_display.emit(...)` → deferred via QueuedConnection → `_start_queued_transfer()` creates Worker B
2. **Path B:** Direct `DirectTransferWorker(...)` + `QThreadPool.globalInstance().start()` creates Worker A

Both workers transferred the same file and emitted progress to the same `transfer_id`'s progress bar.

**Fix:** Removed direct worker creation (Path B). The signal → `_add_transfer_display` → `_start_queued_transfer` pipeline (Path A) already handles everything correctly.

#### Overall Progress Bar Stuck at 0%

**Bug:** The overall progress bar in the transfer tab never updated during directory transfers.

**Root Cause:** The overall progress reads from `_transfer_groups[group_id]` which tracks `completed_files`/`total_files` and `completed_bytes`/`total_bytes`. These counters were only updated for legacy `Transfer` objects, never for `DirectTransferWorker`-based transfers (`_transfer_displays`). Since all transfers now use `DirectTransferWorker`, the counters stayed at 0.

**Fix:**
- `mark_transfer_complete` and `mark_transfer_failed` now increment `_transfer_groups[group_id]["completed_files"]`
- `_start_queued_transfer` adds source file size to `_transfer_groups[group_id]["total_bytes"]`
- `update_transfer_progress` tracks delta byte progress via `_transfer_groups[group_id]["completed_bytes"]`
- Removed dead `update_group_progress` method (defined but never called)

#### Directory Download Signal Tuple Mismatch

**Bug:** Directory downloads showed no progress display and progress bar stayed at "Queued".

**Root Cause:** `signal_add_transfer_display` emit in `sftp_remotefilebrowserclass.py` passed 11 items but `_add_transfer_display_slot` expects 13 (missing `session_id` and `group_id`). PySide6 silently swallowed the `ValueError`.

**Fix:** Added missing `session_id` and `group_id` to the signal emit tuple.

#### Other Bugs Fixed

1. **`sftp_browserclass.py:1907` — Indentation error in `view_edit_file()`**: Over-indented `if is_remote:` block made entire method body unreachable.

2. **`sftp_browserclass.py:1130-1135` — Double `upload_download` call**: Second call with wrong arguments after file save dialog.

3. **`sftp_browserclass.py:1357` — Wrong command for overwrite upload**: Set `"download"` instead of `"upload"`.

4. **`sftp_file_browser_panel.py:216-238` — `.get()` on tuples**: `RemoteFileTableModel.file_list` stores tuples, not dicts. Every `file_info.get(...)` crashed with `AttributeError`.

5. **`sftp_remotefilebrowserclass.py` — `os.path.join` for remote paths**: On Windows, `os.path.join` produces backslash-separated paths. Remote SFTP paths require forward slashes. Added `_remote_join()` helper.

6. **`sftp_remotefilebrowserclass.py:540-624` — 84 lines of dead code**: Copy-pasted `remove_directory_with_prompt` inside `_remove_remote_directory_recursive` that never executed.

#### Thread Safety Fixes

**`sftp_remotefiletablemodel.py` — Module-level `_sftp_ops_cache`:**
- Added `_sftp_ops_lock = threading.Lock()` to protect the check-then-set TOCTOU race
- Added `_clear_sftp_ops()` helper for safe invalidation (close + delete under lock)
- Fixed mutable cache reference: `cache[path] = list(new_file_list)` instead of `cache[path] = self.file_list`

**`sftp_browser_mixins.py` — Dead caching removed:**
- Removed `_sftp_ops_cache`, `_sftp_ops_session_id`, `_sftp_ops_lock`, `get_sftp_operations()` (cached), and `clear_sftp_cache()` from `FileOpsMixin`
- These were all dead code since `Browser` overrides every method via MRO
- Methods now use `_create_ops()` which creates a fresh `SFTPOperations` per call

**Files Modified:**
- `sftp_browserclass.py` — Indentation fix, double call fix, wrong command fix, duplicate worker removal
- `sftp_remotefilebrowserclass.py` — `_remote_join` helper, dead code removal, signal tuple fix, duplicate worker removal
- `sftp_transfer_queue_widget.py` — Group progress tracking in `mark_transfer_complete`/`mark_transfer_failed`/`update_transfer_progress`/`_start_queued_transfer`, removed dead `update_group_progress`
- `sftp_remotefiletablemodel.py` — Thread-safe `_sftp_ops_cache` with lock, cache stores copy not reference
- `sftp_browser_mixins.py` — Removed dead caching, added `_create_ops()`
- `sftp_file_browser_panel.py` — Fixed `.get()` on tuples, uses index access
- `sftp.py` — Added `_on_overall_progress` status bar handler

### Transfer Reliability & Persistent UI State (2026-04-05)

Transfer retry logic, connection pool resilience, and persistent browser preferences.

#### Transient Connection Failures During Bulk Transfers (CRITICAL)

**Bug:** When uploading/downloading many files simultaneously, ~10% of transfers failed with `Secsh channel N open FAILED: open failed: Connect failed`. Retrying manually always succeeded.

**Root Cause:** Two issues:
1. `ConnectionPool.get_connection()` used an infinite `while True` loop. When `open_sftp()` or SSH connect failed, it never gave up — so `DirectTransferWorker` had no way to know a failure occurred and retry at a higher level.
2. `DirectTransferWorker` had **zero retry logic** — any connection failure was a permanent failure.

**Fix — Connection pool bounded retries with exponential backoff:**
- `get_connection()` now retries up to 15 times with exponential backoff (0.3s → 0.6s → 1.2s → ... → 8s cap for channel opens, 0.5s → 10s cap for new SSH connections)
- After 15 failed attempts, raises `RuntimeError` so the caller can handle it
- Failed `open_sftp()` on existing connections now backs off before retrying instead of spinning

**Fix — Worker retry with visual feedback:**
- `DirectTransferWorker.run()` now calls `_do_transfer()` up to 5 times with exponential backoff (2s, 4s, 8s, 16s)
- `_is_transient_error()` detects channel/timeout/EOF/transport errors as retryable; permission errors fail immediately
- New `retrying` signal emits `(attempt, max_attempts, error_msg)` before each retry
- Transfer queue shows amber "Retry 2/5" status and "Retry 2/5 - waiting..." progress bar during retries

**Fix — Manual retry for failed transfers:**
- Failed transfers show "Failed - double-click to retry" in progress bar
- Double-click a failed transfer to re-queue it immediately
- Right-click context menu shows "Retry" option for failed items
- Full `transfer_info` dict stored in each display for re-creation on retry

**Files Modified:**
- `sftp_connection_pool.py` — Bounded retries with exponential backoff in `get_connection()`
- `sftp_transfer_handler.py` — `DirectTransferWorker` retry loop, `_is_transient_error()`, `_do_transfer()`, `retrying` signal
- `sftp_transfer_queue_widget.py` — `retrying` status color, `_handle_retrying()`, `_retry_failed_transfer()` on double-click, context menu retry action, stores `transfer_info` in display dict

#### Persistent Sort Order

Column sort order is now saved between sessions.

**Implementation:**
- `sort_column` (default 0) and `sort_order` (default "ascending") added to preferences
- Browser base class reads preferences on init via `sortByColumn()`
- `sortIndicatorChanged` signal saves to preferences on every column header click
- Subclasses no longer hardcode `sortByColumn(0, AscendingOrder)`

**Files Modified:**
- `sftp_preferences.py` — Added `sort_column` and `sort_order` defaults
- `sftp_browserclass.py` — Read/apply sort preferences, `_on_sort_changed()` handler
- `sftp_filebrowserclass.py` — Removed hardcoded sort
- `sftp_remotefilebrowserclass.py` — Removed hardcoded sort

#### Persistent Tree View State

Tree view enabled/disabled state is saved per side (local/remote) between sessions.

**Implementation:**
- `local_tree_visible` and `remote_tree_visible` (default `False`) added to preferences
- Browser base class sets `_pending_tree_populate` flag during `init_ui()` (before subclass attrs exist)
- Each subclass (`FileBrowser`, `RemoteFileBrowser`) checks flag at end of `__init__` and defers `populate_tree_view()` via `QTimer.singleShot(0, ...)`
- `toggle_tree_view()` saves preference on every toggle

**Files Modified:**
- `sftp_preferences.py` — Added `local_tree_visible` and `remote_tree_visible` defaults
- `sftp_browserclass.py` — Restore tree state, save on toggle, `_pending_tree_populate` flag
- `sftp_filebrowserclass.py` — Deferred tree populate at end of `__init__`
- `sftp_remotefilebrowserclass.py` — Deferred tree populate at end of `__init__`

### Connection Progress Dialog (2026-04-06)

The connection process now shows a modal `QProgressDialog` with step labels instead of freezing the UI.

**Problem:**
The `connect()` method's `test_connection()` call blocked the UI thread for 2-12+ seconds during DNS resolution, SSH handshake, auth, and SFTP channel open. Status messages emitted during this time were never painted because the Qt event loop was blocked. User saw a blank tab and spinning beachball cursor.

**Solution:**
Moved the SSH/SFTP connection test to a background `ConnectionTestWorker` (QRunnable) while showing a window-modal `QProgressDialog` with a local `QEventLoop` to keep the UI responsive.

**New classes in `sftp.py`:**

```python
class ConnectionTestSignals(QObject):
    step = Signal(str)           # "Connecting to host:port..."
    success = Signal(str)        # home directory path
    error = Signal(str)          # error message
    prompt_unknown_host = Signal(str, str, str)  # host, key_type, fingerprint
    prompt_bad_host_key = Signal(str, str)        # host, fingerprint

class ConnectionTestWorker(QRunnable):
    # Runs SSH/SFTP connection test in background thread
    # Emits step labels at each phase
    # Handles host key prompts via threading.Event synchronization
```

**Progress dialog steps:**
1. "Connecting to {hostname}:{port}..." — before `ssh.connect()`
2. "Authenticating..." / "Authenticating with SSH key..." — during auth
3. "Opening SFTP channel..." — before `ssh.open_sftp()`
4. "Testing directory access..." — before `sftp.listdir('.')`
5. "Determining home directory..." — before `ssh.exec_command('pwd')`

**Host key handling in background worker:**
The worker uses `threading.Event` + `resolve_prompt()` for synchronous host key prompts. When `InteractivePolicy.missing_host_key()` or `BadHostKeyException` occurs in the worker thread, it emits a signal (QueuedConnection → UI thread), shows a `QMessageBox`, and calls `worker.resolve_prompt(True/False)`. The worker thread blocks on `Event.wait()` until the UI thread resolves the prompt.

**Modified `connect()` method (`sftp.py:1397`):**
- Validation and credential setup remain synchronous (fast, <100ms)
- SSH key loading (`_load_private_key()`) runs on UI thread (may show passphrase dialog)
- Connection test delegated to `_test_connection_with_progress()` which runs the worker with progress dialog
- Post-connection steps (navigate, create widget, initialize browser) remain synchronous

**Files Modified:**
- `sftp.py` — `ConnectionTestSignals`, `ConnectionTestWorker`, `_test_connection_with_progress()` (new), `connect()` (modified to use worker), added `threading`, `QProgressDialog`, `QRunnable`, `QThreadPool`, `QEventLoop` imports

### Remote Browser Tree View Button Labels (2026-04-06)

**Bug:** Remote browser tree view showed "Upload" and "Upload All" buttons instead of "Download" and "Download All".

**Root Cause:**
`RemoteFileBrowser` extends `FileBrowser`, which overrides the base `Browser` tree buttons from "Download"/"Download All" to "Upload"/"Upload All" (correct for local browser). `RemoteFileBrowser` inherited these overrides without correcting them back.

**Fix:**
Added button text override in `RemoteFileBrowser.__init__()` to set them back to "Download"/"Download All".

**Files Modified:**
- `sftp_remotefilebrowserclass.py` — Added tree button text override after `super().__init__()`

### Overall Transfer Progress Fixes (2026-04-06)

Multiple bugs fixed in the overall progress bar and status display for directory transfers.

#### Bug 1: `total_bytes` always 0 for downloads (CRITICAL)

**Root Cause:**
`_start_queued_transfer()` only called `os.path.getsize()` when `is_source_remote` was `False` (uploads). For downloads the source is remote, so `total_bytes` stayed 0. This broke ETA calculation and status bar byte display (showed "150 MB / 0 B").

**Fix:**
For downloads, use the connection pool to do a quick SFTP `stat()` call to get the remote file size before starting the worker. Adds ~50-100ms per file start but provides accurate byte totals.

```python
if transfer_info['is_source_remote']:
    from sftp_connection_pool import get_connection_pool
    pool = get_connection_pool()
    _ssh, _sftp = pool.get_connection(hostname, port, username, password, key)
    file_size = _sftp.stat(source_path).st_size
    pool.release_connection(hostname, port, username, _sftp)
```

#### Bug 2: `_current_group_id` never reset

**Root Cause:**
`_current_group_id` was set in `start_transfer_group()` but never reset to `None` when the group completed. After a directory transfer finished, subsequent individual transfers would still use the stale group's metrics.

**Fix:**
`mark_transfer_complete()` and `mark_transfer_failed()` now check if `completed_files >= total_files` and reset `_current_group_id = None`.

#### Bug 3: `_transfer_groups` entries never cleaned up

**Root Cause:**
Group entries accumulated indefinitely — one per directory transfer, never deleted. Memory leak over long sessions.

**Fix:**
Same as Bug 2 — `del self._transfer_groups[group_id]` when the group completes.

#### Bug 4: File-count based progress instead of byte-based

**Root Cause:**
`overall_percent = int((completed_files / total_files) * 100)` jumped in equal increments per file regardless of size. A directory with 99 small files and 1 large file would hit 99% almost instantly then stall.

**Fix:**
`update_overall_progress()` now uses `completed_bytes / total_bytes` for the progress bar percentage (capped at 99% while active), falling back to file-count when `total_bytes` is 0 (e.g., if all stat calls failed). The label shows both file count and humanized byte totals:

```
Transferring: 5/20 files • 45.2 MB/120.0 MB • 2.3 MB/s
```

ETA uses `max(0, total_bytes - completed_bytes)` to avoid negative values.

**Files Modified:**
- `sftp_transfer_queue_widget.py` — `_start_queued_transfer()` (remote stat), `mark_transfer_complete()` (group cleanup), `mark_transfer_failed()` (group cleanup), `update_overall_progress()` (byte-based progress)

### Type Safety & Resume Fix (2026-04-08)

Multiple type mismatch bugs fixed across signals, models, and the transfer resume feature.

#### Bug 1: Signal type mismatch in `mark_transfer_failed` (CRITICAL)

**Root Cause:**
`signal_transfer_error` is declared as `Signal(int, str)` (count, message), but `mark_transfer_failed()` emitted `signal_transfer_error.emit(transfer_id, error_message)` where `transfer_id` is a string. PySide6 silently logged `_pythonToCppCopy: Cannot copy-convert (str) to C++` and the handler `_on_transfer_error()` received garbage for the `count` parameter.

**Fix:**
Moved `active_transfers` decrement before the emit, and changed to `signal_transfer_error.emit(self.active_transfers, error_message)` so the first arg is always an int.

#### Bug 2: `QDateTime.fromSecsSinceEpoch()` with float mtime

**Root Cause:**
Paramiko's `SFTPAttributes.st_mtime` can be a float (sub-second precision from some servers). PySide6's `QDateTime.fromSecsSinceEpoch()` expects `int` (C++ `qint64`).

**Fix:**
Wrapped `mtime` in `int()` at `sftp_remotefiletablemodel.py:255`.

#### Bug 3: Port stored as string in credentials

**Root Cause:**
`set_credentials()` stored port as `str(self.temp_port)` instead of `int(self.temp_port)`. The string port propagated through `SFTPOperations`, `ConnectionPool`, and signal emit tuples.

**Fix:**
Changed to `int(self.temp_port)` at `sftp.py:1886`.

#### Bug 4: Resume command not handled in `DirectTransferWorker` (CRITICAL)

**Root Cause:**
When users picked "Resume" from the file conflict dialog, callers set `command = "resume"`. But `_do_transfer()` only checked `self.command == "upload"` and `self.command == "download"`. The "resume" command fell through to the `else` block, emitting `"Unknown command: resume"` and marking the transfer as failed. The resume logic (seek + append) was correct but never executed.

**Fix:**
Added normalization at the top of `_do_transfer()`:
```python
command = self.command
if command == "resume":
    command = "download" if self.is_source_remote else "upload"
```
This maps resume to the correct upload/download branch, where the existing `if resume:` code paths handle seek + append correctly.

#### Bug 5: `QColor` from compat layer not accepted by `setForeground()`

**Root Cause:**
`sftp_toolbar_customizer.py` used `Qt.Color_darkGray` from the compat layer, but PySide6's `QListWidgetItem.setForeground()` requires a proper `QColor` object, not a `QtCore.Qt.GlobalColor` enum value.

**Fix:**
Replaced with `QColor(169, 169, 169)` constant.

#### Other Changes

- Connection test worker: Added transient error retry logic with friendly error messages for banner/timeout/refused/unreachable errors
- Host key removal: Robust `HostKeys` deletion handling across paramiko versions
- Known hosts directory: Auto-created via `create_secure_directory()` before saving
- Tree context menus: Refactored to use customizable context menu items with per-menu configs
- File table context menus: Refactored to use customizable context menu items
- Tab bar context menus: Refactored to use customizable context menu items
- Discovery progress throttling: `TraversalWorker` now throttles discovery signals to max every 200ms or 50 files
- File size tracking: `TraversalWorker` now collects file sizes during discovery (included in 4-tuple)
- Disk full detection: `DirectTransferWorker` detects disk full errors and stops retries
- Batch add: Browser classes use `begin_batch_add()`/`end_batch_add()` when adding multiple transfers from traversal

**Files Modified:**
- `sftp_transfer_queue_widget.py` — Signal type fix, batch add methods, file size in tuples, discovery throttling
- `sftp_transfer_handler.py` — Resume command normalization, disk full detection, file size in collected files, discovery throttling
- `sftp_remotefiletablemodel.py` — `int(mtime)` guard
- `sftp.py` — Port stored as int, transient error retry, friendly error messages, host key fixes, context menu customization, known_hosts path
- `sftp_browserclass.py` — Customizable context menus, file size in transfer tuples, batch add
- `sftp_filebrowserclass.py` — Customizable tree context menus
- `sftp_remotefilebrowserclass.py` — Customizable tree context menus, file size in transfer tuples, batch add
- `sftp_preferences.py` — Added `context_menu_items` default configuration
- `sftp_toolbar_customizer.py` — QColor fix for setForeground
- `sftp_terminal_widget.py` — Known hosts path and directory creation
- `sftp_context_menu_customizer.py` — New file: context menu customization dialog

### Connection Guard & Local Browser Performance (2026-04-16)

Three fixes: connection dialog auto-cancel, concurrent connection re-entrancy, and local file listing performance.

#### Bug 1: `progress.close()` triggers `canceled()` signal (CRITICAL)

**Bug:** `QProgressDialog.close()` emits the `canceled()` signal when a cancel button is present. After a successful connection, `close()` triggered `on_cancel()` which set `cancelled[0] = True`, causing `_test_connection_with_progress()` to return `None` — silently failing every connection.

**Root Cause:** The previous commit added a "Cancel" button to the connection progress dialog (replacing `None`). `QProgressDialog.close()` internally calls `cancel()` which emits `canceled()`. The check `if cancelled[0]: return None` ran after `close()`, treating successful connections as cancelled.

**Fix:** Save result values before closing, disconnect the `canceled` signal before `close()`, and only treat as cancelled if `home_dir is None`:
```python
home_dir = result['home_dir']
was_cancelled = cancelled[0]
progress.canceled.disconnect(on_cancel)
progress.close()
if was_cancelled and home_dir is None:
    return None
```

#### Bug 2: Concurrent connection re-entrancy (CRITICAL)

**Bug:** While a slow connection's progress dialog was showing (UI responsive via `QEventLoop`), clicking another site re-entered `connect()`, clobbering shared instance variables (`self.session_id`, `self.temp_hostname`, etc.). Result: duplicate tabs with mixed credentials.

**Root Cause:** No guard against concurrent `connect()` calls. The `QEventLoop` inside `_test_connection_with_progress()` processes UI events, allowing the user to trigger another connection. All connection state (`self.session_id`, `self.temp_hostname`, `self.container_widget`) are instance-level and get overwritten.

**Fix:** Added `self._connecting = False` flag. `connect()` checks the flag at entry and wraps the body in `try/finally`:
```python
def connect(self, ...):
    if self._connecting:
        self.message_signal.emit("A connection is already in progress. Please wait.")
        return None
    self._connecting = True
    try:
        # ... existing body ...
    finally:
        self._connecting = False
```

#### Fix 3: Local file listing performance

**Problem:** `FileTableModel.get_files()` was synchronous — stating every file in the local directory on the UI thread. For directories with thousands of files, this caused multi-second freezes during connection initialization. Additionally, `data()` called `os.path.isdir()` (fresh stat) for every cell render despite already caching `is_dir` in `file_info[4]`.

**Fix — Async listing:**
- `FileTableModel.__init__()` no longer calls `get_files()` — model starts empty
- `get_files()` now spawns `FileListWorker` (already existed for remote listings) in `QThreadPool`, returns immediately
- Results populate via `beginResetModel()`/`endResetModel()` callback with generation counter to discard stale results
- Mirrors the pattern `RemoteFileTableModel` already uses

**Fix — Cached is_dir in `data()`:**
- `ForegroundRole` and `FontRole` now read `file_info[4]` / `file_info[5]` instead of calling `os.path.isdir()` / `os.path.islink()`
- Eliminates ~80k redundant stat syscalls during initial render of a 10k-file directory

**Files Modified:**
- `sftp.py` — Connection guard (`_connecting` flag), progress dialog `canceled` signal disconnect
- `sftp_filetablemodel.py` — Async `get_files()` with `FileListWorker`, cached `is_dir`/`is_link` in `data()`, removed `processEvents()` and `RemoteFileTableModel` import
- `sftp_filebrowserclass.py` — Added `self.model.get_files()` call after model construction
