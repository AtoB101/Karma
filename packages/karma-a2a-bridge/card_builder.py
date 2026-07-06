import os
from models import AgentCard, AgentCardSkill, AgentCardSkillInputSchema, AgentCardKarmaExt
import config


def build_agent_card(
    agent_id: str,
    name: str,
    description: str,
    capabilities: list[str],
    endpoint: str,
    icon_url: str = "",
    skills: list[dict] | None = None,
    protocols: list[str] | None = None,
    karma_ext: dict | None = None,
) -> AgentCard:
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
    ext = AgentCardKarmaExt(
        contract_address=karma_ext.get("contract_address", config.KARMA_CONTRACT_ADDRESS) if karma_ext else config.KARMA_CONTRACT_ADDRESS,
        network=karma_ext.get("network", config.KARMA_NETWORK) if karma_ext else config.KARMA_NETWORK,
        settlement_modes=karma_ext.get("settlement_modes", config.KARMA_SETTLEMENT_MODES) if karma_ext else config.KARMA_SETTLEMENT_MODES,
    )
    return AgentCard(
        name=name,
        description=description,
        agent_id=agent_id,
        icon_url=icon_url,
        capabilities=capabilities,
        endpoint=endpoint,
        protocols=protocols or ["a2a", "karma"],
        skills=skill_objects,
        karma=ext,
    )


def build_from_karma_agent(agent_data: dict) -> AgentCard:
    return build_agent_card(
        agent_id=agent_data.get("agent_id", "unknown"),
        name=agent_data.get("name", "Unknown Agent"),
        description=agent_data.get("description", ""),
        capabilities=agent_data.get("capabilities", []),
        endpoint=agent_data.get("endpoint_url", ""),
        icon_url=agent_data.get("icon_url", ""),
    )
