"""Unit proofs for migration data-repair logic.

The pg-marked suite runs the full Alembic chain on PostgreSQL; these cover the
portable repair statements directly so the default suite pins their semantics.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import sqlalchemy as sa

REPO = Path(__file__).resolve().parents[2]


def _load_migration(filename: str):
    """Load a version module by path (file names start with a digit)."""
    path = REPO / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDedupeKeepFirst:
    def _conn_with_rows(self, rows: list[tuple[str, str, str]]) -> sqlite3.Connection:
        migration = _load_migration("013_record_job_unique.py")
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE extracted_records ("
            "id TEXT PRIMARY KEY, job_id TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO extracted_records VALUES (?, ?, ?)", rows
        )
        conn.execute(migration.DEDUPE_KEEP_FIRST_SQL)
        return conn

    def test_duplicates_reduced_to_earliest_record_per_job(self):
        conn = self._conn_with_rows([
            ("r-old", "job-1", "2026-09-01T00:00:00"),
            ("r-new", "job-1", "2026-09-02T00:00:00"),
            ("r-mid", "job-1", "2026-09-01T12:00:00"),
            ("r-solo", "job-2", "2026-09-05T00:00:00"),
        ])
        remaining = [
            r[0]
            for r in conn.execute("SELECT id FROM extracted_records ORDER BY id")
        ]
        conn.close()
        assert remaining == ["r-old", "r-solo"]

    def test_created_at_ties_break_deterministically_on_id(self):
        conn = self._conn_with_rows([
            ("b-tie", "job-1", "2026-09-01T00:00:00"),
            ("a-tie", "job-1", "2026-09-01T00:00:00"),
        ])
        remaining = [r[0] for r in conn.execute("SELECT id FROM extracted_records")]
        conn.close()
        assert remaining == ["a-tie"]

    def test_clean_table_is_untouched(self):
        conn = self._conn_with_rows([
            ("r-1", "job-1", "2026-09-01T00:00:00"),
            ("r-2", "job-2", "2026-09-02T00:00:00"),
        ])
        remaining = [
            r[0]
            for r in conn.execute("SELECT id FROM extracted_records ORDER BY id")
        ]
        conn.close()
        assert remaining == ["r-1", "r-2"]


class TestEvalLogTypeRepairGate:
    def test_legacy_string_columns_are_detected(self):
        migration = _load_migration("014_eval_log_type_repair.py")
        assert migration._is_legacy_string(sa.String(36)) is True
        assert migration._is_legacy_string(sa.CHAR(36)) is True

    def test_uuid_columns_are_not_touched(self):
        from sqlalchemy.dialects.postgresql import UUID

        migration = _load_migration("014_eval_log_type_repair.py")
        assert migration._is_legacy_string(UUID(as_uuid=False)) is False
        assert migration._is_legacy_string(sa.Uuid()) is False
        assert migration._is_legacy_string(None) is False
