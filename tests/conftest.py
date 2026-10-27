import pytest

from helpers import fixture_telemetry


@pytest.fixture(scope="session")
def fixture_tel():
    return fixture_telemetry()


@pytest.fixture
def web_paths(tmp_path):
    """Workspace folders under a temporary directory, so no test touches the real data/ or exports/."""
    from app.workspace import WorkspacePaths

    videos = tmp_path / "videos"
    videos.mkdir()
    return WorkspacePaths(
        data_dir=tmp_path / "data",
        exports_dir=tmp_path / "exports",
        videos_dir=videos,
        project_root=tmp_path,
    )


@pytest.fixture
def web_registry():
    """A registry with the test-only overlays: one that needs no telemetry, one that does."""
    from app.overlays.registry import OverlayRegistry
    from overlay_fixtures import TelemetryOverlay, TimestampOverlay

    registry = OverlayRegistry()
    registry.register(TimestampOverlay())
    registry.register(TelemetryOverlay())
    return registry


@pytest.fixture
def make_web_app(web_paths, web_registry):
    """Factory for apps on the test folders. Pass different paths to simulate a restart on the same data."""
    from app.web import create_app

    def make(paths=None):
        return create_app(paths or web_paths, registry=web_registry)

    return make


@pytest.fixture
def web_app(make_web_app):
    return make_web_app()


@pytest.fixture
def web_client(web_app):
    from fastapi.testclient import TestClient

    with TestClient(web_app) as client:
        yield client
