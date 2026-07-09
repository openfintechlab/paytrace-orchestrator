import importlib
import logging

from src.utilities.ConfigLoader import ConfigLoader


def test_logging_uses_config_loader_log_level(monkeypatch):
    monkeypatch.setattr(
        ConfigLoader,
        "get",
        lambda key, default=None: "DEBUG" if key == "OFTL_LOG_LEVEL" else default,
    )

    logging_module = importlib.reload(importlib.import_module("src.utilities.Logging"))

    assert logging_module.Logging._logger.getEffectiveLevel() == logging.DEBUG
