"""
Platform Compatibility Utilities

Provides cross-platform utilities for Windows/macOS/Linux compatibility.
"""

import os
import sys
import platform


def is_windows():
    """Check if running on Windows."""
    return sys.platform == 'win32' or platform.system() == 'Windows'


def is_macos():
    """Check if running on macOS."""
    return sys.platform == 'darwin' or platform.system() == 'Darwin'


def is_linux():
    """Check if running on Linux."""
    return sys.platform.startswith('linux') or platform.system() == 'Linux'


def secure_file_permissions(path):
    """
    Set secure file permissions (owner read/write only).On Unix systems, this sets mode 0o600.
    On Windows, this relies on NTFS ACLs (handled by the OS for user directories).
    
    Args:
        path: Path to the file
    """
    if is_windows():
        return
    if not os.path.exists(path):
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def secure_dir_permissions(path):
    """
    Set secure directory permissions (owner access only).
    On Unix systems, this sets mode 0o700.
    On Windows, this relies on NTFS ACLs.
    
    Args:
        path: Path to the directory
    """
    if is_windows():
        return
    if not os.path.exists(path):
        return
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def create_secure_directory(path):
    """
    Create a directory with secure permissions.
    On Unix, uses restrictive umask during creation.
    On Windows, relies on inherited ACLs from parent.
    
    Args:
        path: Path to create
    """
    if is_windows():
        os.makedirs(path, exist_ok=True)
        return
    
    old_umask = os.umask(0o077)
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
    finally:
        os.umask(old_umask)


def get_config_directory():
    """
    Get the platform-appropriate configuration directory.
    
    Returns:
        str: Path to the configuration directory
    """
    if is_windows():
        appdata = os.environ.get('APPDATA', os.environ.get('LOCALAPPDATA', os.path.expanduser('~')))
        return os.path.join(appdata, 'sftp_client')
    return os.path.join(os.path.expanduser('~'), '.sftp_client')


def get_key_file_path():
    """Get the path to the encryption key file."""
    if is_windows():
        config_dir = get_config_directory()
        return os.path.join(config_dir, 'key.bin')
    return os.path.join(os.path.expanduser('~'), '.sftp_client_key')


def get_connection_data_path():
    """Get the path to the connection data file."""
    if is_windows():
        config_dir = get_config_directory()
        return os.path.join(config_dir, 'connections.json')
    return os.path.join(os.path.expanduser('~'), '.sftp_client_connection_data.json')


def get_preferences_path():
    """Get the path to the preferences file."""
    if is_windows():
        config_dir = get_config_directory()
        return os.path.join(config_dir, 'preferences.json')
    return os.path.join(os.path.expanduser('~'), '.sftp_client_preferences.json')


def get_transfer_queue_path():
    """Get the path to the transfer queue file."""
    if is_windows():
        config_dir = get_config_directory()
        return os.path.join(config_dir, 'transfer_queue.json')
    return os.path.join(os.path.expanduser('~'), '.sftp_client_transfer_queue.json')


def get_history_path():
    """Get the path to the transfer history file."""
    config_dir = get_config_directory()
    return os.path.join(config_dir, 'history.json')


def get_log_directory():
    """Get the path to the log directory."""
    config_dir = get_config_directory()
    return os.path.join(config_dir, 'logs')


def get_known_hosts_path():
    """
    Get the path to the SSH known_hosts file.
    
    Returns:
        str: Path to known_hosts file
    """
    if is_windows():
        user_profile = os.environ.get('USERPROFILE', os.path.expanduser('~'))
        return os.path.join(user_profile, '.ssh', 'known_hosts')
    return os.path.join(os.path.expanduser('~'), '.ssh', 'known_hosts')


def get_default_shell():
    """
    Get the default shell for the local terminal.
    
    Returns:
        str: Path to the shell executable
    """
    if is_windows():
        return os.environ.get('COMSPEC', 'cmd.exe')
    return os.environ.get('SHELL', '/bin/bash')


def supports_local_terminal():
    """
    Check if the local terminal feature is supported on this platform.

    With QProcess-based terminal (no PTY dependency), local terminal
    is supported on all platforms including Windows.

    Returns:
        bool: True if local terminal is supported
    """
    return True


def ensure_config_directory():
    """
    Ensure the configuration directory exists with proper permissions.
    
    Returns:
        str: Path to the configuration directory
    """
    config_dir = get_config_directory()
    create_secure_directory(config_dir)
    return config_dir


def remote_join(base, name):
    """Join remote SFTP path components using forward slashes (safe on all platforms)."""
    base = base.rstrip('/')
    if not base:
        return '/' + name
    return base + '/' + name