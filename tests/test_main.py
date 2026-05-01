from unittest.mock import Mock

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
