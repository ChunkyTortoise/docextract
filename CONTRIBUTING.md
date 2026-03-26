# Contributing to DocExtract AI

## Development Setup

1. Clone and install dependencies:

```bash
git clone https://github.com/ChunkyTortoise/docextract
cd docextract
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env  # Set ANTHROPIC_API_KEY
```

2. Start services:

```bash
docker compose up -d postgres redis
```

## Running Tests

```bash
pytest tests/ -v                      # Full test suite
pytest tests/ -v --run-eval           # Include golden eval (requires API key)
pytest tests/ -v -k "not eval"        # Skip eval tests
```

## Linting and Type Checking

```bash
ruff check .
mypy app/ worker/ frontend/
```

## Adding a New Document Type

1. Add a schema class in `app/schemas/document_types.py`:

```python
class NewDocSchema(BaseModel):
    field_name: str
    ...
```

2. Add extraction prompts in `prompts/`:

```
prompts/
  new_doc/
    draft_prompt.txt
    verify_prompt.txt
```

3. Register in `app/services/extraction.py`:

```python
DOCUMENT_TYPES["new_doc"] = NewDocSchema
```

4. Add fixtures in `autoresearch/fixtures/`:

```
autoresearch/fixtures/new_doc_001.json
```

5. Run eval to establish baseline:

```bash
python -m autoresearch.eval --doc-type new_doc
```

## CI Requirements

All PRs must pass:
- ruff (lint)
- mypy (type check)
- pytest with 80% coverage gate
- Eval gate: 92%+ accuracy on golden dataset
- Docker build (3 images)

## PR Guidelines

- One logical change per PR
- Add tests for new behavior
- Update relevant docs in `docs/`
- Follow existing patterns (see [ARCHITECTURE.md](ARCHITECTURE.md))
