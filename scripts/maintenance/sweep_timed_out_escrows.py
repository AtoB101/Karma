#!/usr/bin/env python3
"""Sweep timed-out escrow orders to refund (cron-friendly, P2-8)."""
from __future__ import annotations

import sys


def _main() -> int:
    from config.settings import settings
    from services.miniapp_commerce.timeout_sweep import sweep_timed_out_escrows

    if not settings.escrow_timeout_sweep_enabled:
        print("SKIP escrow_timeout_sweep_enabled=false")
        return 0
    result = sweep_timed_out_escrows()
    print(
        f"OK refunded_count={len(result['refunded'])} "
        f"skipped_disputed={result.get('skipped_disputed', 0)} scanned={result.get('scanned', 0)}"
    )
    for order_id in result["refunded"]:
        print(f"  refunded: {order_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
