import importlib

import pytest

from src.utilities.ConfigLoader import ConfigLoader
from src.utilities.RabbitMQHelper import RabbitMQConnectionError, RabbitMQHelper, RabbitMQShutdownRequested

rabbitmq_helper_module = importlib.import_module("src.utilities.RabbitMQHelper")


@pytest.fixture(autouse=True)
def reset_rabbitmq_helper_state(monkeypatch):
    monkeypatch.setattr(ConfigLoader._env, "read_env", lambda *args, **kwargs: None)
    ConfigLoader.configurations = {}
    RabbitMQHelper._connection = None
    RabbitMQHelper._channel = None
    RabbitMQHelper._delivery_confirm_enabled = False
    yield
    ConfigLoader.configurations = {}
    RabbitMQHelper._connection = None
    RabbitMQHelper._channel = None
    RabbitMQHelper._delivery_confirm_enabled = False


def test_connection_retry_count_uses_default():
    assert RabbitMQHelper._connection_retry_count() == 3


def test_connection_retry_count_prefers_connection_attempts(monkeypatch):
    monkeypatch.setenv("OFTL_RABITMQ_CONNECTION_ATTEMPTS", "5")
    monkeypatch.setenv("OFTL_RABITMQ_CONN_RETRYCOUNT", "2")

    assert RabbitMQHelper._connection_retry_count() == 5


def test_build_connection_parameters_uses_single_pika_attempt(monkeypatch):
    class FakePikaModule:
        class PlainCredentials:
            def __init__(self, username, password):
                self.username = username
                self.password = password

        class ConnectionParameters:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    monkeypatch.setattr(rabbitmq_helper_module, "pika", FakePikaModule)

    params = RabbitMQHelper._build_connection_parameters()

    assert params.kwargs["connection_attempts"] == 1
    assert params.kwargs["retry_delay"] == 0
    assert params.kwargs["socket_timeout"] == 5.0
    assert params.kwargs["stack_timeout"] == 10.0


def test_connect_with_retry_raises_after_configured_attempts(monkeypatch):
    monkeypatch.setenv("OFTL_RABITMQ_CONNECTION_ATTEMPTS", "2")
    attempts: list[int] = []

    def failing_open():
        attempts.append(1)
        raise RuntimeError("auth failed")

    monkeypatch.setattr(RabbitMQHelper, "_open_connection", classmethod(lambda cls: failing_open()))
    monkeypatch.setattr(RabbitMQHelper, "close", classmethod(lambda cls: None))
    monkeypatch.setattr(rabbitmq_helper_module.time, "sleep", lambda _: None)

    with pytest.raises(RabbitMQConnectionError):
        RabbitMQHelper._connect_with_retry()

    assert len(attempts) == 2


def test_initialize_connection_normalizes_connection_failures(monkeypatch):
    monkeypatch.setattr(
        RabbitMQHelper,
        "_connect_with_retry",
        classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("dns failure"))),
    )
    monkeypatch.setattr(RabbitMQHelper, "close", classmethod(lambda cls: None))

    with pytest.raises(RabbitMQShutdownRequested, match="Exiting application with code 99"):
        RabbitMQHelper.initialize_connection()


def test_send_p2p_message_retries_after_connection_loss(monkeypatch):
    attempts = {"count": 0}
    closed = {"count": 0}

    class FakePikaModule:
        class BasicProperties:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    class FakeChannel:
        is_closed = False

        def confirm_delivery(self):
            return None

        def queue_declare(self, queue, durable):
            _ = (queue, durable)

        def basic_publish(self, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("connection lost during publish")
            return True

    monkeypatch.setattr(rabbitmq_helper_module, "pika", FakePikaModule)
    monkeypatch.setattr(RabbitMQHelper, "_ensure_channel", classmethod(lambda cls: FakeChannel()))
    monkeypatch.setattr(RabbitMQHelper, "close", classmethod(lambda cls: closed.__setitem__("count", closed["count"] + 1)))
    monkeypatch.setattr(rabbitmq_helper_module.time, "sleep", lambda _: None)

    assert RabbitMQHelper.send_p2p_message("queue-name", {"ok": True}) is True
    assert attempts["count"] == 2
    assert closed["count"] == 1


def test_consume_queue_declares_saga_queue_and_starts_consuming(monkeypatch):
    calls: list[tuple[str, object]] = []

    class FakeChannel:
        is_closed = False

        def queue_declare(self, queue, durable):
            calls.append(("queue_declare", (queue, durable)))

        def basic_qos(self, prefetch_count):
            calls.append(("basic_qos", prefetch_count))

        def basic_consume(self, queue, on_message_callback, auto_ack):
            calls.append(("basic_consume", (queue, auto_ack, callable(on_message_callback))))

        def start_consuming(self):
            calls.append(("start_consuming", True))

    monkeypatch.setattr(RabbitMQHelper, "_ensure_channel", classmethod(lambda cls: FakeChannel()))

    RabbitMQHelper.consume_queue("PAYTRACE.SAGA.REQ", lambda body, method, properties: None)

    assert calls == [
        ("queue_declare", ("PAYTRACE.SAGA.REQ", True)),
        ("basic_qos", 1),
        ("basic_consume", ("PAYTRACE.SAGA.REQ", False, True)),
        ("start_consuming", True),
    ]
