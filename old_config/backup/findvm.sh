#!/bin/bash

# Check if the required argument is provided
if [ $# -eq 0 ]; then
  echo "Usage: $0 <vm_name_to_compare>"
  exit 1
fi

# The name of the VM to compare is the first command-line argument
vm_name_to_compare="$1"

# Read the list of ESXi servers from the servers.txt file
servers_file="servers.txt"

# Check if the servers.txt file exists
if [ ! -f "$servers_file" ]; then
  echo "Error: servers.txt file not found."
  exit 1
fi

# Read the list of ESXi servers from the file into an array
mapfile -t esxi_servers < "$servers_file"

# Function to check if a VM is present on an ESXi server and get its data file path
check_vm_on_server() {
  local server="$1"
  local vm_name="$2"
  
  # Use SSH to execute vim-cmd vmsvc/getallvms and extract VM info
  ssh_output=$(ssh root@$server 'vim-cmd vmsvc/getallvms' | grep -E '^\s+[0-9]+ ')

  echo $ssh_output
  
  # Loop through each line of the output
  while read -r vm_line; do
    vm_name_in_line=$(echo "$vm_line" | awk '{print $2}')
    volume_name_in_line=$(echo "$vm_line" | awk '{print $3}')
    data_path_in_line=$(echo "$vm_line" | awk '{print $4}')
    
    if [ "$vm_name_in_line" == "$vm_name" ]; then
      echo "VM '$vm_name' found on $server"
      echo "Volume Name: $volume_name_in_line"
      echo "Path to Data Files: $data_path_in_line"

      # Use SSH to list folders under /vmfs/volumes
      folders_list=$(ssh root@"$server" "ls -1 /vmfs/volumes")

      # Check if there's a folder corresponding to the volume name
      if echo "$folders_list" | grep -q "$volume_name_in_line"; then
        echo "Folder for volume '$volume_name_in_line' found under /vmfs/volumes on $server"
      else
        echo "Folder for volume '$volume_name_in_line' not found under /vmfs/volumes on $server"
      fi
      
      return
    fi
  done <<< "$ssh_output"
  
  echo "VM '$vm_name' not found on $server"
}

# Loop through the ESXi servers
for server in "${esxi_servers[@]}"; do
  echo "Connecting to $server..."
  check_vm_on_server "$server" "$vm_name_to_compare"
  echo "=================================="
done
