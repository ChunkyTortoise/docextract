---
spec: 2026-03-26-infrastructure-cert-mapping-hiring-signal
status: ready
complexity: deep
effort_estimate: 12-16 hours
repos: docextract (primary), finance-analytics-portfolio, multi-agent-demo, ChunkyTortoise (profile), ~/Desktop/Resumes
research: research/cert-mapping-ai-ml-hiring-signal-2026-03-26/RESEARCH.md
---

# Spec: Certification-to-Code Mapping & Hiring Signal Optimization

## 1. Context

A 6-step multi-model research pipeline (Perplexity + Gemini + Grok + ChatGPT + Claude + NotebookLM) produced clear consensus: certifications are inputs, code is output, and the bridge should be lightweight. The research identified critical gaps in the current portfolio that actively hurt hiring signal:

1. **QLoRA training scripts exist but no trained adapter** -- "scripts that never ran" is a known negative heuristic
2. **No experiment tracking** (W&B/MLflow) -- signals MLOps immaturity
3. **Cert count inconsistencies** -- 19/21/16 appear in different files
4. **GitHub Profile README** lacks a capability-focused routing table
5. **Resume variants** reference stale cert clusters and counts
6. **Non-technical certs** (marketing, social media) leak into AI applications

**Research consensus**: Applied Credentials approach is valid but secondary to live demos, test quality, and OSS contributions. Focus on 3-4 flagship repos. Never mention "21 certifications." Get ONE cloud cert (AWS GenAI Developer Pro).

## 2. Goals

- Run QLoRA fine-tuning on Colab T4, save trained adapter to `adapters/`, integrate W&B experiment tracking
- Update docextract README: metrics above fold, methodology-to-implementation cert format
- Update GitHub Profile README: compact 4-row capability table (not cert list)
- Update docs/certifications.md in docextract: methodology-to-implementation format per research
- Add lightweight "Applied Training" sections to finance-analytics-portfolio and multi-agent-demo READMEs
- Update all 5 resume variants with role-specific cert routing (4-5 certs each)
- Reconcile cert count discrepancies across all files (settle on consistent numbers)

## 3. Requirements

### Functional

**REQ-F01**: The system SHALL integrate W&B experiment tracking into `scripts/train_qlora.py` by changing `report_to="none"` to `report_to="wandb"` and adding `wandb` to optional dependencies.

**REQ-F02**: The system SHALL produce a trained QLoRA adapter by running training on a minimum of 50 examples from the existing eval dataset, saving the adapter to `adapters/invoice/<timestamp>/` and updating `adapters/registry.json`.

**REQ-F03**: The system SHALL integrate W&B experiment tracking into `scripts/train_dpo.py` by changing `report_to="none"` to `report_to="wandb"` and adding W&B project/run naming.

**REQ-F04**: The notebook `notebooks/fine_tuning_comparison.ipynb` SHALL include W&B logging cells and a cell that displays the W&B run URL for sharing.

**REQ-F05**: The docextract README SHALL display the live demo URL (`https://docextract-demo.streamlit.app`) as the first interactive element after badges.

**REQ-F06**: The docextract `docs/certifications.md` SHALL use the methodology-to-implementation format: each cert entry includes methodology learned, implementation reference (module-level, not file-level), production metric, and design decision informed.

**REQ-F07**: The GitHub Profile README (`ChunkyTortoise/README.md`) SHALL contain a compact capability table with exactly 4 rows mapping capabilities to repos (not certs to repos).

**REQ-F08**: The finance-analytics-portfolio README SHALL contain a 2-3 sentence "Applied Training" paragraph within the existing "For Hiring Managers" section.

**REQ-F09**: The multi-agent-demo README SHALL update its existing "Maps to:" line to use the methodology-to-implementation format.

**REQ-F10**: All 5 resume variants SHALL list exactly 4-5 role-specific certs per the routing table. No variant SHALL mention a total cert count.

### Non-Functional

