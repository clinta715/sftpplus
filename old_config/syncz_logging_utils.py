import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime

def setup_logging(log_directory='/var/log/syncz', max_log_size=10*1024*1024, backup_count=5):
    # Ensure the log directory exists
    os.makedirs(log_directory, exist_ok=True)

    # Create a timestamp for the log file name
    timestamp = datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(log_directory, f'syncz_{timestamp}.log')

    # Create a logger
    logger = logging.getLogger('syncz')
    logger.setLevel(logging.DEBUG)

    # Create rotating file handler which logs even debug messages
    fh = RotatingFileHandler(log_file, maxBytes=max_log_size, backupCount=backup_count)
    fh.setLevel(logging.DEBUG)

    # Create console handler with a higher log level
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    # Create formatter and add it to the handlers
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    # Add the handlers to the logger
    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger

# Create and configure the logger
logger = setup_logging()

def get_current_log_file():
    # Assuming the file handler is the first handler
    return logger.handlers[0].baseFilename

def clean_old_logs(log_directory='/var/log/syncz', days_to_keep=30):
    """Remove log files older than the specified number of days"""
    import time
    current_time = time.time()
    for filename in os.listdir(log_directory):
        file_path = os.path.join(log_directory, filename)
        if os.path.isfile(file_path):
            if os.stat(file_path).st_mtime < current_time - days_to_keep * 86400:
                os.remove(file_path)
                logger.info(f"Removed old log file: {file_path}")
