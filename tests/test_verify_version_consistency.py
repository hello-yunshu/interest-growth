"""Focused tests for the release version consistency gate."""


def test_current_version_consistency_requires_current_client_version():
    from scripts import verify_version_consistency

    assert verify_version_consistency.main() == 0
