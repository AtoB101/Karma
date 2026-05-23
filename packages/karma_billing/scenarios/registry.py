"""Scenario Registry — maps ScenarioType to its configuration.

Each scenario has:
- receipt_types: the set of ReceiptType values it uses
- state_path: ordered list of BillingState values
- allowed_transitions: explicit (from,to) pairs
- anchoring_policy_overrides: optional custom anchoring rules
"""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from packages.karma_billing.schema import (
    ScenarioType,
    ReceiptType,
    BillingState,
)


@dataclass
class ScenarioConfig:
    """Configuration for a single billing scenario."""

    scenario_type: ScenarioType
    receipt_types: FrozenSet[ReceiptType] = field(default_factory=frozenset)
    state_path: List[BillingState] = field(default_factory=list)
    allowed_transitions: List[Tuple[BillingState, BillingState]] = field(default_factory=list)
    anchoring_policy_overrides: Optional[dict] = None

    @property
    def start_state(self) -> BillingState:
        """First state in the path."""
        return self.state_path[0] if self.state_path else BillingState.INITIATED

    @property
    def terminal_state(self) -> BillingState:
        """Last state in the path."""
        return self.state_path[-1] if self.state_path else BillingState.SETTLED


class ScenarioRegistry:
    """Thread-safe registry of all billing scenarios.

    Scenarios are registered at import time by their respective modules
    and looked up by ScenarioType enum value.
    """

    def __init__(self) -> None:
        self._configs: Dict[ScenarioType, ScenarioConfig] = {}

    def register(self, scenario: ScenarioType, config: ScenarioConfig) -> None:
        """Register a scenario's configuration.

        Raises ValueError if the scenario is already registered.
        """
        if scenario in self._configs:
            raise ValueError(f"Scenario {scenario.value} is already registered")
        self._configs[scenario] = config

    def get(self, scenario: ScenarioType) -> ScenarioConfig:
        """Look up a scenario's configuration.

        Raises KeyError if the scenario is not registered.
        """
        if scenario not in self._configs:
            raise KeyError(f"Scenario {scenario.value} is not registered")
        return self._configs[scenario]

    def list_all(self) -> List[ScenarioConfig]:
        """Return all registered scenario configurations."""
        return list(self._configs.values())

    def is_registered(self, scenario: ScenarioType) -> bool:
        """Check whether a scenario is registered."""
        return scenario in self._configs

    @property
    def count(self) -> int:
        return len(self._configs)


# Global singleton
_scenario_registry = ScenarioRegistry()


def get_registry() -> ScenarioRegistry:
    """Get the global scenario registry singleton."""
    return _scenario_registry
