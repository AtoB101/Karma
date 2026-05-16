from services.openclaw_webhook import build_envelope, emit_openclaw_event, list_stored_events


def test_build_envelope_shape():
    env = build_envelope("voucher.accepted", {"voucher_id": "v1"}, trace_id="t1")
    assert env["event_version"] == "1"
    assert env["event_type"] == "voucher.accepted"
    assert env["payload"]["voucher_id"] == "v1"


def test_ring_buffer_when_store_enabled(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "openclaw_webhook_url", "", raising=False)
    monkeypatch.setattr(settings, "openclaw_webhook_store_events", True, raising=False)
    emit_openclaw_event("settlement.delivered", {"task_id": "task-a"})
    events = list_stored_events(task_id="task-a")
    assert len(events) >= 1
    assert events[-1]["event_type"] == "settlement.delivered"
