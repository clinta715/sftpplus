# Changelog

All notable changes to the SFTP Client application will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
