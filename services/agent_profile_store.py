"""Sidecar store for agent onboarding profile cards (no DB migration required)."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_STORE_PATH = Path(__file__).resolve().parents[1] / ".karma_data" / "agent_profile_cards.json"
_CACHE: dict[str, dict[str, Any]] = {}
_LOADED = False


def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        if _STORE_PATH.is_file():
            try:
                data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    _CACHE.update({str(k): v for k, v in data.items() if isinstance(v, dict)})
            except Exception:  # noqa: BLE001
                pass
        _LOADED = True


def save_profile_card(agent_id: str, card: dict[str, Any]) -> None:
    _ensure_loaded()
    with _LOCK:
        _CACHE[agent_id] = dict(card)
        _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STORE_PATH.write_text(json.dumps(_CACHE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_profile_card(agent_id: str) -> dict[str, Any] | None:
    _ensure_loaded()
    with _LOCK:
        card = _CACHE.get(agent_id)
        return dict(card) if card else None


def clear_profile_cards() -> None:
    global _LOADED
    with _LOCK:
        _CACHE.clear()
        _LOADED = True
        if _STORE_PATH.is_file():
            _STORE_PATH.unlink(missing_ok=True)
