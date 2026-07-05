"""Text detection helpers for visa, citizenship, and role constraints."""

from __future__ import annotations

import re

NO_SPONSORSHIP_PATTERNS = [
    r"no\s+(?:visa\s+)?sponsorship",
    r"do(?:es)?\s+not\s+sponsor",
    r"unable\s+to\s+sponsor",
    r"will\s+not\s+sponsor",
    r"without\s+(?:the\s+need\s+for\s+)?sponsorship",
    r"must\s+not\s+require\s+sponsorship",
    r"no\s+cpt",
    r"no\s+opt",
    r"no\s+h-?1b",
]
SPONSORSHIP_POSITIVE_PATTERNS = [
    r"visa\s+sponsorship\s+(?:is\s+)?available",
    r"sponsorship\s+(?:is\s+)?available",
    r"h-?1b\s+sponsorship",
    r"cpt\s+accepted",
    r"opt\s+accepted",
    r"immigration\s+support",
    r"work\s+authorization\s+support",
]
CITIZEN_PATTERNS = [r"u\.?s\.?\s+citizenship\s+required", r"must\s+be\s+a\s+u\.?s\.?\s+citizen"]
CLEARANCE_PATTERNS = [r"active\s+security\s+clearance", r"security\s+clearance\s+required"]


def contains_any(text: str | None, patterns: list[str]) -> bool:
    """Return true when any regex pattern matches text."""

    haystack = text or ""
    return any(re.search(pattern, haystack, re.I) for pattern in patterns)


def detect_visa_signal(text: str | None) -> str:
    """Detect explicit visa sponsorship support or rejection."""

    if contains_any(text, CITIZEN_PATTERNS) or contains_any(text, CLEARANCE_PATTERNS):
        return "false"
    if contains_any(text, NO_SPONSORSHIP_PATTERNS):
        return "false"
    if contains_any(text, SPONSORSHIP_POSITIVE_PATTERNS):
        return "true"
    return "unknown"


def requires_us_citizenship(text: str | None) -> bool:
    """Detect U.S. citizenship requirements."""

    return contains_any(text, CITIZEN_PATTERNS)


def requires_security_clearance(text: str | None) -> bool:
    """Detect security clearance requirements."""

    return contains_any(text, CLEARANCE_PATTERNS)
