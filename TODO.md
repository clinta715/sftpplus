# SFTP Client - Known Issues and Action Items

## Critical Security Issues

### 1. SSH Host Key Verification Disabled
**Issue**: `AutoAddPolicy()` accepts all host keys without verification
**Fix Required**: Implement proper host key verification with user confirmation

### 2. Sensitive Data in Error Messages
**Issue**: Error messages may contain file paths and credentials
**Fix Required**: Sanitize error messages before display to users

## Code Quality Issues

### 1. Overly Broad Exception Handling
**Locations**: Multiple files use broad `except Exception` or bare `except`
**Fix Required**: Replace with specific exception types

### 2. Resource Management
**Issues**:
- SSH connections not always closed in error paths
- Response queues may accumulate without cleanup

**Fix Required**: Use context managers and implement proper cleanup

### 3. Performance Issues
**Problems**:
- Some busy polling loops may still exist
- Progress tracking intervals could be optimized

**Fix Required**: Review and replace any remaining polling with blocking operations

## Resolved Issues

### ✅ Session-Based API (2026-02-27)
- Complete migration from legacy 11-parameter `add_sftp_job()` to session-based API
- New `SFTPOperations`, `SFTPSessionAPI`, `CommandExecutor` classes
- Connection pooling implemented

### ✅ Auto-Clear Bug Fix (2026-03-03)
- Fixed `get_bool()` in preferences - was returning `True` for string "false"
- Now properly parses string values: "false", "true", "1", "0", "yes", "no", "on", "off"

### ✅ Progress Display (2026-03-03)
- Added `signal_transfer_progress` signal
- Status bar now shows transfer progress, speed, and ETA

### ✅ Browser Refresh on Error (2026-03-03)
- Added `notify_observees()` call in `transfer_error()`
- Both local and remote browsers refresh even when transfers fail

### ✅ Error Feedback (2026-03-03)
- Transfers tab now focuses when transfers fail
- User can see error messages immediately

### ✅ Case-Insensitive Sorting
- Both local and remote browsers use case-insensitive sorting
- Implemented in `DirectoryFirstSortProxyModel` and `FileTableModel`

## Remaining Action Items

### Priority 1 (Security)
1. Fix SSH host key verification
2. Sanitize error messages

### Priority 2 (Code Quality)
1. Replace remaining broad exception handlers
2. Review resource cleanup in error paths

### Priority 3 (Performance)
1. Audit for any remaining busy-polling loops
2. Optimize progress tracking intervals if needed

## Archived Files

See `archive/` for deprecated code and `archive/docs/` for outdated design documents:
- `archive/sftp_browser_actions.py` - Never integrated
- `archive/sftp_navigation.py` - Never integrated  
- `archive/sftp_file_operations.py` - Never integrated
- `archive/docs/ARCHITECTURE_REDESIGN.md` - Session-based design now implemented
- `archive/docs/PARAMETER_PASSING_REVIEW.md` - Old API now deprecated
