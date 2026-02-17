# mount backup device -----------------------------------------------------------------------------------------------
sudo mount /dev/sdb1 /mnt/backup

# mount VM folders on vmhost2 ---------------------------------------------------------------------------------------
sshfs root@172.16.1.11:/vmfs/volumes/645cf636-4ecda4cf-ab48-14feb5c99868 /mnt/vmhost2/raid5
sshfs root@172.16.1.11:/vmfs/volumes/645cf1df-f879d4a5-f7ad-14feb5c99868 /mnt/vmhost2/datastore1

# mount VM folders on vmhost0 ---------------------------------------------------------------------------------------
sshfs root@172.16.1.10:/vmfs/volumes/5d60101a-e13c788c-943d-842b2b74cd60 /mnt/vmhost0/noraid
sshfs root@172.16.1.10:/vmfs/volumes/62842fff-3100eda4-8800-842b2b74cd60 /mnt/vmhost0/noraid1
sshfs root@172.16.1.10:/vmfs/volumes/570fe906-67240df4-7bd4-842b2b74cd60 /mnt/vmhost0/vmhost0-local

# mount VM folders on vmhost1 ---------------------------------------------------------------------------------------
sshfs root@172.16.1.28:/vmfs/volumes/5852bbc9-6bd3fdb3-929d-d067e5f042f0 /mnt/vmhost1/vmhost1-local

# start backup of vmhost2 VMs ---------------------------------------------------------------------------------------
ssh root@172.16.1.11 'vim-cmd vmsvc/getallvms'

ssh root@172.16.1.11 'vim-cmd vmsvc/snapshot.create 11 "Snapshot_Name" "Snapshot_Description" 0 1'
mkdir /mnt/backup/NNBS
find /mnt/vmhost2/raid5/NNBS/ -type f \( -name "*.vmdk" -o -name "*.vmx" -o -name "*.vmxf" -o -name "*.vmsd" \) -print | tar --use-compress-program=zstd -cvf /mnt/backup/NNBS/NNBS.tar.zstd -T -
ssh root@172.16.1.11 'vim-cmd vmsvc/snapshot.removeall 11'

ssh root@172.16.1.11 'vim-cmd vmsvc/snapshot.create 21 "Snapshot_Name" "Snapshot_Description" 0 1'
mkdir /mnt/backup/util2-unify\ rebuild
find /mnt/vmhost2/raid5/util2-unify\ rebuild/ -type f \( -name "*.vmdk" -o -name "*.vmx" -o -name "*.vmxf" -o -name "*.vmsd" \) -print | tar --use-compress-program=zstd -cvf /mnt/backup/util2-unify\ rebuild/util2-unify\ rebuild.tar.zstd -T -
ssh root@172.16.1.11 'vim-cmd vmsvc/snapshot.removeall 21'

# start backup of vmhost0 VMs ---------------------------------------------------------------------------------------
ssh root@172.16.1.10 'vim-cmd vmsvc/getallvms'

ssh root@172.16.1.10 'vim-cmd vmsvc/snapshot.create 52 "Snapshot_Name" "Snapshot_Description" 0 1'
mkdir /mnt/backup/SmartQC
find /mnt/vmhost0/vmhost0-local/SmartQC/ -type f \( -name "*.vmdk" -o -name "*.vmx" -o -name "*.vmxf" -o -name "*.vmsd" \) -print | tar --use-compress-program=zstd -cvf /mnt/backup/SmartQC/SmartQC.tar.zstd -T -
ssh root@172.16.1.10 'vim-cmd vmsvc/snapshot.removeall 52'

# start backup of vmhost1 VMs ---------------------------------------------------------------------------------------
ssh root@172.16.1.28 'vim-cmd vmsvc/getallvms'

ssh root@172.16.1.28 'vim-cmd vmsvc/snapshot.create 53 "Snapshot_Name" "Snapshot_Description" 0 1'
mkdir /mnt/backup/Router_Main
find /mnt/vmhost1/vmhost1-local/Router_Main/ -type f \( -name "*.vmdk" -o -name "*.vmx" -o -name "*.vmxf" -o -name "*.vmsd" \) -print | tar --use-compress-program=zstd -cvf /mnt/backup/Router_Main/Router_Main.tar.zstd -T -
ssh root@172.16.1.28 'vim-cmd vmsvc/snapshot.removeall 53'

