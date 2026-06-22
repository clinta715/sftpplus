# P3: Legacy Transfer System Removal

**Date:** 2026-06-20  
**Status:** Design  

## Goal

Remove the `sftp_queue` / `DownloadWorker` / `Transfer` / `SFTPJob` legacy transfer path from `TransferQueueWidget` and all callers. The new `DirectTransferWorker` path with `TransferModel` / `TransferPersistence` becomes the only file transfer mechanism.

## Scope

**IN SCOPE:**
- Remove 21 legacy-only methods from `sftp_transfer_queue_widget.py`
- Clean legacy code from 7 hybrid methods
- Fix all external callers (`sftp.py`, `sftp_browserclass.py`, `sftp_remotefilebrowserclass.py`)
- Remove dead imports in `sftp_remotefiletablemodel.py`, `sftp_transfer_handler.py`
- Clean `sftp_downloadworkerclass.py` to keep only `ResponseQueueContext` / response queue functions

**OUT OF SCOPE (deferred):**
- Refactoring `sftp_session_executor.py` off `ResponseQueueContext` — separate concern
- Deleting `sftp_downloadworkerclass.py` entirely — still needed by session executor

## Changes by File

### 1. `sftp_transfer_queue_widget.py`

#### 1a. Remove import
```
- from sftp_downloadworkerclass import Transfer, DownloadWorker, SFTPJob, sftp_queue, clear_sftp_queue, response_queues, response_queues_lock
```

#### 1b. Delete 21 legacy-only methods

| # | Method | Lines (~) | Notes |
|---|--------|-----------|-------|
| 1 | `add_queue_item()` | 974 | wraps path + transfer_id for queue |
| 2 | `remove_queue_item()` | 981 | removes by transfer_id |
| 3 | `check_and_start_transfers()` | 1252 | polls `sftp_queue`, calls `start_transfer()` |
| 4 | `start_transfer()` | 1310 | creates `DownloadWorker` + `Transfer` object, starts worker |
| 5 | `cancel_transfer()` | 2050 | stops DownloadWorker, disconnects signals |
| 6 | `cleanup_transfer()` | 2101 | removes Transfer from list, cleans list widget |
| 7 | `_release_transfer()` | 2128 | decrements active_transfers, removes queue item |
| 8 | `transfer_finished()` | 2145 | reads response_queues, updates Transfer UI, logs history |
| 9 | `transfer_error()` | 2278 | marks Transfer as failed, logs history |
| 10 | `_handle_worker_message()` | 2348 | routes messages to `transfer_error()` |
| 11 | `update_progress()` | 2505 | updates Transfer progress_bar/speed_label/eta_label |
| 12 | `format_bytes()` | 2563 | used only by `update_progress()` |
| 13 | `format_speed()` | 2577 | used only by `update_progress()` |
| 14 | `format_time()` | 2588 | used only by `update_progress()` |
| 15 | `toggle_pause_transfer()` | 2599 | pauses individual legacy transfer |
| 16 | `toggle_pause_all()` | 2614 | pauses all legacy transfers |
| 17 | `pause_all_transfers()` | 2634 | pause/resume all via DownloadWorker |
| 18 | `clear_all_transfers()` | 2716 | stops + removes all transfers |
| 19 | `cleanup()` | 2729 | saves, stops timer, clears queue, waits for thread pool |
| 20 | `save_pending_transfers()` | 2755 | reads sftp_queue + self.transfers, writes to file |
| 21 | `load_pending_transfers()` | 2852 | reads file, creates SFTPJob, puts on sftp_queue |

Total: ~860 lines removed.

#### 1c. Clean 7 hybrid methods (remove legacy branches)

1. **`get_active_transfer_count()`** — Remove `self.transfers` iteration. Keep only `_transfer_displays` iteration.

2. **`update_overall_progress()`** — Remove:
   - `active_legacy = [t for t in self.transfers if t.active]`
   - Legacy speed aggregation
   - Legacy bytes aggregation
   - Keep discovery check, current group progress, display-based aggregation.

3. **`stop_all_transfers()`** — Remove:
   - `clear_sftp_queue()` call
   - `self.transfers` iteration for `DownloadWorker._stop_flag`
   - Keep `stop_all_display_transfers()` call + observer traversal cancellation.

4. **`clear_completed()`** — Remove:
   - `self.transfers` iteration
   - `cleanup_transfer()` call
   - Keep `_transfer_displays` iteration + `remove_transfer_display()`.

5. **`add_to_group()`** — Remove:
   - `self.transfers` search
   - `_pending_group_assignments` fallback (model now always initializes this)
   - Keep `_transfer_groups` update.

6. **`_handle_conflict()`** — Remove legacy `self.transfers` search path. Keep only `_active_workers` lookup.

7. **`_process_next_conflict()`** — Remove legacy `self.transfers` search path. Keep only `_active_workers` lookup.

#### 1d. Remove legacy instance attributes

```
- self.queue_items = []
- self.active_transfers = 0
- self.transfers = []
- self.total_queue_items = 0
- self._transfer_lock = QMutex()
- self._active_transfers_lock = QMutex()
- self.check_queue_timer (line 969, in _setup_timers)
- self.thread_pool init + config (lines 866-870)
```

#### 1e. Remove `_setup_timers()` entirely

The timer that polls `check_and_start_transfers` every 100ms. The new system uses `_check_and_start_queued()` called directly.

