"""
Email notification utilities for fantasy football analysis.

This module handles sending email notifications with optional file attachments.
"""

import os
import smtplib
import ssl
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(subject: str, body: str, address: str, filename: str = None):
    """
    Sends an email to the address provided with whichever subject, body, and attachments desired.

    Args:
        subject (str): subject line of the email to be sent.  
        body (str): body text of the email to be sent.  
        address (str): email address to send the message to.  
        filename (str, optional): location of a file to be attached to the email, defaults to None.
    """
    message = MIMEMultipart()
    message["From"] = os.environ["EMAIL_SENDER"]
    message["To"] = address
    message["Subject"] = subject
    message.attach(MIMEText(body + "\n\n", "plain"))
    
    if filename and os.path.exists(str(filename)):
        with open(filename, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition", "attachment; filename= " + filename.split("/")[-1]
        )
        message.attach(part)
    
    text = message.as_string()
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(os.environ["EMAIL_SENDER"], os.environ["EMAIL_PW"])
        server.sendmail(os.environ["EMAIL_SENDER"], address, text)
