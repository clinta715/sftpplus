# P3: Legacy Transfer System Removal — Implementation Plan

> **For agentic workers:** Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task.

**Goal:** Remove the `sftp_queue`/`DownloadWorker`/`Transfer`/`SFTPJob` legacy transfer path from `TransferQueueWidget` and all callers.

**Architecture:** The new `DirectTransferWorker` path with `TransferModel`/`TransferPersistence` is the only file transfer mechanism after this change. The `sftp_downloadworkerclass.py` module is trimmed down to only the response-queue utilities needed by `sftp_session_executor.py`.

**Tech Stack:** Python 3.14, PySide6, paramiko

---

### Task 1: Remove legacy-only methods from `sftp_transfer_queue_widget.py`

**File:** `sftp_transfer_queue_widget.py` — multiple edits

- [ ] **Step 1: Remove the import from `sftp_downloadworkerclass`**

Delete this import line:

```python
from sftp_downloadworkerclass import Transfer, DownloadWorker, SFTPJob, sftp_queue, clear_sftp_queue, response_queues, response_queues_lock
```

- [ ] **Step 2: Remove `add_queue_item()` and `remove_queue_item()`**

Delete both methods. `add_queue_item()` starts at line ~974 and `remove_queue_item()` starts at line ~981.

- [ ] **Step 3: Remove `check_and_start_transfers()` and `start_transfer()`**

Delete both methods. `check_and_start_transfers()` starts at line ~1252 and `start_transfer()` starts at line ~1310.

- [ ] **Step 4: Remove `cancel_transfer()`, `cleanup_transfer()`, `_release_transfer()`**

Delete these three related methods. `cancel_transfer()` starts at line ~2050, `cleanup_transfer()` at line ~2101, `_release_transfer()` at line ~2128.

- [ ] **Step 5: Remove `transfer_finished()`, `transfer_error()`, `_handle_worker_message()`**

Delete these three methods. `transfer_finished()` starts at line ~2145, `transfer_error()` at line ~2278, `_handle_worker_message()` at line ~2348.

- [ ] **Step 6: Remove `update_progress()`, `format_bytes()`, `format_speed()`, `format_time()`**

Delete these four methods. `update_progress()` starts at line ~2505, `format_bytes()` at line ~2563, `format_speed()` at line ~2577, `format_time()` at line ~2588.

- [ ] **Step 7: Remove `toggle_pause_transfer()`, `toggle_pause_all()`, `pause_all_transfers()`**

Delete these three methods. `toggle_pause_transfer()` starts at line ~2599, `toggle_pause_all()` at line ~2614, `pause_all_transfers()` at line ~2634.

- [ ] **Step 8: Remove `clear_all_transfers()`, `cleanup()`, `save_pending_transfers()`, `load_pending_transfers()`**

Delete these four methods. `clear_all_transfers()` starts at line ~2716, `cleanup()` at line ~2729, `save_pending_transfers()` at line ~2755, `load_pending_transfers()` at line ~2852.

- [ ] **Step 9: Remove `_setup_timers()` and the check_queue_timer**

`_setup_timers()` starts at line ~966, creates a `check_queue_timer` that polls `check_and_start_transfers` every 100ms. Delete the entire method and remove the call `self._setup_timers()` in `init_ui()` (around line ~873).

Also remove the legacy timer-related attributes set in `_setup_timers()`:
```python
# Remove this from init_ui or wherever it appears:
self._setup_timers()
```

- [ ] **Step 10: Clean `_on_concurrent_changed`**

`_on_concurrent_changed()` calls `self._check_and_start_queued()` at the end. This still works — it's the new system method. Keep as-is.

- [ ] **Step 11: Clean `get_active_transfer_count()`**

Remove the legacy `self.transfers` iteration. Keep only the `_transfer_displays` iteration:

```python
def get_active_transfer_count(self):
    """Get total number of active display-only transfers"""
    count = 0
    for tid, display in self._transfer_displays.items():
        if display.get('is_active', False):
            count += 1
    return count
```

