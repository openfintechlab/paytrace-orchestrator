# -*- coding: utf-8 -*-
"""File completion checks and response CSV generation."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

try:
    from utilities.ConfigLoader import ConfigLoader
    from utilities.DBHelper import DBHelper
    from utilities.Logging import Logging
except ModuleNotFoundError:  # pragma: no cover
    from src.utilities.ConfigLoader import ConfigLoader
    from src.utilities.DBHelper import DBHelper
    from src.utilities.Logging import Logging


class FileCompletionHandler:
    """Evaluate file completion and generate one response CSV per completed file."""

    _SQL_CHECK_COMPLETION_COUNT: ClassVar[str] = """
        SELECT COUNT(*) AS terminal_count
        FROM oftl_fwcsv_row_dispatch
        WHERE file_id = :fileId
          AND status IN ('PROCESSED', 'FAILED')
    """
    _SQL_GET_REGISTRY_ROW_COUNT: ClassVar[str] = """
        SELECT row_count
        FROM oftl_fwcsv_registry
        WHERE file_id = :fileId
    """
    _SQL_SET_READY_STATUS: ClassVar[str] = """
        UPDATE oftl_fwcsv_registry
        SET response_status = :responseStatus,
            updated_at = NOW()
        WHERE file_id = :fileId
          AND COALESCE(response_status, 'PROCESSING') NOT IN ('READY_FOR_RESPONSE', 'RESP_FILE_GENERATED')
    """
    _SQL_SET_FINAL_STATUS: ClassVar[str] = """
        UPDATE oftl_fwcsv_registry
        SET response_status = :responseStatus,
            response_file_name = :responseFileName,
            response_file_generated_at = NOW(),
            updated_at = NOW()
        WHERE file_id = :fileId
          AND response_status = 'READY_FOR_RESPONSE'
    """
    _SQL_GET_TRANSACTION_RESULTS: ClassVar[str] = """
        SELECT
            transfer_id AS "TransferId",
            transfer_id AS "TransactionId",
            status AS "Status",
            CASE
                WHEN status = 'PROCESSED' THEN 'PT-0000'
                ELSE 'PT-1900'
            END AS "ResponseCode",
            COALESCE(
                error_message,
                CASE
                    WHEN status = 'PROCESSED' THEN 'Processed successfully'
                    ELSE 'Processing failed'
                END
            ) AS "ResponseMessage",
            updated_at AS "ProcessedTimestamp"
        FROM oftl_fwcsv_row_dispatch
        WHERE file_id = :fileId
          AND status IN ('PROCESSED', 'FAILED')
        ORDER BY row_number, transfer_id
    """

    _CNST_STATUS_READY: ClassVar[str] = "READY_FOR_RESPONSE"
    _CNST_STATUS_GENERATED: ClassVar[str] = "RESP_FILE_GENERATED"
    _CNST_RESPONSE_DIR_CONFIG: ClassVar[str] = "OFTL_FWCSV_RESPONSE_DIR"
    _CNST_DEFAULT_RESPONSE_DIR: ClassVar[str] = "fwcsv/response"
    _CNST_RESPONSE_FILE_SUFFIX: ClassVar[str] = "response.csv"
    _CNST_CSV_HEADERS: ClassVar[tuple[str, ...]] = (
        "TransferId",
        "TransactionId",
        "Status",
        "ResponseCode",
        "ResponseMessage",
        "ProcessedTimestamp",
    )

    def __init__(self, *, response_dir: Path | str | None = None) -> None:
        configured_response_dir = response_dir or ConfigLoader.get(
            self._CNST_RESPONSE_DIR_CONFIG,
            self._CNST_DEFAULT_RESPONSE_DIR,
        )
        self.response_dir = Path(str(configured_response_dir))

    def is_file_complete(self, file_id: str) -> bool:
        """Return True when terminal row count equals registry row_count."""
        safe_file_id = self._normalize_file_id(file_id)
        terminal_count = self._get_terminal_row_count(safe_file_id)
        expected_row_count = self._get_registry_row_count(safe_file_id)

        is_complete = expected_row_count is not None and terminal_count == expected_row_count
        Logging.info_context(
            "Evaluated file completion.",
            file_id=safe_file_id,
            terminal_count=terminal_count,
            expected_row_count=expected_row_count,
            is_complete=is_complete,
        )
        return is_complete

    def process_file_if_complete(self, file_id: str) -> Path | None:
        """Generate a response file once when all rows have reached terminal state."""
        safe_file_id = self._normalize_file_id(file_id)
        if not self.is_file_complete(safe_file_id):
            return None

        if not self._set_ready_status(safe_file_id):
            Logging.info_context(
                "Skipping response generation because file is already locked or generated.",
                file_id=safe_file_id,
            )
            return None

        response_file_path = self._generate_response_file(safe_file_id)
        self._set_final_status(safe_file_id, response_file_path.name)
        Logging.info_context(
            "Response CSV generated for completed file.",
            file_id=safe_file_id,
            response_file_name=response_file_path.name,
            response_file_path=str(response_file_path),
        )
        return response_file_path

    def _get_terminal_row_count(self, file_id: str) -> int:
        rows = DBHelper.execute_select(self._SQL_CHECK_COMPLETION_COUNT, {"fileId": file_id})
        if not rows:
            return 0
        return self._as_int(rows[0].get("terminal_count", 0) or 0)

    def _get_registry_row_count(self, file_id: str) -> int | None:
        rows = DBHelper.execute_select(self._SQL_GET_REGISTRY_ROW_COUNT, {"fileId": file_id})
        if not rows:
            return None
        return self._as_int(rows[0].get("row_count", 0) or 0)

    def _set_ready_status(self, file_id: str) -> bool:
        affected_rows = DBHelper.execute_update(
            self._SQL_SET_READY_STATUS,
            {
                "fileId": file_id,
                "responseStatus": self._CNST_STATUS_READY,
            },
        )
        return affected_rows == 1

    def _set_final_status(self, file_id: str, response_file_name: str) -> None:
        affected_rows = DBHelper.execute_update(
            self._SQL_SET_FINAL_STATUS,
            {
                "fileId": file_id,
                "responseStatus": self._CNST_STATUS_GENERATED,
                "responseFileName": response_file_name,
            },
        )
        if affected_rows != 1:
            raise RuntimeError(f"Unable to finalize response status for file_id={file_id}.")

    def _generate_response_file(self, file_id: str) -> Path:
        transaction_rows = DBHelper.execute_select(
            self._SQL_GET_TRANSACTION_RESULTS,
            {"fileId": file_id},
        )
        expected_row_count = self._get_registry_row_count(file_id)
        if expected_row_count is None:
            raise RuntimeError(f"Registry row not found for file_id={file_id}.")
        self._validate_transaction_rows(file_id, transaction_rows, expected_row_count)

        self.response_dir.mkdir(parents=True, exist_ok=True)
        response_file_path = self.response_dir / self._build_response_file_name(file_id)
        with response_file_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(self._CNST_CSV_HEADERS), extrasaction="ignore")
            writer.writeheader()
            for row in transaction_rows:
                writer.writerow(self._format_response_row(row))
        return response_file_path

    def _validate_transaction_rows(
        self,
        file_id: str,
        transaction_rows: list[dict[str, Any]],
        expected_row_count: int,
    ) -> None:
        if len(transaction_rows) != expected_row_count:
            raise RuntimeError(
                f"Response row count mismatch for file_id={file_id}: "
                f"expected {expected_row_count}, got {len(transaction_rows)}."
            )

        transfer_ids = [str(row.get("TransferId", "")).strip() for row in transaction_rows]
        if not all(transfer_ids):
            raise RuntimeError(f"Response rows contain missing TransferId values for file_id={file_id}.")
        if len(set(transfer_ids)) != len(transfer_ids):
            raise RuntimeError(f"Response rows contain duplicate TransferId values for file_id={file_id}.")

    def _build_response_file_name(self, file_id: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"{file_id}.{timestamp}.{self._CNST_RESPONSE_FILE_SUFFIX}"

    def _format_response_row(self, row: dict[str, Any]) -> dict[str, Any]:
        formatted_row = {header: row.get(header, "") for header in self._CNST_CSV_HEADERS}
        processed_timestamp = formatted_row["ProcessedTimestamp"]
        if isinstance(processed_timestamp, datetime):
            formatted_row["ProcessedTimestamp"] = processed_timestamp.astimezone(timezone.utc).isoformat()
        return formatted_row

    def _normalize_file_id(self, file_id: str) -> str:
        safe_file_id = str(file_id or "").strip()
        if not safe_file_id:
            raise ValueError("file_id is required for file completion handling.")
        return safe_file_id

    def _as_int(self, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Expected an int-compatible database value, got {value!r}.") from exc
