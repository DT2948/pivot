"""SMTP email sending."""

from __future__ import annotations

import os
import smtplib
from collections.abc import Iterable
from email.message import EmailMessage

from pivot.models import ScoredJob, SourceHealth


def send_test_email() -> None:
    """Send one test email using environment SMTP settings."""

    msg = _base_message("Pivot test email")
    msg.set_content("Pivot SMTP settings are working.")
    _send(msg)


def send_alert_email(scored_jobs: list[ScoredJob], health: Iterable[SourceHealth]) -> None:
    """Send alert email for strong matches."""

    msg = _base_message(f"New strong SWE matches from Pivot: {len(scored_jobs)}")
    lines: list[str] = []
    for scored in scored_jobs:
        job = scored.job
        lines.extend(
            [
                f"{job.company} - {job.title}",
                f"Location: {job.location or 'Unknown'}",
                f"Source: {job.source}",
                f"Score: {scored.final_score} ({scored.score_source})",
                f"Fit: {scored.fit_summary}",
                f"Matched strengths: {', '.join(scored.matched_strengths) or 'None listed'}",
                f"Concerns: {', '.join(scored.concerns) or 'None listed'}",
                f"Visa: {scored.visa_assessment}",
                f"URL: {job.url}",
                "",
            ]
        )
    lines.append("Source health:")
    for item in health:
        status = item.status if not item.error else f"{item.status} ({item.error})"
        lines.append(
            f"- {item.source}: {item.fetched_count} fetched, {item.candidate_count} candidates, {status}"
        )
    msg.set_content("\n".join(lines))
    _send(msg)


def _base_message(subject: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = _required_env("ALERT_EMAIL_FROM")
    msg["To"] = _required_env("ALERT_EMAIL_TO")
    return msg


def _send(msg: EmailMessage) -> None:
    host = _required_env("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = _required_env("SMTP_USERNAME")
    password = _required_env("SMTP_PASSWORD")
    use_ssl = _env_bool("SMTP_USE_SSL")

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
            smtp.login(username, password)
            smtp.send_message(msg)
        return

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(msg)


def _env_bool(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required email environment variable: {name}")
    return value
