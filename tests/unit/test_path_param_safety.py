"""Tests for URL segment validation on public API paths."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.path_param_safety import validate_public_url_segment


def test_validate_public_url_segment_accepts_common_ids():
    assert validate_public_url_segment("task_id", "task-1") == "task-1"
    assert validate_public_url_segment("task_id", "p2.bundle.test") == "p2.bundle.test"


def test_validate_public_url_segment_rejects_injection_like_chars():
    with pytest.raises(HTTPException) as exc:
        validate_public_url_segment("task_id", "a/b")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException):
        validate_public_url_segment("task_id", "x" * 300)
