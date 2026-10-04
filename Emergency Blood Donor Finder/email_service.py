"""Optional Gmail notifications. Missing configuration is intentionally non-fatal."""
import os
import smtplib
from email.message import EmailMessage


def send_email(subject, body, recipient=None):
    username = os.getenv("EMAIL_USERNAME")
    password = os.getenv("EMAIL_APP_PASSWORD")
    recipient = recipient or os.getenv("ADMIN_EMAIL")
    if not all((username, password, recipient)):
        return False
    message = EmailMessage(); message["Subject"] = subject; message["From"] = username; message["To"] = recipient; message.set_content(body)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(username, password); server.send_message(message)
        return True
    except (OSError, smtplib.SMTPException, ValueError):
        return False
