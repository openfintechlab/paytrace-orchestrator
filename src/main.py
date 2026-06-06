# -*- coding: utf-8 -*-
"""
PayTrace orchestrator entrypoint.
"""

from __future__ import annotations

import sys
import json
from typing import Any

try:
    from domain.FileCompletionHandler import FileCompletionHandler
    from utilities.ConfigLoader import ConfigLoader
    from utilities.Logging import Logging
    from utilities.RabbitMQHelper import RabbitMQConnectionError, RabbitMQHelper, RabbitMQShutdownRequested
except ModuleNotFoundError:
    from src.domain.FileCompletionHandler import FileCompletionHandler
    from src.utilities.ConfigLoader import ConfigLoader
    from src.utilities.Logging import Logging
    from src.utilities.RabbitMQHelper import RabbitMQConnectionError, RabbitMQHelper, RabbitMQShutdownRequested

_DEFAULT_LOG_LEVEL = "INFO"
_DEFAULT_SAGA_REQUEST_QUEUE = "PAYTRACE.SAGA.REQ"
_DEFAULT_SAGA_EXCHANGE = "paytrace.saga"
_DEFAULT_SAGA_SUBSCRIBED_TO = ["#"]


def display_banner() -> None:
    banner = r"""
            ____                   _____       __            __    __          __  
            / __ \____  ___  ____  / __(_)___  / /____  _____/ /_  / /   ____ _/ /_ 
            / / / / __ \/ _ \/ __ \/ /_/ / __ \/ __/ _ \/ ___/ __ \/ /   / __ `/ __ \
            / /_/ / /_/ /  __/ / / / __/ / / / / /_/  __/ /__/ / / / /___/ /_/ / /_/ /
            \____/ .___/\___/_/ /_/_/ /_/_/ /_/\__/\___/\___/_/ /_/_____/\__,_/_.___/ 
                /_/                                                                   
            """
    print(banner)
    Logging.info("===============================================")
    Logging.info("Starting PayTrace Orchestrator")
    Logging.info("Version: %s", ConfigLoader.get("OFTL_SCA_VERSION", "N/A"))
    Logging.info("Log Level: %s", ConfigLoader.get("OFTL_LOG_LEVEL", _DEFAULT_LOG_LEVEL))
    Logging.info("Saga Request Queue: %s", get_saga_request_queue())
    Logging.info("Saga Exchange: %s", get_saga_exchange())
    Logging.info("Saga Subscribed Topics: %s", get_saga_subscribed_topics())
    Logging.info("RabbitMQ Host: %s", ConfigLoader.get("OFTL_RABITMQ_HOST", "localhost"))
    Logging.info("===============================================")


def get_saga_request_queue() -> str:
    """Return the queue the orchestrator waits on."""
    queue_name = str(ConfigLoader.get("OFTL_RABITMQ_SAGA_REQUEST_QUEUE", _DEFAULT_SAGA_REQUEST_QUEUE)).strip()
    return queue_name or _DEFAULT_SAGA_REQUEST_QUEUE


def get_saga_exchange() -> str:
    """Return the topic exchange used for saga subscriptions."""
    exchange_name = str(ConfigLoader.get("OFTL_RABITMQ_SAGA_EXCHANGE", _DEFAULT_SAGA_EXCHANGE)).strip()
    return exchange_name or _DEFAULT_SAGA_EXCHANGE


def get_saga_subscribed_topics() -> list[str]:
    """Return configured saga subscription topics from JSON array or comma-separated text."""
    raw_value = ConfigLoader.get("OFTL_RABITMQ_SAGA_SUSCRIBED_TO")
    if raw_value is None:
        return list(_DEFAULT_SAGA_SUBSCRIBED_TO)

    raw_text = str(raw_value).strip()
    if not raw_text:
        return list(_DEFAULT_SAGA_SUBSCRIBED_TO)

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, list):
        topics = [str(topic).strip() for topic in parsed if str(topic).strip()]
    else:
        topics = [topic.strip() for topic in raw_text.split(",") if topic.strip()]

    return topics or list(_DEFAULT_SAGA_SUBSCRIBED_TO)


def extract_file_id_from_saga_event(body: bytes, properties: Any) -> str | None:
    """Extract file_id from supported saga event shapes or RabbitMQ headers."""
    headers = getattr(properties, "headers", None)
    if isinstance(headers, dict):
        header_file_id = str(headers.get("file_id", "") or "").strip()
        if header_file_id:
            return header_file_id

    try:
        event = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(event, dict):
        return None

    top_level_file_id = str(event.get("file_id", "") or "").strip()
    if top_level_file_id:
        return top_level_file_id

    payload = event.get("payload")
    if isinstance(payload, dict):
        payload_file_id = str(payload.get("file_id", "") or "").strip()
        if payload_file_id:
            return payload_file_id

        message_payload = payload.get("message_payload")
        if isinstance(message_payload, dict):
            message_payload_file_id = str(message_payload.get("file_id", "") or "").strip()
            if message_payload_file_id:
                return message_payload_file_id

    return None


def handle_saga_request(body: bytes, method: Any, properties: Any) -> None:
    """Handle inbound saga requests by delegating business workflow checks."""
    Logging.info_context(
        "Saga request received.",
        delivery_tag=getattr(method, "delivery_tag", None),
        correlation_id=getattr(properties, "correlation_id", None),
        routing_key=getattr(method, "routing_key", None),
        message_size=len(body),
    )

    Logging.debug_context(
        "Saga request received. (MESSAGE TRACE)",
        delivery_tag=getattr(method, "delivery_tag", None),
        correlation_id=getattr(properties, "correlation_id", None),
        routing_key=getattr(method, "routing_key", None),
        message_size=len(body),
        message_body=body.decode("utf-8", errors="replace")[:500]
    )

    file_id = extract_file_id_from_saga_event(body, properties)
    if not file_id:
        Logging.debug_context(
            "Saga request does not include file_id; skipping file completion check.",
            delivery_tag=getattr(method, "delivery_tag", None),
            correlation_id=getattr(properties, "correlation_id", None),
            routing_key=getattr(method, "routing_key", None),
        )
        return

    FileCompletionHandler().process_file_if_complete(file_id)


def run() -> None:
    queue_name = get_saga_request_queue()
    RabbitMQHelper.initialize_connection()
    RabbitMQHelper.bind_queue_to_topics(
        queue_name,
        get_saga_exchange(),
        get_saga_subscribed_topics(),
    )
    RabbitMQHelper.consume_queue(queue_name, handle_saga_request)
 

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
