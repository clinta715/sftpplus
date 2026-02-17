#!/bin/bash

# ESXi host SSH connection details
ESXI_HOST="172.16.1.28"
ESXI_USER="root"
ESXI_PASSWORD="GetInTheVan!"

# VM details
VM_ID="129"
SNAPSHOT_ID="29"

# SSH command to revert to snapshot and power on VM
#sshpass -p "$ESXI_PASSWORD" ssh -o StrictHostKeyChecking=no $ESXI_USER@$ESXI_HOST << EOF
ssh root@172.16.1.28 'vim-cmd vmsvc/snapshot.revert $VM_ID $SNAPSHOT_ID false'
ssh root@172.16.1.28 'vim-cmd vmsvc/power.on $VM_ID'
