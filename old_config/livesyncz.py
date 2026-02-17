import psutil
import json
import sys
import os
import subprocess
import random
import string
import smtplib
import argparse
import re

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime

def process_tarzst_with_filenames(file_path):
    # Construct the file path for the additional file
    additional_file_path = f"{file_path}.txt"

    # Check if the additional file exists
    if not os.path.exists(additional_file_path):
        return None

    # Read up to eight filenames from the additional file
    with open(additional_file_path, 'r') as txt_file:
        filenames = [re.sub(r'[^a-zA-Z0-9]', '_', os.path.basename(line.strip())) for line in txt_file.readlines()][:8]

    # Concatenate the filenames with underscores
    concatenated_filenames = '_'.join(filenames)

    # Construct the new file path
    new_file_path = f"{os.path.splitext(file_path)[0]}_{concatenated_filenames}.txt"
    print(f"{new_file_path}")

    return new_file_path

def generate_random_string(length=8):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def read_smtp_config(log_file_name):
    try:
        with open("smtp.txt", "r") as f:
            smtp_server = f.readline().strip()
            dest_email = f.readline().strip()
            source_email = f.readline().strip()
            base_work_path = f.readline().strip()
    except FileNotFoundError:
        print(f"Error: smtp.txt not found")
        with open(log_file_name, "a") as log:
            log.write(f"Error: smtp.txt not found\n")
        exit(1)

    return smtp_server, dest_email, source_email, base_work_path