- [ ] **Step 12: Clean `update_overall_progress()`**

Remove:
- Line `active_legacy = [t for t in self.transfers if t.active]`
- Line `active_count = len(active_legacy) + active_display_count` — change to just `active_display_count`
- Legacy speed aggregation at lines ~1170-1171
- Legacy bytes aggregation at lines ~1194-1197
- The `active_transfers` counter usage

The method should only iterate `_transfer_displays` for active counts, speeds, and bytes.

- [ ] **Step 13: Clean `stop_all_transfers()`**

Remove:
- `clear_sftp_queue()` call
- `self.transfers` iteration for `DownloadWorker._stop_flag`
- `self._pending_group_assignments.clear()` (redundant, model handles it)

Keep:
- `stop_all_display_transfers()` call
- Observer traversal cancellation

```python
def stop_all_transfers(self):
    """Cancel all active transfers"""
    try:
        # Stop all active display-based transfers (DirectTransferWorker)
        self.stop_all_display_transfers()

        # Cancel any active traversal or deletion workers in browser observees
        with QMutexLocker(self._observees_lock):
            for observee in self._observees:
                if hasattr(observee, '_current_traversal_worker') and observee._current_traversal_worker:
                    observee._current_traversal_worker.cancel()
                    observee._current_traversal_worker = None
                if hasattr(observee, '_deletion_worker') and observee._deletion_worker:
                    observee._deletion_worker.cancel()

        self.text_console.append("All transfers stopped")

    except (OSError, IOError, RuntimeError) as e:
        self.text_console.append(f"Error stopping transfers: {e}")
```

- [ ] **Step 14: Clean `clear_completed()`**

Remove:
- `self.transfers` iteration block (the first for loop)
- `cleanup_transfer()` call path

Keep only the `_transfer_displays` iteration:

```python
def clear_completed(self):
    """Remove completed/cancelled/error transfers"""
    try:
        transfers_to_remove = []

        # Check display-only transfers
        for tid, display in list(self._transfer_displays.items()):
            if not display.get('is_active', False):
                status_text = display['status_label'].text() if 'status_label' in display else ""
                if status_text in ["Done", "Failed", "Stopped", "Cancelled"]:
                    transfers_to_remove.append(tid)

        for transfer_id in transfers_to_remove:
            self.remove_transfer_display(transfer_id)

    except (OSError, IOError, RuntimeError) as e:
        self.text_console.append(f"Error clearing completed transfers: {e}")
```

- [ ] **Step 15: Clean `add_to_group()`**

Remove the `self.transfers` search. The method already updates `_transfer_groups` correctly:

```python
def add_to_group(self, transfer_id, group_id, file_size=0):
    """Add a transfer to a group"""
    if group_id in self._transfer_groups:
        self._transfer_groups[group_id]["total_bytes"] += file_size
```

- [ ] **Step 16: Clean `_handle_conflict()`**

Remove the legacy `self.transfers` search block. Keep only the `_active_workers` lookup (DirectTransferWorker path):

```python
def _handle_conflict(self, transfer_id, dest_path, dest_type):
    """Handle file conflict - queue prompt so only one dialog shows at a time"""
    worker = None
    group_id = None

    # Check active workers (DirectTransferWorker)
    if transfer_id in self._active_workers:
        worker = self._active_workers[transfer_id]
        if transfer_id in self._transfer_displays:
            group_id = self._transfer_displays[transfer_id].get('group_id')

    if not worker:
        return

    # Check per-group flags first (no dialog needed)
    if group_id:
        action = self.model.check_group_conflict_action(group_id)
        if action:
            worker.set_conflict_result(action)
            return

    # Queue the conflict and process serially
    self._conflict_queue.append((transfer_id, dest_path, dest_type))
    if not self._conflict_dialog_active:
        self._process_next_conflict()
```

