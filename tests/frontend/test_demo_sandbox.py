"""Regression coverage for Fields, independent Search replay and honest mode labels."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
import textwrap
from pathlib import Path

from streamlit.testing.v1 import AppTest

ENTRY = Path(__file__).resolve().parents[2] / "streamlit_demo.py"


def test_fields_use_complete_result_renderer_without_service_imports():
    # Warm parent caches deliberately. The guard must not depend on their contents.
    importlib.import_module("frontend.demo_mode")
    importlib.import_module("frontend.pages.demo_sandbox")
    script = textwrap.dedent(
        r"""
        import importlib
        import json
        import sys
        from importlib.abc import MetaPathFinder

        assert not any(n == "frontend" or n.startswith("frontend.") for n in sys.modules)

        class FixtureOnlyImports(MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if (fullname in {"app", "worker", "frontend.api_client"}
                        or fullname.startswith(("app.", "worker.", "frontend.api_client."))):
                    raise AssertionError("Fixture-only import blocked: " + fullname)
                return None

        sys.meta_path.insert(0, FixtureOnlyImports())
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(ENTRY_PATH).run(timeout=20)
        observations = []
        for sample, expected in (
            ("invoice", "API Integration Services"),
            ("contract", "Return or destroy confidential materials upon request"),
            ("receipt", "Cold Brew"),
        ):
            app.selectbox[0].select(sample).run()
            assert not app.exception, str(app.exception)
            fields = " ".join(h.proto.body for h in app.get("html") if "desk-fields" in h.proto.body)
            assert 'class="desk-field-grid"' in fields
            assert expected in fields
            assert any(f"{sample}_sample.json" in c.value for c in app.caption)
            assert any("not calibrated accuracy" in c.value for c in app.caption)
            assert any("Cannot verify extraction" in c.value for c in app.caption)
            observations.append(sample)
        # Negative control proves the guard actually rejects a service import.
        try:
            importlib.import_module("frontend.api_client")
        except AssertionError as exc:
            assert "Fixture-only import blocked" in str(exc)
        else:
            raise AssertionError("Service import guard did not run")
        print(json.dumps(observations))
        """
    ).replace("ENTRY_PATH", repr(str(ENTRY)))
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=ENTRY.parent,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout) == ["invoice", "contract", "receipt"]


def test_fixed_search_survives_fields_switching_then_reset():
    app = AppTest.from_file(str(ENTRY)).run(timeout=20)
    replay = next(b for b in app.button if b.label == "Replay stored search")
    replay.click().run()
    for sample in ("contract", "receipt", "invoice"):
        app.selectbox[0].select(sample).run()
        assert not app.exception
        assert app.text_input[0].disabled
        assert app.text_input[0].value == "What is the total amount due on the invoice?"
        assert any("Total Amount Due: $5,286.50" in t.value for t in app.tabs[1].text)
    next(b for b in app.button if b.label == "Reset recorded search").click().run()
    assert not any("Total Amount Due: $5,286.50" in t.value for t in app.tabs[1].text)
    assert next(b for b in app.button if b.label == "Reset recorded search").disabled
    next(b for b in app.button if b.label == "Replay stored search").click().run()
    assert any("Total Amount Due: $5,286.50" in t.value for t in app.tabs[1].text)


def test_mode_labels_keep_illustrative_evidence_boundaries():
    app = AppTest.from_file(str(ENTRY)).run(timeout=20)
    assert not app.exception
    assert [t.label for t in app.tabs] == ["Fields", "Search", "Trace", "Eval", "Cost"]
    assert any("not a trace captured from this session" in c.value for c in app.caption)
    warnings = " ".join(w.value for w in app.warning)
    assert "not measured RAGAS" in warnings
    assert "not metered spend" in warnings
    assert not app.metric


def test_shell_styles_load_even_when_fields_render_fails(monkeypatch):
    sandbox = importlib.import_module("frontend.pages.demo_sandbox")

    def unavailable_fields():
        raise RuntimeError("Deliberate Fields failure for shell-style regression")

    monkeypatch.setattr(sandbox, "show", unavailable_fields)
    app = AppTest.from_file(str(ENTRY)).run(timeout=20)
    assert any("Deliberate Fields failure" in error.value for error in app.exception)
    assert any("st-key-fixture-explorer" in h.proto.body for h in app.get("html"))
