import os
import subprocess

def process_commands( command_sequence, source_host, source_path, destination_archive, temp_folder_name, log_file_name ):
    lockfile = f"/tmp/{os.path.basename(destination_archive)}.lock"

    try:
        if os.path.exists(lockfile):
            print(f"Lockfile {lockfile} already exists. Skipping.")
            with open(log_file_name, "a") as log:
                log.write(f"Lockfile {lockfile} already exists. Skipping.\n")
            return -1
        else:
            with open(lockfile, "w") as lock:
                lock.write(str(os.getpid()))

        for command_exec in command_sequence:
            print(f"{command_exec}")
            result = subprocess.run(command_exec, shell=True, capture_output=True, text=True)
            print(f"{result.returncode},{result.stdout},{result.stderr}")
            if result.returncode != 0:
                raise Exception(f"{result.returncode},{result.stdout},{result.stderr}")
    except Exception as e:
        subprocess.run("fusermount -u {temp_folder_name}")
        os.remove(lockfile)

        print(f"{e}")
        with open(log_file_name, "a") as log:
            log.write(f"{e}\n")

        return -1
    else:
        os.remove(lockfile)
