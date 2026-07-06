import sys
sys.path.insert(0, "..")
from models import AgentCard, AgentCardSkill, AgentCardSkillInputSchema, AgentCardKarmaExt


def build_card(
    agent_id: str,
    name: str,
    description: str,
    capabilities: list[str],
    endpoint: str,
    skills: list[dict] | None = None,
    contract_address: str = "",
    network: str = "sepolia",
) -> dict:
    skill_objects = []
    if skills:
        for s in skills:
            inp = AgentCardSkillInputSchema(
                type=s.get("input_schema", {}).get("type", "object"),
                properties=s.get("input_schema", {}).get("properties", {}),
                required=s.get("input_schema", {}).get("required", []),
            )
            skill_objects.append(AgentCardSkill(
                id=s["id"],
                name=s.get("name", s["id"]),
                description=s.get("description", ""),
                input_schema=inp,
                output_schema=s.get("output_schema", {"type": "object", "properties": {}}),
            ))
    ext = AgentCardKarmaExt(contract_address=contract_address, network=network)
    card = AgentCard(
        name=name,
        description=description,
        agent_id=agent_id,
        capabilities=capabilities,
        endpoint=endpoint,
        skills=skill_objects,
        karma=ext,
    )
    return card.model_dump()
