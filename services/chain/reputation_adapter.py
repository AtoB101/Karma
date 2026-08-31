"""Broadcast KarmaReputationAnchor pack/slash from the packer key (not a funds mover)."""
from __future__ import annotations

from config.settings import settings

_PACK_ABI = [
    {
        "name": "pack",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "party", "type": "address"},
            {"name": "scoreE2", "type": "uint256"},
            {"name": "successCount", "type": "uint256"},
            {"name": "evidenceHash", "type": "bytes32"},
        ],
        "outputs": [],
    },
    {
        "name": "slash",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "party", "type": "address"},
            {"name": "newScoreE2", "type": "uint256"},
            {"name": "kind", "type": "bytes32"},
        ],
        "outputs": [],
    },
]


def _anchor_address() -> str:
    addr = (settings.karma_reputation_anchor_address or "").strip()
    if not addr:
        raise RuntimeError("KARMA_REPUTATION_ANCHOR_ADDRESS not set")
    return addr


def _to_bytes32(value: str) -> bytes:
    h = value[2:] if value.startswith("0x") else value
    raw = bytes.fromhex(h)
    if len(raw) != 32:
        raise ValueError("value must be 32 bytes")
    return raw


def _contract(adapter):
    w3 = adapter._get_web3()
    return w3.eth.contract(
        address=w3.to_checksum_address(_anchor_address()),
        abi=_PACK_ABI,
    )


def submit_pack(
    *,
    wallet: str,
    score_e2: int,
    success_count: int,
    evidence_hash: str,
) -> str:
    from services.chain.settlement_adapter import OnChainSettlementAdapter

    adapter = OnChainSettlementAdapter()
    w3 = adapter._get_web3()
    digest = _to_bytes32(evidence_hash)
    contract = _contract(adapter)
    party = w3.to_checksum_address(wallet)
    fn = contract.functions.pack(party, int(score_e2), int(success_count), digest)
    tx = adapter._send_tx(fn)
    return tx.tx_hash


def submit_slash(*, wallet: str, score_e2: int, kind: str) -> str:
    from services.chain.settlement_adapter import OnChainSettlementAdapter

    adapter = OnChainSettlementAdapter()
    w3 = adapter._get_web3()
    kind_b32 = w3.keccak(text=str(kind or "default"))
    contract = _contract(adapter)
    party = w3.to_checksum_address(wallet)
    fn = contract.functions.slash(party, int(score_e2), kind_b32)
    tx = adapter._send_tx(fn)
    return tx.tx_hash
