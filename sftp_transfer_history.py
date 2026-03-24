"""
SFTP Transfer History Module

Provides persistent logging of completed file transfers.
History is stored in the platform-appropriate config directory.
"""
import os
import json
import time
import threading
from datetime import datetime
from pathlib import Path

from sftp_platform import get_history_path, create_secure_directory, secure_file_permissions, is_windows


HISTORY_FILE = get_history_path()
MAX_HISTORY_ENTRIES = 1000


_history_lock = threading.Lock()


def _ensure_history_dir():
    """Ensure the history directory exists with proper permissions."""
    create_secure_directory(os.path.dirname(HISTORY_FILE))


def _load_history():
    """Load history from disk."""
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
    except (OSError, IOError, json.JSONDecodeError):
        pass
    return []


def _save_history(history):
    """Save history to disk with proper permissions."""
    _ensure_history_dir()
    if is_windows():
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    else:
        old_umask = os.umask(0o077)
        try:
            with open(HISTORY_FILE, 'w') as f:
                json.dump(history, f, indent=2)
            secure_file_permissions(HISTORY_FILE)
        finally:
            os.umask(old_umask)


def log_transfer(source_path, destination_path, direction, 
                 hostname=None, username=None, file_size=None,
                 status='success', error_message=None, duration=None):
    """
    Log a completed or failed file transfer.
    
    Args:
        source_path: Source file path
        destination_path: Destination file path
        direction: 'upload' or 'download'
        hostname: Remote hostname (optional)
        username: Remote username (optional)
        file_size: File size in bytes (optional)
        status: 'success' or 'failed'
        error_message: Error message if failed (optional)
        duration: Transfer duration in seconds (optional)
    
    Returns:
        dict: The logged entry
    """
    entry = {
        'timestamp': datetime.now().isoformat(),
        'epoch': time.time(),
        'source_path': str(source_path),
        'destination_path': str(destination_path),
        'direction': direction,
        'hostname': hostname,
        'username': username,
        'file_size': file_size,
        'status': status,
        'error_message': error_message,
        'duration': duration
    }
    
    with _history_lock:
        history = _load_history()
        history.insert(0, entry)
        
        # Trim to max entries
        if len(history) > MAX_HISTORY_ENTRIES:
            history = history[:MAX_HISTORY_ENTRIES]
        
        _save_history(history)
    
    return entry


def get_history(limit=None, direction=None, status=None, hostname=None):
    """
    Get transfer history entries.
    
    Args:
        limit: Maximum number of entries to return (optional)
        direction: Filter by 'upload' or 'download' (optional)
        status: Filter by 'success' or 'failed' (optional)
        hostname: Filter by hostname (optional)
    
    Returns:
        list: List of history entries (newest first)
    """
    with _history_lock:
        history = _load_history()
    
    # Apply filters
    if direction:
        history = [h for h in history if h.get('direction') == direction]
    if status:
        history = [h for h in history if h.get('status') == status]
    if hostname:
        history = [h for h in history if h.get('hostname') == hostname]
    
    if limit:
        history = history[:limit]
    
    return history


def clear_history():
    """Clear all transfer history."""
    with _history_lock:
        _save_history([])


def export_history(output_path, format='json'):
    """
    Export transfer history to a file.
    
    Args:
        output_path: Path to export file
        format: 'json', 'csv', or 'txt'
    
    Returns:
        int: Number of entries exported
    """
    with _history_lock:
        history = _load_history()
    
    if not history:
        return 0
    
    if format == 'json':
        with open(output_path, 'w') as f:
            json.dump(history, f, indent=2)
    elif format == 'csv':
        import csv
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'direction', 'source', 'destination', 
                           'hostname', 'size', 'status', 'error'])
            for entry in history:
                writer.writerow([
                    entry.get('timestamp', ''),
                    entry.get('direction', ''),
                    entry.get('source_path', ''),
                    entry.get('destination_path', ''),
                    entry.get('hostname', ''),
                    entry.get('file_size', ''),
                    entry.get('status', ''),
                    entry.get('error_message', '')
                ])
    elif format == 'txt':
        with open(output_path, 'w') as f:
            for entry in history:
                ts = entry.get('timestamp', '')
                direction = entry.get('direction', '')
                src = entry.get('source_path', '')
                dst = entry.get('destination_path', '')
                status = entry.get('status', '')
                size = entry.get('file_size', '')
                err = entry.get('error_message', '')
                f.write(f"{ts} | {direction} | {src} -> {dst} | {status}")
                if size:
                    f.write(f" | {size} bytes")
                if err:
                    f.write(f" | ERROR: {err}")
                f.write('\n')
    
    return len(history)


def get_statistics():
    """
    Get transfer statistics.
    
    Returns:
        dict: Statistics including counts, success rate, total bytes
    """
    with _history_lock:
        history = _load_history()
    
    if not history:
        return {
            'total_transfers': 0,
            'uploads': 0,
            'downloads': 0,
            'success_count': 0,
            'failed_count': 0,
            'total_bytes': 0,
            'success_rate': 0.0
        }
    
    stats = {
        'total_transfers': len(history),
        'uploads': len([h for h in history if h.get('direction') == 'upload']),
        'downloads': len([h for h in history if h.get('direction') == 'download']),
        'success_count': len([h for h in history if h.get('status') == 'success']),
        'failed_count': len([h for h in history if h.get('status') == 'failed']),
        'total_bytes': sum(h.get('file_size', 0) or 0 for h in history),
    }
    
    if stats['total_transfers'] > 0:
        stats['success_rate'] = stats['success_count'] / stats['total_transfers']
    else:
        stats['success_rate'] = 0.0
    
    return stats