"""Keep mocked frontend dependencies local to each legacy unit test."""

import sys
from unittest.mock import MagicMock

import pandas  # noqa: F401
import plotly.express  # noqa: F401
import plotly.graph_objects  # noqa: F401
import pytest
import streamlit  # noqa: F401


@pytest.fixture(autouse=True)
def isolate_frontend_modules(request):
    """Restore real UI dependencies and cached frontend modules after each test."""
    dependency_names = (
        "streamlit",
        "plotly",
        "plotly.express",
        "plotly.graph_objects",
        "pandas",
    )
    dependencies = {name: sys.modules[name] for name in dependency_names}
    frontend_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "frontend" or name.startswith("frontend.")
    }
    factory = getattr(request.module, "_make_st_stub", None) or getattr(
        request.module, "_make_streamlit_stub", None
    )
    if factory is not None:
        sys.modules["streamlit"] = factory()
        for name in ("plotly", "plotly.express", "plotly.graph_objects"):
            sys.modules[name] = MagicMock(name=name)
        for name in frontend_modules:
            sys.modules.pop(name, None)
    try:
        yield
    finally:
        sys.modules.update(dependencies)
        for name in list(sys.modules):
            if name == "frontend" or name.startswith("frontend."):
                sys.modules.pop(name, None)
        sys.modules.update(frontend_modules)
