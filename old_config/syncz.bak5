import os
import sys
from typing import Tuple
from syncz_config import parse_arguments, read_smtp_config, load_commands
from syncz_file_operations import create_temp_folder, generate_random_string
from syncz_command_processor import process_commands
from syncz_email_utils import send_email
from syncz_logging_utils import logger, get_current_log_file, clean_old_logs

def read_source_info(file_path: str) -> Tuple[str, str, str, str]:
    with open(file_path, 'r') as f:
        source_host = f.readline().strip()
        source_path = f.readline().strip()
        dest_archive = f.readline().strip()
        vm_number = f.readline().strip()
    return source_host, source_path, dest_archive, vm_number

def process_sync_file(sync_file: str, base_command: str, base_source_path: str, base_dest_path: str, base_dest_host: str) -> Tuple[str, str, str, str]:
    source_host, source_path, dest_archive, vm_number = "127.0.0.1", "/tmp", "/tmp/archive.tar.zst", "0"
    
    if sync_file.endswith(".syncz") and (base_command == "syncz" or base_command.startswith("incz") or base_command.startswith("cleanz")):
        with open(os.path.join(base_source_path, sync_file), "r") as f:
            source_path_with_host = f.readline().strip()
            dest_archive = f.readline().strip()
        source_parts = source_path_with_host.split(":")
        source_host, source_path = source_parts[0], source_parts[1]

    elif sync_file.endswith(".backup") and base_command == "iterate":
        source_host, source_path, dest_archive, vm_number = read_source_info(os.path.join(base_source_path, sync_file))
        dest_archive = os.path.join(base_dest_path, dest_archive)

    elif sync_file.endswith(".tape") and base_command == "tapez":
        source_archive = os.path.join(base_source_path, os.path.splitext(sync_file)[0])
        dest_archive = os.path.join(base_dest_path, os.path.splitext(sync_file)[0])
        source_path = source_archive

    elif sync_file.endswith(".tar.zst") and base_command == "testz":
        source_archive = os.path.join(base_source_path, sync_file)
        source_path = source_archive

    elif sync_file.endswith(".remote") and (base_command == "remotez" or base_command == "b2z"):
        source_archive = os.path.join(base_source_path, os.path.dirname(sync_file), os.path.splitext(os.path.basename(sync_file))[0])
        dest_archive = os.path.join(base_dest_path, os.path.splitext(sync_file)[0])
        source_path = source_archive
        source_host = base_dest_host

    return source_host, source_path, dest_archive, vm_number

def main():
    args = parse_arguments()
    base_command = args.base_command
    base_dest_path = args.base_dest_path
    base_dest_host = args.base_dest_host
    base_source_path = args.base_source_path

    logger.info(f"Starting syncz script with base command: {base_command}")

    clean_old_logs()

    commands = load_commands()

    if base_command not in commands:
        logger.error(f"Error: Unknown base command - {base_command}")
        sys.exit(1)

    base_dest_options = commands[base_command]

    if "base_dest_path" in base_dest_options and not base_dest_path:
        logger.error("Error: base_dest_path is required for the selected command.")
        sys.exit(1)
    elif "base_dest_host" in base_dest_options and not base_dest_host:
        logger.error("Error: base_dest_host is required for the selected command.")
        sys.exit(1)

    smtp_server, dest_email, source_email, base_work_path = read_smtp_config()
    temp_folder_name = f"{base_work_path}/{os.path.basename(__file__)[:-3]}_{generate_random_string()}"

    try:
        with create_temp_folder(temp_folder_name):
            process_commands(base_command="startup", source_host="127.0.0.1", source_path="/tmp", destination_archive="/tmp/archive.tar.zst", vm_number="0", temp_folder_name=temp_folder_name)

            for sync_file in os.listdir(base_source_path):
                if sync_file.endswith((".syncz", ".backup", ".tape", ".tar.zst", ".remote")):
                    source_host, source_path, dest_archive, vm_number = process_sync_file(sync_file, base_command, base_source_path, base_dest_path, base_dest_host)

                    logger.info(f"Processing file: {sync_file}")
                    logger.info(f"Source host: {source_host}")
                    logger.info(f"Source path: {source_path}")
                    logger.info(f"Destination archive: {dest_archive}")
                    logger.info(f"VM number: {vm_number}")

                    process_commands(base_command=base_command, source_host=source_host, source_path=source_path, destination_archive=dest_archive, vm_number=vm_number, temp_folder_name=temp_folder_name)

    except Exception as e:
        error_msg = f"An error occurred: {e}"
        logger.error(error_msg, exc_info=True)
        send_email(smtp_server, source_email, dest_email, get_current_log_file(), "Script Error", error_msg)
        sys.exit(1)
    else:
        success_msg = "The script completed successfully."
        logger.info(success_msg)
        send_email(smtp_server, source_email, dest_email, get_current_log_file(), "Script Completed Successfully", success_msg)

if __name__ == "__main__":
    main()
