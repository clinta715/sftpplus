import os
import threading
from icecream import ic

sftp_current_creds = {}
_creds_lock = threading.Lock()

def get_home_directory():
    """Get the user's home directory reliably"""
    home = os.path.expanduser("~")
    if home and os.path.exists(home):
        return home
    return os.path.abspath(".")

def get_credentials(session_id):
    with _creds_lock:
        creds = sftp_current_creds.get(session_id, {})
    
    home_dir = get_home_directory()
    
    defaults = {
        'hostname': '',
        'username': '',
        'password': '',
        'port': 22,
        'key': '',
        'current_local_directory': home_dir,
        'current_remote_directory': '.'
    }
    
    if not creds or not isinstance(creds, dict):
        return defaults.copy()
    
    result = defaults.copy()
    result.update(creds)
    return result

# Function to set credentials based on session_id
def set_credentials(session_id, credential, value):
    with _creds_lock:
        if session_id not in sftp_current_creds:
            sftp_current_creds[session_id] = {}  # Initialize dictionary for new session_id
        sftp_current_creds[session_id][credential] = value

# Assertion helpers for directory consistency
def verify_credential_update(session_id, credential, expected_value, context=""):
    """
    Verify that a credential was actually updated to the expected value.
    
    Args:
        session_id: The session to check
        credential: The credential name (e.g., 'current_remote_directory')
        expected_value: The value that should be set
        context: Optional context string for error messages
        
    Returns:
        True if verification passes, raises AssertionError if fails (when DEBUG=True)
    """
    actual_value = get_credentials(session_id).get(credential)
    if actual_value != expected_value:
        error_msg = f"CREDENTIAL MISMATCH: Session {session_id}, {credential} expected '{expected_value}' but got '{actual_value}'"
        if context:
            error_msg += f" (Context: {context})"
        ic(error_msg)
        # In production, log but don't crash
        # In development, could raise AssertionError
        return False
    return True

def verify_directory_consistency(session_id, operation=""):
    """
    Verify that current_remote_directory is a valid absolute path.
    
    Args:
        session_id: The session to check
        operation: Description of the operation being performed
        
    Returns:
        (is_valid, directory) tuple
    """
    creds = get_credentials(session_id)
    directory = creds.get('current_remote_directory', '.')
    
    # Check if it's an absolute path (should start with /)
    is_valid = directory.startswith('/') if directory else False
    
    if not is_valid and directory != '.':
        ic(f"DIRECTORY VALIDATION: Session {session_id} has invalid directory '{directory}' during {operation}")
    
    return is_valid, directory

# Function to delete credentials based on session_id
def del_credentials(session_id):
    with _creds_lock:
        try:
            del sftp_current_creds[session_id]
        except KeyError:
            pass

def clear_all_credentials():
    """Clear all stored credentials - call at application startup"""
    global sftp_current_creds
    with _creds_lock:
        sftp_current_creds = {}

def create_random_integer():
    """
    Generates a really random positive integer using os.urandom.
    Ensures that the number is not interpreted as negative. Keeps track of generated numbers to ensure uniqueness.
    Limits the set size to prevent memory leaks.
    """
    # Initialize the set of generated numbers as a function attribute if it doesn't exist
    if not hasattr(create_random_integer, 'generated_numbers'):
        create_random_integer.generated_numbers = set()
        create_random_integer.max_tracked_numbers = 10000  # Limit memory usage

    # Clean up old numbers if set gets too large
    if len(create_random_integer.generated_numbers) >= create_random_integer.max_tracked_numbers:
        # Clear half the set to prevent memory growth
        # This slightly increases collision chance but prevents memory exhaustion
        numbers_list = list(create_random_integer.generated_numbers)
        create_random_integer.generated_numbers = set(numbers_list[len(numbers_list)//2:])

    while True:
        # Generating a random byte string of length 4
        random_bytes = os.urandom(4)

        # Converting to a positive integer and masking the most significant bit
        random_integer = int.from_bytes(random_bytes, 'big') & 0x7FFFFFFF

        # Check if the number is unique
        if random_integer not in create_random_integer.generated_numbers:
            create_random_integer.generated_numbers.add(random_integer)
            return random_integer
