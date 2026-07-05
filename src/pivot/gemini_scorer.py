"""Optional Gemini scoring with strict fallback behavior."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from pivot.models import Job, RuleScore, ScoredJob
from pivot.scoring import scored_from_rules, threshold_for

LOGGER = logging.getLogger(__name__)


class GeminiScorer:
    """Score high-potential jobs with Gemini, falling back to rules."""

    def __init__(self, settings: dict[str, Any], profile: dict[str, Any], no_gemini: bool = False) -> None:
        gemini = settings.get("gemini", {})
        self.enabled = bool(gemini.get("enabled", True)) and not no_gemini
        self.model = gemini.get("model", "gemini-2.5-flash-lite")
        self.max_jobs = int(gemini.get("max_jobs_per_run", 5))
        self.min_rule_score = float(gemini.get("min_rule_score_before_gemini", 6))
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
            return [scored_from_rules(job, rule, self.settings, "rules_fallback") for job, rule in pairs]

        client = genai.Client(api_key=self.api_key)
        results: list[ScoredJob] = []
        gemini_used = 0
        for job, rule in pairs:
            if rule.score < self.min_rule_score or gemini_used >= self.max_jobs:
                results.append(scored_from_rules(job, rule, self.settings, "rules_fallback"))
                continue
            try:
                payload = self._score_one(client, job)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Gemini failed for %s %s: %s", job.company, job.title, exc)
                results.append(scored_from_rules(job, rule, self.settings, "rules_fallback"))
                continue
            gemini_used += 1
            final_score = float(payload.get("score", rule.score))
            threshold = threshold_for(job, self.settings, "gemini")
            results.append(
                ScoredJob(
                    job=job,
                    rule_score=rule.score,
                    final_score=final_score,
                    score_source="gemini",
                    fit_summary=str(payload.get("fit_summary", "")),
                    matched_strengths=list(payload.get("matched_strengths", [])),
                    concerns=list(payload.get("concerns", [])),
                    visa_assessment=str(payload.get("visa_assessment", "unknown")),
                    should_alert=bool(payload.get("should_alert", False))
                    and final_score >= threshold
                    and rule.is_candidate,
                )
            )
        return results

    def _score_one(self, client: Any, job: Job) -> dict[str, Any]:
        prompt = {
            "instruction": (
                "Be strict. Score this job for Darsh Tejusinghani. Prefer backend, systems, "
                "AI/ML infrastructure, platform, cloud, distributed systems, and ML systems. "
                "Penalize frontend-only, mobile-only, senior, advanced-degree-only, citizenship-required, "
                "or clearly no-sponsorship roles. Return only JSON with keys score, fit_summary, "
                "matched_strengths, concerns, visa_assessment, should_alert."
            ),
            "profile": self.profile,
            "job": job.model_dump(),
        }
        response = client.models.generate_content(
            model=self.model,
            contents=json.dumps(prompt),
            config={
                "response_mime_type": "application/json",
            },
        )
        text = getattr(response, "text", "") or "{}"
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("Gemini returned non-object JSON")
        return data
