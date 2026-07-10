from unittest.mock import Mock
from types import SimpleNamespace

import src.main as main


def test_get_saga_request_queue_uses_default_when_missing(monkeypatch):
    monkeypatch.setattr(main.ConfigLoader, "get", lambda key, default=None: default)

    assert main.get_saga_request_queue() == "PAYTRACE.SAGA.REQ"


def test_get_saga_request_queue_uses_configured_value(monkeypatch):
    monkeypatch.setattr(main.ConfigLoader, "get", lambda key, default=None: "CUSTOM.QUEUE")

    assert main.get_saga_request_queue() == "CUSTOM.QUEUE"


def test_get_saga_subscribed_topics_uses_default_when_missing(monkeypatch):
    monkeypatch.setattr(main.ConfigLoader, "get", lambda key, default=None: default)

    assert main.get_saga_subscribed_topics() == ["#"]


def test_get_saga_subscribed_topics_accepts_json_array(monkeypatch):
    monkeypatch.setattr(main.ConfigLoader, "get", lambda key, default=None: '["payments.created", "payments.*"]')

    assert main.get_saga_subscribed_topics() == ["payments.created", "payments.*"]


def test_get_saga_subscribed_topics_accepts_comma_separated_text(monkeypatch):
    monkeypatch.setattr(main.ConfigLoader, "get", lambda key, default=None: "payments.created, payments.failed")

    assert main.get_saga_subscribed_topics() == ["payments.created", "payments.failed"]


def test_run_initializes_rabbitmq_binds_topics_and_consumes_saga_queue(monkeypatch):
    initialize_mock = Mock()
    bind_mock = Mock()
    consume_mock = Mock()

    monkeypatch.setattr(main.RabbitMQHelper, "initialize_connection", initialize_mock)
    monkeypatch.setattr(main.RabbitMQHelper, "bind_queue_to_topics", bind_mock)
    monkeypatch.setattr(main.RabbitMQHelper, "consume_queue", consume_mock)
    monkeypatch.setattr(main, "get_saga_request_queue", lambda: "PAYTRACE.SAGA.REQ")
    monkeypatch.setattr(main, "get_saga_exchange", lambda: "paytrace.saga")
    monkeypatch.setattr(main, "get_saga_subscribed_topics", lambda: ["payments.created", "payments.failed"])

    main.run()

    initialize_mock.assert_called_once_with()
    bind_mock.assert_called_once_with(
        "PAYTRACE.SAGA.REQ",
        "paytrace.saga",
        ["payments.created", "payments.failed"],
    )
    consume_mock.assert_called_once_with("PAYTRACE.SAGA.REQ", main.handle_saga_request)


def test_extract_file_id_from_saga_event_prefers_headers():
    properties = SimpleNamespace(headers={"file_id": "file-from-header"})

    assert main.extract_file_id_from_saga_event(b'{"payload":{"file_id":"file-from-body"}}', properties) == "file-from-header"


def test_handle_saga_request_delegates_completion_check_for_file_event(monkeypatch):
    handled_file_ids: list[str] = []

    class _FakeCompletionHandler:
        def process_file_if_complete(self, file_id):
            handled_file_ids.append(file_id)

    monkeypatch.setattr(main, "FileCompletionHandler", _FakeCompletionHandler)

    main.handle_saga_request(
        b'{"event_code":"EV003","payload":{"message_payload":{"file_id":"file-123"}}}',
        method=SimpleNamespace(delivery_tag=1, routing_key="payment.row.processed"),
        properties=SimpleNamespace(correlation_id="corr-1", headers={}),
    )

    assert handled_file_ids == ["file-123"]


def test_handle_saga_request_skips_completion_check_without_file_id(monkeypatch):
    class _FakeCompletionHandler:
        def process_file_if_complete(self, file_id):
            raise AssertionError("should not call completion handler")

    monkeypatch.setattr(main, "FileCompletionHandler", _FakeCompletionHandler)

    main.handle_saga_request(
        b'{"event_code":"EV003","payload":{}}',
        method=SimpleNamespace(delivery_tag=1, routing_key="payment.row.processed"),
        properties=SimpleNamespace(correlation_id="corr-1", headers={}),
    )
