from unittest.mock import Mock

import src.main as main


def test_get_saga_request_queue_uses_default_when_missing(monkeypatch):
    monkeypatch.setattr(main.ConfigLoader, "get", lambda key, default=None: default)

    assert main.get_saga_request_queue() == "PAYTRACE.SAGA.REQ"


def test_get_saga_request_queue_uses_configured_value(monkeypatch):
    monkeypatch.setattr(main.ConfigLoader, "get", lambda key, default=None: "CUSTOM.QUEUE")

    assert main.get_saga_request_queue() == "CUSTOM.QUEUE"


def test_run_initializes_rabbitmq_and_consumes_saga_queue(monkeypatch):
    initialize_mock = Mock()
    consume_mock = Mock()

    monkeypatch.setattr(main.RabbitMQHelper, "initialize_connection", initialize_mock)
    monkeypatch.setattr(main.RabbitMQHelper, "consume_queue", consume_mock)
    monkeypatch.setattr(main, "get_saga_request_queue", lambda: "PAYTRACE.SAGA.REQ")

    main.run()

    initialize_mock.assert_called_once_with()
    consume_mock.assert_called_once_with("PAYTRACE.SAGA.REQ", main.handle_saga_request)
