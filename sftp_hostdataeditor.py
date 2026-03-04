"""
Connection Data Storage Module

Handles secure storage and retrieval of SFTP connection data.
Encryption key is stored separately from encrypted data for enhanced security.
"""
import os
import stat
import json
from cryptography.fernet import Fernet
from icecream import ic

KEY_FILE_PATH = os.path.join(os.path.expanduser('~'), '.sftp_client_key')
DATA_FILE_PATH = os.path.join(os.path.expanduser('~'), '.sftp_client_connection_data.json')

encryption_key = None
cipher_suite = None


def _load_encryption_key():
    """Load encryption key from separate file, or generate new one."""
    global encryption_key, cipher_suite
    
    key_loaded = False
    try:
        if os.path.exists(KEY_FILE_PATH):
            with open(KEY_FILE_PATH, 'rb') as f:
                key_data = f.read()
            if len(key_data) == 44:
                encryption_key = key_data
                key_loaded = True
    except (OSError, IOError, ValueError) as e:
        ic(f"Error loading encryption key: {e}")
    
    if not key_loaded:
        encryption_key = Fernet.generate_key()
        _save_encryption_key(encryption_key)
    
    cipher_suite = Fernet(encryption_key)
    return encryption_key


def _save_encryption_key(key):
    """Save encryption key to separate file with restricted permissions."""
    global encryption_key
    try:
        old_umask = os.umask(0o077)
        with open(KEY_FILE_PATH, 'wb') as f:
            f.write(key)
        os.chmod(KEY_FILE_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except (OSError, IOError) as e:
        ic(f"Error saving encryption key: {e}")
        raise
    finally:
        os.umask(old_umask)
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


# Initialize on module load
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

        old_umask = os.umask(0o077)
        try:
            with open(DATA_FILE_PATH, 'w') as f:
                json.dump(data, f, indent=4)
            os.chmod(DATA_FILE_PATH, stat.S_IRUSR | stat.S_IWUSR)
        finally:
            os.umask(old_umask)
        return True
    except PermissionError as e:
        ic(f"Permission denied saving connection data: {e}")
        return False
    except OSError as e:
        ic(f"OS error saving connection data: {e}")
        return False
    except (OSError, IOError, RuntimeError) as e:
        ic(f"Error saving connection data: {e}")
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
            except (OSError, IOError, RuntimeError) as e:
                ic(f"Error decrypting password for {k}: {e}")
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
        ic("Error: Invalid JSON format in connection data file")
        encryption_key = Fernet.generate_key()
        cipher_suite = Fernet(encryption_key)
        return host_data
        
    except (OSError, IOError, RuntimeError) as e:
        ic(f"Error loading connection data: {e}")
        encryption_key = Fernet.generate_key()
        cipher_suite = Fernet(encryption_key)
        return host_data