**REQ-NF01**: All cert count references across files SHALL be reconciled: mapped certs (varies by repo), total completed (21), and hours (1,831h total) must be internally consistent.

**REQ-NF02**: The QLoRA training MUST run on Google Colab T4 free tier (15GB VRAM). Batch size, sequence length, and gradient accumulation must fit within this constraint.

**REQ-NF03**: W&B integration MUST be optional -- training scripts must still work with `report_to="none"` when `WANDB_API_KEY` is not set.

**REQ-NF04**: No new repos shall be created. All changes are to existing repos.

**REQ-NF05**: Cert mappings SHALL reference modules/directories (e.g., `app/services/`) not individual files, to reduce Code Drift maintenance burden.

## 4. Architecture Decisions

### ADR-01: W&B over MLflow for experiment tracking
**Status**: Accepted
**Context**: Need experiment tracking for QLoRA training to show in portfolio.
**Decision**: Use Weights & Biases (wandb) instead of MLflow.
**Rationale**: W&B has: (1) free tier with public projects, (2) shareable dashboard URLs (critical for README linking), (3) native HuggingFace Trainer integration (one-line change: `report_to="wandb"`), (4) higher hiring manager name recognition than MLflow in AI startup ecosystem. MLflow requires self-hosting for shared dashboards.

### ADR-02: Module-level cert references over file-level
**Status**: Accepted
**Context**: Code Drift identified as #1 maintenance risk by Gemini analysis.
**Decision**: Reference `app/services/` modules and `tests/` directories, not specific `.py` files.
**Rationale**: Module-level references survive file renames, refactors, and splits. Individual file references break within weeks. The methodology-to-implementation format (what you learned -> what you built -> metric) is more durable than file pointers.

### ADR-03: 4-row capability table over cert matrix in profile README
**Status**: Accepted
**Context**: Gemini recommended Hub-and-Spoke Traceability Matrix; Contrarian analysis showed hiring managers spend 30-90s on GitHub.
**Decision**: Compact 4-row table mapping production capabilities (not cert names) to repos.
**Rationale**: Capabilities ("Production RAG Pipeline", "Classical ML Portfolio") are what hiring managers search for. Cert names are secondary. 4 rows fit in one screen without scrolling.

### ADR-04: Reconcile cert counts to "21 completed" consistently
**Status**: Accepted
**Context**: 19/21/16 appear in different files causing confusion.
**Decision**: Total = 21 completed. Per-repo mapped = varies (14 in docextract, 16 in finance-analytics). Never state total in AI applications. Only state mapped count per repo.
**Rationale**: Research consensus: never mention "21 certifications" anywhere visible to AI/ML hiring managers. Per-repo mapped counts are factual and non-alarming. The portfolio site meta tags (21) are for SEO, not hiring.

## 5. Implementation Waves

### Wave 1: QLoRA Training + W&B Integration (docextract)
**Exit gate**: Trained adapter exists in `adapters/`, W&B run URL is accessible, `registry.json` is populated.

#### Task 1.1: Add W&B to training scripts
```json
{
  "subject": "Add W&B experiment tracking to QLoRA and DPO training scripts",
  "description": "In scripts/train_qlora.py: (1) Add 'import wandb' with try/except ImportError fallback. (2) Change report_to='none' to report_to='wandb' when WANDB_API_KEY is set, else keep 'none'. (3) Add wandb.init() with project='docextract-finetune', run name from doc_type+timestamp. (4) Log final metrics (train_loss, eval_loss, adapter_path) as wandb.summary. Same changes in scripts/train_dpo.py. (5) Add 'wandb>=0.16.0' to requirements_full.txt under a '# Experiment tracking (optional)' comment. (6) Update notebooks/fine_tuning_comparison.ipynb: add pip install wandb cell, add wandb.init cell after setup, add wandb.log calls in training cells.",
  "activeForm": "Adding W&B experiment tracking"
}
```

