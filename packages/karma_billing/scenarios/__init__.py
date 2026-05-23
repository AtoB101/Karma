"""Karma Billing Scenarios — pre-registered scenario configurations.

Importing this package automatically registers:
- S1: Single Delegation (full implementation)
- S2: Bidding / Auction (skeleton)
- S3: Pipeline (skeleton)
- S5: Data Marketplace (skeleton)
- S8: Dispute Resolution (skeleton)
"""

from packages.karma_billing.scenarios.s1_delegation import register as _register_s1
from packages.karma_billing.scenarios.s2_bidding import register as _register_s2
from packages.karma_billing.scenarios.s3_pipeline import register as _register_s3
from packages.karma_billing.scenarios.s5_data import register as _register_s5
from packages.karma_billing.scenarios.s8_dispute import register as _register_s8

# Auto-register on import
_register_s1()
_register_s2()
_register_s3()
_register_s5()
_register_s8()
