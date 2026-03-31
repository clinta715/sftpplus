# SFTP Client - Known Issues and Action Items

## Active Action Items

(None currently - all phases complete)

---

## Resolved Issues

### ✅ Full Migration to SFTPSessionAPI (2026-03-31)
- **Phase 1**: Added ssh/sftp kwargs to SFTPOperations for connection reuse
- **Phase 2**: Added DirectTransferWorker using SFTPSessionAPI.execute() directly
- **Phase 3**: Migrated directory transfer (_add_files_to_queue) to use DirectTransferWorker
- Legacy add_sftp_job() still available for remaining callers during transition
- New DirectTransferWorker coexists with legacy queue

### ✅ SFTPSessionAPI Enhancement (2026-03-31)
- Expanded `SFTPSessionAPI.__init__()` to accept optional `ssh` and `sftp` keyword arguments
- This allows passing pre-established SSH/SFTP connections for specialized use cases
- Enables reserved discovery channels for faster directory traversal during large downloads

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

### ✅ SSH Host Key Verification (2026-03-06)
- Replaced `AutoAddPolicy` with `RejectPolicy` in `sftp_connection_pool.py`
- Implemented interactive host key verification in `sftp_terminal_widget.py`
- Added security tests to verify policy settings

### ✅ Error Message Sanitization (2026-03-11)
- Added `sanitize_error_message()` function in `sftp_creds.py`
- Removes passwords, private keys, and sensitive data from error messages
- Applied to all user-facing error messages

### ✅ Exception Handler Improvements (2026-03-11)
- Replaced broad `except Exception` with specific exception types
- Files updated: `sftp_browser_mixins.py`, `sftp_terminal_widget.py`, `sftp_transfer_handler.py`
- Uses `(OSError, IOError, RuntimeError)` or paramiko-specific exceptions

### ✅ Busy-Polling Elimination (2026-03-11)
- Added `wait_for_response()` function with blocking queue get
- Updated `waitjob()` to use blocking wait instead of busy-polling
- Eliminates CPU waste during file transfers

### ✅ Directory Download Functionality (2026-03-11)
- Fixed `FileOpsMixin.__init__` signature to support cooperative multiple inheritance
- Added `DirectoryTransferTask` with QThread for background directory traversal
- Fixed `TraversalWorker` to properly handle signals and cancellation
- Added `auto_overwrite` parameter to avoid blocking prompts during bulk transfers
- Fixed context menu handler to properly select rows before showing menu

### ✅ Directory Structure Preservation (2026-03-11)
- Downloads now preserve directory structure
- When downloading folder `abc`, creates `/local/abc/` and downloads contents into it
- Previously flattened the structure into the local directory

### ✅ Delete Confirmation (2026-03-11)
- Now prompts for confirmation when deleting any directory (not just non-empty)
- Supports multi-select: selecting multiple items and choosing "Remove Directory" deletes all

### ✅ Stop All Transfers (2026-03-11)
- "Stop" button now clears the transfer queue to prevent new transfers
- Also cancels any active directory traversal

### ✅ Refresh Debouncing (2026-03-11)
- Added 500ms debounce to browser refresh during bulk transfers
- Prevents excessive refreshing and duplicate entries when downloading many files

## No Remaining Critical Issues

All priority items have been addressed. The codebase is now:
- Thread-safe with proper locking
- Using specific exception types
- Sanitizing sensitive data from errors
- Using efficient blocking operations instead of busy-polling

## Future Improvements

### SFTPSessionAPI Enhancement
- Expand `SFTPSessionAPI.__init__()` to accept optional `ssh` and `sftp` keyword arguments
- This would allow passing pre-established SSH/SFTP connections for specialized use cases like:
  - Reserved discovery channels for faster directory traversal during large downloads
  - Custom connection handling scenarios
- Currently reverted: discovery channel feature caused TypeError because SFTPSessionAPI doesn't support these kwargs

## Archived Files

See `archive/` for deprecated code and `archive/docs/` for outdated design documents:
- `archive/sftp_browser_actions.py` - Never integrated
- `archive/sftp_navigation.py` - Never integrated  
- `archive/sftp_file_operations.py` - Never integrated
- `archive/docs/ARCHITECTURE_REDESIGN.md` - Session-based design now implemented
- `archive/docs/PARAMETER_PASSING_REVIEW.md` - Old API now deprecated
