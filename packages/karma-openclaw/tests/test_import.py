def test_build_app():
    from karma_openclaw.server import build_app

    app = build_app()
    assert app is not None


def test_p1_modules_import():
    from karma_openclaw import handoff, helpers  # noqa: F401

    assert handoff.HANDOFF_VERSION == "1"
    assert "Console" in helpers.manual_authorization_checklist("both")
