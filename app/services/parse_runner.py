"""Killable-subprocess parse execution for hard wall-clock budget enforcement.

No fitz/cv2 imports at module scope - the heavy parse stack is loaded only
inside the child process (standalone module, no app.* wiring beyond targets).
"""
from __future__ import annotations

import importlib
import multiprocessing
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.pdf_extractor import ExtractedContent

# Dotted "module:callable" so the target stays picklable across the spawn
# boundary and tests can point the runner at importable fixtures.
_INGEST_TARGET = "app.services.ingestion:ingest"

_KILL_GRACE_SECONDS = 5.0


class ParseSubprocessError(RuntimeError):
    """Raised when the parse subprocess exits without a usable result."""


def _resolve_target(target: str):
    module_name, _, attr = target.partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def _parse_child(
    conn,
    target: str,
    file_bytes: bytes,
    mime_type: str,
    filename: str,
    budget: float | None,
) -> None:
    try:
        deadline = None if budget is None else time.monotonic() + budget
        result = _resolve_target(target)(
            file_bytes, mime_type, filename, deadline=deadline
        )
        conn.send(("ok", result))
    except BaseException as exc:  # noqa: BLE001 - report any child failure
        try:
            conn.send(("err", exc))
        except Exception:
            conn.send(("err", ParseSubprocessError(f"{type(exc).__name__}: {exc}")))
    finally:
        conn.close()


def run_parse_subprocess(
    file_bytes: bytes,
    mime_type: str,
    filename: str,
    deadline: float | None = None,
    target: str | None = None,
) -> ExtractedContent:
    """Run one parse in a killable child process.

    The child receives the remaining wall-clock budget and forwards it to the
    parse entrypoint as its cooperative deadline. The parent join is
    authoritative: when the budget elapses the child is killed regardless of
    cooperation, so an unresponsive parser cannot outlive its budget.
    """
    ctx = multiprocessing.get_context("spawn")
    recv_conn, send_conn = ctx.Pipe(duplex=False)
    budget = None if deadline is None else max(0.0, deadline - time.monotonic())
    proc = ctx.Process(
        target=_parse_child,
        args=(
            send_conn,
            target or _INGEST_TARGET,
            file_bytes,
            mime_type,
            filename,
            budget,
        ),
        daemon=True,
    )
    proc.start()
    send_conn.close()
    proc.join(budget)
    if proc.is_alive():
        proc.kill()
        proc.join(_KILL_GRACE_SECONDS)
        recv_conn.close()
        raise TimeoutError("Parsing time budget exhausted")
    payload = None
    if recv_conn.poll():
        try:
            payload = recv_conn.recv()
        except EOFError:
            payload = None
    recv_conn.close()
    if payload is None:
        raise ParseSubprocessError(
            f"parse subprocess exited with code {proc.exitcode} without a result"
        )
    status, value = payload
    if status == "ok":
        return value
    raise value
