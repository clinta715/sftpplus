#!/bin/bash

smtp_host="172.16.1.25"
smtp_destination="DL_ITMonitor@dairylandlabs.com"
smtp_from="backups@dairylandlabs.com"
base_directory="/mnt/backup/"

figlet -f slant iterate.sh

#!/bin/bash

# Generate a random string
random_string=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 10)

# Combine the random string with the word 'remote'
error_log="/tmp/iterate_${random_string}.log"

# Display the generated filename
echo "Generated filename: $error_log"

# Function to perform backups
perform_backup() {
    local source_host="$1"
    local source_path="$2"
    local dest_path="/mnt/backup/tmp"
    local dest_filename="$3"
    local vm_number="$4"
    local archive_dest="$5"

    # Generate a random string for the lock file name
    lockfile="/tmp/$dest_filename.lock"

    if [ -e "$lockfile" ]; then
        echo "File $lockfile exists. Returning from function." | tee -a "$error_log"
        return 1
    fi

    # Write the current process number to the lock file
    echo "Create lockfile $lockfile"
    echo $$ > "$lockfile"

    # Generate a unique folder name using date/time and a random string
    timestamp=$(date +"%Y%m%d%H%M%S")
    random_string=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 8 | head -n 1)
    random_folder_name="iterate_${timestamp}_${random_string}"

    # Combine the base directory and random folder name
    random_folder_path="${base_directory}/${random_folder_name}"

    # Create the folder if it doesn't exist
    echo "Create $random_folder_path"
    mkdir -p "$random_folder_path"

    # Now you can use $random_folder_path in your code
    dest_path="$random_folder_path"

    # Create a snapshot of the VM using its VMware ID
    ssh root@$source_host "vim-cmd vmsvc/snapshot.create $vm_number BackupSnapshot SnapshotBackup 0 1"

    # Check if the snapshot creation was successful
    if [ $? -eq 0 ]; then
        echo "Created snapshot for VM $vm_number successfully."
    else
        echo "Failed to create a snapshot for VM $vm_number. Exiting." | tee -a "$error_log"
        return
    fi

    # Mount the VM host path using SSHFS
    sshfs "root@$source_host:$source_path" "$dest_path"

    # Check if the mount was successful
    if [ $? -eq 0 ]; then
        echo "Mounted $source_host:$source_path to $dest_path successfully."
        # Create a backup using tar and zstd

        if [ -e "$archive_dest/$dest_filename" ]; then
     	    echo "Removing old backup $archive_dest/$dest_filename""
	    rm "$archive_dest/$dest_filename"
        fi

        find $dest_path -type f \( -name "*.vmdk" -o -name "*.vmx" -o -name "*.vmxf" -o -name "*.vmsd" \) -not \( -name "*00000*" -o -name "*sesparse*" \) -print | tar --use-compress-program=zstd -cvf $archive_dest/$dest_filename -T - | tee -a "$error_log"

        # Unmount the SSHFS mount point
        fusermount -u "$dest_path"

        echo "Backup completed for VM $vm_number."
    else
        echo "Failed to mount $source_host:$source_path to $dest_path." | tee -a "$error_log"
    fi

    # Remove the snapshot after backup is completed
    ssh root@$source_host "vim-cmd vmsvc/snapshot.removeall $vm_number"
    echo "Removed snapshot for VM $vm_number."
    rm -rf "$dest_path"

    # Remove the lock file when the script is done
    echo "Remove $lockfile lock file"
    rm -f "$lockfile"
}

# Check if an argument was provided for the directory path
if [ $# -eq 0 ]; then
  echo "Usage: $0 <directory_path> <archive path>"
  exit 1
fi

# Directory path provided as the first argument
directory_path="$1"
archive_path="$2"

# Ensure the provided directory exists
if [ ! -d "$directory_path" ]; then
  echo "Directory not found: $directory_path"
  exit 1
fi

# Ensure the provided directory exists
if [ ! -d "$archive_path" ]; then
  echo "Directory not found: $archive_path"
  exit 1
fi

# Get the directory where the script was executed
current_directory=$(dirname "$0")
smtp_file="$current_directory/smtp.txt"

# Check if smtp.txt file exists
if [ -e "$smtp_file" ]; then
    # Read lines from smtp.txt and assign them to variables
    {
        IFS= read -r smtp_host
        IFS= read -r smtp_from
        IFS= read -r smtp_destination
        IFS= read -r base_directory
    } < "$smtp_file"

    echo "SMTP Host: $smtp_host"
    echo "SMTP From: $smtp_from"
    echo "SMTP Destination: $smtp_destination"
    echo "Base Directory: $base_directory"
else
    echo "Error: smtp.txt file not found in the current directory."
fi

# Find all .backup files in the backups subfolder
find "$directory_path" -type f -name "*.backup" | while read -r file; do
    # Read 4 lines from each .backup file
    while IFS= read -r source_host &&
          IFS= read -r source_path &&
          IFS= read -r dest_filename &&
          IFS= read -r vm_number; do

        # Perform the backup
        perform_backup "$source_host" "$source_path" "$dest_filename" "$vm_number" "$archive_path"

    done < "$file"

if [ -e "$error_log" ]; then
    echo "Remove $error_log"
    python sendEmail.py -o -s "$smtp_host" -m "iterate.sh ERRORS BACKING UP VM" -f "$smtp_from" -t "$smtp_destination" -a "$error_log" -p 25 -b "iterate.sh ERRORS BACKING UP VM"
    rm "$error_log"
else
    python sendEmail.py -o -s "$smtp_host" -m "iterate.sh SUCCESS NO ERRORS" -f "$smtp_from" -t "$smtp_destination"  -p 25 -b "iterate.sh SUCCESS NO ERRORS"
fi

done