#### Task 1.2: Run QLoRA training on Colab T4
```json
{
  "subject": "Run QLoRA training and save adapter artifacts",
  "description": "Create a Colab-ready training script or use the existing notebook. (1) Export 50+ supervised examples from autoresearch/eval_dataset.json (convert golden eval fixtures to supervised JSONL format: system prompt + document text -> expected extraction). (2) Run train_qlora.py with --doc-type=invoice --epochs=3 --batch-size=2 (fits T4 15GB with Mistral-7B 4-bit). (3) Save adapter to adapters/invoice/<timestamp>/. (4) Verify registry.json is updated with the new adapter entry. (5) Commit adapter config files (adapter_config.json, adapter_model.safetensors if small enough, or .gitignore large files and document download URL). (6) Screenshot or export W&B dashboard showing training curves (loss, lr, gradient norm).",
  "activeForm": "Training QLoRA adapter on Colab"
}
```

### Wave 2: README Updates (docextract + profile)
**Exit gate**: docextract README has metrics above fold + W&B link. Profile README has 4-row capability table. All cert counts reconciled.
**Blocked by**: Wave 1 (needs W&B run URL and adapter existence for README references)

#### Task 2.1: Update docextract README
```json
{
  "subject": "Update docextract README with hiring signal optimizations",
  "description": "Edit ~/Projects/docextract/README.md: (1) Ensure live demo link (https://docextract-demo.streamlit.app) appears immediately after badges, before the 'For Hiring Managers' table. (2) Add W&B experiment tracking link to the Performance section or a new 'Model Training' subsection: 'Fine-tuned adapter trained via QLoRA on Mistral-7B — [W&B Dashboard](URL)'. (3) Update test count to current number (verify with pytest --co -q | tail -1). (4) In the 'For Hiring Managers' table, update the AI/ML Engineer row to include 'Fine-tuning: scripts/train_qlora.py, adapters/' in the code files column. (5) Verify architecture Mermaid diagram still renders correctly. Do NOT change the overall README structure — it is already well-organized.",
  "activeForm": "Updating docextract README"
}
```

#### Task 2.2: Update docextract docs/certifications.md
```json
{
  "subject": "Rewrite docs/certifications.md to methodology-to-implementation format",
  "description": "Rewrite ~/Projects/docextract/docs/certifications.md using this format per cert entry:\n\n## [Cert Name] — [Issuer] ([Hours]h)\n**Methodology learned**: [1 sentence: what the cert taught]\n**Applied in**: `app/services/[module]/` — [what was built using this methodology]\n**Production metric**: [accuracy, test count, or latency number]\n**Design decision informed**: [1 sentence referencing an ADR or architectural choice]\n\nKeep the existing 14 mapped certs. Change code references from individual file links to module-level references (e.g., app/services/ not app/services/claude_extractor.py). Keep the bottom note about 7 unmapped certs but reword: 'Additional certifications in data analytics and marketing inform business understanding but are not directly mapped to this codebase.' Update total hours if changed. Do NOT add Credly/verification URLs (not all certs have them).",
  "activeForm": "Rewriting certifications.md"
}
```

#### Task 2.3: Update GitHub Profile README
```json
{
  "subject": "Rewrite GitHub Profile README with 4-row capability table",
  "description": "Edit ~/Projects/ChunkyTortoise/README.md. Replace current content with:\n\n# Cayman Roden\nAI Engineer — Roden AI Solutions\n\n| Capability | Repository | Signal |\n|---|---|---|\n| Production RAG Pipeline | [docextract](link) | 1,183 tests, 94.6% accuracy, QLoRA fine-tuning, [Live Demo](https://docextract-demo.streamlit.app) |\n| Classical ML & Analytics | [finance-analytics-portfolio](link) | 1,422 tests, 21 analysis modules, dbt analytics, SHAP explainability |\n| Multi-Agent Orchestration | [multi-agent-demo](link) | LangGraph state machines, parallel fan-out, 89 tests |\n| Open Source | [mcp-server-toolkit](link) | PyPI published, 412 tests, 9 MCP servers |\n\n**OSS Contributions**: LiteLLM #24551, pgvector-python #151, FastAPI #15217\n\nStack badges: Python, FastAPI, Claude API, pgvector, dbt, Docker\nFooter: Portfolio link, LinkedIn, email\n\nDo NOT include any cert count, cert list, or 'certifications' word. The table is capability-first. Remove the existing DA/BI cert badge from header.",
  "activeForm": "Rewriting GitHub Profile README"
}
```

