"""
SFTP Client Logging Module

Provides configured logging for the SFTP client application.
"""
import logging
import os
from pathlib import Path

from sftp_platform import get_log_directory, create_secure_directory


_log_file_path = None


def setup_logging(log_level=None, log_file=None):
    """
    Set up logging for the SFTP client.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
                   If None, defaults to INFO
        log_file: Optional path to log file. If None, logs to:
                  platform-specific log directory
    """
    global _log_file_path
    
    if log_level is None:
        log_level = logging.INFO
    
    # Create logger
    logger = logging.getLogger('sftp')
    logger.setLevel(log_level)
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler
    if log_file is None:
        log_dir = get_log_directory()
        create_secure_directory(log_dir)
        log_file = os.path.join(log_dir, 'sftp.log')
    
    _log_file_path = log_file
    
    try:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except (OSError, IOError) as e:
        logger.warning(f"Could not create log file: {e}")
    
    return logger


def get_logger(name=None):
    """
    Get a logger instance.
    
    Args:
        name: Optional sub-logger name. If None, returns root sftp logger.
    
    Returns:
        Logger instance
    """
    if name:
        return logging.getLogger(f'sftp.{name}')
    return logging.getLogger('sftp')


def get_log_file_path():
    """Return the current log file path, or None if not set."""
    return _log_file_path


# Default logger for convenience
logger = get_logger()