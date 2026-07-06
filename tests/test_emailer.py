from __future__ import annotations

from email.message import EmailMessage

from pivot import emailer
from pivot.models import Job, ScoredJob


class FakeSMTP:
    instances: list[FakeSMTP] = []

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in = False
        self.sent = False
        self.message: EmailMessage | None = None
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
        self.message = msg


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


def scored_job(company: str, url: str, *, source: str | None = None) -> ScoredJob:
    job = Job(
        source=source or company,
        source_type="target_company" if source is None else "curated_repo",
        source_priority=10,
        company=company,
        external_id=url,
        title="Software Engineer New Grad - Backend Infrastructure",
        location="New York, NY",
        url=url,
        description="Build backend infrastructure and AI/ML systems.",
    )
    return ScoredJob(
        job=job,
        rule_score=9.1,
        final_score=9.1,
        score_source="rules_fallback",
        fit_summary="Strong backend infrastructure fit.",
        matched_strengths=["software engineering", "backend"],
        concerns=[],
        visa_assessment="unknown",
        should_alert=True,
        rule_reasons=["software engineering", "new-grad", "backend", "infrastructure"],
    )


def test_alert_email_plain_text_contains_all_apply_links(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    FakeSMTP.instances = []
    set_email_env(monkeypatch, use_ssl=None, port="587")
    monkeypatch.setattr(emailer.smtplib, "SMTP", FakeSMTP)
    first = scored_job("Google", "https://google.example/apply")
    second = scored_job("Nuro", "https://nuro.example/apply", source="Simplify New Grad")

    emailer.send_alert_email([first, second], [])

    msg = FakeSMTP.instances[0].message
    assert msg is not None
    plain = msg.get_body(preferencelist=("plain",)).get_content()
    assert "https://google.example/apply" in plain
    assert "https://nuro.example/apply" in plain


def test_alert_email_html_contains_card_fields(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    FakeSMTP.instances = []
    set_email_env(monkeypatch, use_ssl=None, port="587")
    monkeypatch.setattr(emailer.smtplib, "SMTP", FakeSMTP)
    item = scored_job("Google", "https://google.example/apply")

    emailer.send_alert_email([item], [])

    msg = FakeSMTP.instances[0].message
    assert msg is not None
    html = msg.get_body(preferencelist=("html",)).get_content()
    assert "Google" in html
    assert "Software Engineer New Grad - Backend Infrastructure" in html
    assert "New York, NY" in html
    assert "9.1" in html
    assert "Direct Source" in html
    assert "backend" in html
    assert "https://google.example/apply" in html