ssh root@172.16.1.28 'vim-cmd vmsvc/snapshot.create 70 "Snapshot_Name" "Snapshot_Description" 0 1'
mkdir /mnt/backup/jerry
find /mnt/vmhost1/vmhost1-local/jerry/ -type f \( -name "*.vmdk" -o -name "*.vmx" -o -name "*.vmxf" -o -name "*.vmsd" \) -print | tar --use-compress-program=zstd -cvf /mnt/backup/jerry/jerry.tar.zstd -T -
ssh root@172.16.1.28 'vim-cmd vmsvc/snapshot.removeall 70'

ssh root@172.16.1.28 'vim-cmd vmsvc/snapshot.create 129 "Snapshot_Name" "Snapshot_Description" 0 1'
mkdir /mnt/backup/utility3
find /mnt/vmhost0/vmhost0-local/utility3/ -type f \( -name "*.vmdk" -o -name "*.vmx" -o -name "*.vmxf" -o -name "*.vmsd" \) -print | tar --use-compress-program=zstd -cvf /mnt/backup/utility3/utility3.tar.zstd -T -
ssh root@172.16.1.28 'vim-cmd vmsvc/snapshot.removeall 129'

ssh root@172.16.1.28 'vim-cmd vmsvc/snapshot.create 72 "Snapshot_Name" "Snapshot_Description" 0 1'
mkdir /mnt/backup/BOBBIJO-VIRTUAL
find /mnt/vmhost0/vmhost0-local/BOBBIJO-VIRTUAL/ -type f \( -name "*.vmdk" -o -name "*.vmx" -o -name "*.vmxf" -o -name "*.vmsd" \) -print | tar --use-compress-program=zstd -cvf /mnt/backup/BOBBIJO-VIRTUAL/BOBBIJO-VIRTUAL.tar.zstd -T -
ssh root@172.16.1.28 'vim-cmd vmsvc/snapshot.removeall 72'

ssh root@172.16.1.28 'vim-cmd vmsvc/snapshot.create 131 "Snapshot_Name" "Snapshot_Description" 0 1'
mkdir /mnt/backup/HVAC\ PC
find /mnt/vmhost0/vmhost0-local/HVAC\ PC/ -type f \( -name "*.vmdk" -o -name "*.vmx" -o -name "*.vmxf" -o -name "*.vmsd" \) -print | tar --use-compress-program=zstd -cvf /mnt/backup/HVAC\ PC/HVAC\ PC.tar.zstd -T -
ssh root@172.16.1.28 'vim-cmd vmsvc/snapshot.removeall 131'

ssh root@172.16.1.28 'vim-cmd vmsvc/snapshot.create 104 "Snapshot_Name" "Snapshot_Description" 0 1'
mkdir /mnt/backup/Unscrambler
find /mnt/vmhost0/vmhost0-local/Unscrambler/ -type f \( -name "*.vmdk" -o -name "*.vmx" -o -name "*.vmxf" -o -name "*.vmsd" \) -print | tar --use-compress-program=zstd -cvf /mnt/backup/Unscrambler/Unscrambler.tar.zstd -T -
ssh root@172.16.1.28 'vim-cmd vmsvc/snapshot.removeall 104'

ssh root@172.16.1.28 'vim-cmd vmsvc/snapshot.create 111 "Snapshot_Name" "Snapshot_Description" 0 1'
mkdir /mnt/backup/Nik
find /mnt/vmhost0/vmhost0-local/Nik/ -type f \( -name "*.vmdk" -o -name "*.vmx" -o -name "*.vmxf" -o -name "*.vmsd" \) -print | tar --use-compress-program=zstd -cvf /mnt/backup/Nik/Nik.tar.zstd -T -
ssh root@172.16.1.28 'vim-cmd vmsvc/snapshot.removeall 111'

# unmount vmhost2 folders -------------------------------------------------------------------------------------------
umount /mnt/vmhost2/raid5
umount /mnt/vmhost2/datastore1

# unmount vmhost1 folders -------------------------------------------------------------------------------------------
umount /mnt/vmhost0/noraid
umount /mnt/vmhost0/noraid1
umount /mnt/vmhost0/vmhost0-local

# unmount vmhost0 folders -------------------------------------------------------------------------------------------
umount /mnt/vmhost1/vmhost1-local

# unmount backup device
umount /dev/sdb1

