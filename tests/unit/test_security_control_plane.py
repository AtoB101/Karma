from __future__ import annotations

from services.security_control_plane import (
    classify_and_maybe_freeze,
    clear_control_plane_state,
    funds_overview,
)


def test_critical_event_requests_freeze():
    clear_control_plane_state()
    incident = classify_and_maybe_freeze(
        classification="unauthorized_payout",
        severity="critical",
        actor_id="admin-1",
        reason="double settlement spike",
        submit_on_chain=False,
    )
    assert incident.freeze_requested is True
    overview = funds_overview()
    assert overview["frozen_funds"]["reason"] == "double settlement spike"
    assert overview["active_incidents"]


def test_info_event_does_not_freeze():
    clear_control_plane_state()
    incident = classify_and_maybe_freeze(
        classification="heartbeat",
        severity="info",
        actor_id="system",
        reason="ok",
        freeze_scope="global",
        submit_on_chain=False,
    )
    assert incident.freeze_requested is False
