"""Durable local inbox/outbox. A future queue transport keeps the same contract."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from .contracts import A2AMessage


class DuckDBMessageBus:
    def __init__(self, path: Path) -> None:
        self._connection = duckdb.connect(str(path))
        self._connection.execute(
            """
            create table if not exists a2a_messages (
                message_id varchar primary key,
                idempotency_key varchar unique not null,
                recipient varchar not null,
                status varchar not null,
                payload json not null
            )
            """
        )
        self._connection.execute(
            "alter table a2a_messages add column if not exists idempotency_key varchar"
        )
        self._connection.execute(
            "update a2a_messages set idempotency_key = "
            "json_extract_string(payload, '$.idempotency_key') where idempotency_key is null"
        )
        self._connection.execute(
            "create unique index if not exists a2a_messages_idempotency "
            "on a2a_messages(idempotency_key)"
        )

    def publish(self, message: A2AMessage) -> bool:
        """Write once by idempotency key; duplicate deliveries are harmless."""

        exists = self._connection.execute(
            "select 1 from a2a_messages where idempotency_key = ?", [message.idempotency_key]
        ).fetchone()
        if exists is not None:
            return False
        self._connection.execute(
            "insert into a2a_messages values (?, ?, ?, 'pending', ?)",
            [
                str(message.message_id),
                message.idempotency_key,
                message.recipient,
                json.dumps(message.model_dump(mode="json")),
            ],
        )
        return True

    def inbox(self, recipient: str) -> list[A2AMessage]:
        rows = self._connection.execute(
            "select payload from a2a_messages "
            "where recipient = ? and status = 'pending' order by message_id",
            [recipient],
        ).fetchall()
        return [A2AMessage.model_validate_json(payload) for (payload,) in rows]

    def acknowledge(self, message_id: str) -> None:
        self._connection.execute(
            "update a2a_messages set status = 'acknowledged' where message_id = ?", [message_id]
        )
