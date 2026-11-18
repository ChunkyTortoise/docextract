#!/usr/bin/env bash
# Assemble a self-contained Hugging Face Space folder for the offline replay demo.
# Usage: scripts/build_hf_space.sh <output-dir>
# Copies only committed files; needs no API key and makes no network calls.
set -euo pipefail

out="${1:?usage: scripts/build_hf_space.sh <output-dir>}"
repo="$(cd "$(dirname "$0")/.." && pwd)"

if [ -e "$out" ] && [ -n "$(ls -A "$out" 2>/dev/null)" ]; then
  echo "refusing to write into non-empty directory: $out" >&2
  exit 1
fi
mkdir -p "$out/autoresearch"

cp "$repo/space_app.py" "$out/space_app.py"
cp "$repo/LICENSE" "$out/LICENSE"
for f in __init__.py eval.py grounding.py eval_dataset_72.json baseline.json; do
  cp "$repo/autoresearch/$f" "$out/autoresearch/$f"
done
cp -R "$repo/autoresearch/golden_responses" "$out/autoresearch/golden_responses"

streamlit_pin="$(grep -m1 '^streamlit' "$repo/requirements_demo.txt")"
printf '%s\n' "$streamlit_pin" > "$out/requirements.txt"

cat > "$out/README.md" <<'MD'
---
title: DocExtract eval replay
sdk: streamlit
app_file: space_app.py
license: mit
---

Re-scores frozen document-extraction outputs committed to the DocExtract repository.
No model calls and no API key. Source: https://github.com/ChunkyTortoise/docextract
MD

echo "built Space folder: $out ($(find "$out" -type f | wc -l | tr -d ' ') files)"
