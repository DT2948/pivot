"""SMTP email sending."""

from __future__ import annotations

import os
import smtplib
from collections.abc import Iterable
from email.message import EmailMessage

from pivot.alerts import (
    alert_subject,
    badges,
    escape,
    priority_group,
    run_timestamp,
    sort_alerts,
    top_reasons,
)
from pivot.models import ScoredJob, SourceHealth


def send_test_email() -> None:
    """Send one test email using environment SMTP settings."""

    msg = _base_message("Pivot test email")
    msg.set_content("Pivot SMTP settings are working.")
    _send(msg)


def send_alert_email(scored_jobs: list[ScoredJob], health: Iterable[SourceHealth]) -> None:
    """Send a readable multipart alert email for strong matches."""

    sorted_jobs = sort_alerts(scored_jobs)
    msg = _base_message(alert_subject(scored_jobs))
    timestamp = run_timestamp()
    msg.set_content(_plain_text_digest(sorted_jobs, health, timestamp))
    msg.add_alternative(_html_digest(sorted_jobs, health, timestamp), subtype="html")
    _send(msg)


def _plain_text_digest(
    scored_jobs: list[ScoredJob], health: Iterable[SourceHealth], timestamp: str
) -> str:
    lines = [
        "Pivot Job Alerts",
        f"Run: {timestamp}",
        f"New alerts: {len(scored_jobs)}",
        "",
    ]
    for group in ["Google Priority", "Target Companies", "Other Strong Matches"]:
        group_jobs = [item for item in scored_jobs if priority_group(item) == group]
        if not group_jobs:
            continue
        lines.extend([group, "=" * len(group)])
        for scored in group_jobs:
            job = scored.job
            reasons = ", ".join(top_reasons(scored)) or scored.fit_summary
            lines.extend(
                [
                    f"{job.company} - {job.title}",
                    f"Location: {job.location or 'Unknown'}",
                    f"Score: {scored.final_score} ({scored.score_source})",
                    f"Source: {job.source}",
                    f"Priority group: {group}",
                    f"Labels: {', '.join(badges(scored))}",
                    f"Why: {reasons}",
                    f"Apply: {job.url}",
                    "",
                ]
            )
    lines.append("Source health:")
    for item in health:
        status = item.status if not item.error else f"{item.status} ({item.error})"
        lines.append(
            f"- {item.source}: {item.fetched_count} fetched, {item.candidate_count} candidates, {status}"
        )
    return "\n".join(lines)


def _html_digest(scored_jobs: list[ScoredJob], health: Iterable[SourceHealth], timestamp: str) -> str:
    sections = []
    for group in ["Google Priority", "Target Companies", "Other Strong Matches"]:
        group_jobs = [item for item in scored_jobs if priority_group(item) == group]
        if not group_jobs:
            continue
        cards = "".join(_job_card(item, group) for item in group_jobs)
        sections.append(
            f"""
            <h2 style="font-size:18px;margin:28px 0 12px;color:#1f2937;">{escape(group)}</h2>
            {cards}
            """
        )
    health_items = "".join(
        f"<li><strong>{escape(item.source)}</strong>: {item.fetched_count} fetched, "
        f"{item.candidate_count} candidates, {escape(item.status if not item.error else item.status + ' - ' + item.error)}</li>"
        for item in health
    )
    return f"""
    <!doctype html>
    <html>
      <body style="margin:0;padding:0;background:#f6f7f9;font-family:Arial,Helvetica,sans-serif;color:#111827;">
        <div style="max-width:760px;margin:0 auto;padding:24px;">
          <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;padding:24px;">
            <h1 style="font-size:24px;line-height:1.25;margin:0 0 8px;color:#111827;">Pivot Job Alerts</h1>
            <p style="margin:0;color:#4b5563;font-size:14px;">Run: {escape(timestamp)}</p>
            <p style="margin:8px 0 0;color:#111827;font-size:15px;"><strong>{len(scored_jobs)}</strong> new alert(s)</p>
            {''.join(sections)}
            <h2 style="font-size:16px;margin:28px 0 8px;color:#1f2937;">Source Health</h2>
            <ul style="margin:0;padding-left:20px;color:#4b5563;font-size:13px;line-height:1.5;">{health_items}</ul>
          </div>
        </div>
      </body>
    </html>
    """


def _job_card(scored: ScoredJob, group: str) -> str:
    job = scored.job
    label_html = "".join(
        f"<span style=\"display:inline-block;margin:0 6px 6px 0;padding:3px 7px;border-radius:12px;background:#eef2ff;color:#3730a3;font-size:12px;\">{escape(label)}</span>"
        for label in badges(scored)
    )
    reasons = top_reasons(scored)
    reason_html = "".join(f"<li>{escape(reason)}</li>" for reason in reasons)
    if not reason_html:
        reason_html = f"<li>{escape(scored.fit_summary)}</li>"
    return f"""
    <div style="border:1px solid #d1d5db;border-radius:8px;padding:16px;margin:0 0 14px;background:#ffffff;">
      <div style="font-size:13px;color:#6b7280;margin-bottom:4px;">{escape(job.company)} - {escape(group)}</div>
      <h3 style="font-size:18px;line-height:1.3;margin:0 0 8px;color:#111827;">{escape(job.title)}</h3>
      <p style="margin:0 0 8px;color:#374151;font-size:14px;">{escape(job.location or 'Unknown location')}</p>
      <p style="margin:0 0 8px;color:#374151;font-size:14px;">Score: <strong>{scored.final_score}</strong> - Source: {escape(job.source)}</p>
      <div style="margin:8px 0;">{label_html}</div>
      <p style="margin:10px 0 4px;color:#111827;font-size:14px;"><strong>Why it matched</strong></p>
      <ul style="margin:0 0 12px;padding-left:20px;color:#374151;font-size:14px;line-height:1.45;">{reason_html}</ul>
      <a href="{escape(job.url)}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;padding:9px 12px;border-radius:6px;font-size:14px;">Apply</a>
    </div>
    """


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
