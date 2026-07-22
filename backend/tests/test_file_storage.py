# backend/tests/test_file_storage.py
from pathlib import Path

import pytest


def test_local_storage_stage_commit_read_delete(tmp_path: Path):
    from backend.app.storage.files import LocalFileStorage

    storage = LocalFileStorage(tmp_path)
    staged = storage.stage("tenant-a", "kb-a", "file-a", "a.md", b"hello")
    assert staged.sha256 == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    final_uri = storage.commit(staged)
    assert storage.read_bytes(final_uri) == b"hello"
    storage.delete(final_uri)
    assert not storage.exists(final_uri)


def test_local_storage_rejects_path_traversal(tmp_path: Path):
    from backend.app.storage.files import InvalidStorageUri, LocalFileStorage

    storage = LocalFileStorage(tmp_path)
    with pytest.raises(InvalidStorageUri):
        storage.read_bytes("local://../../secret")


def test_local_storage_rejects_non_local_scheme(tmp_path: Path):
    from backend.app.storage.files import InvalidStorageUri, LocalFileStorage

    storage = LocalFileStorage(tmp_path)
    with pytest.raises(InvalidStorageUri):
        storage.read_bytes("http://evil/secret")


def test_staged_file_not_visible_outside_staging(tmp_path: Path):
    from backend.app.storage.files import LocalFileStorage

    storage = LocalFileStorage(tmp_path)
    staged = storage.stage("tenant-a", "kb-a", "file-b", "b.md", b"world")
    uri = storage.commit(staged)
    assert not staged.path.exists()
    assert storage.exists(uri)


def test_commit_overwrites_existing_file(tmp_path: Path):
    from backend.app.storage.files import LocalFileStorage

    storage = LocalFileStorage(tmp_path)
    staged1 = storage.stage("tenant-a", "kb-a", "file-c", "c.md", b"v1")
    uri = storage.commit(staged1)
    staged2 = storage.stage("tenant-a", "kb-a", "file-c", "c.md", b"v2")
    storage.commit(staged2)
    assert storage.read_bytes(uri) == b"v2"