#### 1f. Remove unused imports

- `import queue`
- `import time` (check if still used elsewhere)

#### 1g. Result
~2915 lines → ~1900 lines (saving ~860 legacy + ~155 hybrid cleanup).

---

### 2. `sftp.py`

| Line | Change |
|------|--------|
| 6 | Remove `from sftp_downloadworkerclass import clear_sftp_queue` |
| 525 | Remove `self.transfers = {}` |
| 635 | Remove `QTimer.singleShot(500, self.transfer_queue_widget.load_pending_transfers)` |
| 723 | Remove `self.clear_queue_button` + `clicked.connect(clear_sftp_queue)` |
| 1016-1019 | Remove `cancel_transfer()` block accessing `self.transfers` |
| 1749 | Replace `self.transfer_queue_widget.cleanup()` with inline: stop queue save timer, stop model workers |
| 1787 | Replace `check_queue_timer.stop()` with `_queue_save_timer` stop |
| 1790-1793 | Remove `transfers[:]` iteration + `_stop_flag` setting |
| 1799 | Remove `thread_pool.waitForDone(2000)` |
| 1823-1824 | Replace `get_active_transfer_count()` + `active_transfers = count` with new path |
| 1825-1826 | Remove local `from sftp_downloadworkerclass import sftp_queue` + `qsize()` |
| 1846-1847 | Replace `clear_all_transfers()` + `clear_sftp_queue()` with existing new-system cleanup |

---

### 3. `sftp_browserclass.py`

| Line | Change |
|------|--------|
| 19-21 | Remove `from sftp_downloadworkerclass import (...)` — 7 symbols |
| 965 | Remove `wait_for_response()` call block |
| 977 | Remove `delete_response_queue()` call |
| 1428 | Remove `QueueItem()` usage |
| 1470 | Remove `delete_response_queue()` call |
| 1887 | Replace `update_progress(...)` → `update_transfer_progress(...)` |
| 1894 | Replace `transfer_finished(...)` → `mark_transfer_complete(...)` |

---

### 4. `sftp_remotefilebrowserclass.py`

| Line | Change |
|------|--------|
| 15 | Remove `from sftp_downloadworkerclass import add_sftp_job` |

---

### 5. `sftp_remotefiletablemodel.py`

| Line | Change |
|------|--------|
| 11 | Remove `from sftp_downloadworkerclass import create_response_queue, delete_response_queue` |

---

### 6. `sftp_transfer_handler.py`

| Line | Change |
|------|--------|
| 5 | Remove `from sftp_downloadworkerclass import add_sftp_job` |

---

### 7. `sftp_downloadworkerclass.py`

Remove dead symbols, keep only what `sftp_session_executor.py` needs:

**KEEP:**
- `response_queues`
- `response_queues_lock`
- `ResponseQueueContext`
- `put_response`
- `create_response_queue`
- `delete_response_queue`
- `check_response_queue`
- `wait_for_response`

**REMOVE:**
- `WorkerSignals`
- `Transfer`
- `transferSignals`
- `QueueItem`
- `SFTPJob` (and `to_dict` / `from_dict`)
- `DownloadWorker` (entire ~600-line class)
- `clear_sftp_queue`
- `add_sftp_job`
- `sftp_queue`
- `sftp_queue_get`, `sftp_queue_put`, `sftp_queue_isempty`
- `strip_decorative_chars`
- `SIZE_UNIT`
- `DEBUG` block

---

### 8. `tests/test_transfer_queue.py`

Rewrite tests that depend on removed legacy classes:
- Remove `SFTPJob` test cases
- Remove `Transfer` test cases
- Remove `WorkerSignals` test cases
- Remove `sftp_queue` test cases
- Keep or rewrite tests for `ResponseQueueContext`, `put_response`, etc.

---

## Verification

1. Syntax check all modified modules:
```bash
python -m py_compile sftp_transfer_queue_widget.py
python -m py_compile sftp.py
python -m py_compile sftp_browserclass.py
python -m py_compile sftp_remotefilebrowserclass.py
python -m py_compile sftp_remotefiletablemodel.py
python -m py_compile sftp_transfer_handler.py
python -m py_compile sftp_downloadworkerclass.py
```

2. Run test suite:
```bash
pytest archive/test_sftp.py -v
pytest tests/test_transfer_queue.py -v
```

3. Verify no remaining references to deleted symbols:
```bash
rg "from sftp_downloadworkerclass import" --include="*.py" | grep -v archive | grep -v tests
```
Should only show `sftp_session_executor.py` after cleanup.

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| `sftp_browserclass.py:1887` wrong signal routing | Verify `update_transfer_progress` accepts same signature (transfer_id, bytes_done, bytes_total, speed_bps) — yes, it does |
| `sftp_browserclass.py:1894` wrong signal routing | Verify `mark_transfer_complete` accepts just (transfer_id) — yes, it does |
| `sftp.py:635` removed `load_pending_transfers` breaks queue restoration | Restoration is now handled by `_load_pending_queue()` in `__init__` via `TransferPersistence` |
| Removing `self.transfers` breaks some hybrid method | All 7 hybrid methods have been cleaned to remove legacy branches |
| `sftp_session_executor.py` broken | Only touches `response_queues`/`ResponseQueueContext`/`put_response` — all kept in `sftp_downloadworkerclass.py` |
