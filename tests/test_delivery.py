import smtplib

import pytest

from src.reports.delivery import (
    DeliveryError,
    EmailSettings,
    build_message,
    send_email,
)

ENV = {
    'SMTP_HOST': 'smtp.example.com',
    'SMTP_PORT': '587',
    'SMTP_USER': 'sender@example.com',
    'SMTP_PASSWORD': 'app-password-123',
    'REPORT_TO': 'mum@example.com',
}


class FakeSMTP:
    """Records what the sender does instead of touching the network."""

    instances = []

    def __init__(self, host, port, **kwargs):
        self.host, self.port = host, port
        self.calls = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, **kwargs):
        self.calls.append('starttls')

    def login(self, user, password):
        self.calls.append(('login', user))

    def send_message(self, message):
        self.calls.append(('send', message['To']))


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeSMTP.instances.clear()


@pytest.fixture
def settings(monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    return EmailSettings.from_env()


def test_settings_are_read_from_the_environment(settings):
    assert settings.host == 'smtp.example.com'
    assert settings.port == 587
    assert settings.recipient == 'mum@example.com'


def test_password_is_not_shown_in_the_repr(settings):
    assert 'app-password-123' not in repr(settings)


@pytest.mark.parametrize('missing', list(ENV))
def test_missing_settings_fail_closed(monkeypatch, missing):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv(missing)
    with pytest.raises(DeliveryError, match=missing):
        EmailSettings.from_env()


def test_message_has_text_and_html_versions(settings):
    message = build_message('Weekly', 'plain body', '<p>html body</p>', settings)
    assert message['Subject'] == 'Weekly'
    assert message['To'] == 'mum@example.com'
    assert message['From'] == 'sender@example.com'
    kinds = {part.get_content_type() for part in message.iter_parts()}
    assert kinds == {'text/plain', 'text/html'}


def test_send_uses_starttls_logs_in_and_sends_once(settings):
    message = build_message('Weekly', 'plain', '<p>x</p>', settings)
    send_email(settings, message, smtp_factory=FakeSMTP)
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ('smtp.example.com', 587)
    assert smtp.calls == [
        'starttls', ('login', 'sender@example.com'), ('send', 'mum@example.com'),
    ]


def test_port_465_skips_starttls(monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv('SMTP_PORT', '465')
    settings = EmailSettings.from_env()
    message = build_message('Weekly', 'plain', '<p>x</p>', settings)
    send_email(settings, message, smtp_factory=FakeSMTP, ssl_factory=FakeSMTP)
    assert 'starttls' not in FakeSMTP.instances[0].calls


def test_network_failures_become_delivery_errors_without_the_password(settings):
    class Broken(FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b'bad credentials')

    message = build_message('Weekly', 'plain', '<p>x</p>', settings)
    with pytest.raises(DeliveryError) as info:
        send_email(settings, message, smtp_factory=Broken)
    assert 'app-password-123' not in str(info.value)
