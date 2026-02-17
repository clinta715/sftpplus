#!/bin/bash

smtp_host="172.16.1.25"
smtp_destination="DL_ITMonitor@dairylandlabs.com"
smtp_from="backups@dairylandlabs.com"
base_directory="/mnt/backup/"

figlet -f slant remote.sh

# Check if the script has been provided with three arguments
if [ "$#" -ne 3 ]; then
    echo "Usage: $0 <source_path> <destination_host> <destination_path>"
    exit 1
fi

# Assign the arguments to variables
source_path="$1"
destination_host="$2"
destination_path="$3"

#!/bin/bash

# Generate a random string
random_string=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 10)

# Combine the random string with the word 'remote'
error_log="/tmp/remote_${random_string}.log"

# Display the generated filename
echo "Generated filename: $error_log"

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

# Iterate through the source_path and find .remote files
for remote_file in "$source_path"/*.remote; do
    if [ -e "$remote_file" ]; then
        # Extract the base filename (remove .remote extension)
        base_filename=$(basename "$remote_file" .remote)
        source_file="$source_path/$base_filename"
        tmp_lock_file="/tmp/$base_filename.lock"

        # Check if a lock file exists in /tmp
        if [ -e "$tmp_lock_file" ]; then
            echo "Skipping $base_filename due to lock file" | tee -a "$error_log"
            echo "$base_filename" > "$error_log"
            continue
        fi

        # Create a lock file in /tmp
        touch "$tmp_lock_file"

        # Attempt to use rsync to copy the file to the destination host
        rsync -e "ssh" "$source_file" "$destination_host:$destination_path/"

        if [ $? -eq 0 ]; then
            echo "Successfully copied $base_filename to $destination_host:$destination_path/"
        else
            echo "Error copying $base_filename to $destination_host:$destination_path/" | tee -a "$error_log"
            echo "$base_filename" >> "$error_log"
        fi

        echo "Remove $tmp_lock_file"
        rm "$tmp_lock_file"

    fi
done

#!/bin/bash

if [ -e "$error_log" ]; then
    python sendEmail.py -o -s "$smtp_host" -m "remote.sh ERROR FILE SKIPPED" -f "$smtp_from" -t "$smtp_destination" -a "$error_log" -p 25 -b "remote.sh ERROR FILE SKIPPED"
    rn "$error_log"
    remove "$error_log"
else
    python sendEmail.py -o -s "$smtp_host" -m "remote.sh SUCCESS NO ERRORS" -f "$smtp_from" -t "$smtp_destination" -p 25 -b "remote.sh SUCCESS NO ERRORS"
fi