- [ ] **Step 17: Clean `_process_next_conflict()`**

Remove the legacy `self.transfers` search block. Keep only the `_active_workers` lookup:

```python
def _process_next_conflict(self):
    """Show the next conflict dialog in the queue"""
    if not self._conflict_queue:
        self._conflict_dialog_active = False
        return

    self._conflict_dialog_active = True
    transfer_id, dest_path, dest_type = self._conflict_queue.pop(0)

    try:
        worker = None
        group_id = None

        # Check active workers (DirectTransferWorker)
        if transfer_id in self._active_workers:
            worker = self._active_workers[transfer_id]
            if transfer_id in self._transfer_displays:
                group_id = self._transfer_displays[transfer_id].get('group_id')

        if not worker:
            self._process_next_conflict()
            return

        # Re-check group flags (may have been set by a previous dialog)
        if group_id:
            action = self.model.check_group_conflict_action(group_id)
            if action:
                worker.set_conflict_result(action)
                self._process_next_conflict()
                return

        filename = os.path.basename(dest_path)
        location = "on remote" if dest_type == "remote" else "locally"

        msg_box = QMessageBox()
        msg_box.setIcon(Qt.MsgIcon_Question)
        # ... rest of method stays the same ...
```

- [ ] **Step 18: Remove legacy instance attributes**

Remove these lines from `__init__`:
```python
self.queue_items = []
self.active_transfers = 0
self.transfers = []
self.total_queue_items = 0
self._transfer_lock = QMutex()
self._active_transfers_lock = QMutex()
```

Also remove `self.thread_pool` lines (init and config) from `init_ui`:
```python
# Initialize thread pool
self.thread_pool = QThreadPool.globalInstance()
if self.thread_pool.maxThreadCount() < 20:
    self.thread_pool.setMaxThreadCount(20)
```

- [ ] **Step 19: Remove unused imports**

Remove:
```python
import queue
import time
```

Check if `time` is used anywhere else in the file first (it might be used for `time.time()` in `add_transfer_display`):
- `time.time()` at line ~1541 — this is in the new `add_transfer_display()` method. So `time` import is still needed.
- `queue.Empty` in the removed legacy code — this was the only use of `queue`.

So just remove `import queue`, keep `import time`.

- [ ] **Step 20: Syntax check**

```bash
python -m py_compile sftp_transfer_queue_widget.py
```
Expected: SYNTAX OK

---

### Task 2: Fix `sftp.py` — MainWindow cleanup

**File:** `sftp.py` — multiple edits

- [ ] **Step 1: Remove the top-level import**

Delete line 6:
```python
from sftp_downloadworkerclass import clear_sftp_queue
```

- [ ] **Step 2: Remove `self.transfers` dict**

Delete line 525:
```python
self.transfers = {}  # Dictionary to store active transfers
```

- [ ] **Step 3: Remove `cancel_transfer()` method**

Delete lines 1016-1019 — the entire `cancel_transfer()` method:
```python
def cancel_transfer(self, transfer_id):
    if transfer_id in self.transfers:
        self.transfers[transfer_id].download_worker._stop_flag = True
        self.message_signal.emit(f"Cancelling transfer {transfer_id}")
```

- [ ] **Step 4: Remove `create_cancel_button()` method**

Delete lines 1011-1014 — the entire `create_cancel_button()` method references the removed `cancel_transfer`:
```python
def create_cancel_button(self, transfer_id):
    cancel_button = QPushButton("Cancel")
    cancel_button.clicked.connect(lambda: self.cancel_transfer(transfer_id))
    return cancel_button
```

- [ ] **Step 5: Remove `clear_queue_button`**

Delete these lines:
```python
self.clear_queue_button = QPushButton("Clear Queue")
self.clear_queue_button.setStyleSheet(BUTTON_STYLE_DARK)
```
(at lines ~513-514)

Remove the button from the layout:
```python
self.button_layout.addWidget(self.clear_queue_button)
```
at line ~710.

