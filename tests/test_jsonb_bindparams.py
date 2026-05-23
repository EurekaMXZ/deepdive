from __future__ import annotations

import unittest

from sqlalchemy.dialects.postgresql import JSONB

from backend.api.services import PostgresAnalysisService
from backend.events import EventEnvelope, EventType
from backend.events.repositories import DbOutboxSink
from backend.ids import new_uuid7


class JsonbBindparamTest(unittest.IsolatedAsyncioTestCase):
    async def test_postgres_analysis_create_binds_jsonb_parameters(self) -> None:
        connection = CapturingConnection()
        service = PostgresAnalysisService(FakeDatabase(connection))

        await service.create(
            repository_url="https://github.com/EurekaMXZ/relaybot",
            requested_ref="HEAD",
        )

        config_statement = connection.statement_containing("INSERT INTO config_snapshots")
        session_statement = connection.statement_containing("INSERT INTO agent_sessions")
        outbox_statement = connection.statement_containing("INSERT INTO outbox_events")

        self.assertIsInstance(config_statement._bindparams["config_json"].type, JSONB)
        self.assertIsInstance(session_statement._bindparams["effective_limits_json"].type, JSONB)
        self.assertIsInstance(session_statement._bindparams["effective_runtime_json"].type, JSONB)
        self.assertIsInstance(outbox_statement._bindparams["payload_json"].type, JSONB)

    async def test_db_outbox_sink_binds_payload_json_as_jsonb(self) -> None:
        connection = CapturingConnection()

        await DbOutboxSink(connection).add(
            EventEnvelope.new(
                event_type=EventType.ANALYSIS_REQUESTED,
                analysis_id=new_uuid7(),
                payload={"repository_url": "https://github.com/EurekaMXZ/relaybot"},
            )
        )

        statement = connection.statement_containing("INSERT INTO outbox_events")

        self.assertIsInstance(statement._bindparams["payload_json"].type, JSONB)


class FakeDatabase:
    def __init__(self, connection: "CapturingConnection") -> None:
        self.connection = connection

    def begin(self) -> "FakeTransaction":
        return FakeTransaction(self.connection)


class FakeTransaction:
    def __init__(self, connection: "CapturingConnection") -> None:
        self.connection = connection

    async def __aenter__(self) -> "CapturingConnection":
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class CapturingConnection:
    def __init__(self) -> None:
        self.executed = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        return FakeResult([])

    def statement_containing(self, text: str):
        for statement, _ in self.executed:
            if text in str(statement):
                return statement
        raise AssertionError(f"Statement containing {text!r} was not executed")


class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "FakeResult":
        return self

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[dict]:
        return self._rows


if __name__ == "__main__":
    unittest.main()
