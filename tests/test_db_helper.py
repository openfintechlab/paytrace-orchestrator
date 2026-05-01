import pytest

from src.utilities.ConfigLoader import ConfigLoader
from src.utilities.DBHelper import DBHelper


@pytest.fixture(autouse=True)
def reset_db_helper(monkeypatch):
    monkeypatch.setattr(ConfigLoader._env, "read_env", lambda *args, **kwargs: None)
    ConfigLoader.configurations = {}
    DBHelper.dispose_connection()
    yield
    ConfigLoader.configurations = {}
    DBHelper.dispose_connection()


def test_build_connection_url_and_schema_encodes_password(monkeypatch):
    monkeypatch.setenv("OFTL_POSTGRESDB_USERNAME", "admin")
    monkeypatch.setenv("OFTL_POSTGRESDB_PASSWORD", "p@ss word")
    monkeypatch.setenv("OFTL_POSTGRESDB_HOST", "localhost")
    monkeypatch.setenv("OFTL_POSTGRESDB_PORT", "5432")
    monkeypatch.setenv("OFTL_POSTGRESDB_NAME", "paytrace")
    monkeypatch.setenv("OFTL_POSTGRESDB_SCHEMA", "workflow")

    url, schema = DBHelper._build_connection_url_and_schema()

    assert url == "postgresql+psycopg2://admin:p%40ss+word@localhost:5432/paytrace"
    assert schema == "workflow"


def test_build_connection_url_and_schema_rejects_missing_values(monkeypatch):
    monkeypatch.setenv("OFTL_POSTGRESDB_USERNAME", "admin")

    with pytest.raises(ValueError, match="OFTL_POSTGRESDB_PASSWORD"):
        DBHelper._build_connection_url_and_schema()


def test_initialize_connection_skips_when_configuration_is_missing():
    assert DBHelper.initialize_connection() is False
