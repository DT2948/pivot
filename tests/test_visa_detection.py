from __future__ import annotations

from pivot.verification import detect_visa_signal


def test_visa_detection_false() -> None:
    assert detect_visa_signal("We are unable to sponsor now or in the future.") == "false"


def test_visa_detection_true() -> None:
    assert detect_visa_signal("OPT accepted and immigration support available.") == "true"


def test_visa_detection_unknown() -> None:
    assert detect_visa_signal("Great backend engineering role.") == "unknown"