### Wave 3: Supporting Repos + Resume Updates
**Exit gate**: finance-analytics and multi-agent READMEs updated. All 5 resume variants have role-specific cert routing. No file mentions "21 certifications."
**Blocked by**: Wave 2 (profile README must be finalized first for consistency)

#### Task 3.1: Update finance-analytics-portfolio README
```json
{
  "subject": "Add Applied Training context to finance-analytics-portfolio README",
  "description": "Edit ~/Projects/finance-analytics-portfolio/README.md. In the existing 'For Hiring Managers' table, update the 'Training behind it' column to use methodology-to-implementation format: instead of just cert names and hours, write 'Applied [cert concept] to build [feature] — see [module]'. Example: 'Applied Google Advanced DA regression methodology to build credit risk scoring pipeline — see analysis/credit_models.py'. Keep it concise (1 line per row). Do NOT add a separate certifications section. Do NOT change the link to docs/certifications.md or the '1,541h across 16 certifications' text (it is accurate for this repo). Fix the discrepancy: the Credentials page says '21 professional certifications' but should say '21 completed courses, 16 applied in this repo'.",
  "activeForm": "Updating finance-analytics README"
}
```

#### Task 3.2: Update multi-agent-demo README
```json
{
  "subject": "Update multi-agent-demo cert reference to methodology format",
  "description": "Edit ~/Projects/multi-agent-demo/README.md line 12. Change the current blockquote:\n> Maps to: IBM RAG and Agentic AI cert, Duke LLMOps cert, IBM GenAI Engineering cert\n\nTo methodology-to-implementation format:\n> Built using patterns from IBM RAG & Agentic AI (LangGraph state machines, tool-augmented agents) and Duke LLMOps (CI/CD pipeline, deployment patterns). See src/orchestrator.py for parallel fan-out implementation.\n\nKeep it as a single blockquote. Do NOT add a docs/certifications.md file to this repo.",
  "activeForm": "Updating multi-agent-demo README"
}
```

#### Task 3.3: Update 5 resume variants with cert routing
```json
{
  "subject": "Update resume variants with role-specific cert routing",
  "description": "Update ~/Desktop/Resumes/application-guide.md cert clusters table AND the corresponding resume markdown sources (if they exist at ~/Desktop/Resumes/*.md). For each variant, list exactly 4-5 certs:\n\nAI Engineer: DeepLearning.AI Deep Learning Spec, IBM GenAI Engineering, IBM RAG & Agentic AI, AWS GenAI Developer Pro (pending), Anthropic Claude Code\nPython Developer: Python for Everybody, Google Advanced Analytics, DeepLearning.AI Deep Learning Spec, Linux Foundation OSS/Git, Duke LLMOps\nData Analyst: Google Data Analytics, Google Advanced Analytics, IBM BI Analyst, Microsoft Data Visualization, Microsoft AI-Enhanced Analysis\nSolutions Engineer: IBM GenAI Engineering, Vanderbilt GenAI Leader, Google Cloud GenAI, Anthropic Claude Code, AWS GenAI Developer Pro (pending)\nSoftware Engineer: DeepLearning.AI Deep Learning Spec, Linux Foundation OSS/Git, Duke LLMOps, IBM GenAI Engineering, Python for Everybody\n\nIn application-guide.md: (1) Update the cert clusters table. (2) Change '19 professional certifications' in Quick Differentiators to just list the top 3 issuers without a count: 'Professional certifications from DeepLearning.AI, IBM, and Google'. (3) Remove any reference to total cert count.\n\nDo NOT regenerate PDFs (that requires pandoc + weasyprint and is a separate task).",
  "activeForm": "Updating resume cert routing"
}
```

