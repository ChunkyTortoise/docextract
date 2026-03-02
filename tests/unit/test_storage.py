"""Tests for storage backends."""
from __future__ import annotations

import pytest

from app.storage.local import LocalStorageBackend


@pytest.fixture
def local_storage(tmp_path, monkeypatch):
    """Create a LocalStorageBackend using tmp_path."""
    monkeypatch.setattr("app.storage.local.settings", type("S", (), {"storage_local_path": str(tmp_path)})())
    return LocalStorageBackend()


@pytest.mark.asyncio
async def test_upload_creates_file(local_storage, tmp_path):
    path = await local_storage.upload("test/file.txt", b"hello world", "text/plain")
    assert (tmp_path / "test" / "file.txt").exists()
    assert (tmp_path / "test" / "file.txt").read_bytes() == b"hello world"


@pytest.mark.asyncio
async def test_download_returns_bytes(local_storage, tmp_path):
    (tmp_path / "doc.bin").write_bytes(b"\x00\x01\x02")
    data = await local_storage.download("doc.bin")
    assert data == b"\x00\x01\x02"


@pytest.mark.asyncio
async def test_delete_existing_file(local_storage, tmp_path):
    (tmp_path / "to_delete.txt").write_text("gone")
    result = await local_storage.delete("to_delete.txt")
    assert result is True
    assert not (tmp_path / "to_delete.txt").exists()


@pytest.mark.asyncio
async def test_delete_missing_file(local_storage):
    result = await local_storage.delete("nonexistent.txt")
    assert result is False


@pytest.mark.asyncio
async def test_get_presigned_url(local_storage, tmp_path):
    url = await local_storage.get_presigned_url("some/key.pdf")
    assert url.startswith("file://")
    assert "some/key.pdf" in url


@pytest.mark.asyncio
async def test_list_keys_all(local_storage, tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.txt").write_text("c")

    keys = await local_storage.list_keys()
    assert sorted(keys) == ["a.txt", "b.txt", "sub/c.txt"]


@pytest.mark.asyncio
async def test_list_keys_with_prefix(local_storage, tmp_path):
    (tmp_path / "a.txt").write_text("a")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.txt").write_text("c")

    keys = await local_storage.list_keys(prefix="sub/")
    assert keys == ["sub/c.txt"]


@pytest.mark.asyncio
async def test_upload_and_download_roundtrip(local_storage):
    content = b"PDF content here \xff\xfe"
    await local_storage.upload("docs/invoice.pdf", content, "application/pdf")
    downloaded = await local_storage.download("docs/invoice.pdf")
    assert downloaded == content


# --- R2 Backend (mocked) ---

@pytest.fixture
def mock_r2_storage(monkeypatch):
    """Create an R2StorageBackend with mocked boto3 client."""
    from unittest.mock import MagicMock, AsyncMock
    import io

    mock_client = MagicMock()
    mock_settings = type("S", (), {
        "r2_account_id": "test-account",
        "r2_access_key_id": "test-key",
        "r2_secret_access_key": "test-secret",
        "r2_bucket_name": "test-bucket",
    })()

    monkeypatch.setattr("app.storage.r2.settings", mock_settings)
    monkeypatch.setattr("app.storage.r2.boto3", MagicMock())

    from app.storage.r2 import R2StorageBackend
    backend = R2StorageBackend()
    backend._client = mock_client
    backend._bucket = "test-bucket"
    return backend, mock_client


@pytest.mark.asyncio
async def test_r2_upload(mock_r2_storage):
    backend, mock_client = mock_r2_storage
    result = await backend.upload("test.pdf", b"data", "application/pdf")
    assert result == "r2://test-bucket/test.pdf"
    mock_client.upload_fileobj.assert_called_once()


@pytest.mark.asyncio
async def test_r2_download(mock_r2_storage):
    backend, mock_client = mock_r2_storage

    def fake_download(bucket, key, buf):
        buf.write(b"downloaded-data")

    mock_client.download_fileobj.side_effect = fake_download
    data = await backend.download("test.pdf")
    assert data == b"downloaded-data"


@pytest.mark.asyncio
async def test_r2_delete_success(mock_r2_storage):
    backend, mock_client = mock_r2_storage
    result = await backend.delete("test.pdf")
    assert result is True
    mock_client.delete_object.assert_called_once_with(Bucket="test-bucket", Key="test.pdf")


@pytest.mark.asyncio
async def test_r2_presigned_url(mock_r2_storage):
    backend, mock_client = mock_r2_storage
    mock_client.generate_presigned_url.return_value = "https://presigned-url.example.com"
    url = await backend.get_presigned_url("test.pdf", expires_in=600)
    assert url == "https://presigned-url.example.com"
