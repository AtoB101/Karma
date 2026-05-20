"""
MVVS V1 Week 3 — Scene 2 (Data Service) + Scene 3 (AI Content) Auto-Verify Tests
"""

import pytest
from core.mvvs_schemas import DataServiceEvidence, AiContentEvidence


class TestDataServiceAutoVerify:
    def test_has_data_passes_to_review(self):
        """Data services always go to review (require buyer confirmation)."""
        dse = DataServiceEvidence(
            data_file_hash="a" * 64,
            row_count=1000,
            column_count=10,
            delivery_uri="https://storage.example.com/data.csv",
        )
        assert dse.auto_verdict() == "review"

    def test_no_file_fails(self):
        dse = DataServiceEvidence()
        assert dse.auto_verdict() == "fail"

    def test_zero_rows_fails(self):
        dse = DataServiceEvidence(
            data_file_hash="a" * 64,
            row_count=0,
        )
        assert dse.auto_verdict() == "fail"

    def test_revision_exceeded_fails(self):
        dse = DataServiceEvidence(
            data_file_hash="a" * 64,
            row_count=100,
            revision_count=2,
            max_revisions=1,
        )
        assert dse.auto_verdict() == "fail"

    def test_default_revision_limits(self):
        dse = DataServiceEvidence(
            data_file_hash="a" * 64,
            row_count=100,
        )
        assert dse.max_revisions == 1
        assert dse.revision_count == 0


class TestAiContentAutoVerify:
    def test_text_content_review(self):
        """AI content always goes to review (subjective quality)."""
        ace = AiContentEvidence(
            output_file_hash="a" * 64,
            output_format="md",
            word_count=500,
            delivery_uri="https://storage.example.com/article.md",
        )
        assert ace.auto_verdict() == "review"

    def test_empty_file_fails(self):
        ace = AiContentEvidence(
            output_file_hash="a" * 64,
            file_size=0,
            word_count=0,
            code_lines=0,
            page_count=0,
        )
        assert ace.auto_verdict() == "fail"

    def test_no_delivery_fails(self):
        ace = AiContentEvidence()
        assert ace.auto_verdict() == "fail"

    def test_revision_exceeded_fails(self):
        ace = AiContentEvidence(
            output_file_hash="a" * 64,
            output_format="py",
            code_lines=100,
            revision_count=3,
            max_revisions=2,
        )
        assert ace.auto_verdict() == "fail"

    def test_image_content(self):
        ace = AiContentEvidence(
            output_file_hash="b" * 64,
            output_format="jpg",
            resolution="1920x1080",
            file_size=1024000,
        )
        assert ace.auto_verdict() == "review"

    def test_video_content(self):
        ace = AiContentEvidence(
            output_file_hash="c" * 64,
            output_format="mp4",
            duration_seconds=120,
            resolution="1920x1080",
            file_size=50000000,
        )
        assert ace.auto_verdict() == "review"

    def test_code_content(self):
        ace = AiContentEvidence(
            output_file_hash="d" * 64,
            output_format="py",
            code_lines=500,
            file_size=15000,
        )
        assert ace.auto_verdict() == "review"
