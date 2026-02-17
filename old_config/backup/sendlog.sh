#!/bin/bash

# SMTP server configuration
smtp_server="172.16.1.25"  # Replace with the SMTP server address or hostname
smtp_port=25  # SMTP server port (typically 25 for unsecured)

# Email content
recipient="canderson@dairylandlabs.com"
subject="iterate.log"
attachment="/tmp/iterate.log"

# Email headers
{
  echo "EHLO dairylandlabs.com"
  echo "MAIL FROM: <backuppc@dairylandlabs.com>"
  echo "RCPT TO: <$recipient>"
  echo "DATA"
  echo "Subject: $subject"
  echo "To: $recipient"
  echo "MIME-Version: 1.0"
  echo "Content-Type: text/plain"
  echo "Content-Disposition: inline"
  cat "$attachment"
  echo
  echo "."
  echo
  echo "QUIT"
} | telnet "$smtp_server" "$smtp_port"

echo "Email sent successfully."
