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
            from google import genai
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("google-genai unavailable, using rules fallback: %s", exc)
            return [
                scored_from_rules(job, rule, self.settings, "rules_fallback") for job, rule in pairs
            ]

        client = genai.Client(api_key=self.api_key)
        results: list[ScoredJob] = []
        gemini_used = 0
        for job, rule in sorted(pairs, key=self._gemini_sort_key):
            if rule.score < self._min_rule_score_for(job) or gemini_used >= self.max_jobs:
                results.append(scored_from_rules(job, rule, self.settings, "rules_fallback"))
                continue
            try:
                payload = self._score_one(client, job)
                final_score = normalize_gemini_score(payload.get("score"))
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Gemini failed for %s %s: %s", job.company, job.title, exc)
                results.append(scored_from_rules(job, rule, self.settings, "rules_fallback"))
                continue
            gemini_used += 1
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
            results.append(
                ScoredJob(
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
            )
        return results

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