Remove the click connection:
```python
self.clear_queue_button.clicked.connect(clear_sftp_queue)
```
at line ~723.

- [ ] **Step 6: Clean `cleanup()` method**

Replace the legacy-heavy `cleanup()` method:

```python
def cleanup(self):
    if hasattr(self, '_cleanup_performed') and self._cleanup_performed:
        return
    self._cleanup_performed = True

    try:
        if hasattr(self, 'transfer_queue_widget'):
            # Stop the queue save timer if it exists
            if hasattr(self.transfer_queue_widget, '_queue_save_timer') and self.transfer_queue_widget._queue_save_timer:
                self.transfer_queue_widget._queue_save_timer.stop()
            # Cancel all active workers
            self.transfer_queue_widget.model.cancel_all_workers()

        self.close_sftp_connections()
    except (OSError, RuntimeError) as e:
        pass
```

- [ ] **Step 7: Clean `stop_background_thread()` method**

Replace with a simple version that only stops the new system:

```python
def stop_background_thread(self):
    """Stop the transfer queue processing"""
    try:
        if hasattr(self, 'transfer_queue_widget'):
            # Stop the queue save timer
            if hasattr(self.transfer_queue_widget, '_queue_save_timer') and self.transfer_queue_widget._queue_save_timer:
                self.transfer_queue_widget._queue_save_timer.stop()

            # Cancel all active workers
            self.transfer_queue_widget.model.cancel_all_workers()

    except (OSError, IOError, RuntimeError) as e:
        logger.debug(f"Error stopping background thread: {e}")
```

- [ ] **Step 8: Clean `closeEvent()` method**

Replace lines 1819-1847 with logic that uses the new system only:

```python
active_count = 0
queued_count = 0
if hasattr(self, 'transfer_queue_widget'):
    tw = self.transfer_queue_widget
    active_count = tw.get_active_transfer_count()
    queued_count = len(tw._pending_display_transfers)

if active_count > 0 or queued_count > 0:
    total = active_count + queued_count
    msg = f'There are {total} pending file transfers ({active_count} active, {queued_count} queued).\n\n'
    msg += 'Unfinished transfers will be saved and resumed on next launch.\n\n'
    msg += 'What would you like to do?'
    reply = QMessageBox(self)
    reply.setWindowTitle("Confirm Exit")
    reply.setText(msg)
    save_button = reply.addButton("Exit and Save Transfers", QMessageBox.ButtonRole.ActionRole)
    discard_button = reply.addButton("Exit and Discard Transfers", QMessageBox.ButtonRole.DestructiveRole)
    cancel_button = reply.addButton(QMessageBox.StandardButton.Cancel)
    reply.setDefaultButton(save_button)
    reply.exec()

    if reply.clickedButton() == cancel_button:
        event.ignore()
        return
    elif reply.clickedButton() == discard_button:
        tw._pending_display_transfers.clear()
        self.message_signal.emit("Transfers discarded")

event.accept()
```

- [ ] **Step 9: Replace `load_pending_transfers` timer call**

Delete line 635:
```python
QTimer.singleShot(500, self.transfer_queue_widget.load_pending_transfers)
```

The queue restoration is now handled automatically by `_load_pending_queue()` called in `TransferQueueWidget.__init__()` (line ~221).

- [ ] **Step 10: Syntax check**

```bash
python -m py_compile sftp.py
```
Expected: SYNTAX OK

---

### Task 3: Fix `sftp_browserclass.py` — remove legacy routing

**File:** `sftp_browserclass.py` — 3 edits

- [ ] **Step 1: Remove the `sftp_downloadworkerclass` import**

Delete lines 19-21:
```python
from sftp_downloadworkerclass import (create_response_queue, delete_response_queue,
                                       check_response_queue, wait_for_response, QueueItem, ResponseQueueContext,
                                       add_sftp_job)
```

- [ ] **Step 2: Remove `waitjob()` method entirely (dead code)**

