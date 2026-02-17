#!/bin/bash

smtp_host="172.16.1.25"
smtp_destination="DL_ITMonitor@dairylandlabs.com"
smtp_from="backups@dairylandlabs.com"
base_directory="/mnt/backup/"

figlet -f slant tapez.sh

# Check if the correct number of arguments are provided
if [ "$#" -ne 2 ]; then
    echo "Usage: $0 source_directory destination_directory"
    exit 1
fi

source_directory="$1"
destination_directory="$2"
tmp_directory="/tmp"

# Get the directory where the script was executed
current_directory=$(dirname "$0")
smtp_file="$current_directory/smtp.txt"

# Generate a random string
random_string=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 10)

# Combine the random string with the word 'remote'
error_log="/tmp/tapez_${random_string}.log"

# Display the generated filename
echo "Generated filename: $error_log"

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

# Iterate through .tar.zst files in the source directory
for tar_file in "$source_directory"/*.tar.zst; do
    # Extract the file name without extension
    file_name=$(basename "$tar_file" .tar.zst)
    # lock_file=$(basename "$tar_file" .tar.zst)
    lock_file="/tmp/$(basename "$tar_file" .tar.zst).lock"

    tape_file="$source_directory/$file_name.tar.zst.tape"

    # Check if a file with the same name exists in /tmp, if so, skip
    if [ -e "$lock_file" ]; then
        echo "Lock file $lock_file exists, skipping." | tee -a "$error_log"
        continue
    fi

    # If a .tar.zst.tape file exists, copy the .tar.zst file to the destination directory
    if [ -e "$tape_file" ]; then
        echo "Creating $lock_file"
        echo $$ > "$lock_file"

        cp "$tar_file" "$destination_directory/"
        echo "Copied $tar_file to $destination_directory/"

        echo "Removing $lock_file"
        rm "$lock_file"
    fi
done

echo "Copy operation completed."

if [ -e "$error_log" ]; then
    python sendEmail.py -o -s "$smtp_host" -m "tapez ERROR FILE SKIPPED" -f "$smtp_from" -t "$smtp_destination" -a "$error_log" -p 25 -b "tapez.sh ERROR FILE SKIPPED"
    echo "Removing $error_log"
    rm "$error_log"
else
    python sendEmail.py -o -s "$smtp_host" -m "tapez SUCCESS NO ERRORS" -f "$smtp_from" -t "$smtp_destination" -p 25 -b "tapez.sh SUCCESS NO ERRORS"
fi