#### Task 3.4: Reconcile cert counts across all files
```json
{
  "subject": "Reconcile cert count discrepancies across portfolio",
  "description": "Fix these specific discrepancies found during exploration:\n\n1. ~/Projects/personal/chunkytortoise.github.io/certifications.html: Body text says '19 certifications' but meta says '21'. The filter button says 'All (19)'. Change body + button to '21' to match meta and actual count.\n2. ~/Projects/ChunkyTortoise/README.md: Remove the 'DA/BI certs - 7 (917h)' badge entirely (replaced by capability table in Task 2.3).\n3. ~/Projects/finance-analytics-portfolio/README.md: The Credentials page description says '21 professional certifications'. Change to '21 completed courses, 16 applied in this codebase'.\n4. Verify ~/Projects/docextract/docs/certifications.md says '14 certifications mapped' (not a total count).\n5. Verify no file in the portfolio says 'XX certifications' as a headline number visible to AI/ML hiring managers. Cert counts should only appear in per-repo context ('14 mapped to this codebase').",
  "activeForm": "Reconciling cert counts"
}
```

### Wave 4: Verification
**Exit gate**: All changes verified, no broken links, no cert count discrepancies, W&B dashboard accessible.

#### Task 4.1: Cross-repo verification
```json
{
  "subject": "Verify all changes across repos",
  "description": "Run verification checks:\n1. In docextract: pytest tests/ --co -q | tail -1 (verify test count matches README)\n2. In docextract: verify adapters/registry.json has at least 1 adapter entry\n3. In docextract: verify docs/certifications.md uses module-level references (grep for '.py)' — should find 0 individual file links)\n4. In all repos: grep -r '21 certifications' across docextract/, finance-analytics-portfolio/, multi-agent-demo/, ChunkyTortoise/, Desktop/Resumes/ — should find 0 matches in hiring-visible contexts\n5. In all repos: grep -r '19 certifications' — should find 0 matches except portfolio site SEO meta\n6. Verify GitHub Profile README has exactly 4 rows in capability table\n7. Verify each resume variant in application-guide.md lists exactly 4-5 certs\n8. Verify W&B dashboard URL is accessible (curl the URL, expect 200)",
  "activeForm": "Running cross-repo verification"
}
```

## 6. Cert-to-Role Routing Table

| Resume Variant | Cert 1 | Cert 2 | Cert 3 | Cert 4 | Cert 5 | Flagship Repo |
|---|---|---|---|---|---|---|
| AI Engineer | DeepLearning.AI DL Spec | IBM GenAI Engineering | IBM RAG & Agentic AI | AWS GenAI Dev Pro* | Anthropic Claude Code | docextract |
| Python Developer | Python for Everybody | Google Advanced Analytics | DeepLearning.AI DL Spec | Linux Foundation OSS | Duke LLMOps | finance-analytics |
| Data Analyst | Google Data Analytics | Google Advanced Analytics | IBM BI Analyst | Microsoft Data Viz | MS AI-Enhanced Analysis | finance-analytics |
| Solutions Engineer | IBM GenAI Engineering | Vanderbilt GenAI Leader | Google Cloud GenAI | Anthropic Claude Code | AWS GenAI Dev Pro* | EnterpriseHub |
| Software Engineer | DeepLearning.AI DL Spec | Linux Foundation OSS | Duke LLMOps | IBM GenAI Engineering | Python for Everybody | docextract |

*pending — register and study as separate Tier 2 action

## 7. Quality Gates

