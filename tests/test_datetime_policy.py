"""P2: ensure trusted_agent_runtime avoids deprecated naive UTC helpers."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


class TestDatetimePolicy(unittest.TestCase):
    def test_no_datetime_utcnow_in_trusted_agent_runtime(self) -> None:
        root = Path(__file__).resolve().parents[1] / "trusted_agent_runtime"
        pattern = re.compile(r"\butcnow\s*\(")
        hits: list[str] = []
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                hits.append(str(path.relative_to(root.parent)))
        self.assertEqual(
            hits,
            [],
            "Remove datetime.utcnow(); use datetime.now(timezone.utc) or explicit tzinfo=timezone.utc",
        )


if __name__ == "__main__":
    unittest.main()
