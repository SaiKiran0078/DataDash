import pytest


@pytest.fixture()
def make_client(tmp_path):
    """Builds an isolated app (in-memory DB, temp data folder). Needs FastAPI installed."""
    from app.core.config import Settings
    from app.main import create_app
    from fastapi.testclient import TestClient

    created = []

    def build(**overrides):
        options = {
            "database_url": "sqlite://",
            "data_dir": tmp_path / f"data{len(created)}",
            "secret_key": "t" * 40,
            "rate_limit_enabled": False,
        }
        settings = Settings(**{**options, **overrides})
        client = TestClient(create_app(settings))
        created.append(client)
        return client

    yield build
    for c in created:
        c.close()


@pytest.fixture()
def client(make_client):
    return make_client()
