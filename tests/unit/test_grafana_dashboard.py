"""Tests for Grafana dashboard and Prometheus config file correctness."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

DEPLOY_DIR = Path(__file__).parent.parent.parent / "deploy"
GRAFANA_DIR = DEPLOY_DIR / "grafana"
PROMETHEUS_DIR = DEPLOY_DIR / "prometheus"

KNOWN_METRICS = {
    "llm_call_duration_ms",
    "llm_calls_total",
    "llm_tokens_total",
    "circuit_breaker_state",
}


class TestGrafanaDashboard:
    def setup_method(self):
        self.dashboard = json.loads(
            (GRAFANA_DIR / "docextract-dashboard.json").read_text()
        )

    def test_dashboard_has_title(self):
        assert "title" in self.dashboard
        assert self.dashboard["title"]

    def test_dashboard_has_uid(self):
        assert "uid" in self.dashboard
        assert self.dashboard["uid"]

    def test_dashboard_references_known_metrics(self):
        dashboard_text = (GRAFANA_DIR / "docextract-dashboard.json").read_text()
        for metric in KNOWN_METRICS:
            assert metric in dashboard_text, f"Dashboard missing metric: {metric}"

    def test_dashboard_has_panels(self):
        panels = self.dashboard.get("panels", [])
        # Expect at least one non-row panel
        data_panels = [p for p in panels if p.get("type") != "row"]
        assert len(data_panels) >= 4

    def test_datasource_is_prometheus(self):
        dashboard_text = (GRAFANA_DIR / "docextract-dashboard.json").read_text()
        assert "prometheus" in dashboard_text.lower()

    def test_circuit_breaker_panel_exists(self):
        dashboard_text = (GRAFANA_DIR / "docextract-dashboard.json").read_text()
        assert "circuit_breaker_state" in dashboard_text

    def test_schema_version_present(self):
        assert "schemaVersion" in self.dashboard
        assert isinstance(self.dashboard["schemaVersion"], int)


class TestGrafanaProvisioning:
    def test_datasource_yaml_valid(self):
        ds = yaml.safe_load((GRAFANA_DIR / "datasource.yaml").read_text())
        assert ds["apiVersion"] == 1
        sources = ds["datasources"]
        assert len(sources) >= 1
        assert sources[0]["type"] == "prometheus"

    def test_datasource_points_to_prometheus_service(self):
        ds = yaml.safe_load((GRAFANA_DIR / "datasource.yaml").read_text())
        url = ds["datasources"][0]["url"]
        assert "prometheus" in url

    def test_dashboard_provider_yaml_valid(self):
        prov = yaml.safe_load((GRAFANA_DIR / "dashboard-provider.yaml").read_text())
        assert prov["apiVersion"] == 1
        assert len(prov["providers"]) >= 1

    def test_dashboard_provider_has_file_path(self):
        prov = yaml.safe_load((GRAFANA_DIR / "dashboard-provider.yaml").read_text())
        provider = prov["providers"][0]
        assert "path" in provider["options"]


class TestPrometheusConfig:
    def test_prometheus_config_valid_yaml(self):
        config = yaml.safe_load((PROMETHEUS_DIR / "prometheus.yml").read_text())
        assert "scrape_configs" in config

    def test_scrapes_docextract_api(self):
        config = yaml.safe_load((PROMETHEUS_DIR / "prometheus.yml").read_text())
        job_names = [sc["job_name"] for sc in config["scrape_configs"]]
        assert any("docextract" in name for name in job_names)

    def test_metrics_path_is_slash_metrics(self):
        config = yaml.safe_load((PROMETHEUS_DIR / "prometheus.yml").read_text())
        for sc in config["scrape_configs"]:
            if "docextract" in sc["job_name"]:
                assert sc.get("metrics_path", "/metrics") == "/metrics"