| AC | Layer | Verification Method | Command | Pass Criteria |
|---|---|---|---|---|
| Adapter exists | 0 (Structural) | File check | `test -f adapters/invoice/*/adapter_config.json` | File exists |
| Registry populated | 0 (Structural) | JSON check | `python -c "import json; d=json.load(open('adapters/registry.json')); assert len(d['adapters'])>0"` | At least 1 adapter |
| W&B optional | 1 (Semantic) | Unit test | `WANDB_API_KEY= python -c "from scripts.train_qlora import main"` | No ImportError |
| Tests still pass | 1 (Semantic) | Test suite | `pytest tests/ -x -q` | Exit 0 |
| No cert count leaks | 2 (Conformance) | Grep | `grep -rn '21 certifications\|19 certifications' README.md docs/ ~/Desktop/Resumes/application-guide.md` | 0 matches |
| Profile table rows | 2 (Conformance) | Manual check | Count rows in ChunkyTortoise/README.md capability table | Exactly 4 |
| Resume cert count | 2 (Conformance) | Manual check | Each variant in application-guide.md | 4-5 certs per variant |

## 8. Files Modified

### docextract (primary)
- `scripts/train_qlora.py` — add W&B integration
- `scripts/train_dpo.py` — add W&B integration
- `notebooks/fine_tuning_comparison.ipynb` — add W&B cells
- `requirements_full.txt` — add `wandb>=0.16.0`
- `adapters/registry.json` — populated by training run
- `adapters/invoice/<timestamp>/` — new adapter files (created by training)
- `README.md` — metrics, W&B link, test count
- `docs/certifications.md` — methodology-to-implementation rewrite

### ChunkyTortoise (GitHub profile)
- `README.md` — complete rewrite to 4-row capability table

### finance-analytics-portfolio
- `README.md` — update "For Hiring Managers" table, fix Credentials page description

### multi-agent-demo
- `README.md` — update line 12 blockquote to methodology format

### Portfolio site
- `personal/chunkytortoise.github.io/certifications.html` — fix 19→21 discrepancy

### Resumes
- `~/Desktop/Resumes/application-guide.md` — cert clusters, remove total count

## 9. Rollback Plan

All changes are documentation/config updates (no DB migrations, no API changes). Rollback = `git checkout HEAD~1 -- <file>` per repo. No data loss risk.

For the QLoRA training: adapter files are additive (new directory). Rollback = delete `adapters/invoice/<timestamp>/` and reset `registry.json` to `{"version":"1.0","adapters":[]}`.

## 10. Dependencies & Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Colab T4 OOM during QLoRA training | Medium | Blocks Wave 1 | Reduce batch_size to 1, max_seq_length to 256, gradient_accumulation to 8 |
| W&B free tier rate limits | Low | Blocks W&B dashboard link | Use `WANDB_MODE=offline` and export manually |
| Adapter files too large for git | Medium | Can't commit artifacts | .gitignore safetensors, commit only adapter_config.json + README with download instructions |
| Colab session timeout during training | Medium | Incomplete training | Use --epochs=1 for first run, verify completion, then optionally run more epochs |

## 11. Research Gaps & Assumptions

| Gap | Assumption | Confidence |
|---|---|---|
| Whether docs/certifications.md files are actually viewed | They serve as interview prep artifacts even if not browsed on GitHub | MEDIUM |
| GitHub -> interview conversion rate | Portfolio polish has indirect value through interview confidence | LOW |
| W&B free tier project visibility | Public projects are viewable by anyone with the URL | HIGH |
| Colab T4 can fit Mistral-7B 4-bit + LoRA training | Standard for QLoRA; r=16 adds ~40MB to 4GB base | HIGH |
| Career change narrative effectiveness | Not addressed in this spec; separate effort | N/A |

## 12. Success Criteria

1. `adapters/registry.json` contains at least 1 trained adapter entry
2. W&B dashboard URL is accessible and shows training curves
3. docextract README mentions fine-tuning with W&B link
4. GitHub Profile README has exactly 4 capability rows, zero cert counts
5. Zero files across portfolio contain "21 certifications" or "19 certifications" in hiring-visible contexts
6. Each resume variant lists exactly 4-5 role-specific certs
7. All existing tests continue to pass (`pytest tests/` in docextract)
