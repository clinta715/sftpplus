#!/bin/bash

if [ $# -ne 1 ]; then
    echo "Usage: $0 <data_file>"
    exit 1
fi

data_file="$1"

if [ ! -f "$data_file" ]; then
    echo "Error: File '$data_file' not found."
    exit 1
fi

# Read the lines from the file
IFS=$'\n' read -r -d '' -a lines < "$data_file"

# Assign variables
ip_address=${lines[0]}
vm_path=${lines[1]}
archive_name=${lines[2]}

# Step 1: Mount the VM data files path using sshfs
sshfs $ip_address:$vm_path /mnt/backup/tmp

# Step 2: Ask the user if they want to erase or rename files
read -p "Do you want to erase or rename the files? (erase/rename): " action

if [ "$action" == "erase" ]; then
    # Step 3: Erase files
    rm -rf /mnt/backup/tmp/*
elif [ "$action" == "rename" ]; then
    # Step 4: Rename files
    cd /mnt/backup/tmp
    for file in *; do
        mv "$file" "$file.backup"
    done
else
    echo "Invalid option. Please choose 'erase' or 'rename'."
fi

# Step 5: Locate and extract the archive file
tar --use-compress-program=zstd -xf $archive_name -C /mnt/backup/tmp

# Step 6: Remove paths stored in the tar file
find /mnt/backup/tmp -type f -exec sed -i -E 's/([a-zA-Z0-9]+)-[0-9]{6}\.vmdk/\1.vmdk/g' {} \;

# Step 7: Unmount the VM data files path
fusermount -u /mnt/backup/tmp

