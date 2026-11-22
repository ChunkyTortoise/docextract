"""Exact DocExtract source integration, isolated settings and mock transport only."""

from __future__ import annotations

import ast
import importlib
import json
import logging
import os
import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
from anthropic import AsyncAnthropic

from attempt_meter import AttemptMeter, MeterStop
from runner import REPO, digest

LOG = logging.getLogger(__name__)
BINDING = Path(__file__).with_name("EXECUTION-BINDING.json")


def verify_binding() -> None:
    binding = json.loads(BINDING.read_text())
    if (
        digest(BINDING.parent / "candidate/claude_extractor.py")
        != binding["candidate_extractor_sha256"]
    ):
        raise ValueError("Candidate extractor changed")
    for relative, sha in binding["source_hashes"].items():
        if digest(REPO / relative) != sha:
            raise ValueError("Immutable extractor source changed: " + relative)


def load_extractor():
    """Reuse the actual Settings class, bypass only ambient .env instantiation."""
    verify_binding()
    sys.dont_write_bytecode = True
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    if "app.config" not in sys.modules:
        path = REPO / "app/config.py"
        tree = ast.parse(path.read_text(), filename=str(path))
        matches = [
            n
            for n in tree.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "settings" for t in n.targets)
        ]
        if len(matches) != 1 or ast.unparse(matches[0].value) != "Settings()":
            raise ValueError("Unexpected settings initialization")
        tree.body.remove(matches[0])
        module = types.ModuleType("app.config")
        module.__file__ = str(path)
        module.__package__ = "app"
        sys.modules["app.config"] = module
        exec(compile(tree, str(path), "exec"), module.__dict__)
        with patch.dict(os.environ, {}, clear=True):
            module.settings = module.Settings(
                _env_file=None,
                anthropic_api_key="synthetic-not-a-secret",
                langsmith_enabled=False,
                langfuse_enabled=False,
                otel_enabled=False,
                active_learning_enabled=False,
            )
    name = "app.services.claude_extractor"
    if not getattr(sys.modules.get(name), "_heldout_candidate", False):
        importlib.import_module(name)
        path = BINDING.parent / "candidate/claude_extractor.py"
        binding = json.loads(BINDING.read_text())
        if digest(path) != binding["candidate_extractor_sha256"]:
            raise ValueError("Candidate extractor changed")
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        module._heldout_candidate = True
    return sys.modules[name]


class ExtractorAdapter:
    kind = "fake"

    def __init__(self, meter: AttemptMeter) -> None:
        self.meter = meter
        self.module = load_extractor()
        self.case_id = None
        self.offset = 0
        self.client_count = 0

    @property
    def accounting_complete(self) -> bool:
        return self.meter.blocked is None and self.meter.reserved == 0

    def bound(self, case: dict):
        verify_binding()
        self.case_id = case["id"]
        # At most 3 Instructor attempts and one correction per routed model.
        return 4 * sum(p.bound(4096) for p in self.meter.models.values())

    def clear(self) -> None:
        self.offset = len(self.meter.rows)
        self.meter.set_context(self.case_id, "extract")

    def traces(self) -> list[dict]:
        return self.meter.receipt()["attempts"][self.offset :]

    async def extract(self, text: str, doc_type: str):
        verify_binding()
        if doc_type not in ("invoice", "receipt", "purchase_order") or not self.case_id:
            raise ValueError("Only declared text extraction document types are allowed")
        if not self.accounting_complete:
            raise MeterStop("Accounting halted before extraction")
        tracer = importlib.import_module("app.services.llm_tracer")
        settings = self.module.settings
        original_trace = tracer.trace_llm_call

        @asynccontextmanager
        async def trace(db, model, operation, *args, **kwargs):
            if db is not None:
                raise ValueError("Database operations are outside the text-only run")
            self.meter.set_context(self.case_id, operation)
            async with original_trace(db, model, operation, *args, **kwargs) as context:
                yield context

        async with httpx.AsyncClient(
            transport=self.meter, trust_env=False, follow_redirects=False
        ) as http:
            guarded = AsyncAnthropic(
                api_key="synthetic-not-a-secret", http_client=http, max_retries=0
            )

            def factory(*args, **kwargs):
                if args or set(kwargs) != {"api_key"}:
                    raise ValueError(
                        "Unexpected unguarded provider constructor configuration"
                    )
                self.client_count += 1
                return guarded

            with (
                patch.object(self.module, "AsyncAnthropic", factory),
                patch.object(tracer, "trace_llm_call", trace),
                patch.object(settings, "extraction_models", list(self.meter.models)),
                patch.object(settings, "active_learning_enabled", False),
            ):
                tracer.clear_in_memory_traces()
                result = await self.module.extract(
                    text, doc_type, db=None, citations=False, reflection=False
                )
        # Source correction handler can swallow a meter error. Fail the case.
        if not self.accounting_complete:
            LOG.warning("Extractor returned after meter halt for %s", self.case_id)
            raise MeterStop("Extraction incomplete because provider accounting halted")
        return result
