"""Pydantic models used throughout Pivot."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Signal = Literal["true", "false", "unknown"]
VerificationStatus = Literal["verified", "unverified", "failed", "not_required"]


class Job(BaseModel):
    """A normalized job listing from any source."""

    source: str
    source_type: str
    source_priority: int = 50
    company: str
    external_id: str
    title: str
    location: str | None = None
    url: str
    department: str | None = None
    description: str | None = None
    posted_at: str | None = None
    updated_at: str | None = None
    raw: dict = Field(default_factory=dict)
    repo_flags: list[str] = Field(default_factory=list)
    repo_sponsorship_flag: str | None = None
    verified_sponsorship_signal: Signal = "unknown"
    new_grad_signal: Signal = "unknown"
    visa_signal: Signal = "unknown"
    verification_status: VerificationStatus = "not_required"


class RuleScore(BaseModel):
    """Deterministic pre-Gemini score and filtering result."""

    score: float
    reasons: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    is_candidate: bool

    requires_gemini_review: bool = False
    can_rule_alert: bool = True
    role_family: str = "unknown"


class ScoredJob(BaseModel):
    """Final job score after rules or Gemini."""

    job: Job
    rule_score: float
    final_score: float
    score_source: str
    fit_summary: str
    matched_strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    visa_assessment: str
    should_alert: bool

    requires_gemini_review: bool = False
    can_rule_alert: bool = True
    role_family: str = "unknown"
    rule_reasons: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)


class SourceHealth(BaseModel):
    """Per-source health information for a run."""

    source: str
    source_type: str
    status: Literal["success", "partial", "failed", "skipped", "not_implemented"]
    fetched_count: int = 0
    candidate_count: int = 0
    error: str | None = None
