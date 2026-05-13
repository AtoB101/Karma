def test_build_app():
    from karma_openclaw.server import build_app

    app = build_app()
    assert app is not None
