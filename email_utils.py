"""Sends email over SMTP (works with SendGrid, Postmark, Amazon SES, Gmail SMTP, etc.)."""
import os
import smtplib
import ssl
from email.message import EmailMessage


def send_email(to: str, subject: str, body: str):
    host = os.getenv("SMTP_HOST")
    if not host:
        # Development fallback only. Set SMTP_HOST in production so links are never printed to logs.
        print(f"\n[SMTP not configured, email not sent]\nTo: {to}\nSubject: {subject}\n\n{body}\n")
        return
    msg = EmailMessage()
    msg["From"] = os.getenv("EMAIL_FROM") or os.getenv("SMTP_USER", "")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    port = int(os.getenv("SMTP_PORT", "587"))
    ctx = ssl.create_default_context()
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, context=ctx, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls(context=ctx)
        with server:
            if os.getenv("SMTP_USER"):
                server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS", ""))
            server.send_message(msg)
    except Exception as e:  # never break signup because email is down
        print("Email failed:", e)
