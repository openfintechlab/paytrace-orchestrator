# -*- coding: utf-8 -*-
"""
PayTrace orchestrator entrypoint.
"""

from __future__ import annotations

import sys
from typing import Any

try:
    from utilities.ConfigLoader import ConfigLoader
    from utilities.Logging import Logging
    from utilities.RabbitMQHelper import RabbitMQConnectionError, RabbitMQHelper, RabbitMQShutdownRequested
except ModuleNotFoundError:
    from src.utilities.ConfigLoader import ConfigLoader
    from src.utilities.Logging import Logging
    from src.utilities.RabbitMQHelper import RabbitMQConnectionError, RabbitMQHelper, RabbitMQShutdownRequested

_DEFAULT_LOG_LEVEL = "INFO"
_DEFAULT_SAGA_REQUEST_QUEUE = "PAYTRACE.SAGA.REQ"


def display_banner() -> None:
    banner = r"""
        ____              ______
       / __ \____ ___  __/_  __/________ _________
      / /_/ / __ `/ / / / / / / ___/ __ `/ ___/ _ \
     / ____/ /_/ / /_/ / / / / /  / /_/ / /__/  __/
    /_/    \__,_/\__, / /_/ /_/   \__,_/\___/\___/
                /____/
    """
    print(banner)
    Logging.info("===============================================")
    Logging.info("Starting PayTrace Orchestrator")
    Logging.info("Version: %s", ConfigLoader.get("OFTL_SCA_VERSION", "N/A"))
    Logging.info("Log Level: %s", ConfigLoader.get("OFTL_LOG_LEVEL", _DEFAULT_LOG_LEVEL))
    Logging.info("Saga Request Queue: %s", get_saga_request_queue())
    Logging.info("RabbitMQ Host: %s", ConfigLoader.get("OFTL_RABITMQ_HOST", "localhost"))
    Logging.info("===============================================")


def get_saga_request_queue() -> str:
    """Return the queue the orchestrator waits on."""
    queue_name = str(ConfigLoader.get("OFTL_RABITMQ_SAGA_REQUEST_QUEUE", _DEFAULT_SAGA_REQUEST_QUEUE)).strip()
    return queue_name or _DEFAULT_SAGA_REQUEST_QUEUE


def handle_saga_request(body: bytes, method: Any, properties: Any) -> None:
    """Acknowledge inbound saga requests without applying business workflow logic."""
    Logging.info_context(
        "Saga request received.",
        delivery_tag=getattr(method, "delivery_tag", None),
        correlation_id=getattr(properties, "correlation_id", None),
        message_size=len(body),
    )


def run() -> None:
    RabbitMQHelper.initialize_connection()
    RabbitMQHelper.consume_queue(get_saga_request_queue(), handle_saga_request)


if __name__ == "__main__":
    try:
        display_banner()
        Logging.info("Application starting...")
        run()
    except KeyboardInterrupt:
        Logging.warning("Shutdown requested by user.")
        sys.exit(0)
    except RabbitMQShutdownRequested as exc:
        Logging.error("Error starting orchestrator service")
        Logging.error(str(exc))
        sys.exit(99)
    except RabbitMQConnectionError as exc:
        Logging.error("Error starting orchestrator service")
        Logging.error(str(exc))
        sys.exit(99)
    except Exception as exc:
        Logging.error("Error starting orchestrator service")
        Logging.error(str(exc))
        sys.exit(91)
