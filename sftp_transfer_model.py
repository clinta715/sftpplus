"""
Pure data model for TransferQueueWidget state.

Owns all transfer state.

This class has zero Qt widget dependencies and zero file I/O.
"""

import threading
from PySide6.QtCore import QObject


class TransferModel(QObject):
    """
    Thread-safe data model for transfer queue state.

    Owns:
    - _transfer_displays_data (transfer_id -> data dict, no widget refs)
    - _active_workers / _running_workers (worker references for cancellation)
    - _pending_display_transfers (queued transfer info dicts)
    - _session_waiters (transfer_id -> hostname)
    - _transfer_groups / _current_group_id (batch directory transfers)
    - Discovery state, conflict state, pause state, batch state
    - Observers list

    Does NOT own: legacy transfers, sftp_queue, queue_items, active_transfers
    (those remain in TransferQueueWidget for P2).
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Display-only transfer tracking (DirectTransferWorker path)
        # Data only — no QWidget references (those live in UI's _widget_displays)
        self._transfer_displays_data = {}  # transfer_id -> dict
        self._active_workers = {}  # transfer_id -> worker (for cancellation)
        self._running_workers = set()  # strong refs to prevent GC

        # Observer pattern — for refreshing browser after transfers
        self._observees = []
        self._observees_lock = threading.Lock()

        # Directory transfer discovery tracking
        self._discovery_active = False
        self._discovery_files_found = 0
        self._discovery_dirs_scanned = 0
        self._discovery_total_files = None

        # Per-group conflict resolution flags (no dialog needed)
        self._group_overwrite_all = set()
        self._group_skip_all = set()
        self._group_resume_all = set()
        self._group_cancel_all = set()

        # Serialize conflict dialogs — only one at a time
        self._conflict_queue = []
        self._conflict_dialog_active = False

        # Transfer groups — batch progress for directory transfers
        self._transfer_groups = {}  # group_id -> counters dict
        self._current_group_id = None

        # Legacy transfer thread safety
        self._released_transfers = set()

        # Concurrent queue system
        self._pending_display_transfers = []
        self._max_concurrent_transfers = 8
        self._paused = False
        self._paused_by_user = False
        self._session_waiters = {}
        self._batch_add_active = False

        # Legacy pending group assignments
        self._pending_group_assignments = {}

        # Status colors (shared with UI)
        self._status_colors = {
            'waiting_session': '#FFA500',
            'queued': '#888888',
            'transferring': '#4CAF50',
            'complete': '#2196F3',
            'failed': '#F44336',
            'paused': '#666666',
            'retrying': '#FF9800',
        }

    # ====================================================================
    # Transfer display data accessors
    # ====================================================================

    def get_display_data(self, transfer_id):
        """Get data dict for a transfer display, or None."""
        return self._transfer_displays_data.get(transfer_id)

    def get_all_display_data(self):
        """Get all display data dicts (returns a copy)."""
        return dict(self._transfer_displays_data)

    def get_display_data_items(self):
        """Get items view of display data (for iteration)."""
        return list(self._transfer_displays_data.items())

    def has_display(self, transfer_id):
        """Check if a transfer display exists."""
        return transfer_id in self._transfer_displays_data

    def set_display_data(self, transfer_id, data):
        """Set the data dict for a transfer display."""
        self._transfer_displays_data[transfer_id] = data

    def remove_display_data(self, transfer_id):
        """Remove display data and worker references."""
        self._transfer_displays_data.pop(transfer_id, None)
        self._active_workers.pop(transfer_id, None)

    def set_display_field(self, transfer_id, key, value):
        """Set a single field on a display data dict."""
        d = self._transfer_displays_data.get(transfer_id)
        if d is not None:
            d[key] = value

    def get_display_field(self, transfer_id, key, default=None):
        """Get a single field from a display data dict."""
        d = self._transfer_displays_data.get(transfer_id)
        if d is not None:
            return d.get(key, default)
        return default

    # ====================================================================
    # Worker tracking
    # ====================================================================

    def register_worker(self, transfer_id, worker):
        """Register a worker for later cancellation."""
        self._active_workers[transfer_id] = worker
        self._running_workers.add(worker)

    def get_worker(self, transfer_id):
        """Get worker for a transfer_id, or None."""
        return self._active_workers.get(transfer_id)

    def unregister_worker(self, transfer_id):
        """Unregister a worker (on completion/failure)."""
        worker = self._active_workers.pop(transfer_id, None)
        if worker is not None:
            self._running_workers.discard(worker)

    def cancel_all_workers(self):
        """Call cancel() on all active workers."""
        for worker in list(self._active_workers.values()):
            if hasattr(worker, 'cancel'):
                worker.cancel()

    # ====================================================================
    # Pending transfer queue
    # ====================================================================

    def insert_pending_by_priority(self, transfer_info):
        """Insert transfer into pending queue, sorted by priority then time."""
        if self._batch_add_active:
            self._pending_display_transfers.append(transfer_info)
            return
        priority = transfer_info['priority']
        added_time = transfer_info['added_time']
        insert_pos = len(self._pending_display_transfers)
        for i, existing in enumerate(self._pending_display_transfers):
            if existing['priority'] < priority:
                insert_pos = i
                break
            elif existing['priority'] == priority and existing['added_time'] > added_time:
                insert_pos = i
                break
        self._pending_display_transfers.insert(insert_pos, transfer_info)

    def find_pending_index(self, transfer_id):
        """Find index of a transfer in pending queue, or None."""
        for i, t in enumerate(self._pending_display_transfers):
            if t['transfer_id'] == transfer_id:
                return i
        return None

    def remove_pending(self, transfer_id):
        """Remove a transfer from pending queue. Returns the item or None."""
        idx = self.find_pending_index(transfer_id)
        if idx is not None:
            return self._pending_display_transfers.pop(idx)
        return None

    def clear_pending(self):
        """Clear all pending transfers."""
        self._pending_display_transfers.clear()

    def get_next_queued(self):
        """Get the first queued transfer_info, or None."""
        for t in self._pending_display_transfers:
            if t['status'] in ('queued',):
                return t
        return None

    def count_by_status(self, *statuses):
        """Count pending transfers matching any of the given statuses."""
        return sum(1 for t in self._pending_display_transfers
                   if t['status'] in statuses)

    def count_active_displays(self):
        """Count active display transfers."""
        return sum(
            1 for d in self._transfer_displays_data.values()
            if d.get('is_active', False)
        )

    # ====================================================================
    # Pause state
    # ====================================================================

    def is_paused(self):
        return self._paused

    def set_paused(self, paused, by_user=False):
        self._paused = paused
        if by_user:
            self._paused_by_user = paused

    # ====================================================================
    # Batch mode
    # ====================================================================

    def is_batch_active(self):
        return self._batch_add_active

    def set_batch_active(self, active):
        self._batch_add_active = active

    # ====================================================================
    # Session waiters
    # ====================================================================

    def add_session_waiter(self, transfer_id, hostname):
        self._session_waiters[transfer_id] = hostname

    def remove_session_waiter(self, transfer_id):
        self._session_waiters.pop(transfer_id, None)

    def get_waiting_transfers(self, hostname):
        """Get pending transfers waiting for a hostname session."""
        return [
            t for t in self._pending_display_transfers
            if t.get('hostname') == hostname and t.get('status') == 'waiting_session'
        ]

    def has_waiters_for_host(self, hostname):
        """Check if any waiters exist for a host."""
        return hostname in self._session_waiters.values()

    # ====================================================================
    # Transfer groups (batch directory transfers)
    # ====================================================================

    def start_group(self, group_id, total_files):
        """Start tracking a new transfer group."""
        self._current_group_id = group_id
        self._transfer_groups[group_id] = {
            "total_files": total_files,
            "completed_files": 0,
            "total_bytes": 0,
            "completed_bytes": 0,
        }

    def get_group(self, group_id):
        """Get group tracking dict, or None."""
        return self._transfer_groups.get(group_id)

    def get_current_group(self):
        """Get the current active group dict, or None."""
        if self._current_group_id and self._current_group_id in self._transfer_groups:
            return self._transfer_groups[self._current_group_id]
        return None

    def increment_group_completed(self, group_id):
        """Increment completed files and optionally cleanup the group."""
        group = self._transfer_groups.get(group_id)
        if group is None:
            return
        group["completed_files"] += 1
        if group["completed_files"] >= group["total_files"]:
            if self._current_group_id == group_id:
                self._current_group_id = None
            del self._transfer_groups[group_id]

    def add_group_bytes(self, group_id, bytes_count):
        """Add bytes to a group's total_bytes."""
        group = self._transfer_groups.get(group_id)
        if group is not None:
            group["total_bytes"] += bytes_count

    def update_group_bytes(self, group_id, delta):
        """Update completed_bytes by delta."""
        group = self._transfer_groups.get(group_id)
        if group is not None:
            group["completed_bytes"] += delta

    # ====================================================================
    # Group conflict flags
    # ====================================================================

    def check_group_conflict_action(self, group_id):
        """Check if a group has a global conflict action. Returns action or None."""
        if group_id in self._group_cancel_all:
            return "cancel"
        if group_id in self._group_overwrite_all:
            return "overwrite_all"
        if group_id in self._group_skip_all:
            return "skip_all"
        if group_id in self._group_resume_all:
            return "resume_all"
        return None

    def set_group_conflict_action(self, group_id, action):
        """Set a per-group conflict action."""
        if action == "overwrite_all":
            self._group_overwrite_all.add(group_id)
        elif action == "skip_all":
            self._group_skip_all.add(group_id)
        elif action == "resume_all":
            self._group_resume_all.add(group_id)
        elif action == "cancel":
            self._group_cancel_all.add(group_id)

    # ====================================================================
    # Discovery state
    # ====================================================================

    def set_discovery_progress(self, files_found, dirs_scanned):
        self._discovery_files_found = files_found
        self._discovery_dirs_scanned = dirs_scanned
        self._discovery_active = True

    def finish_discovery(self):
        self._discovery_active = False
        self._discovery_total_files = self._discovery_files_found
        self._discovery_files_found = 0
        self._discovery_dirs_scanned = 0

    def is_discovery_active(self):
        return self._discovery_active

    # ====================================================================
    # Conflict dialog queue
    # ====================================================================

    def queue_conflict(self, transfer_id, dest_path, dest_type):
        self._conflict_queue.append((transfer_id, dest_path, dest_type))

    def pop_conflict(self):
        """Pop the next queued conflict. Returns (transfer_id, dest_path, dest_type) or None."""
        if not self._conflict_queue:
            return None
        return self._conflict_queue.pop(0)

    def has_pending_conflicts(self):
        return len(self._conflict_queue) > 0

    # ====================================================================
    # Observers
    # ====================================================================

    def add_observee(self, observee):
        """Add an observer. Thread-safe."""
        with self._observees_lock:
            if observee not in self._observees:
                self._observees.append(observee)

    def remove_observee(self, observee):
        """Remove an observer. Thread-safe."""
        with self._observees_lock:
            if observee in self._observees:
                self._observees.remove(observee)

    def get_observees(self):
        """Get a copy of the observees list. Thread-safe."""
        with self._observees_lock:
            return list(self._observees)
