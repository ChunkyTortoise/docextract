"""Tests for Kubernetes manifest correctness.

Validates that all K8s YAML files in deploy/k8s/ are well-formed and follow
the conventions required for the DocExtract deployment. No cluster needed.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

K8S_DIR = Path(__file__).parent.parent.parent / "deploy" / "k8s"
BASE_FILES = [
    "namespace.yaml",
    "configmap.yaml",
    "secrets.yaml",
    "api-deployment.yaml",
    "api-service.yaml",
    "worker-deployment.yaml",
    "frontend-deployment.yaml",
    "frontend-service.yaml",
    "ingress.yaml",
    "hpa.yaml",
    "kustomization.yaml",
]


def load(filename: str) -> dict | list:
    path = K8S_DIR / filename
    docs = list(yaml.safe_load_all(path.read_text()))
    return docs[0] if len(docs) == 1 else docs


class TestManifestFiles:
    def test_all_files_exist(self):
        for f in BASE_FILES:
            assert (K8S_DIR / f).exists(), f"Missing {f}"

    def test_all_files_are_valid_yaml(self):
        for f in BASE_FILES:
            path = K8S_DIR / f
            try:
                list(yaml.safe_load_all(path.read_text()))
            except yaml.YAMLError as exc:
                pytest.fail(f"{f} is invalid YAML: {exc}")

    def test_kustomization_references_all_resources(self):
        kust = load("kustomization.yaml")
        assert "resources" in kust
        for f in BASE_FILES:
            if f != "kustomization.yaml":
                assert f in kust["resources"], f"kustomization.yaml missing {f}"


class TestNamespace:
    def test_namespace_kind_and_name(self):
        ns = load("namespace.yaml")
        assert ns["kind"] == "Namespace"
        assert ns["metadata"]["name"] == "docextract"


class TestConfigMap:
    def setup_method(self):
        self.cm = load("configmap.yaml")

    def test_kind_and_namespace(self):
        assert self.cm["kind"] == "ConfigMap"
        assert self.cm["metadata"]["namespace"] == "docextract"

    def test_required_keys_present(self):
        data = self.cm["data"]
        required = [
            "STORAGE_BACKEND",
            "LOG_LEVEL",
            "OTEL_ENABLED",
            "ENVIRONMENT",
            "API_URL",
        ]
        for key in required:
            assert key in data, f"ConfigMap missing {key}"

    def test_api_url_points_to_api_service(self):
        # Frontend must reach the API via the K8s service name
        assert "docextract-api" in self.cm["data"]["API_URL"]


class TestApiDeployment:
    def setup_method(self):
        self.dep = load("api-deployment.yaml")

    def test_kind_and_namespace(self):
        assert self.dep["kind"] == "Deployment"
        assert self.dep["metadata"]["namespace"] == "docextract"

    def test_replicas_at_least_two(self):
        assert self.dep["spec"]["replicas"] >= 2

    def test_health_check_path(self):
        container = self.dep["spec"]["template"]["spec"]["containers"][0]
        readiness = container["readinessProbe"]["httpGet"]
        assert readiness["path"] == "/api/v1/health"
        assert readiness["port"] == 8000

        liveness = container["livenessProbe"]["httpGet"]
        assert liveness["path"] == "/api/v1/health"

    def test_resource_limits_set(self):
        container = self.dep["spec"]["template"]["spec"]["containers"][0]
        resources = container["resources"]
        assert "limits" in resources
        assert "cpu" in resources["limits"]
        assert "memory" in resources["limits"]
        assert "requests" in resources
        assert "cpu" in resources["requests"]
        assert "memory" in resources["requests"]

    def test_env_from_configmap_and_secret(self):
        container = self.dep["spec"]["template"]["spec"]["containers"][0]
        env_from = container["envFrom"]
        names = [ref.get("configMapRef", {}).get("name", "") or
                 ref.get("secretRef", {}).get("name", "") for ref in env_from]
        assert "docextract-config" in names
        assert "docextract-secrets" in names

    def test_rolling_update_strategy(self):
        strategy = self.dep["spec"]["strategy"]
        assert strategy["type"] == "RollingUpdate"
        assert strategy["rollingUpdate"]["maxUnavailable"] == 0

    def test_selector_matches_template_labels(self):
        selector = self.dep["spec"]["selector"]["matchLabels"]
        labels = self.dep["spec"]["template"]["metadata"]["labels"]
        for k, v in selector.items():
            assert labels.get(k) == v


class TestWorkerDeployment:
    def setup_method(self):
        self.dep = load("worker-deployment.yaml")

    def test_no_http_port(self):
        container = self.dep["spec"]["template"]["spec"]["containers"][0]
        # Worker has no HTTP port — it's an ARQ consumer
        assert "ports" not in container

    def test_liveness_probe_is_exec(self):
        container = self.dep["spec"]["template"]["spec"]["containers"][0]
        assert "exec" in container["livenessProbe"]

    def test_higher_memory_than_api(self):
        container = self.dep["spec"]["template"]["spec"]["containers"][0]
        worker_mem = container["resources"]["limits"]["memory"]
        # Worker needs more memory for OCR (Tesseract + PDF processing)
        assert worker_mem in ("512Mi", "1Gi", "2Gi")

    def test_replicas_at_least_two(self):
        assert self.dep["spec"]["replicas"] >= 2


class TestServices:
    def test_api_service_port(self):
        svc = load("api-service.yaml")
        assert svc["kind"] == "Service"
        port = svc["spec"]["ports"][0]
        assert port["port"] == 8000
        assert port["targetPort"] == 8000

    def test_frontend_service_port(self):
        svc = load("frontend-service.yaml")
        assert svc["kind"] == "Service"
        port = svc["spec"]["ports"][0]
        assert port["port"] == 8501
        assert port["targetPort"] == 8501

    def test_services_use_cluster_ip(self):
        for filename in ("api-service.yaml", "frontend-service.yaml"):
            svc = load(filename)
            assert svc["spec"]["type"] == "ClusterIP"


class TestIngress:
    def setup_method(self):
        self.ing = load("ingress.yaml")

    def test_kind(self):
        assert self.ing["kind"] == "Ingress"

    def test_api_path_before_root(self):
        paths = self.ing["spec"]["rules"][0]["http"]["paths"]
        path_strs = [p["path"] for p in paths]
        # /api must appear before / so nginx matches it first
        assert "/api" in path_strs
        assert "/" in path_strs
        api_idx = path_strs.index("/api")
        root_idx = path_strs.index("/")
        assert api_idx < root_idx, "/api must be listed before / in ingress"

    def test_api_routes_to_port_8000(self):
        paths = self.ing["spec"]["rules"][0]["http"]["paths"]
        api_path = next(p for p in paths if p["path"] == "/api")
        assert api_path["backend"]["service"]["port"]["number"] == 8000

    def test_root_routes_to_frontend(self):
        paths = self.ing["spec"]["rules"][0]["http"]["paths"]
        root_path = next(p for p in paths if p["path"] == "/")
        assert root_path["backend"]["service"]["port"]["number"] == 8501

    def test_sse_buffering_disabled(self):
        annotations = self.ing["metadata"]["annotations"]
        assert annotations.get("nginx.ingress.kubernetes.io/proxy-buffering") == "off"


class TestHPA:
    def setup_method(self):
        # hpa.yaml contains two documents (API + Worker HPAs)
        path = K8S_DIR / "hpa.yaml"
        self.docs = list(yaml.safe_load_all(path.read_text()))

    def test_two_hpa_resources(self):
        assert len(self.docs) == 2

    def test_all_are_hpa_kind(self):
        for doc in self.docs:
            assert doc["kind"] == "HorizontalPodAutoscaler"

    def test_api_hpa_targets_api_deployment(self):
        api_hpa = next(d for d in self.docs if "api-hpa" in d["metadata"]["name"])
        assert api_hpa["spec"]["scaleTargetRef"]["name"] == "docextract-api"

    def test_min_replicas_at_least_two(self):
        for doc in self.docs:
            assert doc["spec"]["minReplicas"] >= 2

    def test_max_replicas_greater_than_min(self):
        for doc in self.docs:
            assert doc["spec"]["maxReplicas"] > doc["spec"]["minReplicas"]

    def test_cpu_metric_target_is_reasonable(self):
        for doc in self.docs:
            metrics = doc["spec"]["metrics"]
            cpu_metrics = [m for m in metrics
                           if m["type"] == "Resource" and
                           m["resource"]["name"] == "cpu"]
            assert cpu_metrics, f"{doc['metadata']['name']} has no CPU metric"
            util = cpu_metrics[0]["resource"]["target"]["averageUtilization"]
            assert 50 <= util <= 90, f"CPU target {util}% seems off — expected 50-90%"
