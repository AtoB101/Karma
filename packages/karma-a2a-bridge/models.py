from pydantic import BaseModel, Field
from typing import Any, Optional


class AgentCardSkillInputSchema(BaseModel):
    type: str = "object"
    properties: dict = {}
    required: list[str] = []


class AgentCardSkill(BaseModel):
    id: str
    name: str
    description: str
    input_schema: AgentCardSkillInputSchema
    output_schema: dict = {"type": "object", "properties": {}}


class AgentCardKarmaExt(BaseModel):
    version: str = "0.1.0"
    contract_address: str = ""
    # Discoverable attestation surface (addresses only — not privileged method ABIs)
    verifier_registry: str = ""
    attestation_gateway: str = ""
    supports_voucher: bool = True
    supports_evidence: bool = True
    supports_attestation: bool = False
    settlement_modes: list[str] = ["bilateral"]
    accepted_tokens: list[str] = ["USDC"]
    network: str = "sepolia"
    # On-chain DID projection metadata (SSOT pointer)
    did_agent_address: str = ""
    on_chain_did: str = ""


class AgentCard(BaseModel):
    a2a_version: str = "1.0"
    name: str
    description: str
    # Read-only projection of on-chain DID when configured (did:karma:0x…)
    agent_id: str
    icon_url: str = ""
    capabilities: list[str]
    endpoint: str
    protocols: list[str] = ["a2a", "karma"]
    skills: list[AgentCardSkill] = []
    karma: AgentCardKarmaExt = AgentCardKarmaExt()


class A2ASignedAuth(BaseModel):
    """EIP-712 auth payload required on all A2A write operations."""
    agent: str = Field(..., description="Signer wallet / DID agent address (0x…)")
    signature: str
    nonce: int
    deadline: int
    amount_micro: int = 0
    requester_id: str = ""


class A2ATaskRequest(BaseModel):
    task_id: str
    skill: str
    params: dict = {}
    requester_id: Optional[str] = None
    callback_url: Optional[str] = None
    auth: Optional[A2ASignedAuth] = None


class A2AConfirmRequest(BaseModel):
    seller_id: str = ""
    amount: float = 0.0
    auth: Optional[A2ASignedAuth] = None


class A2ASubmitRequest(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)
    auth: Optional[A2ASignedAuth] = None


class A2ACancelRequest(BaseModel):
    reason: str = ""
    auth: Optional[A2ASignedAuth] = None


class A2AHandoffRequest(BaseModel):
    buyer_id: str = ""
    seller_id: str = ""
    auth: Optional[A2ASignedAuth] = None


class A2ATaskResponse(BaseModel):
    task_id: str
    status: str  # negotiating | accepted | rejected | completed | failed | cancelled
    message: str = ""
    voucher_id: Optional[str] = None
    result: Optional[dict] = None
