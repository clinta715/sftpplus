import argparse
import pysftp

def sftp_upload(host, username, password, local_file, remote_path):
    try:
        with pysftp.Connection(host, username=username, password=password) as sftp:
            print(f"Connected to {host}")
            sftp.put(local_file, remote_path)
            print(f"Uploaded '{local_file}' to '{remote_path}' on {host}")
    except FileNotFoundError as e:
        print(f"Error: Local file '{local_file}' not found.")
    except PermissionError as e:
        print(f"Error: Permission denied. Check if you have the necessary permissions.")
    except pysftp.ConnectionException as e:
        print(f"Error: Failed to establish connection to {host}. Please check the host address and port.")
    except pysftp.CredentialException as e:
        print(f"Error: Authentication failed. Please check the username and password.")
    except pysftp.SSHException as e:
        print(f"Error: SSH error occurred. Please check your SSH configuration.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SFTP file upload")
    parser.add_argument("-u", "--username", help="User name for SFTP connection", required=True)
    parser.add_argument("-p", "--password", help="Password for SFTP connection", required=True)
    parser.add_argument("-H", "--host", help="Host name for SFTP connection", required=True)
    parser.add_argument("-l", "--local_file", help="Local file path to upload", required=True)
    parser.add_argument("-r", "--remote_path", help="Remote path on the host", required=True)
    args = parser.parse_args()

    try:
        sftp_upload(args.host, args.username, args.password, args.local_file, args.remote_path)
    except Exception as e:
        print(f"An error occurred: {e}")
