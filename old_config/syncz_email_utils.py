import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from syncz_logging_utils import logger

def send_email(smtp_server, source_email, dest_email, log_file_name, subject, body):
    msg = MIMEMultipart()
    msg['From'] = source_email
    msg['To'] = dest_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    if log_file_name and os.path.exists(log_file_name):
        with open(log_file_name, 'rb') as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f"attachment; filename={os.path.basename(log_file_name)}")
            msg.attach(part)

    try:
        with smtplib.SMTP(smtp_server) as server:
            server.sendmail(source_email, dest_email, msg.as_string())
        logger.info(f"Email sent successfully to {dest_email}")
    except Exception as e:
        logger.error(f"Failed to send email. Error: {e}")
