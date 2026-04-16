# Contributing to DocExtract AI

## Development Setup

1. Clone and install dependencies:

```bash
git clone https://github.com/ChunkyTortoise/docextract
cd docextract
pip install -r requirements_full.txt
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

## Updating Prompts

Prompts live in `prompts/<family>/vX.Y.Z.txt` and follow semver:

- **Patch** (v1.0.1): wording tweaks, typo fixes, no behavior change
- **Minor** (v1.1.0): new field handling, structural changes, model instructions
- **Major** (v2.0.0): breaking schema changes (new required fields, removed fields)

Never edit an existing version file in place. Always create a new version.

### Workflow

1. Create the new version file:
   ```bash
   cp prompts/extraction/v1.1.0.txt prompts/extraction/v1.2.0.txt
   # edit v1.2.0.txt
   ```

2. Update `prompts/CHANGELOG.md` with the version, date, rationale, and eval delta table (required — the pre-commit hook blocks commits without it).

3. Iterate with the fast eval loop:
   ```bash
   make eval-fast   # Promptfoo only, ~20s, no cost
   make eval        # Full suite (Promptfoo + Ragas + LLM-judge), ~4 min, ~$0.44
   ```

4. Push and open a PR. The eval gate posts a before/after metric table as a sticky comment.

5. On merge, sync the new prompt to Langfuse (once `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set):
   ```bash
   python scripts/sync_langfuse.py --family extraction --version 1.2.0 --label production
   ```

6. Create the git tag:
   ```bash
   git tag prompt/extraction-v1.2.0 -m "extraction v1.2.0: brief description"
   git push origin prompt/extraction-v1.2.0
   ```

See `docs/eval-methodology.md` for the full design rationale and runbooks.

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
