# Agent Guidelines for SFTP Client Project

This document provides guidelines for AI coding agents working on this PyQt6-based SFTP client application.

## Features Overview

- **Multi-tabbed interface**: Connect to multiple SFTP servers simultaneously
- **SSH Terminal**: Interactive SSH shell sessions in addition to SFTP
- **Ephemeral connections**: Each operation creates a fresh connection for security
- **Threaded operations**: Uploads/downloads run in background threads
- **Dual-pane interface**: Local and remote file browsers side-by-side
- **Progress tracking**: Real-time progress indicators for file transfers
- **Queue management**: Pause/cancel transfer operations
- **Persistent preferences**: User settings saved to home directory

## New Session-Based API (2026-02-11)

The project now includes a clean session-based API for SFTP operations. This provides a better alternative to the legacy 11-parameter `add_sftp_job()` calls.

### Module Overview

| File | Purpose |
|------|---------|
| `sftp_session.py` | SessionManager and SFTPSession classes for isolated credential storage |
| `sftp_commands.py` | Typed command classes (DownloadCommand, UploadCommand, etc.) |
| `sftp_connection_pool.py` | Thread-safe SSH/SFTP connection pooling |
| `sftp_session_executor.py` | Command executor using sessions and pool |
| `sftp_operations.py` | High-level convenience functions |
| `sftp_terminal_widget.py` | SSH terminal widget with ANSI code stripping |
| `sftp_preferences.py` | Persistent user preferences storage |

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

### Legacy API Compatibility

The old `add_sftp_job()` function is still available and works identically:

```python
# Old API still works (11 parameters)
add_sftp_job(
    source_path, is_source_remote,
    destination_path, is_destination_remote,
    hostname, username, password, port,
    command, job_id, key
)
```

For new code, prefer the session-based API for better type safety and cleaner interfaces.

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
sftp.py                      # Main application entry point
sftp_creds.py               # Thread-safe credential management
sftp_downloadworkerclass.py # Background transfer workers
sftp_backgroundthreadwindow.py # Transfer queue UI
sftp_hostdataeditor.py      # Site manager dialog
sftp_browserclass.py        # Local file browser
sftp_remotefilebrowserclass.py # Remote file browser
sftp_filebrowserclass.py    # Base browser class
sftp_*tablemodel.py         # Table models for file listings
sftp_editwindowclass.py     # Edit window dialog
connection_data.json        # Site configurations (auto-generated)
```

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
   - Includes: `clear_completed_on_complete`, `overwrite_on_transfer`, `confirm_exit`, `focus_transfers_on_start`

6. **Backward Compatibility:**
   - Original `sftp_backgroundthreadwindow.py` preserved
   - Original `sftp_hostdataeditor.py` preserved
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
- PyQt5
- paramiko
- cryptography
- icecream

No formal requirements.txt exists - install manually as needed.
