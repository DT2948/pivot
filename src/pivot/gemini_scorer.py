"""Optional Gemini scoring with strict fallback behavior."""

from __future__ import annotations

import json
import logging
import math
import os
from typing import Any

from pivot.models import Job, RuleScore, ScoredJob
from pivot.scoring import final_alert_allowed, scored_from_rules, threshold_for

LOGGER = logging.getLogger(__name__)


class GeminiScorer:
    """Score high-potential jobs with Gemini, falling back to rules."""

    def __init__(
        self, settings: dict[str, Any], profile: dict[str, Any], no_gemini: bool = False
    ) -> None:
        gemini = settings.get("gemini", {})
        self.enabled = bool(gemini.get("enabled", True)) and not no_gemini
        self.model = gemini.get("model", "gemini-2.5-flash-lite")
        self.max_jobs = int(gemini.get("max_jobs_per_run", 5))
        self.min_rule_score = float(gemini.get("min_rule_score_before_gemini", 6))
        self.curated_min_rule_score = float(gemini.get("curated_min_rule_score_before_gemini", 5))
        self.max_unavailable_failures = int(gemini.get("max_unavailable_failures", 2))
        self.settings = settings
        self.profile = profile
        self.api_key = os.environ.get("GEMINI_API_KEY")

    def score(self, pairs: list[tuple[Job, RuleScore]]) -> list[ScoredJob]:
        """Score jobs, using Gemini for a capped subset if configured."""

        if not self.enabled or not self.api_key:
            reason = "rules_only" if not self.enabled else "rules_fallback"
            if self.enabled and not self.api_key:
                LOGGER.info("GEMINI_API_KEY missing; using rule-only fallback")
            return [scored_from_rules(job, rule, self.settings, reason) for job, rule in pairs]

        try:
            client = self._build_client()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("google-genai unavailable, using rules fallback: %s", exc)
            return [
                scored_from_rules(job, rule, self.settings, "rules_fallback") for job, rule in pairs
            ]

        ordered_pairs = sorted(pairs, key=self._gemini_sort_key)
        results: list[ScoredJob] = []
        attempts = 0
        unavailable_failures = 0
        stop_gemini = False
        stop_reason: str | None = None
        LOGGER.info("Gemini scoring capped at %s attempts", self.max_jobs)

        for job, rule in ordered_pairs:
            if rule.score < self._min_rule_score_for(job):
                results.append(scored_from_rules(job, rule, self.settings, "rules_fallback"))
                continue
            if stop_gemini:
                results.append(scored_from_rules(job, rule, self.settings, "rules_fallback"))
                continue
            if attempts >= self.max_jobs:
                stop_gemini = True
                stop_reason = f"Gemini scoring capped at {self.max_jobs} attempts"
                LOGGER.info(stop_reason)
                results.append(scored_from_rules(job, rule, self.settings, "rules_fallback"))
                continue

            payload: dict[str, Any] | None = None
            while attempts < self.max_jobs:
                attempts += 1
                try:
                    payload = self._score_one(client, job)
                    break
                except Exception as exc:  # noqa: BLE001
                    message = str(exc)
                    LOGGER.warning(
                        "Gemini attempt %s/%s failed for %s %s: %s",
                        attempts,
                        self.max_jobs,
                        job.company,
                        job.title,
                        message,
                    )
                    if _is_quota_exhausted(message):
                        stop_gemini = True
                        stop_reason = "Stopping Gemini scoring after quota exhaustion"
                        LOGGER.warning(stop_reason)
                        break
                    if _is_unavailable(message):
                        unavailable_failures += 1
                        if unavailable_failures >= self.max_unavailable_failures:
                            stop_gemini = True
                            stop_reason = "Gemini unavailable; remaining required-Gemini candidates will not alert"
                            LOGGER.warning(stop_reason)
                            break
                        if attempts < self.max_jobs:
                            LOGGER.info("Retrying Gemini once after 503/unavailable response")
                            continue
                    break
            if payload is None:
                results.append(scored_from_rules(job, rule, self.settings, "rules_fallback"))
                continue

            try:
                final_score = normalize_gemini_score(payload.get("score"))
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(
                    "Gemini returned invalid score for %s %s: %s", job.company, job.title, exc
                )
                results.append(scored_from_rules(job, rule, self.settings, "rules_fallback"))
                continue

            unavailable_failures = 0
            results.append(self._scored_from_gemini(job, rule, payload, final_score))

        if stop_reason:
            LOGGER.info("%s; remaining candidates used safe rule fallback", stop_reason)
        return results

    def _build_client(self) -> Any:
        from google import genai

        return genai.Client(api_key=self.api_key)

    def _scored_from_gemini(
        self, job: Job, rule: RuleScore, payload: dict[str, Any], final_score: float
    ) -> ScoredJob:
        threshold = threshold_for(job, self.settings, "gemini")
        fit_summary = str(payload.get("fit_summary", ""))
        concerns = [str(item) for item in payload.get("concerns", [])]
        visa_assessment = str(payload.get("visa_assessment", "unknown"))
        gemini_text = " ".join([fit_summary, visa_assessment, " ".join(concerns)])
        gate_allowed, final_rejections = final_alert_allowed(
            job,
            rule,
            self.settings,
            score_source="gemini",
            gemini_valid=True,
            gemini_text=gemini_text,
        )
        should_alert = (
            bool(payload.get("should_alert", False))
            and final_score >= threshold
            and rule.is_candidate
            and gate_allowed
        )
        return ScoredJob(
            job=job,
            rule_score=rule.score,
            final_score=final_score,
            score_source="gemini",
            fit_summary=fit_summary,
            matched_strengths=list(payload.get("matched_strengths", [])),
            concerns=concerns + final_rejections,
            visa_assessment=visa_assessment,
            should_alert=should_alert,
            requires_gemini_review=rule.requires_gemini_review,
            can_rule_alert=rule.can_rule_alert,
            role_family=rule.role_family,
            rule_reasons=rule.reasons,
            rejection_reasons=final_rejections,
        )

    @staticmethod
    def _gemini_sort_key(pair: tuple[Job, RuleScore]) -> tuple[int, int, float, int]:
        job, rule = pair
        curated_new_grad = int(
            job.source_type == "curated_repo"
            and any("new-grad" in reason for reason in rule.reasons)
        )
        return (
            -int(rule.requires_gemini_review),
            job.source_priority,
            -rule.score,
            -curated_new_grad,
        )

    def _min_rule_score_for(self, job: Job) -> float:
        if job.source_type == "curated_repo":
            return self.curated_min_rule_score
        return self.min_rule_score

    def _score_one(self, client: Any, job: Job) -> dict[str, Any]:
        prompt = {
            "instruction": (
                "Return JSON only. The `score` field must be a number from 0.0 to 10.0. "
                "Do not use percentages. Do not use 20, 30, 40, 80, 85, 90, or any score "
                "above 10. 10 means near-perfect fit. 7 means good fit. 5 means maybe "
                "worth reviewing. Below 5 means weak fit. Be strict. Score this job for "
                "Darsh Tejusinghani. Prefer backend, systems, AI/ML infrastructure, platform, "
                "cloud, distributed systems, and ML systems. Penalize frontend-only, mobile-only, "
                "senior, advanced-degree-only, citizenship-required, sales, legal, finance, "
                "support, fellowship/program, ambiguous security, and clearly no-sponsorship roles. "
                "Unknown sponsorship is a concern, not automatic rejection. Return only JSON with "
                "keys score, fit_summary, matched_strengths, concerns, visa_assessment, should_alert."
            ),
            "profile": self.profile,
            "job": job.model_dump(),
        }
        response = client.models.generate_content(
            model=self.model,
            contents=json.dumps(prompt),
            config={"response_mime_type": "application/json"},
        )
        text = getattr(response, "text", "") or "{}"
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("Gemini returned non-object JSON")
        return data


def normalize_gemini_score(value: Any) -> float:
    """Validate and normalize a Gemini score to Pivot's 0-10 scale."""

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Gemini score is missing or not numeric")
    score = float(value)
    if math.isnan(score) or math.isinf(score):
        raise ValueError("Gemini score is NaN or infinite")
    if 10 < score <= 100:
        LOGGER.warning(
            "Gemini returned percent-like score %.2f; normalizing by dividing by 10", score
        )
        score = score / 10
    if 0 <= score <= 10:
        return round(score, 2)
    LOGGER.warning("Gemini score %.2f is outside 0-10 after normalization", score)
    raise ValueError("Gemini score outside 0-10 scale")


def _is_quota_exhausted(message: str) -> bool:
    upper = message.upper()
    return "429" in upper or "RESOURCE_EXHAUSTED" in upper or "QUOTA" in upper


def _is_unavailable(message: str) -> bool:
    upper = message.upper()
    return "503" in upper or "UNAVAILABLE" in upper
