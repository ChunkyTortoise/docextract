"""Unit proofs for migration data-repair logic.

The pg-marked suite runs the full Alembic chain on PostgreSQL; these cover the
portable repair statements directly so the default suite pins their semantics.
"""
from __future__ import annotations

import ast
import importlib.util
import re
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


class TestServerDefaultDomains:
    """015-class guard (docs/default-domain-audit.md).

    A literal server_default may never land outside the check-constraint
    domain of its column. The scan tracks the effective default per column
    across create_table/add_column/alter_column in revision order, so a
    historical violating default repaired later passes while the unrepaired
    state would fail.
    """

    _IN_RE = re.compile(r"(\w+)\s+IN\s*\(([^)]*)\)", re.IGNORECASE)
    _LITERAL_RE = re.compile(r"'([^']*)'")

    @staticmethod
    def _const(node: ast.AST) -> str | None:
        return node.value if isinstance(node, ast.Constant) else None

    @classmethod
    def _literal(cls, node: ast.AST) -> str | None:
        """Literal value of a server_default; None for expressions (NOW(), ...)."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "text"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            raw = node.args[0].value.strip()
            if len(raw) >= 2 and raw.startswith("'") and raw.endswith("'"):
                return raw[1:-1]
        return None

    @classmethod
    def _record_column(
        cls,
        effective: dict[tuple[str, str], str | None],
        table: str | None,
        column_call: ast.AST,
    ) -> None:
        if (
            table is None
            or not isinstance(column_call, ast.Call)
            or not column_call.args
        ):
            return
        col = cls._const(column_call.args[0])
        if col is None:
            return
        for kw in column_call.keywords:
            if kw.arg == "server_default":
                effective[(table, col)] = cls._literal(kw.value)

    def _scan(self):
        domains: dict[tuple[str, str], set[str]] = {}
        effective: dict[tuple[str, str], str | None] = {}
        versions = sorted((REPO / "alembic" / "versions").glob("*.py"))
        for path in versions:
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Call):
                    continue
                fn = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else None
                )
                if fn == "create_check_constraint" and len(node.args) >= 3:
                    table = self._const(node.args[1])
                    sql = self._const(node.args[2])
                    if table and sql:
                        for col, members in self._IN_RE.findall(sql):
                            domains[(table, col)] = set(
                                self._LITERAL_RE.findall(members)
                            )
                elif fn == "create_table" and node.args:
                    table = self._const(node.args[0])
                    for sub in ast.walk(node):
                        if (
                            isinstance(sub, ast.Call)
                            and isinstance(sub.func, ast.Attribute)
                            and sub.func.attr == "Column"
                        ):
                            self._record_column(effective, table, sub)
                elif fn == "add_column" and len(node.args) >= 2:
                    self._record_column(
                        effective, self._const(node.args[0]), node.args[1]
                    )
                elif fn == "alter_column" and len(node.args) >= 2:
                    table = self._const(node.args[0])
                    col = self._const(node.args[1])
                    for kw in node.keywords:
                        if kw.arg == "server_default" and table and col:
                            effective[(table, col)] = self._literal(kw.value)
        return domains, effective

    def test_effective_defaults_stay_inside_check_domains(self):
        domains, effective = self._scan()
        assert domains, "scan found no check constraints (guard broken)"
        assert ("extracted_records", "validation_status") in domains
        violations = [
            (table, col, value, sorted(domains[(table, col)]))
            for (table, col), value in sorted(effective.items())
            if value is not None
            and (table, col) in domains
            and value not in domains[(table, col)]
        ]
        assert violations == []

    def test_model_default_matches_server_default_and_domain(self):
        from app.models.record import ExtractedRecord

        domains, effective = self._scan()
        key = ("extracted_records", "validation_status")
        model_default = ExtractedRecord.__table__.c.validation_status.default.arg
        assert model_default in domains[key]
        assert effective[key] == model_default
