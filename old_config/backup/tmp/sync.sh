#!/bin/bash

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
        source_path=$(sed -n '1p' "$file")
        dest_path=$(sed -n '2p' "$file")
        
        # Check if source path and destination path are valid
        if [ -d "$source_path" ] && [ -d "$dest_path" ]; then
            echo "Syncing $source_path to $dest_path"
            rsync -av --delete "$source_path/" "$dest_path/"
        else
            echo "Error: Invalid source or destination path in $file"
        fi
    fi
done
