"""SMTP email sender tool."""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src import config

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> bool:
    """Sends a plain-text email. Returns True on success."""
    try:
        msg = MIMEMultipart()
        msg["From"] = config.EMAIL_FROM
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(config.EMAIL_FROM, to, msg.as_string())

        logger.info("Email sent to %s.", to)
        return True
    except Exception:
        logger.error("Email send failed.", exc_info=True)
        return False
