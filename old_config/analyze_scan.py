# analyze_scan.py

def ip_to_int(ip):
    """
    Convert an IP address to an integer.
    """
    parts = ip.split('.')
    return int(parts[0]) * 256**3 + int(parts[1]) * 256**2 + int(parts[2]) * 256 + int(parts[3])

def int_to_ip(n):
    """
    Convert an integer back to an IP address.
    """
    return '.'.join([str(n // (256**i) % 256) for i in range(3, -1, -1)])

def find_contiguous_blocks(ips, block_size=10):
    """
    Find contiguous blocks of open IP addresses.
    """
    contiguous_blocks = []
    sorted_ips = sorted([ip_to_int(ip) for ip in ips])
    
    start_block = None
    current_count = 0

    for ip in sorted_ips:
        if start_block is None:
            start_block = ip
            current_count = 1
        elif ip == start_block + current_count:
            current_count += 1
            if current_count == block_size:
                contiguous_blocks.append((start_block, ip))
                start_block = None
                current_count = 0
        else:
            start_block = ip
            current_count = 1

    return [(int_to_ip(start), int_to_ip(end)) for start, end in contiguous_blocks]

def main():
    # Read scan results
    with open('scan_results.txt', 'r') as file:
        scanned_ips = file.read().splitlines()

    # Assuming a full class C subnet (254 hosts), you can modify as needed
    all_possible_ips = [f'172.16.1.{i}' for i in range(1, 255)]

    # Open IPs are those not in the scanned results
    open_ips = [ip for ip in all_possible_ips if ip not in scanned_ips]

    # Find contiguous blocks
    blocks = find_contiguous_blocks(open_ips, 10)

    # Output the blocks found
    for start, end in blocks:
        print(f"Contiguous block: {start} - {end}")

if __name__ == "__main__":
    main()
