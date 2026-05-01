import os
from unittest.mock import Mock

import pytest

from src.utilities.ConfigLoader import ConfigLoader


@pytest.fixture(autouse=True)
def reset_config_loader_state(monkeypatch):
    monkeypatch.setattr(ConfigLoader._env, "read_env", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.utilities.ConfigLoader.dotenv_values", Mock(return_value={}))

    existing_oftl_keys = [key for key in os.environ if key.startswith("OFTL_")]
    for key in existing_oftl_keys:
        monkeypatch.delenv(key, raising=False)

    ConfigLoader.configurations = {}
    yield
    ConfigLoader.configurations = {}


@pytest.mark.parametrize(
    "key",
    [
        "OFTL_A_B",
        "OFTL_SERVICE_TIMEOUT",
        "OFTL_SERVICE_TIMEOUT_1",
        "OFTL_API_PRIVATE_KEY_SECRET",
    ],
)
def test_is_valid_key_positive_cases(key):
    assert ConfigLoader._is_valid_key(key) is True


@pytest.mark.parametrize(
    "key",
    [
        "",
        "OFTL_",
        "OFTL_A_",
        "OFTL__B",
        "oftl_A_B",
        "OFTL_A_b",
        "OFTL-A-B",
        "NOTOFTL_A_B",
    ],
)
def test_is_valid_key_negative_cases(key):
    assert ConfigLoader._is_valid_key(key) is False


def test_load_configurations_loads_only_valid_oftl_keys(monkeypatch):
    monkeypatch.setenv("OFTL_SERVICE_TIMEOUT", "30")
    monkeypatch.setenv("OFTL_API_KEY_SECRET", "encrypted-value")
    monkeypatch.setenv("OFTL_A_", "invalid")
    monkeypatch.setenv("OTHER_PREFIX_VALUE", "ignored")

    decrypt_mock = Mock(return_value="decrypted-value")
    monkeypatch.setattr(ConfigLoader, "decrypt", decrypt_mock)

    loaded = ConfigLoader.load_configurations()

    assert loaded == {
        "OFTL_SERVICE_TIMEOUT": "30",
        "OFTL_API_KEY_SECRET": "decrypted-value",
    }
    decrypt_mock.assert_called_once_with("encrypted-value")


def test_load_configurations_reads_project_env_file(monkeypatch):
    dotenv_values_mock = Mock(return_value={"OFTL_FILE_VALUE": "from-file"})
    monkeypatch.setattr("src.utilities.ConfigLoader.dotenv_values", dotenv_values_mock)

    loaded = ConfigLoader.load_configurations()

    assert loaded["OFTL_FILE_VALUE"] == "from-file"
    dotenv_values_mock.assert_called_once_with(ConfigLoader._ENV_FILE)


def test_process_environment_overrides_env_file(monkeypatch):
    monkeypatch.setattr(
        "src.utilities.ConfigLoader.dotenv_values",
        Mock(return_value={"OFTL_RABITMQ_USERNAME": "from-file"}),
    )
    monkeypatch.setenv("OFTL_RABITMQ_USERNAME", "from-process")

    loaded = ConfigLoader.load_configurations()

    assert loaded["OFTL_RABITMQ_USERNAME"] == "from-process"


def test_get_triggers_lazy_load_and_uses_default(monkeypatch):
    def _fake_load():
        ConfigLoader.configurations = {"OFTL_REGION": "us-east-1"}
        return ConfigLoader.configurations

    load_mock = Mock(side_effect=_fake_load)
    monkeypatch.setattr(ConfigLoader, "load_configurations", load_mock)

    assert ConfigLoader.get("OFTL_REGION") == "us-east-1"
    assert ConfigLoader.get("OFTL_UNKNOWN", default="fallback") == "fallback"
    load_mock.assert_called_once()
