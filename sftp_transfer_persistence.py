"""
File I/O and encryption for persistent transfer queue.

Handles save/load of _pending_display_transfers to disk with
password encryption. The caller (TransferQueueWidget) owns the
debounce timer and decides when to trigger saves.
"""

import os
import json
import logging

import sftp_hostdataeditor
from sftp_platform import get_transfer_queue_path, create_secure_directory, secure_file_permissions, is_windows

logger = logging.getLogger('sftp.transfer_persistence')

QUEUE_FILE_PATH = get_transfer_queue_path()


class TransferPersistence:
    """
    Read/write transfer queue data to disk with encrypted passwords.

    Pure I/O — no Qt dependencies, no widget references.
    """

    @staticmethod
    def encrypt_password(password):
        """Encrypt a password for storage, or return as-is if encryption unavailable."""
        if not password:
            return ''
        if sftp_hostdataeditor.cipher_suite:
            try:
                return sftp_hostdataeditor.cipher_suite.encrypt(password.encode()).decode()
            except Exception:
                pass
        return password

    @staticmethod
    def decrypt_password(encrypted_password):
        """Decrypt a stored password, or return as-is if decryption unavailable."""
        if not encrypted_password:
            return ''
        if sftp_hostdataeditor.cipher_suite:
            try:
                return sftp_hostdataeditor.cipher_suite.decrypt(encrypted_password.encode()).decode()
            except Exception:
                pass
        return encrypted_password

    @classmethod
    def save_pending_queue(cls, pending_transfers):
        """
        Save pending transfers to disk.

        Args:
            pending_transfers: List of transfer_info dicts to persist.
                Only entries with status 'queued' or 'waiting_session' are saved.

        Returns:
            int: Number of transfers saved, or 0 if none.
        """
        data = []
        for t in pending_transfers:
            if t['status'] in ('queued', 'waiting_session'):
                data.append({
                    'transfer_id': t['transfer_id'],
                    'hostname': t['hostname'],
                    'port': t['port'],
                    'username': t['username'],
                    'password': cls.encrypt_password(t.get('password', '')),
                    'key': cls.encrypt_password(t.get('key', '')),
                    'source_path': t['source_path'],
                    'dest_path': t['dest_path'],
                    'is_source_remote': t['is_source_remote'],
                    'is_destination_remote': t['is_destination_remote'],
                    'command': t['command'],
                    'group_id': t.get('group_id'),
                    'priority': t['priority'],
                    'status': t['status'],
                    'added_time': t['added_time'],
                })

        if not data:
            cls._remove_queue_file()
            return 0

        try:
            json_str = json.dumps(data)
            with open(QUEUE_FILE_PATH, 'w') as f:
                f.write(json_str)
            secure_file_permissions(QUEUE_FILE_PATH)
            return len(data)
        except Exception as e:
            logger.error(f"Error saving queue: {e}")
            return 0

    @classmethod
    def load_pending_queue(cls):
        """
        Load pending transfers from disk.

        Returns:
            list: List of transfer_info dicts with decrypted passwords,
                  status set to 'waiting_session', and session_id set to None.
                  Empty list if no saved data or on error.
        """
        if not os.path.exists(QUEUE_FILE_PATH):
            return []

        try:
            with open(QUEUE_FILE_PATH, 'r') as f:
                data = json.loads(f.read())

            restored = []
            for item in data:
                item['password'] = cls.decrypt_password(item.get('password', ''))
                item['key'] = cls.decrypt_password(item.get('key', ''))
                item['status'] = 'waiting_session'
                item['added_time'] = item.get('added_time', 0)
                item['session_id'] = None
                restored.append(item)

            return restored
        except Exception as e:
            logger.error(f"Error loading queue: {e}")
            return []

    @classmethod
    def _remove_queue_file(cls):
        """Remove the queue file if it exists."""
        if os.path.exists(QUEUE_FILE_PATH):
            try:
                os.remove(QUEUE_FILE_PATH)
            except Exception:
                pass
