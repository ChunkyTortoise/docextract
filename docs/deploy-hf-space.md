# Deploy the offline replay demo to a Hugging Face Space

`space_app.py` is a Streamlit page that re-scores the 28 committed prediction fixtures and shows, per fixture, the source text, the frozen prediction, the expected output and any values not found in the source. It calls no model and needs no API key or Space secret. The numbers it shows are computed by the same scorers as `scripts/eval_offline_replay.py` and `scripts/eval_hallucination.py`; `tests/unit/test_space_app.py` fails if they diverge.

Nothing here has been deployed. These are the steps for the repository owner.

## 1. Check it locally

```bash
python3 -m venv .venv-demo
.venv-demo/bin/python -m pip install -r requirements_demo.txt
.venv-demo/bin/python -m streamlit run space_app.py
```

The page should show a weighted field-level score of 0.9555 and 474/482 values grounded.

## 2. Build the Space folder

```bash
scripts/build_hf_space.sh /tmp/docextract-space
```

This copies `space_app.py`, `LICENSE`, the scorer modules, `eval_dataset_72.json`, `baseline.json` and `autoresearch/golden_responses/` into a new folder, and writes a `requirements.txt` (Streamlit only) and a `README.md` with the Space front matter (`sdk: streamlit`, `app_file: space_app.py`). The folder is about 37 files and under 1 MB. It contains no client data beyond what is already committed to this repository.

## 3. Create the Space and push

On huggingface.co: New Space, SDK "Streamlit", hardware "CPU basic" (free), visibility of your choice. Then:

```bash
cd /tmp/docextract-space
git init -b main && git add . && git commit -m "replay demo"
git remote add origin https://huggingface.co/spaces/<your-user>/<space-name>
git push origin main
```

Pushing asks for a Hugging Face access token with write scope. No Space secrets are needed.

## 4. After it builds

- Open the Space and confirm the three metrics match step 1.
- If you want the README to link it, add the URL to the Quickstart section. Until then the README does not mention a hosted demo.

## Updating

Rebuild the folder into an empty directory with `scripts/build_hf_space.sh` and push again. The script refuses to write into a non-empty directory.
