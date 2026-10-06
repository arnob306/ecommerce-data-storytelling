"""
Email delivery for the weekly report.

Settings come from environment variables (kept in .env, never in git). Errors
never include the password or the underlying server message.
"""

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Mapping, Optional

logger = logging.getLogger(__name__)

SSL_PORT = 465
TIMEOUT_SECONDS = 30
REQUIRED_VARS = (
    'SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASSWORD', 'REPORT_TO',
)


class DeliveryError(RuntimeError):
    """Raised when email settings are missing or sending fails."""


@dataclass(frozen=True)
class EmailSettings:
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    recipient: str

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> 'EmailSettings':
        """Read settings, failing closed if anything is missing."""
        env = os.environ if env is None else env
        for name in REQUIRED_VARS:
            if not env.get(name):
                raise DeliveryError(f'{name} is not set (put it in .env).')
        try:
            port = int(env['SMTP_PORT'])
        except ValueError:
            raise DeliveryError('SMTP_PORT must be a number.') from None
        if '@' not in env['REPORT_TO']:
            raise DeliveryError('REPORT_TO must be an email address.')
        return cls(env['SMTP_HOST'], port, env['SMTP_USER'],
                   env['SMTP_PASSWORD'], env['REPORT_TO'])


def build_message(
    subject: str, text: str, html: str, settings: EmailSettings
) -> EmailMessage:
    """A multipart email with plain-text and HTML versions."""
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = settings.user
    message['To'] = settings.recipient
    message.set_content(text)
    message.add_alternative(html, subtype='html')
    return message


def send_email(
    settings: EmailSettings,
    message: EmailMessage,
    smtp_factory=smtplib.SMTP,
    ssl_factory=smtplib.SMTP_SSL,
) -> None:
    """Send ``message``; raises DeliveryError without leaking secrets."""
    try:
        if settings.port == SSL_PORT:
            with ssl_factory(settings.host, settings.port,
                             timeout=TIMEOUT_SECONDS) as server:
                server.login(settings.user, settings.password)
                server.send_message(message)
        else:
            with smtp_factory(settings.host, settings.port,
                              timeout=TIMEOUT_SECONDS) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(settings.user, settings.password)
                server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        logger.error('Email sending failed: %s', type(exc).__name__)
        raise DeliveryError(
            f'Could not send the email ({type(exc).__name__}). '
            'Check the SMTP settings.'
        ) from None
    logger.info('Weekly report emailed')
