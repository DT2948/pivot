"""Alert prioritization and delivery helpers."""

from __future__ import annotations

import html
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pivot.dedupe import job_key
from pivot.models import ScoredJob

GOOGLE = "google"
ACTIVE_TARGET_COMPANIES = {"google", "anthropic", "nvidia", "microsoft", "meta", "tesla"}
EMAIL_ENV_VARS = [
    "SMTP_HOST",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "ALERT_EMAIL_FROM",
    "ALERT_EMAIL_TO",
]


@dataclass(frozen=True)
class AlertRecord:
    """A scored alert plus delivery/debug metadata."""

    scored: ScoredJob
    priority_group: str
    was_seen_before: bool = False
    emailed: bool = False
    skip_reason: str | None = None


def priority_group(scored: ScoredJob) -> str:
    """Return the user-facing priority group for an alert."""

    job = scored.job
    company = _clean_company(job.company)
    is_google = company == GOOGLE
    is_target = company in ACTIVE_TARGET_COMPANIES
    if is_google:
        return "Google Priority"
    if is_target:
        return "Target Companies"
    return "Other Strong Matches"


def priority_rank(scored: ScoredJob) -> tuple[int, float]:
    """Sort Google/direct/target/curated matches before general curated roles."""

    job = scored.job
    company = _clean_company(job.company)
    source = _clean_company(job.source)
    is_google = company == GOOGLE
    is_target = company in ACTIVE_TARGET_COMPANIES
    is_direct = job.source_type == "target_company" and company == source
    if is_google and is_direct:
        group = 0
    elif is_google:
        group = 1
    elif is_target and is_direct:
        group = 2
    elif is_target:
        group = 3
    else:
        group = 4
    return (group, -scored.final_score)


def sort_alerts(scored_jobs: list[ScoredJob]) -> list[ScoredJob]:
    """Sort alert-worthy jobs by Darsh's current priority model."""

    return sorted(scored_jobs, key=priority_rank)


def build_alert_records(
    alert_worthy: list[ScoredJob],
    seen: dict[str, Any],
    emailed_keys: set[str] | None = None,
) -> list[AlertRecord]:
    """Build debug records for every alert-worthy candidate."""

    emailed_keys = emailed_keys or set()
    records: list[AlertRecord] = []
    for scored in sort_alerts(alert_worthy):
        key = job_key(scored.job)
        was_seen = key in seen
        emailed = key in emailed_keys
        skip_reason = None
        if was_seen and not emailed:
            skip_reason = "already_seen"
        elif not emailed:
            skip_reason = "not_emailed_this_run"
        records.append(
            AlertRecord(
                scored=scored,
                priority_group=priority_group(scored),
                was_seen_before=was_seen,
                emailed=emailed,
                skip_reason=skip_reason,
            )
        )
    return records


def records_to_debug(records: list[AlertRecord]) -> list[dict[str, Any]]:
    """Serialize alert records for data/last_run_alerts.json."""

    return [
        {
            "title": record.scored.job.title,
            "company": record.scored.job.company,
            "url": record.scored.job.url,
            "source": record.scored.job.source,
            "source_type": record.scored.job.source_type,
            "priority_group": record.priority_group,
            "final_score": record.scored.final_score,
            "should_alert": record.scored.should_alert,
            "was_seen_before": record.was_seen_before,
            "emailed": record.emailed,
            "skip_reason": record.skip_reason,
        }
        for record in records
    ]


def alert_subject(scored_jobs: list[ScoredJob]) -> str:
    """Build the alert subject using the highest-priority group present."""

    count = len(scored_jobs)
    if any(_clean_company(item.job.company) == GOOGLE for item in scored_jobs):
        return f"Pivot: {count} new Google-priority job alert(s)"
    if any(_clean_company(item.job.company) in ACTIVE_TARGET_COMPANIES for item in scored_jobs):
        return f"Pivot: {count} new target-company job alert(s)"
    return f"Pivot: {count} new strong job match(es)"


def email_config_present() -> bool:
    """Return true when required SMTP env vars are present, without exposing values."""

    return all(os.environ.get(name) for name in EMAIL_ENV_VARS)


def missing_email_config() -> list[str]:
    """Return missing required SMTP env var names."""

    return [name for name in EMAIL_ENV_VARS if not os.environ.get(name)]


def delivery_summary(
    *,
    total_candidates: int,
    alert_worthy_candidates_count: int,
    already_seen_alerts_count: int,
    new_alerts_to_email_count: int,
    alert_worthy: list[ScoredJob],
    email_send_attempted: bool,
    email_send_succeeded: bool,
) -> dict[str, Any]:
    """Return a log-safe delivery summary."""

    google_priority_alert_count = sum(
        1 for item in alert_worthy if _clean_company(item.job.company) == GOOGLE
    )
    target_company_alert_count = sum(
        1 for item in alert_worthy if _clean_company(item.job.company) in ACTIVE_TARGET_COMPANIES
    )
    curated_alert_count = sum(1 for item in alert_worthy if item.job.source_type == "curated_repo")
    return {
        "total_candidates": total_candidates,
        "alert_worthy_candidates_count": alert_worthy_candidates_count,
        "already_seen_alerts_count": already_seen_alerts_count,
        "new_alerts_to_email_count": new_alerts_to_email_count,
        "google_priority_alert_count": google_priority_alert_count,
        "target_company_alert_count": target_company_alert_count,
        "curated_alert_count": curated_alert_count,
        "email_config_present": email_config_present(),
        "email_send_attempted": email_send_attempted,
        "email_send_succeeded": email_send_succeeded,
    }


def run_timestamp() -> str:
    """Return a UTC timestamp for email/debug display."""

    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def badges(scored: ScoredJob) -> list[str]:
    """Return compact text labels for an alert card."""

    text = " ".join([scored.job.title, scored.job.description or "", " ".join(scored.rule_reasons)]).lower()
    labels = [priority_group(scored)]
    if _clean_company(scored.job.company) in ACTIVE_TARGET_COMPANIES:
        labels.append("Target Company")
    labels.append("Direct Source" if scored.job.source_type == "target_company" else "Curated Source")
    if "new-grad" in text or "new grad" in text or "university graduate" in text:
        labels.append("New Grad")
    if any(term in text for term in ["systems", "infrastructure", "platform", "distributed"]):
        labels.append("Systems/Infra")
    if any(term in text for term in ["ai/ml", "machine learning", " ml ", " ai "]):
        labels.append("AI/ML")
    if "compiler" in text:
        labels.append("Compiler")
    if "backend" in text or "back end" in text:
        labels.append("Backend")
    return list(dict.fromkeys(labels))


def top_reasons(scored: ScoredJob, limit: int = 6) -> list[str]:
    """Return the highest-signal match reasons for email cards."""

    reasons = scored.rule_reasons or scored.matched_strengths
    return [reason for reason in reasons if not reason.startswith("role_family:")][:limit]


def escape(value: object) -> str:
    """HTML-escape helper for email rendering."""

    return html.escape(str(value), quote=True)


def _clean_company(value: str) -> str:
    cleaned = value.lower()
    cleaned = cleaned.replace("??", "")
    return cleaned.strip()