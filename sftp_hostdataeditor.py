"""
Connection Data Storage Module

Handles secure storage and retrieval of SFTP connection data.
Encryption key is stored separately from encrypted data for enhanced security.
"""
import logging
import os
import stat
import json
import threading
from cryptography.fernet import Fernet, InvalidToken

from sftp_platform import (
    get_key_file_path, get_connection_data_path,
    secure_file_permissions, create_secure_directory, is_windows
)

logger = logging.getLogger('sftp')

KEY_FILE_PATH = get_key_file_path()
DATA_FILE_PATH = get_connection_data_path()

encryption_key = None
cipher_suite = None
_data_lock = threading.Lock()


def _ensure_keys(host_data):
    """Ensure all expected keys exist in host_data dict."""
    for key in ("hostnames", "usernames", "passwords", "ports", "key",
                "connection_type", "initial_remote_dir", "initial_local_dir",
                "bookmarks", "ssh_commands", "follow_symlinks"):
        if key not in host_data:
            host_data[key] = {}
    if "show_manager_on_startup" not in host_data:
        host_data["show_manager_on_startup"] = True


def _load_encryption_key():
    """Load encryption key from separate file, or generate new one."""
    global encryption_key, cipher_suite

    create_secure_directory(os.path.dirname(KEY_FILE_PATH))

    key_loaded = False
    try:
        if os.path.exists(KEY_FILE_PATH):
            with open(KEY_FILE_PATH, 'rb') as f:
                key_data = f.read()
            if len(key_data) == 44:
                encryption_key = key_data
                key_loaded = True
    except (OSError, ValueError) as e:
        logger.warning(f"Error reading encryption key: {e}")

    if not key_loaded:
        encryption_key = Fernet.generate_key()
        _save_encryption_key(encryption_key)

    cipher_suite = Fernet(encryption_key)
    return encryption_key


def _save_encryption_key(key):
    """Save encryption key to separate file with restricted permissions."""
    global encryption_key
    create_secure_directory(os.path.dirname(KEY_FILE_PATH))
    with open(KEY_FILE_PATH, 'wb') as f:
        f.write(key)
    secure_file_permissions(KEY_FILE_PATH)
    encryption_key = key


def _migrate_old_key_format(data):
    """Migrate from old format where key was stored with data."""
    global encryption_key, cipher_suite
    if "encryption_key" in data:
        old_key = data["encryption_key"]
        if isinstance(old_key, str):
            old_key = old_key.encode()
        _save_encryption_key(old_key)
        cipher_suite = Fernet(old_key)
        logger.info("Migrated encryption key from old format to separate key file")
        return True
    return False


_load_encryption_key()


def save_connection_data(host_data):
    """
    Save connection data to encrypted JSON file.

    Args:
        host_data: Dictionary containing connection information

    Returns:
        bool: True if successful, False otherwise
    """
    global encryption_key, cipher_suite
    try:
        if not all(key in host_data for key in ["hostnames", "usernames", "passwords", "ports", "key"]):
            raise ValueError("Incomplete host data structure")

        encrypted_passwords = {k: cipher_suite.encrypt(v.encode()).decode()
                             for k, v in host_data["passwords"].items()}

        data = {
            "hostnames": host_data["hostnames"],
            "usernames": host_data["usernames"],
            "passwords": encrypted_passwords,
            "ports": host_data["ports"],
            "key": host_data["key"],
            "connection_type": host_data.get("connection_type", {}),
            "initial_remote_dir": host_data.get("initial_remote_dir", {}),
            "initial_local_dir": host_data.get("initial_local_dir", {}),
            "show_manager_on_startup": host_data.get("show_manager_on_startup", True),
            "bookmarks": host_data.get("bookmarks", {}),
            "ssh_commands": host_data.get("ssh_commands", {}),
            "follow_symlinks": host_data.get("follow_symlinks", {}),
            "nicknames": host_data.get("nicknames", {})
        }

        create_secure_directory(os.path.dirname(DATA_FILE_PATH))

        if is_windows():
            with open(DATA_FILE_PATH, 'w') as f:
                json.dump(data, f, indent=4)
        else:
            old_umask = os.umask(0o077)
            try:
                with open(DATA_FILE_PATH, 'w') as f:
                    json.dump(data, f, indent=4)
                secure_file_permissions(DATA_FILE_PATH)
            finally:
                os.umask(old_umask)
        return True
    except (OSError, RuntimeError) as e:
        logger.error(f"Failed to save connection data: {e}")
        return False


