"""Prompt Lab — version comparison and regression testing UI."""
from __future__ import annotations

import difflib

import streamlit as st

from app.services.prompt_registry import PromptRegistry

_REGISTRY = PromptRegistry()

_CATEGORIES = ["extraction", "classification", "search"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_versions(category: str) -> list[str]:
    try:
        return _REGISTRY.list_versions(category)  # type: ignore[arg-type]
    except Exception:
        return []


def _get_prompt_safe(category: str, version: str) -> str:
    try:
        return _REGISTRY.get_prompt(category, version)  # type: ignore[arg-type]
    except Exception as exc:
        return f"[Error loading prompt: {exc}]"


def _unified_diff(text_a: str, text_b: str, label_a: str, label_b: str) -> str:
    """Return a unified diff string between two prompt texts."""
    lines_a = text_a.splitlines(keepends=True)
    lines_b = text_b.splitlines(keepends=True)
    diff = difflib.unified_diff(lines_a, lines_b, fromfile=label_a, tofile=label_b)
    return "".join(diff)


def _parse_changelog(raw: str) -> list[dict]:
    """Parse CHANGELOG.md into a list of {version, date, category, summary} rows."""
    rows: list[dict] = []
    current: dict | None = None
    for line in raw.splitlines():
        line = line.rstrip()
        if line.startswith("## ["):
            # e.g.  ## [1.1.0] - 2026-03-22 - extraction/
            parts = line[3:].split("]")
            version = parts[0].strip("[").strip()
            rest = parts[1] if len(parts) > 1 else ""
            rest_parts = [p.strip() for p in rest.split(" - ") if p.strip()]
            date = rest_parts[0] if rest_parts else ""
            category = rest_parts[1] if len(rest_parts) > 1 else ""
            current = {"version": version, "date": date, "category": category, "summary": ""}
            rows.append(current)
        elif current is not None and line.startswith("- "):
            bullet = line[2:].strip()
            if current["summary"]:
                current["summary"] += "; " + bullet
            else:
                current["summary"] = bullet
    return rows


# ---------------------------------------------------------------------------
# Mocked regression result (used when no real eval is available)
# ---------------------------------------------------------------------------


def _mock_regression_result(baseline: str, candidate: str) -> dict:
    """Return a mocked comparison result for demo purposes."""
    import random
    random.seed(hash(baseline + candidate) % 2**31)
    metrics = {
        "accuracy": round(0.85 + random.uniform(-0.05, 0.05), 4),
        "completeness": round(0.88 + random.uniform(-0.05, 0.05), 4),
        "hallucination_rate": round(0.05 + random.uniform(-0.02, 0.02), 4),
    }
    baseline_metrics = {
        "accuracy": round(metrics["accuracy"] + random.uniform(-0.03, 0.03), 4),
        "completeness": round(metrics["completeness"] + random.uniform(-0.03, 0.03), 4),
        "hallucination_rate": round(metrics["hallucination_rate"] + random.uniform(-0.02, 0.02), 4),
    }
    regressions = [
        f"{k}: {baseline_metrics[k]:.4f} -> {metrics[k]:.4f} (dropped {baseline_metrics[k]-metrics[k]:.4f})"
        for k in metrics
        if baseline_metrics[k] - metrics[k] > 0.02
    ]
    improvements = [
        f"{k}: {baseline_metrics[k]:.4f} -> {metrics[k]:.4f} (gained {metrics[k]-baseline_metrics[k]:.4f})"
        for k in metrics
        if metrics[k] - baseline_metrics[k] > 0.02
    ]
    return {
        "metrics": metrics,
        "baseline_metrics": baseline_metrics,
        "regressions": regressions,
        "improvements": improvements,
        "passed": len(regressions) == 0,
    }


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------


def render() -> None:
    st.title("Prompt Lab")
    st.caption(
        "Compare prompt versions side-by-side, inspect diffs, and run regression checks. "
        "Active version is set via PROMPT_{CATEGORY}_VERSION env vars."
    )

    # ── Active versions banner ───────────────────────────────────────────
    st.subheader("Active Versions")
    cols = st.columns(len(_CATEGORIES))
    for col, cat in zip(cols, _CATEGORIES):
        active = _REGISTRY.get_active_version(cat)  # type: ignore[arg-type]
        if active == "latest":
            versions = _get_versions(cat)
            resolved = versions[0] if versions else "—"
            label = f"{resolved} (latest)"
        else:
            label = active
        with col:
            st.metric(cat, label)

    st.divider()

    # ── Category + version selectors ────────────────────────────────────
    st.subheader("Version Comparison")
    col_cat, col_base, col_cand = st.columns([1, 1, 1])
    with col_cat:
        category = st.selectbox("Category", _CATEGORIES, key="lab_category")
    versions = _get_versions(category)
    if not versions:
        st.warning(f"No prompt versions found for category '{category}'.")
        return
    with col_base:
        baseline_ver = st.selectbox(
            "Baseline version",
            versions,
            index=min(1, len(versions) - 1),
            key="lab_baseline",
        )
    with col_cand:
        candidate_ver = st.selectbox(
            "Candidate version",
            versions,
            index=0,
            key="lab_candidate",
        )

    # ── Side-by-side prompt display ──────────────────────────────────────
    st.subheader("Prompt Content")
    left, right = st.columns(2)
    baseline_text = _get_prompt_safe(category, baseline_ver)
    candidate_text = _get_prompt_safe(category, candidate_ver)
    with left:
        st.markdown(f"**{baseline_ver}** (baseline)")
        st.code(baseline_text, language="text")
    with right:
        st.markdown(f"**{candidate_ver}** (candidate)")
        st.code(candidate_text, language="text")

    # ── Unified diff ─────────────────────────────────────────────────────
    st.subheader("Diff")
    if baseline_ver == candidate_ver:
        st.info("Baseline and candidate are the same version — no diff.")
    else:
        diff_text = _unified_diff(baseline_text, candidate_text, baseline_ver, candidate_ver)
        if diff_text:
            st.code(diff_text, language="diff")
        else:
            st.success("Prompts are identical despite different version tags.")

    st.divider()

    # ── Regression comparison ────────────────────────────────────────────
    st.subheader("Regression Check")
    if st.button("Run Comparison", type="primary", key="lab_compare"):
        if baseline_ver == candidate_ver:
            st.warning("Select two different versions to compare.")
        else:
            with st.spinner("Running eval comparison (mocked — no API credits required)..."):
                result = _mock_regression_result(baseline_ver, candidate_ver)

            if result["passed"]:
                st.success("No regressions detected.")
            else:
                st.error(
                    "Regressions detected:\n\n"
                    + "\n".join(f"- {r}" for r in result["regressions"])
                )

            if result["improvements"]:
                st.info(
                    "Improvements noted:\n\n"
                    + "\n".join(f"- {i}" for i in result["improvements"])
                )

            # Metrics table
            metric_rows = [
                {
                    "Metric": k,
                    "Baseline": f"{result['baseline_metrics'][k]:.4f}",
                    "Candidate": f"{result['metrics'][k]:.4f}",
                    "Delta": f"{result['metrics'][k] - result['baseline_metrics'][k]:+.4f}",
                }
                for k in result["metrics"]
            ]
            st.dataframe(metric_rows, use_container_width=True, hide_index=True)
            st.caption("Mocked eval data. Wire PromptRegressionTester to show real scores.")

    st.divider()

    # ── Prompt history table ─────────────────────────────────────────────
    st.subheader("Prompt History")
    changelog_raw = _REGISTRY.get_changelog()
    if changelog_raw:
        rows = _parse_changelog(changelog_raw)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("No structured entries found in CHANGELOG.md.")
    else:
        st.info("No CHANGELOG.md found in the prompts directory.")
