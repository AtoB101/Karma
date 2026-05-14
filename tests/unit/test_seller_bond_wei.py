from trusted_agent_runtime.testnet_client import seller_bond_wei


def test_seller_bond_rounds_up_when_bps_times_amount_truncates_to_zero() -> None:
    assert seller_bond_wei(100, 1) == 1


def test_seller_bond_typical() -> None:
    assert seller_bond_wei(10_000_000, 500) == 500_000


def test_zero_amount_yields_zero_bond() -> None:
    assert seller_bond_wei(0, 500) == 0
