#!/bin/bash

figlet -f slant iterate.sh

# Check if folder argument is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <folder>"
    exit 1
fi

# Check if folder exists
if [ ! -d "$1" ]; then
    echo "Error: Folder '$1' does not exist."
    exit 1
fi

# Iterate through .sync files
for file in "$1"/*.sync; do
    if [ -f "$file" ]; then
        source_info=$(sed -n '1p' "$file")
        dest_path=$(sed -n '2p' "$file")
        
        # Extract source host and path
        source_host=$(echo "$source_info" | awk -F ':' '{print $1}')
        source_path=$(echo "$source_info" | awk -F ':' '{print $2}')
        
        # Check if source path and destination path are valid
        if [ -n "$source_host" ] && [ -n "$source_path" ] && [ -d "$dest_path" ]; then
            echo "Syncing $source_path from $source_host to $dest_path"
            rsync -av --delete -e "ssh -l root" "$source_host:$source_path/" "$dest_path/"
        else
            echo "Error: Invalid source host, source path, or destination path in $file"
        fi
    fi
done
