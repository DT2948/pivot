from __future__ import annotations

from email.message import EmailMessage

from pivot import emailer


class FakeSMTP:
    instances: list[FakeSMTP] = []

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in = False
        self.sent = False
        FakeSMTP.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.logged_in = (username, password) == ("user", "pass")

    def send_message(self, msg: EmailMessage) -> None:
        self.sent = True


def set_email_env(monkeypatch, *, use_ssl: str | None, port: str) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", port)
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")
    monkeypatch.setenv("ALERT_EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("ALERT_EMAIL_TO", "to@example.com")
    if use_ssl is None:
        monkeypatch.delenv("SMTP_USE_SSL", raising=False)
    else:
        monkeypatch.setenv("SMTP_USE_SSL", use_ssl)


def test_send_uses_smtp_ssl_when_configured(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    FakeSMTP.instances = []
    set_email_env(monkeypatch, use_ssl="true", port="465")
    monkeypatch.setattr(emailer.smtplib, "SMTP_SSL", FakeSMTP)

    emailer.send_test_email()

    smtp = FakeSMTP.instances[0]
    assert smtp.host == "smtp.gmail.com"
    assert smtp.port == 465
    assert not smtp.started_tls
    assert smtp.logged_in
    assert smtp.sent


def test_send_uses_starttls_by_default(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    FakeSMTP.instances = []
    set_email_env(monkeypatch, use_ssl=None, port="587")
    monkeypatch.setattr(emailer.smtplib, "SMTP", FakeSMTP)

    emailer.send_test_email()

    smtp = FakeSMTP.instances[0]
    assert smtp.port == 587
    assert smtp.started_tls
    assert smtp.logged_in
    assert smtp.sent
