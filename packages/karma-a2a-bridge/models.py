from pydantic import BaseModel
from typing import Optional


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
    supports_voucher: bool = True
    supports_evidence: bool = True
    settlement_modes: list[str] = ["bilateral"]
    accepted_tokens: list[str] = ["USDC"]
    network: str = "sepolia"


class AgentCard(BaseModel):
    a2a_version: str = "1.0"
    name: str
    description: str
    agent_id: str
    icon_url: str = ""
    capabilities: list[str]
    endpoint: str
    protocols: list[str] = ["a2a", "karma"]
    skills: list[AgentCardSkill] = []
    karma: AgentCardKarmaExt = AgentCardKarmaExt()


class A2ATaskRequest(BaseModel):
    task_id: str
    skill: str
    params: dict = {}
    requester_id: Optional[str] = None
    callback_url: Optional[str] = None


class A2ATaskResponse(BaseModel):
    task_id: str
    status: str  # negotiating | accepted | rejected | completed | failed
    message: str = ""
    voucher_id: Optional[str] = None
    result: Optional[dict] = None
