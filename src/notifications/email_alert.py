import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv


load_dotenv()


def send_failure_alert(subject: str, message: str):
    sender = os.getenv("ALERT_EMAIL_SENDER")
    password = os.getenv("ALERT_EMAIL_PASSWORD")
    receiver = os.getenv("ALERT_EMAIL_RECEIVER")

    if not sender or not password or not receiver:
        print("Email alert settings missing. Skipping notification.")
        return

    email = EmailMessage()
    email["Subject"] = subject
    email["From"] = sender
    email["To"] = receiver
    email.set_content(message)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(sender, password)
            smtp.send_message(email)

        print("Failure alert email sent successfully.")

    except Exception as error:
        print(f"Failed to send email alert: {error}")