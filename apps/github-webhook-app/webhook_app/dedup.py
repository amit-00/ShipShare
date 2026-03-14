from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DeliveryRecord:
    github_delivery_id: str
    event_type: str
    action: str | None
    installation_id: int | None
    payload_hash: str
    processing_status: str
    last_error: str | None


class DeliveryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS webhook_delivery (
                    github_delivery_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    action TEXT,
                    installation_id INTEGER,
                    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    processing_status TEXT NOT NULL,
                    last_error TEXT,
                    payload_hash TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def accept_delivery(
        self,
        github_delivery_id: str,
        event_type: str,
        action: str | None,
        installation_id: int | None,
        payload_hash: str,
    ) -> bool:
        with closing(sqlite3.connect(self.db_path)) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO webhook_delivery (
                    github_delivery_id,
                    event_type,
                    action,
                    installation_id,
                    processing_status,
                    payload_hash
                ) VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (github_delivery_id, event_type, action, installation_id, payload_hash),
            )
            connection.commit()
            return cursor.rowcount == 1

    def mark_processed(self, github_delivery_id: str) -> None:
        self._update_status(github_delivery_id, "processed", None)

    def mark_failed(self, github_delivery_id: str, error: str) -> None:
        self._update_status(github_delivery_id, "failed", error[:1000])

    def get(self, github_delivery_id: str) -> DeliveryRecord | None:
        with closing(sqlite3.connect(self.db_path)) as connection:
            row = connection.execute(
                """
                SELECT github_delivery_id, event_type, action, installation_id, payload_hash, processing_status, last_error
                FROM webhook_delivery
                WHERE github_delivery_id = ?
                """,
                (github_delivery_id,),
            ).fetchone()
        if row is None:
            return None
        return DeliveryRecord(*row)

    def _update_status(self, github_delivery_id: str, status: str, error: str | None) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """
                UPDATE webhook_delivery
                SET processing_status = ?, last_error = ?
                WHERE github_delivery_id = ?
                """,
                (status, error, github_delivery_id),
            )
            connection.commit()
