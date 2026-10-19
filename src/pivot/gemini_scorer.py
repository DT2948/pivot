"""Optional Gemini scoring with strict fallback behavior."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from pathlib import Path
from typing import Any

from pivot.dedupe import dedupe_jobs, job_key
from pivot.models import Job, RuleScore, ScoredJob
from pivot.scoring import final_alert_allowed, scored_from_rules, threshold_for
from pivot.state import is_new_or_changed
from pivot.targets import ACTIVE_TARGET_COMPANIES

LOGGER = logging.getLogger(__name__)
SCORING_CONTEXT_FILES = tuple(
    Path(__file__).with_name(name)
    for name in ("gemini_scorer.py", "filtering.py", "scoring.py", "verification.py", "targets.py")
)


class GeminiScorer:
    """Score high-potential jobs with Gemini, falling back to rules."""

    def __init__(
        self, settings: dict[str, Any], profile: dict[str, Any], no_gemini: bool = False
    ) -> None:
        gemini = settings.get("gemini", {})
        self.enabled = bool(gemini.get("enabled", True)) and not no_gemini
        self.model = gemini.get("model", "gemini-2.5-flash-lite")
        self.max_jobs = int(gemini.get("max_jobs_per_run", 2))
        self.min_rule_score = float(gemini.get("min_rule_score_before_gemini", 6))
        self.curated_min_rule_score = float(gemini.get("curated_min_rule_score_before_gemini", 5))
        self.max_unavailable_failures = int(gemini.get("max_unavailable_failures", 2))
        self.settings = settings
        self.profile = profile
        self.seen: dict[str, Any] = {}
        # Automatically invalidate prompt/rule edits without a manual version bump.
        # Normalize line endings so Windows and Actions produce the same signature.
        self.scoring_code_signature = hashlib.sha256(
            json.dumps(
                {path.name: path.read_text(encoding="utf-8") for path in SCORING_CONTEXT_FILES},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        self.api_key = os.environ.get("GEMINI_API_KEY")

    def score(self, pairs: list[tuple[Job, RuleScore]]) -> list[ScoredJob]:
        """Score jobs, using Gemini for a capped subset if configured."""

        unique_jobs = dedupe_jobs([job for job, _ in pairs])
        rules = {id(job): rule for job, rule in pairs}
        pairs = [(job, rules[id(job)]) for job in unique_jobs]
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
            if (
                not rule.is_candidate
                or rule.rejection_reasons
                or rule.role_family
                in {"sales", "legal", "finance", "product_management", "support"}
                or (
                    rule.role_family == "fellowship_program"
                    and not self.settings.get("allow_fellowship_alerts", False)
                )
            ):
                results.append(scored_from_rules(job, rule, self.settings, "rules_fallback"))
                continue
            cache = (self.seen.get(job_key(job)) or {}).get("assessment_cache")
            if isinstance(cache, dict) and cache.get("signature") == self._assessment_signature(
                job
            ):
                try:
                    validate_payload(cache["payload"])
                    score = normalize_gemini_score(cache["payload"].get("score"))
                    reused = self._scored_from_gemini(job, rule, cache["payload"], score)
                    reused.assessment_cache = cache
                    results.append(reused)
                    continue
                except (ValueError, KeyError, TypeError):
                    pass
            previous = scored_from_rules(job, rule, self.settings, "rules_fallback")
            if not is_new_or_changed(self.seen, previous):
                results.append(previous)
                continue
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
                validate_payload(payload)
                final_score = normalize_gemini_score(payload.get("score"))
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(
                    "Gemini returned invalid score for %s %s: %s", job.company, job.title, exc
                )
                results.append(scored_from_rules(job, rule, self.settings, "rules_fallback"))
                continue

            unavailable_failures = 0
            assessed = self._scored_from_gemini(job, rule, payload, final_score)
            assessed.assessment_cache = {
                "signature": self._assessment_signature(job),
                "payload": payload,
            }
            results.append(assessed)

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
        company = job.company.strip().lower()
        group = 0 if company == "google" else 1 if company in ACTIVE_TARGET_COMPANIES else 2
        return (-int(rule.requires_gemini_review), group, -rule.score, job.source_priority)

    def _assessment_signature(self, job: Job) -> str:
        # Include scoring context; raw ATS metadata and timestamps do not affect fit.
        content = {
            "version": 3,
            "scoring_code": self.scoring_code_signature,
            "model": self.model,
            "profile": self.profile,
            "settings": self.settings,
            "job": job.model_dump(exclude={"raw", "posted_at", "updated_at"}),
        }
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    def _min_rule_score_for(self, job: Job) -> float:
        if job.source_type == "curated_repo":
            return self.curated_min_rule_score
        return self.min_rule_score

    def _score_one(self, client: Any, job: Job) -> dict[str, Any]:
        prompt = {
            "instruction": (
                "Return JSON only with keys score, fit_summary, matched_strengths, concerns, "
                "visa_assessment, should_alert. Score actual engineering responsibilities and "
                "bachelor's-level eligibility, not keyword counts or employer prestige. "
                "Use 0-10 only: 9-10 exceptional undergraduate-eligible fit, 8-8.9 strong, "
                "7-7.9 good, 5-6.9 partial, below 5 weak. Never use percentages. "
                "Backend/systems/infrastructure SWE and ML systems/AI infrastructure are "
                "equally important. Excellent general new-grad SWE (including Google University "
                "Graduate and Microsoft SWE I) remains highly desirable without ML keywords. "
                "Value distributed systems, databases/storage, cloud/platform, observability, "
                "training/inference serving, compilers/runtimes, GPU software and performance. "
                "Interests are learning directions, not demonstrated professional expertise. "
                "Graph ML research is experience, not a required career specialization. "
                "Assess research engineering, forward deployed, full-stack, MLE, GPU drivers and "
                "SRE individually by implementation depth and qualifications. Meaningful backend "
                "full-stack work is welcome. Lower frontend/mobile-only and routine UI fit. "
                "Reject advanced-degree-only, excessive experience/seniority, hardware-only, "
                "non-engineering and non-US roles regardless of company. Bachelor's alongside "
                "Master's/PhD is eligible; research scientist/PhD-only is not. "
                "Company/referral priority affects review allocation and presentation, never "
                "technical score; target employers do not automatically earn 9+. "
                "Follow sponsorship_policy below; accurately preserve restrictions in concerns "
                "and visa_assessment and never claim sponsorship without evidence."
            ),
            "sponsorship_policy": (
                "Direct active target: do not reject or penalize solely for visa, sponsorship, "
                "citizenship or clearance restrictions. This visibility preference is not proof "
                "of eligibility. Preserve original requirements."
                if job.source_type == "target_company"
                and job.company.lower() in ACTIVE_TARGET_COMPANIES
                else "Apply citizenship, clearance and explicit no-sponsorship restrictions. "
                "Unknown sponsorship is a concern, not automatic rejection."
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


def validate_payload(payload: Any) -> None:
    """Only complete, typed assessments can be used or persisted for reuse."""
    if not isinstance(payload, dict):
        raise ValueError("Gemini returned non-object JSON")
    if not isinstance(payload.get("should_alert"), bool):
        raise ValueError("Gemini should_alert must be boolean")
    for key in ("fit_summary", "visa_assessment"):
        if not isinstance(payload.get(key), str):
            raise ValueError(f"Gemini {key} must be text")
    for key in ("matched_strengths", "concerns"):
        value = payload.get(key)
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ValueError(f"Gemini {key} must be a text list")


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