Delete lines 957-983 — the entire `waitjob()` method:
```python
def waitjob(self, job_id, timeout=30):
    ...
```

- [ ] **Step 3: Remove `QueueItem` usage and `delete_response_queue` cleanup**

In `upload_download()` method, delete line 1428:
```python
queue_item = QueueItem(os.path.basename(selected_path), job_id)
```

Also delete lines 1467-1470 — the `finally` block that does `delete_response_queue(job_id)`:
```python
finally:
    # Clean up any remaining job resources
    if job_id is not None:
        delete_response_queue(job_id)
```

- [ ] **Step 4: Fix `_handle_direct_transfer_progress()`**

Replace the legacy `update_progress` call with the new `update_transfer_progress`:

```python
def _handle_direct_transfer_progress(self, transfer_id, bytes_done, bytes_total, speed, eta):
    """Handle progress updates from DirectTransferWorker"""
    if not hasattr(self, 'transfer_queue_widget') or not self.transfer_queue_widget:
        return

    logger.debug(f"_handle_direct_transfer_progress: {transfer_id}, {bytes_done}/{bytes_total}, speed={speed}")

    self.transfer_queue_widget.update_transfer_progress(transfer_id, bytes_done, bytes_total, speed)
```

Note: `update_transfer_progress` takes (transfer_id, bytes_done, bytes_total, speed_bps) — it doesn't need the `eta` or `value` params that `update_progress` required.

- [ ] **Step 5: Fix `_handle_direct_transfer_finished()`**

Replace the legacy `transfer_finished` call with the new `mark_transfer_complete`:

```python
def _handle_direct_transfer_finished(self, transfer_id):
    """Handle transfer finished from DirectTransferWorker"""
    if not hasattr(self, 'transfer_queue_widget') or not self.transfer_queue_widget:
        return

    self.transfer_queue_widget.mark_transfer_complete(transfer_id)
```

- [ ] **Step 6: Syntax check**

```bash
python -m py_compile sftp_browserclass.py
```
Expected: SYNTAX OK

---

### Task 4: Fix `sftp_remotefilebrowserclass.py` — remove dead import

**File:** `sftp_remotefilebrowserclass.py` — 1 edit

- [ ] **Step 1: Remove dead import**

Delete line 15:
```python
from sftp_downloadworkerclass import add_sftp_job
```

- [ ] **Step 2: Syntax check**

```bash
python -m py_compile sftp_remotefilebrowserclass.py
```
Expected: SYNTAX OK

---

### Task 5: Fix `sftp_remotefiletablemodel.py` — remove dead import

**File:** `sftp_remotefiletablemodel.py` — 1 edit

- [ ] **Step 1: Remove dead import**

Delete line 11:
```python
from sftp_downloadworkerclass import create_response_queue, delete_response_queue
```

- [ ] **Step 2: Syntax check**

```bash
python -m py_compile sftp_remotefiletablemodel.py
```
Expected: SYNTAX OK

---

### Task 6: Fix `sftp_transfer_handler.py` — remove dead import

**File:** `sftp_transfer_handler.py` — 1 edit

- [ ] **Step 1: Remove dead import**

Delete line 5:
```python
from sftp_downloadworkerclass import add_sftp_job
```

- [ ] **Step 2: Syntax check**

```bash
python -m py_compile sftp_transfer_handler.py
```
Expected: SYNTAX OK

---

### Task 7: Clean `sftp_downloadworkerclass.py` — remove dead classes

**File:** `sftp_downloadworkerclass.py` — trim to only keep what `sftp_session_executor.py` needs

- [ ] **Step 1: Remove all dead code**

