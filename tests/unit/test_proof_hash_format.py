"""Tests for canonical karma-ta proofHash string format."""
from __future__ import annotations

import unittest

from trusted_agent_runtime.proof_hash_format import (
    assert_canonical_karma_proof_hash,
    is_canonical_karma_proof_hash,
    normalize_karma_proof_hash,
    validate_karma_proof_hash_for_create_bill,
)


class ProofHashFormatTests(unittest.TestCase):
    def test_valid_lowercase(self) -> None:
        h = "karma-ta:v1/sha256/" + "a" * 64
        self.assertTrue(is_canonical_karma_proof_hash(h))
        ok, msg = validate_karma_proof_hash_for_create_bill(h)
        self.assertTrue(ok, msg)

    def test_uppercase_tail_normalizes(self) -> None:
        tail = "A" * 64
        raw = "karma-ta:v1/sha256/" + tail
        # Public helper treats uppercase hex tail as acceptable and normalizes.
        self.assertTrue(is_canonical_karma_proof_hash(raw))
        out = assert_canonical_karma_proof_hash(raw)
        self.assertEqual(out, "karma-ta:v1/sha256/" + "a" * 64)

    def test_rejects_raw_bytes32(self) -> None:
        ok, msg = validate_karma_proof_hash_for_create_bill("0x" + "ab" * 32)
        self.assertFalse(ok)
        self.assertIn("bytes32", msg)

    def test_rejects_0x_on_tail(self) -> None:
        ok, msg = validate_karma_proof_hash_for_create_bill("karma-ta:v1/sha256/0x" + "ab" * 32)
        self.assertFalse(ok)
        self.assertIn("0x", msg)

    def test_rejects_whitespace(self) -> None:
        h = " karma-ta:v1/sha256/" + "c" * 64
        ok, _ = validate_karma_proof_hash_for_create_bill(h)
        self.assertFalse(ok)

    def test_rejects_wrong_length(self) -> None:
        ok, _ = validate_karma_proof_hash_for_create_bill("karma-ta:v1/sha256/" + "d" * 63)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
