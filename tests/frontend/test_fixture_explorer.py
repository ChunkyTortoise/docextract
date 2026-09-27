"""Exercise the standalone fixture UI without backend services or model keys."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

ENTRY = Path(__file__).resolve().parents[2] / "streamlit_demo.py"


def test_each_document_selection_renders_its_own_stored_fields():
    app = AppTest.from_file(str(ENTRY)).run(timeout=20)
    assert not app.exception
    expected_fields = {
        "invoice": "Invoice Number",
        "contract": "Contract Type",
        "receipt": "Merchant Name",
    }
    for sample, expected in expected_fields.items():
        app.selectbox[0].select(sample).run()
        assert not app.exception
        assert expected in app.table[0].value["Field"].tolist()
        assert any(f"{sample}_sample.json" in c.value for c in app.caption)


def test_search_is_explicit_replay_not_an_ignored_freeform_query():
    app = AppTest.from_file(str(ENTRY)).run(timeout=20)
    assert not app.exception
    assert app.text_input[0].disabled
    assert app.text_input[0].value == "What is the total amount due on the invoice?"
    assert app.button[0].label == "Replay stored search"
    app.button[0].click().run()
    assert not app.exception
    assert any("Total Amount Due: $5,286.50" in m.value for m in app.text)


def test_seeded_metrics_cannot_be_mistaken_for_measured_results():
    app = AppTest.from_file(str(ENTRY)).run(timeout=20)
    assert not app.exception
    assert not app.metric
    warnings = " ".join(w.value for w in app.warning)
    assert "not measured RAGAS" in warnings
    assert "not metered spend" in warnings
    assert "Sample confidence" in app.table[0].value.columns
