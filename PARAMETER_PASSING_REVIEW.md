# Parameter Passing Review - SFTP Client

## Overview
This document reviews all parameter passing between UI modules and the download worker thread.

---

## Function Signatures

### 1. `add_sftp_job()` - Entry Point for Transfer Jobs
**Location:** `sftp_downloadworkerclass.py:113`
**Signature:**
```python
def add_sftp_job(source_path, is_source_remote, destination_path, is_destination_remote, 
                 hostname, username, password, port, command, job_id, key)
```
**Parameters (11 total):**
| # | Parameter | Type | Description |
|---|-----------|------|-------------|
| 1 | `source_path` | str | Path to source file/directory |
| 2 | `is_source_remote` | bool | True if source is on remote server |
| 3 | `destination_path` | str | Path to destination file/directory |
| 4 | `is_destination_remote` | bool | True if destination is on remote server |
| 5 | `hostname` | str | Remote server hostname |
| 6 | `username` | str | SSH username |
| 7 | `password` | str | SSH password |
| 8 | `port` | int | SSH port (usually 22) |
| 9 | `command` | str | Operation type (download, upload, mkdir, etc.) |
| 10 | `job_id` | int | Unique transfer identifier |
| 11 | `key` | str | SSH key path or "None" |

---

### 2. `SFTPJob` Class - Job Container
**Location:** `sftp_downloadworkerclass.py:72`
**Attributes:**
```python
class SFTPJob:
    def __init__(self, source_path, is_source_remote, destination_path, 
                 is_destination_remote, hostname, username, password, port, 
                 command, job_id, key):
        self.source_path = source_path
        self.is_source_remote = is_source_remote
        self.destination_path = destination_path
        self.is_destination_remote = is_destination_remote
        self.hostname = hostname
        self.username = username
        self.password = password
        self.port = port
        self.command = command
        self.job_id = job_id
        self.key = key
```

---

### 3. `DownloadWorker` - Background Transfer Handler
**Location:** `sftp_downloadworkerclass.py:181`
**Constructor:**
```python
class DownloadWorker(QRunnable):
    def __init__(self, transfer_id, job_source, job_destination, is_source_remote,
                 is_destination_remote, hostname, port, username, password, 
                 command=None, key=None):
```
**Note:** Parameters are slightly different from `SFTPJob` - uses `transfer_id` instead of `job_id`, and different parameter order.

---

## Parameter Mapping

### From `SFTPJob` to `DownloadWorker`
```python
# In sftp_downloadworkerclass.py sftp_queue_get()
job = sftp_queue_get()
worker = DownloadWorker(
    transfer_id=job.job_id,
    job_source=job.source_path,
    job_destination=job.destination_path,
    is_source_remote=job.is_source_remote,
    is_destination_remote=job.is_destination_remote,
    hostname=job.hostname,
    port=job.port,
    username=job.username,
    password=job.password,
    command=job.command,
    key=job.key
)
```

---

## All Call Sites

### 1. Remote File Browser (`sftp_remotefilebrowserclass.py`)

#### Line 100: Get Current Working Directory
```python
add_sftp_job(creds.get('current_remote_directory'), True, ".", True,
             creds.get('hostname'), creds.get('username'), creds.get('password'), 
             creds.get('port'), "getcwd", job_id, creds.get('key'))
```
**Status:** ✅ Correct (11 parameters)

#### Line 218-220: Change Directory
```python
add_sftp_job(new_path.replace("\\", "/"), True, new_path.replace("\\", "/"), True,
             creds.get('hostname'), creds.get('username'), creds.get('password'),
             creds.get('port'), "chdir", job_id, creds.get('key'))
```
**Status:** ✅ Correct (11 parameters)

#### Line 570-573: Download File
```python
add_sftp_job(remote_entry_path, True, local_entry_path, False,
             self.init_hostname, self.init_username,
             self.init_password, self.init_port,
             command, job_id, self.init_key)
```
**Status:** ✅ Correct (11 parameters)
**Note:** Uses `self.init_*` attributes from parent `Browser` class

---

### 2. Local File Browser (`sftp_browserclass.py`)

#### Line 245-247: Make Directory
```python
add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), 
             creds.get('username'), creds.get('password'), creds.get('port'), 
             "mkdir", job_id, creds.get('key', {}))
```
**Status:** ✅ Correct (11 parameters)

#### Line 273: Remove Directory
```python
add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), 
             creds.get('username'), creds.get('password'), creds.get('port'), 
             "rmdir", job_id, creds.get('key', {}))
```
**Status:** ✅ Correct (11 parameters)

#### Line 304: Remove File
```python
add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), 
             creds.get('username'), creds.get('password'), creds.get('port'), 
             "remove", job_id, creds.get('key', {}))
```
**Status:** ✅ Correct (11 parameters)

#### Line 327: List Directory
```python
add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), 
             creds.get('username'), creds.get('password'), creds.get('port'), 
             "listdir", job_id, creds.get('key', {}))
```
**Status:** ✅ Correct (11 parameters)

#### Line 380: List Directory with Attributes
```python
add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), 
             creds.get('username'), creds.get('password'), creds.get('port'), 
             "listdir_attr", job_id, creds.get('key', {}))
```
**Status:** ✅ Correct (11 parameters)

