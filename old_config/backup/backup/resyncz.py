import sys
import os
import subprocess
import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def generate_random_string(length=8):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def read_smtp_config(log_file_name):
    try:
        with open("smtp.txt", "r") as f:
            smtp_server = f.readline().strip()
            dest_email = f.readline().strip()
            source_email = f.readline().strip()
            base_work_path = f.readline().strip()
    except FileNotFoundError:
        with open(log_file_name, "a") as log:
            log.write(f"Error: smtp.txt not found\n")
        print(f"Error: smtp.txt not found")
        exit(1)

    return smtp_server, dest_email, source_email, base_work_path

def send_email(smtp_server, source_email, dest_email, log_file_name, subject, body):
    msg = MIMEMultipart()
    msg['From'] = source_email
    msg['To'] = dest_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    if log_file_name:
        with open(log_file_name, 'rb') as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload((attachment).read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', "attachment; filename= %s" % os.path.basename(log_file_name))
            msg.attach(part)

    try:
        server = smtplib.SMTP(smtp_server)
        server.sendmail(source_email, dest_email, msg.as_string())
        server.quit()
        print(f"Email sent successfully to {dest_email}")
    except Exception as e:
        print(f"Failed to send email. Error: {e}")
        with open(log_file_name, "a") as log:
            log.write(f"Failed to send email. Error: {e}\n")

def send_success_email(smtp_server, source_email, dest_email):
    subject = "Script Completed Successfully"
    body = "The script completed successfully without any errors."

    send_email(smtp_server, source_email, dest_email, None, subject, body)

def main():
    if len(sys.argv) < 2:
        print("Usage: python your_script.py source_path destination_path")
        sys.exit(1)

    base_work_path = sys.argv[1]
    base_dest_path = sys.argv[2]

    temp_folder_name = f"/tmp/{os.path.basename(__file__)[:-3]}_{generate_random_string()}"
    log_file_name = f"/tmp/{os.path.basename(__file__)[:-3]}_{generate_random_string()}.log"
    smtp_server, dest_email, source_email, base_work_path = read_smtp_config(log_file_name)

    print(f"Using SMTP server: {smtp_server}")
    print(f"Destination Email: {dest_email}")
    print(f"Source Email: {source_email}")
    print(f"Base Work Path: {base_work_path}")
    print(f"Temporary Folder Name: {temp_folder_name}")
    print(f"Log File Name: {log_file_name}")

    try:
        # Process .sync files
        for sync_file in os.listdir(base_work_path):
            if sync_file.endswith(".syncz"):
                with open(sync_file), "r") as f:
                    source_path_with_host = f.readline().strip()
                    dest_archive = f.readline().strip()

                source_parts = source_path_with_host.split(":")
                source_host = source_parts[0]
                source_path = source_parts[1]

                print(f"Source Host: {source_host}")
                print(f"Source Path: {source_path}")

                os.makedirs( temp_folder_name, exist_ok=True)
                resyncz( source_host, source_path, dest_archive, temp_folder_name, log_file_name )
           if sync_file.endswith(".backup"):
                with open(sync_file), "r") as f:
                    source_host = f.readline().strip()
                    source_path = f.readline().strip()
                    dest_archive = f.readline().strip()
                    resulting_path = os.path.join(base_dest_path, dest_archive)
                    vm_number = f.readline().strip()

                iterate( source_host, source_path, vm_number, dest_archive, temp_folder_name, log_file_name )
            if sync_file.endswith(".tape"):
                source_archive = os.path.join(base_work_path, sync_file[:-5])
                destination_archive = os.path.join(base_dest_path, sync_file[:-5])

                tapez( source_archive, destination_archive, log_file_name)
            if sync_file.endswith(".tar.zst"):
                testz( sync_file )
    except Exception as e:
        with open(log_file_name, "a") as log:
            log.write(f"Error: {e}\n")
        print(f"Error: {e}")
        send_email(smtp_server, source_email, dest_email, log_file_name, "Script Error", f"Error: {e}")
    else:
        send_success_email(smtp_server, source_email, dest_email)

if __name__ == "__main__":
    main()
