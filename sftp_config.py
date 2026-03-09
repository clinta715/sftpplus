"""SFTP Client Configuration Constants

Central location for configuration values that need to be shared across modules.
"""

# Maximum number of concurrent file transfers
MAX_TRANSFERS = 8

# Connection pool settings
CONNECTION_POOL_MAX_AGE = 300  # Keep connections for 5 minutes
CONNECTION_POOL_MAX_SIZE = 20  # Maximum number of connections in pool

# File transfer settings
TRANSFER_TIMEOUT = 300  # 5 minutes timeout for transfers
CHUNK_SIZE = 8192  # 8KB chunks for file operations

# UI Settings
DEFAULT_LOCAL_DIRECTORY = "/"
DEFAULT_REMOTE_DIRECTORY = "."
