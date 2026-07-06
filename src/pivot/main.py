"""Command line entry point for Pivot."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from pivot.config import load_config
from pivot.dedupe import dedupe_jobs, job_key
from pivot.emailer import send_alert_email, send_test_email
from pivot.fetchers.apple import build_fetcher as build_apple_fetcher
from pivot.fetchers.base import Fetcher, PlaceholderFetcher
from pivot.fetchers.github_markdown import GitHubMarkdownAdapter, MarkdownSource
from pivot.fetchers.google import build_fetcher as build_google_fetcher
from pivot.fetchers.greenhouse import GreenhouseFetcher
from pivot.fetchers.meta import build_fetcher as build_meta_fetcher
from pivot.fetchers.microsoft import build_fetcher as build_microsoft_fetcher
from pivot.fetchers.tesla import build_fetcher as build_tesla_fetcher
from pivot.fetchers.workday import build_nvidia_fetcher
from pivot.filtering import score_job
from pivot.gemini_scorer import GeminiScorer
from pivot.logging_utils import configure_logging
from pivot.models import Job, RuleScore, ScoredJob, SourceHealth
from pivot.state import is_new_or_changed, load_seen, save_seen, update_seen

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Pivot job alerts")
    parser.add_argument(
        "--dry-run", action="store_true", help="Fetch and score without emailing/state updates"
    )
    parser.add_argument(
        "--send-test-email", action="store_true", help="Send one SMTP test email and exit"
    )
    parser.add_argument(
        "--max-gemini-jobs", type=int, default=None, help="Override Gemini jobs per run"
    )
    parser.add_argument("--no-gemini", action="store_true", help="Disable Gemini scoring")
    parser.add_argument("--config-dir", default="config", help="Config directory")
    parser.add_argument("--log-level", default="INFO", help="Python logging level")
    return parser.parse_args()


def main() -> int:
    """Run the Pivot CLI."""

    args = parse_args()
    configure_logging(args.log_level)
    if args.send_test_email:
        send_test_email()
        LOGGER.info("Sent Pivot test email")
        return 0

    config = load_config(args.config_dir)
    settings = config["settings"]
    if args.max_gemini_jobs is not None:
        settings.setdefault("gemini", {})["max_jobs_per_run"] = args.max_gemini_jobs

    jobs, health = fetch_all(build_fetchers(config["companies"]))
    jobs = dedupe_jobs(jobs)
    scored_pairs, rejections = filter_jobs(jobs, settings)
    for item in health:
        item.candidate_count = sum(1 for job, _ in scored_pairs if job.source == item.source)

    scorer = GeminiScorer(settings, config["profile"], no_gemini=args.no_gemini)
    scored = scorer.score(scored_pairs)
    seen_path = Path("data/seen_jobs.json")
    seen = load_seen(seen_path)
    alertable = [item for item in scored if item.should_alert and is_new_or_changed(seen, item)]

    write_debug(scored, rejections, health)
    print_summary(health, scored, rejections)

    if args.dry_run:
        LOGGER.info("Dry run complete; not sending email or updating seen state")
        return 0

    alerted_keys: set[str] = set()
    if alertable:
        send_alert_email(alertable, health)
        alerted_keys = {job_key(item.job) for item in alertable}
        LOGGER.info("Sent alert email for %s jobs", len(alertable))
    else:
        LOGGER.info("No new strong matches to email")
    save_seen(seen_path, update_seen(seen, scored, alerted_keys))
    return 0


def build_fetchers(companies: dict[str, Any]) -> list[Fetcher]:
    """Build fetchers from config."""

    fetchers: list[Fetcher] = []
    for item in companies.get("target_companies", []):
        if not item.get("enabled", False) and not item.get("best_effort", False):
            continue
        name = item["name"]
        kind = item.get("adapter")
        priority = int(item.get("source_priority", 40))
        if kind == "greenhouse":
            fetchers.append(GreenhouseFetcher(name, item["board_token"], source_priority=priority))
        elif name.lower() == "tesla":
            fetchers.append(build_tesla_fetcher(source_priority=priority))
        elif name.lower() == "nvidia":
            fetchers.append(build_nvidia_fetcher(source_priority=priority))
        elif name.lower() == "meta":
            fetchers.append(build_meta_fetcher(source_priority=priority))
        elif name.lower() == "microsoft":
            fetchers.append(build_microsoft_fetcher(source_priority=priority))
        elif name.lower() == "google":
            fetchers.append(build_google_fetcher(source_priority=priority))
        elif name.lower() == "apple":
            fetchers.append(build_apple_fetcher())
        else:
            fetchers.append(PlaceholderFetcher(name, f"adapter {kind!r} not implemented", priority))

    for item in companies.get("github_markdown_sources", []):
        if not item.get("enabled", False):
            continue
        fetchers.append(
            GitHubMarkdownAdapter(
                MarkdownSource(
                    name=item["name"],
                    raw_url=item["raw_url"],
                    source_priority=int(item.get("source_priority", 60)),
                    verify_original=bool(item.get("verify_original", False)),
                )
            )
        )
    return fetchers


def fetch_all(fetchers: list[Fetcher]) -> tuple[list[Job], list[SourceHealth]]:
    """Fetch all enabled sources."""

    jobs: list[Job] = []
    health: list[SourceHealth] = []
    for fetcher in fetchers:
        fetched, source_health = fetcher.safe_fetch()
        jobs.extend(fetched)
        health.append(source_health)
    return jobs, health


def filter_jobs(
    jobs: list[Job], settings: dict[str, Any]
) -> tuple[list[tuple[Job, RuleScore]], list[dict[str, Any]]]:
    """Run rule filtering and collect rejection debug entries."""

    candidates: list[tuple[Job, RuleScore]] = []
    rejections: list[dict[str, Any]] = []
    for job in jobs:
        rule = score_job(job, settings)
        if rule.is_candidate:
            candidates.append((job, rule))
        else:
            rejections.append(
                {
                    "company": job.company,
                    "title": job.title,
                    "location": job.location,
                    "url": job.url,
                    "source": job.source,
                    "rule_score": rule.score,
                    "rejection_reasons": rule.rejection_reasons,
                }
            )
    return candidates, rejections


def write_debug(
    scored: list[ScoredJob], rejections: list[dict[str, Any]], health: list[SourceHealth]
) -> None:
    """Write last-run debug JSON files."""

    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    candidates = [
        {
            "company": item.job.company,
            "title": item.job.title,
            "location": item.job.location,
            "url": item.job.url,
            "source": item.job.source,
            "rule_score": item.rule_score,
            "final_score": item.final_score,
            "score_source": item.score_source,
            "fit_summary": item.fit_summary,
            "should_alert": item.should_alert,
            "role_family": item.role_family,
            "requires_gemini_review": item.requires_gemini_review,
            "can_rule_alert": item.can_rule_alert,
            "rule_reasons": item.rule_reasons,
            "rejection_reasons": item.rejection_reasons,
        }
        for item in scored
    ]
    _write_json(data_dir / "last_run_candidates.json", candidates)
    _write_json(data_dir / "last_run_rejections.json", rejections)
    _write_json(data_dir / "last_run_source_health.json", [item.model_dump() for item in health])


def print_summary(
    health: list[SourceHealth], scored: list[ScoredJob], rejections: list[dict[str, Any]]
) -> None:
    """Print a human-readable run summary."""

    print("Source health:")
    for item in health:
        error = f", {item.error}" if item.error else ""
        print(
            f"- {item.source}: {item.fetched_count} fetched, {item.candidate_count} candidates, {item.status}{error}"
        )
    print(f"Candidates: {len(scored)}")
    print(f"Rejected: {len(rejections)}")
    print(f"Would alert: {sum(1 for item in scored if item.should_alert)}")


def _write_json(path: Path, value: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
