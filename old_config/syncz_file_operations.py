import os
import subprocess
import random
import string
from contextlib import contextmanager
from syncz_logging_utils import logger

@contextmanager
def create_temp_folder(temp_folder_name):
    try:
        logger.info(f"Attempting to create directory: {temp_folder_name}")
        result = subprocess.run(['mkdir', '-p', temp_folder_name], capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(f"mkdir returned non-zero exit status: {result.returncode}")
            logger.warning(f"stdout: {result.stdout}")
            logger.warning(f"stderr: {result.stderr}")
        
        if os.path.isdir(temp_folder_name):
            logger.info(f"Directory exists: {temp_folder_name}")
            yield temp_folder_name
        else:
            raise OSError(f"Failed to create or access directory: {temp_folder_name}")
    except Exception as e:
        logger.error(f"Error in create_temp_folder: {e}")
        raise
    finally:
        cleanup_temp_folder(temp_folder_name)

def cleanup_temp_folder(temp_folder_name):
    try:
        subprocess.run(f"fusermount -u {temp_folder_name}", shell=True, check=False)
        if os.path.exists(temp_folder_name):
            os.rmdir(temp_folder_name)
        logger.info(f"Attempted cleanup of temporary folder: {temp_folder_name}")
    except Exception as e:
        logger.warning(f"Error during cleanup of {temp_folder_name}: {e}")

def generate_random_string(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def process_tarzst_with_filenames(file_path):
    additional_file_path = f"{file_path}.txt"
    
    if not os.path.exists(additional_file_path):
        return None

    with open(additional_file_path, 'r') as txt_file:
        filenames = [re.sub(r'[^a-zA-Z0-9]', '_', os.path.basename(line.strip())) for line in txt_file.readlines()][:8]

    concatenated_filenames = '_'.join(filenames)
    new_file_path = f"{os.path.splitext(file_path)[0]}_{concatenated_filenames}.txt"
    logger.info(f"New file path: {new_file_path}")

    return new_file_path
