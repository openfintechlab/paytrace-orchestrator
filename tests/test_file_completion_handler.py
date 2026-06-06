from datetime import datetime, timezone

import pytest

import src.domain.FileCompletionHandler as file_completion_module
from src.domain.FileCompletionHandler import FileCompletionHandler


def test_is_file_complete_returns_true_when_terminal_count_matches_registry(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    def _fake_select(query, params=None):
        calls.append((query, params or {}))
        if query == FileCompletionHandler._SQL_CHECK_COMPLETION_COUNT:
            return [{"terminal_count": 2}]
        if query == FileCompletionHandler._SQL_GET_REGISTRY_ROW_COUNT:
            return [{"row_count": 2}]
        raise AssertionError(f"Unexpected query: {query}")

    monkeypatch.setattr(file_completion_module.DBHelper, "execute_select", _fake_select)

    assert FileCompletionHandler(response_dir="unused").is_file_complete("file-123") is True
    assert calls == [
        (FileCompletionHandler._SQL_CHECK_COMPLETION_COUNT, {"fileId": "file-123"}),
        (FileCompletionHandler._SQL_GET_REGISTRY_ROW_COUNT, {"fileId": "file-123"}),
    ]


def test_is_file_complete_returns_false_when_counts_do_not_match(monkeypatch):
    def _fake_select(query, params=None):
        if query == FileCompletionHandler._SQL_CHECK_COMPLETION_COUNT:
            return [{"terminal_count": 1}]
        if query == FileCompletionHandler._SQL_GET_REGISTRY_ROW_COUNT:
            return [{"row_count": 2}]
        raise AssertionError(f"Unexpected query: {query}")

    monkeypatch.setattr(file_completion_module.DBHelper, "execute_select", _fake_select)

    assert FileCompletionHandler(response_dir="unused").is_file_complete("file-123") is False


def test_is_file_complete_returns_false_when_registry_row_is_missing(monkeypatch):
    def _fake_select(query, params=None):
        if query == FileCompletionHandler._SQL_CHECK_COMPLETION_COUNT:
            return [{"terminal_count": 0}]
        if query == FileCompletionHandler._SQL_GET_REGISTRY_ROW_COUNT:
            return []
        raise AssertionError(f"Unexpected query: {query}")

    monkeypatch.setattr(file_completion_module.DBHelper, "execute_select", _fake_select)

    assert FileCompletionHandler(response_dir="unused").is_file_complete("file-123") is False


def test_is_file_complete_allows_zero_row_registry_files(monkeypatch):
    def _fake_select(query, params=None):
        if query == FileCompletionHandler._SQL_CHECK_COMPLETION_COUNT:
            return [{"terminal_count": 0}]
        if query == FileCompletionHandler._SQL_GET_REGISTRY_ROW_COUNT:
            return [{"row_count": 0}]
        raise AssertionError(f"Unexpected query: {query}")

    monkeypatch.setattr(file_completion_module.DBHelper, "execute_select", _fake_select)

    assert FileCompletionHandler(response_dir="unused").is_file_complete("file-123") is True


def test_process_file_if_complete_generates_response_once_and_marks_final(monkeypatch, tmp_path):
    updates: list[tuple[str, dict[str, object]]] = []
    response_rows = [
        {
            "TransferId": "PTX-001",
            "TransactionId": "PTX-001",
            "Status": "PROCESSED",
            "ResponseCode": "PT-0000",
            "ResponseMessage": "Processed successfully",
            "ProcessedTimestamp": datetime(2026, 6, 6, 10, 0, tzinfo=timezone.utc),
        },
        {
            "TransferId": "PTX-002",
            "TransactionId": "PTX-002",
            "Status": "FAILED",
            "ResponseCode": "PT-1900",
            "ResponseMessage": "Adapter rejected payment",
            "ProcessedTimestamp": datetime(2026, 6, 6, 10, 1, tzinfo=timezone.utc),
        },
    ]

    def _fake_select(query, params=None):
        if query == FileCompletionHandler._SQL_CHECK_COMPLETION_COUNT:
            return [{"terminal_count": 2}]
        if query == FileCompletionHandler._SQL_GET_REGISTRY_ROW_COUNT:
            return [{"row_count": 2}]
        if query == FileCompletionHandler._SQL_GET_TRANSACTION_RESULTS:
            return response_rows
        raise AssertionError(f"Unexpected query: {query}")

    def _fake_update(query, params=None):
        updates.append((query, params or {}))
        return 1

    monkeypatch.setattr(file_completion_module.DBHelper, "execute_select", _fake_select)
    monkeypatch.setattr(file_completion_module.DBHelper, "execute_update", _fake_update)

    response_file = FileCompletionHandler(response_dir=tmp_path).process_file_if_complete("file-123")

    assert response_file is not None
    assert response_file.parent == tmp_path
    assert response_file.name.endswith(".response.csv")
    assert response_file.read_text(encoding="utf-8").splitlines() == [
        "TransferId,TransactionId,Status,ResponseCode,ResponseMessage,ProcessedTimestamp",
        "PTX-001,PTX-001,PROCESSED,PT-0000,Processed successfully,2026-06-06T10:00:00+00:00",
        "PTX-002,PTX-002,FAILED,PT-1900,Adapter rejected payment,2026-06-06T10:01:00+00:00",
    ]
    assert updates == [
        (
            FileCompletionHandler._SQL_SET_READY_STATUS,
            {"fileId": "file-123", "responseStatus": FileCompletionHandler._CNST_STATUS_READY},
        ),
        (
            FileCompletionHandler._SQL_SET_FINAL_STATUS,
            {
                "fileId": "file-123",
                "responseStatus": FileCompletionHandler._CNST_STATUS_GENERATED,
                "responseFileName": response_file.name,
            },
        ),
    ]


def test_process_file_if_complete_skips_generation_when_ready_lock_is_not_acquired(monkeypatch, tmp_path):
    def _fake_select(query, params=None):
        if query == FileCompletionHandler._SQL_CHECK_COMPLETION_COUNT:
            return [{"terminal_count": 1}]
        if query == FileCompletionHandler._SQL_GET_REGISTRY_ROW_COUNT:
            return [{"row_count": 1}]
        if query == FileCompletionHandler._SQL_GET_RESPONSE_STATE:
            return [{"response_status": FileCompletionHandler._CNST_STATUS_GENERATED, "response_file_name": "done.csv"}]
        if query == FileCompletionHandler._SQL_GET_TRANSACTION_RESULTS:
            raise AssertionError("should not fetch response rows without lock")
        raise AssertionError(f"Unexpected query: {query}")

    monkeypatch.setattr(file_completion_module.DBHelper, "execute_select", _fake_select)
    monkeypatch.setattr(file_completion_module.DBHelper, "execute_update", lambda query, params=None: 0)

    response_file = FileCompletionHandler(response_dir=tmp_path).process_file_if_complete("file-123")

    assert response_file is None
    assert list(tmp_path.iterdir()) == []


def test_process_file_if_complete_waits_for_row_dispatch_to_catch_up(monkeypatch, tmp_path):
    completion_counts = iter([0, 1])
    updates: list[tuple[str, dict[str, object]]] = []
    sleeps: list[float] = []

    def _fake_select(query, params=None):
        if query == FileCompletionHandler._SQL_CHECK_COMPLETION_COUNT:
            return [{"terminal_count": next(completion_counts)}]
        if query == FileCompletionHandler._SQL_GET_REGISTRY_ROW_COUNT:
            return [{"row_count": 1}]
        if query == FileCompletionHandler._SQL_GET_TRANSACTION_RESULTS:
            return [
                {
                    "TransferId": "PTX-001",
                    "TransactionId": "PTX-001",
                    "Status": "PROCESSED",
                    "ResponseCode": "PT-0000",
                    "ResponseMessage": "Processed successfully",
                    "ProcessedTimestamp": "2026-06-06T10:00:00+00:00",
                }
            ]
        raise AssertionError(f"Unexpected query: {query}")

    def _fake_update(query, params=None):
        updates.append((query, params or {}))
        return 1

    monkeypatch.setattr(file_completion_module.DBHelper, "execute_select", _fake_select)
    monkeypatch.setattr(file_completion_module.DBHelper, "execute_update", _fake_update)
    monkeypatch.setattr(file_completion_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    handler = FileCompletionHandler(response_dir=tmp_path)
    handler.completion_wait_seconds = 1.0
    handler.completion_poll_seconds = 0.01

    response_file = handler.process_file_if_complete("file-123")

    assert response_file is not None
    assert response_file.is_file()
    assert sleeps == [0.01]
    assert updates[0][0] == FileCompletionHandler._SQL_SET_READY_STATUS
    assert updates[1][0] == FileCompletionHandler._SQL_SET_FINAL_STATUS


def test_process_file_if_complete_finalizes_existing_ready_response(monkeypatch, tmp_path):
    existing_response = tmp_path / "file-123.20260606T100000Z.response.csv"
    existing_response.write_text("TransferId,TransactionId,Status,ResponseCode,ResponseMessage,ProcessedTimestamp\n", encoding="utf-8")
    updates: list[tuple[str, dict[str, object]]] = []

    def _fake_select(query, params=None):
        if query == FileCompletionHandler._SQL_CHECK_COMPLETION_COUNT:
            return [{"terminal_count": 1}]
        if query == FileCompletionHandler._SQL_GET_REGISTRY_ROW_COUNT:
            return [{"row_count": 1}]
        if query == FileCompletionHandler._SQL_GET_RESPONSE_STATE:
            return [{"response_status": FileCompletionHandler._CNST_STATUS_READY, "response_file_name": None}]
        if query == FileCompletionHandler._SQL_GET_TRANSACTION_RESULTS:
            raise AssertionError("should not regenerate response when existing ready file can be finalized")
        raise AssertionError(f"Unexpected query: {query}")

    def _fake_update(query, params=None):
        updates.append((query, params or {}))
        return 0 if query == FileCompletionHandler._SQL_SET_READY_STATUS else 1

    monkeypatch.setattr(file_completion_module.DBHelper, "execute_select", _fake_select)
    monkeypatch.setattr(file_completion_module.DBHelper, "execute_update", _fake_update)

    response_file = FileCompletionHandler(response_dir=tmp_path).process_file_if_complete("file-123")

    assert response_file == existing_response
    assert updates == [
        (
            FileCompletionHandler._SQL_SET_READY_STATUS,
            {"fileId": "file-123", "responseStatus": FileCompletionHandler._CNST_STATUS_READY},
        ),
        (
            FileCompletionHandler._SQL_SET_FINAL_STATUS,
            {
                "fileId": "file-123",
                "responseStatus": FileCompletionHandler._CNST_STATUS_GENERATED,
                "responseFileName": existing_response.name,
            },
        ),
    ]


def test_generate_response_file_rejects_duplicate_transfer_ids(monkeypatch, tmp_path):
    response_rows = [
        {
            "TransferId": "PTX-001",
            "TransactionId": "PTX-001",
            "Status": "PROCESSED",
            "ResponseCode": "PT-0000",
            "ResponseMessage": "Processed successfully",
            "ProcessedTimestamp": "2026-06-06T10:00:00+00:00",
        },
        {
            "TransferId": "PTX-001",
            "TransactionId": "PTX-001",
            "Status": "FAILED",
            "ResponseCode": "PT-1900",
            "ResponseMessage": "Adapter rejected payment",
            "ProcessedTimestamp": "2026-06-06T10:01:00+00:00",
        },
    ]

    def _fake_select(query, params=None):
        if query == FileCompletionHandler._SQL_GET_TRANSACTION_RESULTS:
            return response_rows
        if query == FileCompletionHandler._SQL_GET_REGISTRY_ROW_COUNT:
            return [{"row_count": 2}]
        raise AssertionError(f"Unexpected query: {query}")

    monkeypatch.setattr(file_completion_module.DBHelper, "execute_select", _fake_select)

    with pytest.raises(RuntimeError, match="duplicate TransferId"):
        FileCompletionHandler(response_dir=tmp_path)._generate_response_file("file-123")