def send_email(smtp_server, source_email, dest_email, log_file_name, subject, body):
    msg = MIMEMultipart()
    msg['From'] = source_email
    msg['To'] = dest_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    if log_file_name:
        with open(log_file_name, 'rb') as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload((attachment).read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', "attachment; filename= %s" % os.path.basename(log_file_name))
            msg.attach(part)

    try:
        server = smtplib.SMTP(smtp_server)
        server.sendmail(source_email, dest_email, msg.as_string())
        server.quit()
        print(f"Email sent successfully to {dest_email}")
    except Exception as e:
        print(f"Failed to send email. Error: {e}")
        with open(log_file_name, "a") as log:
            log.write(f"Failed to send email. Error: {e}\n")

def send_success_email(smtp_server, source_email, dest_email):
    subject = "Script Completed Successfully"
    body = "The script completed successfully without any errors."

    send_email(smtp_server, source_email, dest_email, None, subject, body)

def read_process_number_from_lockfile(lockfile_path):
    with open(lockfile_path, 'r') as file:
        process_number_str = file.read().strip()
    return int(process_number_str)

def is_process_running(process_number):
    try:
        # Check if the process with the given PID is running
        process = psutil.Process(process_number)
        return process.is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False

def process_commands( base_command="startup", source_host="127.0.0.1", source_path="/tmp", destination_archive="startup", vm_number="0", temp_folder_name="/tmp", log_file_name="/tmp/process_commands.log"):
    current_datetime = datetime.now()
    syncz = os.path.join(temp_folder_name, ".syncz")
    incz = os.path.join(os.path.dirname(destination_archive), current_datetime.strftime("%Y-%m-%d_%H-%M-%S") + "_" + os.path.basename(destination_archive))

    script_me = os.path.basename(__file__)
    script_dir = os.path.dirname(os.path.realpath(__file__))
    json_path = os.path.join(script_dir, 'syncz_commands.json')

    if os.path.exists(json_path):
        with open(json_path, 'r') as json_file:
            command_sequence = json.load(json_file)['command_sequence']
    else:
        print(f"{json_path} not found.")

    lockfile = f"/tmp/{os.path.basename(destination_archive)}.lock"

    try:
        if os.path.exists(lockfile):
            print(f"Lockfile {lockfile} already exists. Skipping.")
            locking_process = read_process_number_from_lockfile(lockfile)
            if is_process_running(locking_process):
                with open(log_file_name, "a") as log:
                    log.write(f"Lockfile {lockfile} exists and process {locking_process} is running.\n")
                return
            else:
                os.remove(lockfile)

        with open(lockfile, "w") as lock:
            lock.write(str(os.getpid()))

        for command_exec in command_sequence[base_command]:
            print(f"{command_exec}")

            formatted_command = command_exec.format(
                source_host=source_host,
                source_path=source_path,
                temp_folder_name=temp_folder_name,
                syncz=syncz,
                incz=incz,
                destination_archive=destination_archive,
                vm_number=vm_number,
                script_me=script_me,
                destination_path=os.path.dirname(destination_archive),
                destination_file=os.path.basename(destination_archive)
                # Add other variables as needed
            )

            print(formatted_command)
            try:
                result = subprocess.run(formatted_command, shell=True, capture_output=True, text=True)
            except:
                print(f"{result.returncode},{result.stdout},{result.stderr}")
                pass
            # if result.returncode != 0 and result.returncode != 12 and base_command != "iterate":
            #    raise Exception(f"{result.returncode},{result.stdout},{result.stderr}")
            # else:
            if(base_command == "incz"):
                coolname = process_tarzst_with_filenames(incz)
                if coolname != None:
                    print(f"Renaming {incz}.txt to {coolname}")
                    os.rename((incz + ".txt"),coolname)
    except Exception as e:
        # if base_command in ["inczst", "incz", "syncz", "iterate", "b2z", "cleanz"]:
        #    subprocess.run(f"fusermount -u {temp_folder_name}", shell=True)
        print(f"{e}")

        with open(log_file_name, "a") as log:
            log.write(f"{e}\n")

        pass

    finally:
        os.remove(lockfile)
        return -1

def parse_arguments():
    parser = argparse.ArgumentParser(description=__file__)

    # Add named parameters
    parser.add_argument('--base_command', help='Base command', required=True)
    parser.add_argument('--base_dest_path', help='Value for base_dest_path')
    parser.add_argument('--base_dest_host', help='Value for base_dest_host')
    parser.add_argument('--base_source_path', help='Value for base_source_path', required=True)

    return parser.parse_args()

def main():
    script_me = os.path.basename(__file__)
    script_dir = os.path.dirname(os.path.realpath(__file__))
    json_path = os.path.join(script_dir, 'syncz_commands.json')

    # Load the JSON file
    with open(json_path, 'r') as file:
        commands = json.load(file)["commands"]

    # Parse command-line arguments
    args = parse_arguments()

    # Get the values from named parameters
    base_command = args.base_command
    base_dest_path = args.base_dest_path
    base_dest_host = args.base_dest_host
    base_source_path = args.base_source_path

    # Check if base_command is in the commands dictionary
    if base_command in commands:
        # Get the corresponding base_dest options for the given base_command
        base_dest_options = commands[base_command]

        # Check if required arguments are provided based on the commands dictionary
        if "base_dest_path" in base_dest_options and not base_dest_path:
            print("Error: base_dest_path is required for the selected command.")
        elif "base_dest_host" in base_dest_options and not base_dest_host:
            print("Error: base_dest_host is required for the selected command.")
        else:
            # Print the assigned values for demonstration
            print("base_command:", base_command)
            print("base_dest_path:", base_dest_path)
            print("base_dest_host:", base_dest_host)
            print("base_source_path:", base_source_path)
    else:
        print(f"Error: Unknown base command - {base_command}")

    log_file_name = f"/tmp/{os.path.basename(__file__)[:-3]}_{generate_random_string()}.log"
    smtp_server, dest_email, source_email, base_work_path = read_smtp_config(log_file_name)
    temp_folder_name = f"{base_work_path}/{os.path.basename(__file__)[:-3]}_{generate_random_string()}"

    source_host = "127.0.0.1"
    vm_number = "0"
    source_path = "/tmp"
    destination_archive = "/tmp/archive.tar.zst"

    process_commands( base_command="startup", temp_folder_name=temp_folder_name )

    try:
        for sync_file in os.listdir(base_source_path):
            if sync_file.endswith(".syncz") and (base_command == "syncz" or base_command.startswith("incz") or base_command.startswith("cleanz")):
                with open(os.path.join(base_source_path,sync_file), "r") as f:
                    source_path_with_host = f.readline().strip()
                    dest_archive = f.readline().strip()

                source_parts = source_path_with_host.split(":")
                source_host = source_parts[0]
                source_path = source_parts[1]

                if process_commands( base_command=base_command, source_host=source_host, source_path=source_path, destination_archive=dest_archive, temp_folder_name=temp_folder_name, log_file_name=log_file_name ) == -1:
                    raise Exception(f"Error creating {dest_archive}")

            if sync_file.endswith(".backup") and base_command == "iterate":
                with open(os.path.join(base_source_path,sync_file), "r") as f:
                    source_host = f.readline().strip()
                    source_path = f.readline().strip()
                    dest_archive = f.readline().strip()
                    vm_number = f.readline().strip()

                process_commands( base_command=base_command, source_host=source_host, source_path=source_path, vm_number=vm_number, destination_archive=os.path.join(base_dest_path,dest_archive), temp_folder_name=temp_folder_name, log_file_name=log_file_name )
                #if process_commands( base_command=base_command, source_host=source_host, source_path=source_path, vm_number=vm_number, destination_archive=os.path.join(base_dest_path,dest_archive), temp_folder_name=temp_folder_name, log_file_name=log_file_name ) == -1:
                #    raise Exception(f"Error on {source_host}:{source_path}")

            if sync_file.endswith(".tape") and base_command == "tapez":
                # print("tapez")
                source_archive = os.path.join(base_source_path, os.path.splitext( sync_file )[0])
                # print("tapez 2")
                destination_archive = os.path.join(base_dest_path, os.path.splitext( sync_file )[0])
                # print("tapez 3")
                if process_commands( base_command=base_command, source_path=source_archive, destination_archive=destination_archive, log_file_name=log_file_name) == -1:
                    raise Exception(f"Error copying {source_archive}")

            if sync_file.endswith(".tar.zst") and base_command == "testz":
                source_archive = os.path.join(base_source_path, sync_file)
                if process_commands( base_command=base_command, source_path=source_archive, log_file_name=log_file_name ) == -1:
                    raise Exception(f"Error testing {source_archive}")

            if sync_file.endswith(".remote") and (base_command == "remotez" or base_command == "b2z"):
                source_archive = os.path.join(base_source_path, os.path.join(os.path.dirname(sync_file), os.path.splitext(os.path.basename(sync_file))[0]))
                destination_archive = os.path.join(base_dest_path, os.path.splitext(sync_file)[0])
                if process_commands( base_command=base_command, source_host=base_dest_host, source_path=source_archive, destination_archive=destination_archive, log_file_name=log_file_name ) == -1:
                    raise Exception(f"Error syncing {source_archive} to {base_dest_host}")

    except Exception as e:
        if base_command not in ["incz", "testz", "remote", "tapez", "b2z"]:
            subprocess.run(f"fusermount -u {temp_folder_name}", shell=True)
            subprocess.run(f"rmdir {temp_folder_name}", shell=True)

        print(f"Error: {e}")
        with open(log_file_name, "a") as log:
            log.write(f"Error: {e}\n")
        return

    finally:
        if base_command not in ["incz", "testz", "remote", "tapez", "b2z"]:
            subprocess.run(f"fusermount -u {temp_folder_name}", shell=True)
            subprocess.run(f"rmdir {temp_folder_name}", shell=True)

if __name__ == "__main__":
    main()
