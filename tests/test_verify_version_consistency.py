"""Focused tests for the release version compatibility gate."""

from scripts.verify_version_consistency import _semver_lte


def test_semver_lte_is_fail_closed_for_valid_and_invalid_inputs():
    cases = [
        ("1.0.0", "1.0.20", True),
        ("1.0.20", "1.0.20", True),
        ("1.0.21", "1.0.20", False),
        ("banana", "1.0.20", False),
        ("1.x", "1.0.20", False),
        ("", "1.0.20", False),
        ("1.0.0", "banana", False),
    ]

    for left, right, expected in cases:
        assert _semver_lte(left, right) is expected, (left, right)