def load_connection_data():
    """
    Load connection data from encrypted JSON file.

    Returns:
        dict: Connection data dictionary with decrypted passwords
    """
    global encryption_key, cipher_suite
    host_data = {
        "hostnames": {}, "usernames": {}, "passwords": {}, "ports": {}, "key": {},
        "connection_type": {}, "initial_remote_dir": {}, "initial_local_dir": {},
        "show_manager_on_startup": True, "bookmarks": {},
        "ssh_commands": {}, "follow_symlinks": {}, "nicknames": {}
    }

    try:
        filepath = DATA_FILE_PATH

        if not os.path.exists(filepath):
            old_filepath = 'connection_data.json'
            if os.path.exists(old_filepath):
                filepath = old_filepath
            else:
                raise FileNotFoundError("Connection data file not found")

        with open(filepath, 'r') as f:
            data = json.load(f)

        if _migrate_old_key_format(data):
            pass
        elif encryption_key is None or cipher_suite is None:
            _load_encryption_key()

        host_data["hostnames"] = data.get("hostnames", {})
        host_data["usernames"] = data.get("usernames", {})

        encrypted_passwords = data.get("passwords", {})
        host_data["passwords"] = {}
        for k, v in encrypted_passwords.items():
            try:
                host_data["passwords"][k] = cipher_suite.decrypt(v.encode()).decode()
            except (InvalidToken, Exception) as e:
                logger.warning(f"Failed to decrypt password for '{k}': {e}")
                host_data["passwords"][k] = ""

        host_data["ports"] = {k: int(v) if v else 22 for k, v in data.get("ports", {}).items()}
        host_data["key"] = data.get("key", {})
        host_data["connection_type"] = data.get("connection_type", {})
        host_data["initial_remote_dir"] = data.get("initial_remote_dir", {})
        host_data["initial_local_dir"] = data.get("initial_local_dir", {})
        host_data["show_manager_on_startup"] = data.get("show_manager_on_startup", True)
        host_data["bookmarks"] = data.get("bookmarks", {})
        host_data["ssh_commands"] = data.get("ssh_commands", {})
        host_data["follow_symlinks"] = data.get("follow_symlinks", {})
        host_data["nicknames"] = data.get("nicknames", {})

        return host_data

    except FileNotFoundError:
        logger.info("No connection data file found, starting fresh")
        encryption_key = Fernet.generate_key()
        _save_encryption_key(encryption_key)
        cipher_suite = Fernet(encryption_key)
        return host_data

    except json.JSONDecodeError as e:
        logger.error(f"Corrupted connection data file: {e}")
        encryption_key = Fernet.generate_key()
        _save_encryption_key(encryption_key)
        cipher_suite = Fernet(encryption_key)
        return host_data

    except (OSError, RuntimeError) as e:
        logger.error(f"Error loading connection data: {e}")
        encryption_key = Fernet.generate_key()
        _save_encryption_key(encryption_key)
        cipher_suite = Fernet(encryption_key)
        return host_data


def update_connection_data(callback):
    """Atomically load, modify via callback, and save connection data.

    The callback receives the host_data dict and should modify it in-place.
    Thread-safe: acquires a lock for the entire load-modify-save cycle.

    Args:
        callback: Callable that takes host_data dict and modifies it in-place.

    Returns:
        bool: True if saved successfully, False otherwise.
    """
    with _data_lock:
        host_data = load_connection_data()
        callback(host_data)
        return save_connection_data(host_data)


def get_site_names():
    """Return list of configured site hostnames.

    Returns:
        list[str]: Hostname strings.
    """
    host_data = load_connection_data()
    return list(host_data.get("hostnames", {}).keys())


def get_site_data(hostname):
    """Return all configured data for a specific site.

    Args:
        hostname: The site hostname to look up.

    Returns:
        dict: Site data with keys: hostname, username, password, port, key,
              connection_type, initial_remote_dir, initial_local_dir,
              ssh_commands, follow_symlinks.
              Returns None if hostname not found.
    """
    host_data = load_connection_data()
    if hostname not in host_data.get("hostnames", {}):
        return None
    return {
        "hostname": host_data["hostnames"].get(hostname, hostname),
        "username": host_data["usernames"].get(hostname, ""),
        "password": host_data["passwords"].get(hostname, ""),
        "port": host_data["ports"].get(hostname, 22),
        "key": host_data["key"].get(hostname, ""),
        "connection_type": host_data.get("connection_type", {}).get(hostname, "SFTP Browser"),
        "initial_remote_dir": host_data.get("initial_remote_dir", {}).get(hostname, ""),
        "initial_local_dir": host_data.get("initial_local_dir", {}).get(hostname, ""),
        "ssh_commands": host_data.get("ssh_commands", {}).get(hostname, ""),
        "follow_symlinks": host_data.get("follow_symlinks", {}).get(hostname, False),
        "nickname": host_data.get("nicknames", {}).get(hostname, ""),
    }


def get_setting(key, default=None):
    """Return a global setting value from connection data.

    Args:
        key: Setting key (e.g. 'show_manager_on_startup').
        default: Default value if key not found.

    Returns:
        The setting value, or default.
    """
    host_data = load_connection_data()
    return host_data.get(key, default)


def delete_site(hostname):
    """Atomically delete a site by hostname.

    Removes the hostname from all connection data dictionaries.

    Args:
        hostname: The site hostname to delete.

    Returns:
        bool: True if successful, False otherwise.
    """
    def remover(host_data):
        for key in host_data:
            if isinstance(host_data[key], dict):
                host_data[key].pop(hostname, None)
    return update_connection_data(remover)


def copy_site(original_hostname, new_hostname):
    """Atomically copy a site to a new hostname.

    Args:
        original_hostname: The source hostname to copy from.
        new_hostname: The destination hostname for the copy.

    Returns:
        bool: True if successful, False otherwise.
    """
    def copier(host_data):
        for key in host_data:
            if isinstance(host_data[key], dict):
                if original_hostname in host_data[key]:
                    host_data[key][new_hostname] = host_data[key][original_hostname]
        host_data["hostnames"][new_hostname] = new_hostname
    return update_connection_data(copier)


def rename_site(old_hostname, new_hostname):
    """Atomically rename a site (change its hostname).

    Args:
        old_hostname: The current hostname to rename.
        new_hostname: The new hostname.

    Returns:
        bool: True if successful, False otherwise.
    """
    def migrator(host_data):
        for key in host_data:
            if isinstance(host_data[key], dict):
                if old_hostname in host_data[key]:
                    host_data[key][new_hostname] = host_data[key].pop(old_hostname)
    return update_connection_data(migrator)