Keep only:
```python
"""
Legacy download worker — only response queue utilities remain for sftp_session_executor.py
"""
import threading
import queue
from unittest.mock import Mock

response_queues = {}
response_queues_lock = threading.Lock()


class ResponseQueueContext:
    """Context manager for thread-safe response queue lifecycle"""

    def __init__(self, job_id):
        self.job_id = job_id

    def __enter__(self):
        create_response_queue(self.job_id)
        return response_queues[self.job_id]

    def __exit__(self, exc_type, exc_val, exc_tb):
        delete_response_queue(self.job_id)
        return False


def delete_response_queue(job_id):
    with response_queues_lock:
        try:
            del response_queues[job_id]
        except KeyError:
            pass


def create_response_queue(job_id):
    with response_queues_lock:
        response_queues[job_id] = queue.Queue()


def check_response_queue(job_id):
    if job_id in response_queues:
        try:
            return response_queues[job_id].get_nowait()
        except queue.Empty:
            return None
    return None


def wait_for_response(job_id, timeout=30):
    if job_id not in response_queues:
        return False, None
    try:
        response = response_queues[job_id].get(timeout=timeout)
        return True, response
    except queue.Empty:
        return False, None


def put_response(transfer_id, *items):
    with response_queues_lock:
        if transfer_id in response_queues:
            try:
                for item in items:
                    response_queues[transfer_id].put(item)
            except Exception:
                pass
```

Remove everything else: `WorkerSignals`, `Transfer`, `transferSignals`, `QueueItem`, `SFTPJob`, `DownloadWorker`, `clear_sftp_queue`, `add_sftp_job`, `sftp_queue`, `sftp_queue_get`, `sftp_queue_put`, `sftp_queue_isempty`, `strip_decorative_chars`, `SIZE_UNIT`, `DEBUG` block.

- [ ] **Step 2: Syntax check**

```bash
python -m py_compile sftp_downloadworkerclass.py
```
Expected: SYNTAX OK

---

### Task 8: Fix tests

**File:** `tests/test_transfer_queue.py` — rewrite

- [ ] **Step 1: Remove tests for removed classes**

Remove test classes that depend on removed symbols:
- `TestTransferQueuePersistence` — uses `SFTPJob`
- `TestTransferQueueProgress` — uses `WorkerSignals`, `Transfer`
- `TestTransferQueueMessages` — uses `QueueItem`
- `TestTransferUtils` — uses `strip_decorative_chars`, `SIZE_UNIT`

- [ ] **Step 2: Keep/update tests for kept symbols**

Keep:
- `TestTransferQueueControls` — uses `TransferQueueWidget` (still exists)
- `TestTransferQueueThreadSafety` — uses `response_queues`, `response_queues_lock`, `ResponseQueueContext` (all kept)
- `TestTransferFormatting` — tests general math concepts, imports nothing from downloadworkerclass
- `TestTransferProgress` — tests general math concepts, imports nothing from downloadworkerclass

- [ ] **Step 3: Run the test suite**

```bash
pytest tests/test_transfer_queue.py -v
```

---

### Task 9: Final verification

- [ ] **Step 1: Syntax check all modified modules**

```bash
python -m py_compile sftp_downloadworkerclass.py
python -m py_compile sftp_transfer_queue_widget.py
python -m py_compile sftp.py
python -m py_compile sftp_browserclass.py
python -m py_compile sftp_remotefilebrowserclass.py
python -m py_compile sftp_remotefiletablemodel.py
python -m py_compile sftp_transfer_handler.py
```

- [ ] **Step 2: Run archive test suite**

```bash
pytest archive/test_sftp.py -v
```
Expected: 24 passed, 1 failed (AutoAddPolicy — pre-existing, unrelated)

- [ ] **Step 3: Verify no remaining references to deleted symbols**

```bash
rg "from sftp_downloadworkerclass import" --include="*.py" | grep -v archive | grep -v tests
```

Expected output: only `sftp_session_executor.py` (which imports `put_response` and `ResponseQueueContext`).

- [ ] **Step 4: Quick import test**

```bash
python -c "from sftp_transfer_queue_widget import TransferQueueWidget; print('OK')"
```
Expected: OK
