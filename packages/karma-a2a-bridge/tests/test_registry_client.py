import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from unittest.mock import patch, MagicMock
from registry_client import RegistryClient
from models import AgentCard, AgentCardKarmaExt


class TestRegistryClient:
    def setup_method(self):
        self.client = RegistryClient(base_url="https://fake-registry.example.com")
        self.card = AgentCard(
            name="Test", description="Test", agent_id="t1",
            capabilities=["test"], endpoint="http://localhost",
            karma=AgentCardKarmaExt(),
        )

    @patch("registry_client.httpx.post")
    def test_register_card(self, mock_post):
        mock_post.return_value = MagicMock(is_success=True)
        result = self.client.register(self.card)
        assert result is True
        mock_post.assert_called_once()

    @patch("registry_client.httpx.get")
    def test_search_by_capability(self, mock_get):
        mock_get.return_value = MagicMock(is_success=True, json=lambda: [{"agent_id": "a1"}])
        results = self.client.search(capabilities=["karma_settle", "order_food"])
        assert isinstance(results, list)
        assert len(results) == 1

    @patch("registry_client.httpx.post")
    def test_heartbeat(self, mock_post):
        mock_post.return_value = MagicMock(is_success=True)
        result = self.client.heartbeat("agent_001")
        assert result is True

    @patch("registry_client.httpx.delete")
    def test_unregister(self, mock_delete):
        mock_delete.return_value = MagicMock(is_success=True)
        result = self.client.unregister("agent_001")
        assert result is True