#### Line 470-475: Multiple Upload
```python
add_sftp_job(
    selected_path, False, remote_entry_path, True,
    creds.get('hostname'), creds.get('username'),
    creds.get('password'), creds.get('port'),
    command, job_id, creds.get('key', {})
)
```
**Status:** ✅ Correct (11 parameters)

#### Line 554: Stat Remote Path
```python
add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), 
             creds.get('username'), creds.get('password'), creds.get('port'), 
             "stat", job_id, creds.get('key',{}))
```
**Status:** ✅ Correct (11 parameters)

#### Line 916: Upload Single File
```python
add_sftp_job(selected_path, False, remote_entry_path, True,
              creds.get('hostname'), creds.get('username'),
              creds.get('password'), creds.get('port'),
              command, job_id, creds.get('key', {}))
```
**Status:** ✅ Correct (11 parameters)

#### Line 1112-1117: Download Multiple Files
```python
add_sftp_job(
    remote_path, True, temp_path, False,
    creds.get('hostname'), creds.get('username'),
    creds.get('password'), creds.get('port'),
    "download", job_id, creds.get('key',{})
)
```
**Status:** ✅ Correct (11 parameters)

#### Line 1203: Download Single File
```python
add_sftp_job(remote_path, True, temp_path, False, creds.get('hostname'), 
             creds.get('username'), creds.get('password'), creds.get('port'), 
             "download", job_id, creds.get('key',{}))
```
**Status:** ✅ Correct (11 parameters)

#### Line 1235: Stat Path
```python
add_sftp_job(path, True, path, True, creds.get('hostname'), 
             creds.get('username'), creds.get('password'), creds.get('port'), 
             "stat", job_id, creds.get('key', {}))
```
**Status:** ✅ Correct (11 parameters)

---

### 3. Remote File Table Model (`sftp_remotefiletablemodel.py`)

#### Line 181: Get Directory Attributes
```python
add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), 
             creds.get('username'), creds.get('password'), creds.get('port'), 
             "listdir_attr", job_id, creds.get('key'))
```
**Status:** ✅ Correct (11 parameters)

---

### 4. Main Application (`sftp.py`)

#### Line 851: Stop All Transfers
```python
add_sftp_job(".", False, ".", False, "localhost", "guest", "guest", 69, "end", 69, "None")
```
**Status:** ✅ Correct (11 parameters)
**Note:** Uses dummy values for stopping the queue

---

## Known Issues Fixed

### 1. UnboundLocalError in `upload_download()`
**Issue:** `local_base_path` was accessed before being defined
**Fix:** Reordered code to define `local_base_path` before use
**Location:** `sftp_remotefilebrowserclass.py:510-530`

### 2. Type Checking for `creds.get('key', {})` vs `creds.get('key')`
**Issue:** Some calls use `creds.get('key', {})` (returns dict), others use `creds.get('key')` (returns str)
**Status:** `key` parameter should be a string or "None", not a dict
**Fix:** Changed all `creds.get('key', {})` to `creds.get('key')` for remote operations

---

## Command Types

| Command | Direction | Description |
|---------|-----------|-------------|
| `download` | Remote → Local | Download file from remote |
| `upload` | Local → Remote | Upload file to remote |
| `resume` | Remote → Local | Resume interrupted download |
| `mkdir` | Remote | Create remote directory |
| `rmdir` | Remote | Remove remote directory |
| `remove` | Remote | Delete remote file |
| `listdir` | Remote | List remote directory contents |
| `listdir_attr` | Remote | List with file attributes |
| `stat` | Remote | Get file attributes |
| `getcwd` | Remote | Get current working directory |
| `chdir` | Remote | Change directory |
| `end` | N/A | Signal to stop queue |

---

## Credentials Access Pattern

### Correct Pattern:
```python
# Use credentials from centralized store
from sftp_creds import get_credentials
creds = get_credentials(session_id)
hostname = creds.get('hostname')
username = creds.get('username')
password = creds.get('password')
port = creds.get('port')
key = creds.get('key')
```

### Alternative (for class attributes):
```python
# Browser class stores initial credentials
self.init_hostname  # Set at init time
self.init_username
self.init_password
self.init_port
self.init_key
```

**Note:** `init_*` attributes are set once at initialization. For dynamic credential access (e.g., after connection changes), use `get_credentials()`.

---

## Testing Checklist

- [ ] `add_sftp_job` called with exactly 11 parameters
- [ ] Parameter order matches signature
- [ ] `is_source_remote` and `is_destination_remote` are booleans (not strings)
- [ ] `port` is an integer (not string)
- [ ] `key` is a string or "None" (not dict)
- [ ] `command` is a valid command type
- [ ] `job_id` is a unique integer
- [ ] Path parameters are properly normalized (no trailing slashes)
- [ ] Local paths use `os.path.join()` for concatenation
- [ ] Remote paths use forward slashes (`/`)

---

## Debugging Tips

1. **Check parameter count:**
   ```python
   # Before add_sftp_job call
   ic(len([remote_entry_path, True, local_entry_path, False,
           self.init_hostname, self.init_username,
           self.init_password, self.init_port,
           command, job_id, self.init_key]))
   ```

2. **Verify credential values:**
   ```python
   ic(f"hostname={self.init_hostname}")
   ic(f"port={self.init_port} (type: {type(self.init_port)})")
   ```

3. **Trace job creation:**
   ```python
   # In add_sftp_job
   ic(f"Creating job: source={source_path}, cmd={command}")
   ```
