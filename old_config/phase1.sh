#!/bin/bash

# Determine your own IP and subnet
ip=$(hostname -I | cut -d' ' -f1)
subnet=$(echo $ip | cut -d'.' -f1-3)

# Scan the subnet
echo "Scanning the subnet for open IP addresses. This may take a while..."
nmap -sn ${subnet}.0/24 | grep "Nmap scan report" | cut -d' ' -f5 > scan_results.txt

# Analyze the scan results
echo "Analyzing results..."
python analyze_scan.py

echo "Analysis complete."
