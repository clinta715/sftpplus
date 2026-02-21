"""
SFTP Client Preferences

Persistent user preferences stored in JSON file.
"""
import os
import json
from typing import Any, Optional
from threading import Lock
from icecream import ic


DEFAULT_PREFERENCES = {
    "clear_completed_on_complete": False,
    "overwrite_on_transfer": False,
    "confirm_exit": True,
    "focus_transfers_on_start": True,
    "max_transfer_speed": 0,
    "show_hidden_files": False,
    "default_local_directory": "",
    "default_remote_directory": "",
}


class Preferences:
    """Thread-safe preferences manager with persistence"""
    
    _instance: Optional['Preferences'] = None
    _lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._preferences = DEFAULT_PREFERENCES.copy()
                    cls._instance._preferences_lock = Lock()
                    cls._instance._load()
        return cls._instance
    
    def _get_filepath(self) -> str:
        """Get the preferences file path"""
        return os.path.join(os.path.expanduser('~'), '.sftp_client_preferences.json')
    
    def _load(self):
        """Load preferences from disk"""
        filepath = self._get_filepath()
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    data = json.load(f)
                with self._preferences_lock:
                    self._preferences.update(data)
                ic(f"Loaded preferences from {filepath}")
        except (json.JSONDecodeError, OSError, IOError) as e:
            ic(f"Error loading preferences: {e}")
    
    def _save(self):
        """Save preferences to disk"""
        filepath = self._get_filepath()
        try:
            with self._preferences_lock:
                data = self._preferences.copy()
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=4)
            ic(f"Saved preferences to {filepath}")
        except (OSError, IOError) as e:
            ic(f"Error saving preferences: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a preference value"""
        with self._preferences_lock:
            return self._preferences.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set a preference value and persist"""
        with self._preferences_lock:
            self._preferences[key] = value
        self._save()
    
    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get a boolean preference"""
        return bool(self.get(key, default))
    
    def set_bool(self, key: str, value: bool):
        """Set a boolean preference"""
        self.set(key, bool(value))
    
    def reset(self):
        """Reset all preferences to defaults"""
        with self._preferences_lock:
            self._preferences = DEFAULT_PREFERENCES.copy()
        self._save()


def get_preferences() -> Preferences:
    """Get the global preferences instance"""
    return Preferences()
