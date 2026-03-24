"""
Connection Data Storage Module

Handles secure storage and retrieval of SFTP connection data.
Encryption key is stored separately from encrypted data for enhanced security.
"""
import os
import stat
import json
from cryptography.fernet import Fernet, InvalidToken

from sftp_platform import (
    get_key_file_path, get_connection_data_path,
    secure_file_permissions, create_secure_directory, is_windows
)

KEY_FILE_PATH = get_key_file_path()
DATA_FILE_PATH = get_connection_data_path()

encryption_key = None
cipher_suite = None


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
    except (OSError, IOError, ValueError):
        pass
    
    if not key_loaded:
        encryption_key = Fernet.generate_key()
        _save_encryption_key(encryption_key)
    
    cipher_suite = Fernet(encryption_key)
    return encryption_key


def _save_encryption_key(key):
    """Save encryption key to separate file with restricted permissions."""
    global encryption_key
    try:
        create_secure_directory(os.path.dirname(KEY_FILE_PATH))
        with open(KEY_FILE_PATH, 'wb') as f:
            f.write(key)
        secure_file_permissions(KEY_FILE_PATH)
    except (OSError, IOError):
        pass
        raise
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
            "bookmarks": host_data.get("bookmarks", {})
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
    except PermissionError:
        return False
    except OSError:
        return False
    except (OSError, IOError, RuntimeError):
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
        "show_manager_on_startup": True, "bookmarks": {}
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
            except (OSError, IOError, RuntimeError, InvalidToken):
                host_data["passwords"][k] = ""
                
        host_data["ports"] = data.get("ports", {})
        host_data["key"] = data.get("key", {})
        host_data["connection_type"] = data.get("connection_type", {})
        host_data["initial_remote_dir"] = data.get("initial_remote_dir", {})
        host_data["initial_local_dir"] = data.get("initial_local_dir", {})
        host_data["show_manager_on_startup"] = data.get("show_manager_on_startup", True)
        host_data["bookmarks"] = data.get("bookmarks", {})

        return host_data

    except FileNotFoundError:
        encryption_key = Fernet.generate_key()
        cipher_suite = Fernet(encryption_key)
        return host_data
        
    except json.JSONDecodeError:
        encryption_key = Fernet.generate_key()
        cipher_suite = Fernet(encryption_key)
        return host_data
        
    except (OSError, IOError, RuntimeError):
        encryption_key = Fernet.generate_key()
        cipher_suite = Fernet(encryption_key)
        return host_data