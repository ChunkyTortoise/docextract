"""Locust load test for DocExtract AI API.

Usage:
    locust -f tests/load/locustfile.py --host=http://localhost:8000 --users=100 --spawn-rate=10
"""
from __future__ import annotations

import io
import os

from locust import HttpUser, between, task

# Minimal PDF fixture
SAMPLE_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
xref
0 4
0000000000 65535 f
trailer<</Size 4/Root 1 0 R>>
startxref
0
%%EOF"""

API_KEY = os.environ.get("DOCEXTRACT_API_KEY", "test-key")


class DocExtractUser(HttpUser):
    """Standard mixed-workload user."""
    wait_time = between(1, 5)

    def on_start(self):
        """Set auth headers."""
        self.client.headers["X-API-Key"] = API_KEY

    @task(3)
    def upload_document(self):
        """Upload a small PDF document."""
        with self.client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.pdf", io.BytesIO(SAMPLE_PDF), "application/pdf")},
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 202):
                response.failure(f"Upload failed: {response.status_code}")

    @task(5)
    def list_jobs(self):
        """List recent jobs."""
        self.client.get("/api/v1/jobs?page_size=20")

    @task(8)
    def list_records(self):
        """List extracted records."""
        self.client.get("/api/v1/records?page_size=20")

    @task(2)
    def export_records(self):
        """Export records as CSV."""
        self.client.get("/api/v1/records/export?format=csv")

    @task(1)
    def get_stats(self):
        """Get dashboard statistics."""
        self.client.get("/api/v1/stats")

    @task(2)
    def health_check(self):
        """Health check endpoint."""
        self.client.get("/api/v1/health")


class ReadHeavyUser(HttpUser):
    """Simulates dashboard users (read-heavy)."""
    wait_time = between(2, 8)

    def on_start(self):
        self.client.headers["X-API-Key"] = API_KEY

    @task(10)
    def list_records(self):
        self.client.get("/api/v1/records?page_size=50")

    @task(5)
    def get_stats(self):
        self.client.get("/api/v1/stats")

    @task(3)
    def export_csv(self):
        self.client.get("/api/v1/records/export?format=csv")

    @task(2)
    def list_jobs(self):
        self.client.get("/api/v1/jobs")


class UploadHeavyUser(HttpUser):
    """Simulates batch ingestion workload."""
    wait_time = between(0.5, 2)

    def on_start(self):
        self.client.headers["X-API-Key"] = API_KEY

    @task(8)
    def upload_document(self):
        with self.client.post(
            "/api/v1/documents/upload",
            files={"file": ("batch.pdf", io.BytesIO(SAMPLE_PDF), "application/pdf")},
            data={"priority": "high"},
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 202):
                response.failure(f"Upload failed: {response.status_code}")

    @task(2)
    def poll_jobs(self):
        self.client.get("/api/v1/jobs?status=queued&page_size=10")
