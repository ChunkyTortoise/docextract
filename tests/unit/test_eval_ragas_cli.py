"""The optional evaluator must remain inspectable in a lean installation."""

import subprocess
import sys
from pathlib import Path


def test_help_without_optional_eval_dependencies():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy, sys; "
            "sys.modules.update(dict.fromkeys(['datasets', 'ragas', 'langchain_anthropic'])); "
            "sys.argv = ['scripts/eval_ragas.py', '--help']; "
            "runpy.run_path('scripts/eval_ragas.py', run_name='__main__')",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "--golden" in result.stdout
    assert "--single" in result.stdout
