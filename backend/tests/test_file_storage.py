# backend/tests/test_file_storage.py
from dataclasses import replace
from pathlib import Path

import pytest


# -- existing happy-path tests (kept) --

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


# -- new path-security tests (Task 4 rework) --

def _storage(tmp_path: Path):
    from backend.app.storage.files import LocalFileStorage
    return LocalFileStorage(tmp_path)


# ---- stage() component validation ----

@pytest.mark.parametrize("field,bad_value", [
    ("tenant_id", "../escape"),
    ("tenant_id", r"..\escape"),
    ("tenant_id", "sub/../escape"),
    ("tenant_id", r"sub\..\escape"),
    ("kb_uid", "../escape"),
    ("kb_uid", r"..\escape"),
    ("kb_uid", "kb/../escape"),
    ("file_uid", "../escape"),
    ("file_uid", r"..\escape"),
    ("file_uid", "file/../escape"),
])
def test_stage_rejects_parent_traversal_in_path_components(tmp_path, field, bad_value):
    storage = _storage(tmp_path)
    kwargs = {"tenant_id": "t", "kb_uid": "kb", "file_uid": "f", "filename": "a.md", "content": b"x"}
    kwargs[field] = bad_value
    with pytest.raises(ValueError):
        storage.stage(**kwargs)


@pytest.mark.parametrize("field,bad_value", [
    ("tenant_id", "/etc/passwd"),
    ("tenant_id", "\\Windows"),
    ("tenant_id", "C:\\Users"),
    ("tenant_id", "C:"),
    ("tenant_id", "\\\\server\\share"),
    ("tenant_id", "//server/share"),
    ("kb_uid", "/absolute"),
    ("kb_uid", "\\absolute"),
    ("file_uid", "D:\\absolute"),
])
def test_stage_rejects_absolute_and_unc_paths(tmp_path, field, bad_value):
    storage = _storage(tmp_path)
    kwargs = {"tenant_id": "t", "kb_uid": "kb", "file_uid": "f", "filename": "a.md", "content": b"x"}
    kwargs[field] = bad_value
    with pytest.raises(ValueError):
        storage.stage(**kwargs)


@pytest.mark.parametrize("field,bad_value", [
    ("tenant_id", ""),
    ("kb_uid", ""),
    ("file_uid", ""),
    ("tenant_id", "."),
    ("kb_uid", "."),
    ("file_uid", "."),
    ("tenant_id", ".."),
    ("kb_uid", ".."),
    ("file_uid", ".."),
])
def test_stage_rejects_empty_and_dot_components(tmp_path, field, bad_value):
    storage = _storage(tmp_path)
    kwargs = {"tenant_id": "t", "kb_uid": "kb", "file_uid": "f", "filename": "a.md", "content": b"x"}
    kwargs[field] = bad_value
    with pytest.raises(ValueError):
        storage.stage(**kwargs)


def test_stage_rejects_embedded_slash_in_filename(tmp_path):
    storage = _storage(tmp_path)
    with pytest.raises(ValueError):
        storage.stage("t", "kb", "f", "a/b.md", b"x")


def test_stage_rejects_embedded_backslash_in_filename(tmp_path):
    storage = _storage(tmp_path)
    with pytest.raises(ValueError):
        storage.stage("t", "kb", "f", "a\\b.md", b"x")


def test_stage_rejects_empty_filename(tmp_path):
    storage = _storage(tmp_path)
    with pytest.raises(ValueError):
        storage.stage("t", "kb", "f", "", b"x")


def test_stage_rejects_dot_only_filename(tmp_path):
    storage = _storage(tmp_path)
    with pytest.raises(ValueError):
        storage.stage("t", "kb", "f", ".", b"x")


def test_stage_accepts_valid_unicode_identifiers(tmp_path):
    storage = _storage(tmp_path)
    staged = storage.stage("tenant-测试", "kb-日本語", "file-ü", "résumé.md", b"unicode")
    assert staged.sha256 is not None
    assert staged.size_bytes == 7


# ---- forged StagedFile attacks on commit() ----

def test_commit_rejects_forged_staged_path_outside_staging(tmp_path):
    storage = _storage(tmp_path)
    forged = storage.stage("t", "kb", "f", "a.md", b"x")
    escaped = tmp_path / ".." / "escape.txt"
    escaped.parent.mkdir(parents=True, exist_ok=True)
    escaped.write_text("stolen", encoding="utf-8")
    bad = replace(forged, path=escaped)
    with pytest.raises(ValueError):
        storage.commit(bad)


def test_commit_rejects_forged_final_path_outside_root(tmp_path):
    storage = _storage(tmp_path)
    forged = storage.stage("t", "kb", "f", "a.md", b"x")
    escaped = tmp_path / ".." / "escape.txt"
    bad = replace(forged, final_path=escaped)
    with pytest.raises(ValueError):
        storage.commit(bad)


def test_commit_rejects_forged_final_path_absolute_elsewhere(tmp_path):
    storage = _storage(tmp_path)
    forged = storage.stage("t", "kb", "f", "a.md", b"x")
    bad = replace(forged, final_path=Path("/etc/passwd"))
    with pytest.raises(ValueError):
        storage.commit(bad)


def test_commit_rejects_forged_staging_path_absolute(tmp_path):
    storage = _storage(tmp_path)
    forged = storage.stage("t", "kb", "f", "a.md", b"x")
    bad = replace(forged, path=Path("/etc/passwd"))
    with pytest.raises(ValueError):
        storage.commit(bad)


def test_commit_rejects_forged_staging_path_resolves_outside(tmp_path):
    storage = _storage(tmp_path)
    forged = storage.stage("t", "kb", "f", "a.md", b"x")
    bad = replace(forged, path=tmp_path / ".staging" / ".." / ".." / "escape.txt")
    with pytest.raises(ValueError):
        storage.commit(bad)


def test_commit_rejects_forged_final_path_resolves_outside(tmp_path):
    storage = _storage(tmp_path)
    forged = storage.stage("t", "kb", "f", "a.md", b"x")
    bad = replace(forged, final_path=tmp_path / "sub" / ".." / ".." / "escape.txt")
    with pytest.raises(ValueError):
        storage.commit(bad)


def test_commit_rejects_staged_file_with_shorter_final_path_prefix(tmp_path):
    """final_path must start with the resolved root."""
    storage = _storage(tmp_path)
    forged = storage.stage("t", "kb", "f", "a.md", b"x")
    # forged.path is inside staging, but final_path is a sibling of root
    bad = replace(forged, final_path=tmp_path.parent / "sibling.txt")
    with pytest.raises(ValueError):
        storage.commit(bad)


# ---- _resolve() edge cases ----

def test_resolve_rejects_local_uri_escaping_root(tmp_path):
    storage = _storage(tmp_path)
    with pytest.raises(ValueError):
        storage.read_bytes("local://../outside.txt")


def test_resolve_rejects_local_uri_with_absolute_embedded(tmp_path):
    storage = _storage(tmp_path)
    with pytest.raises(ValueError):
        storage.read_bytes("local:///etc/passwd")


def test_stage_then_commit_produces_uri_readable(tmp_path):
    storage = _storage(tmp_path)
    staged = storage.stage("tenant-1", "kb-1", "file-1", "doc.txt", b"content")
    uri = storage.commit(staged)
    assert uri.startswith("local://")
    assert ".." not in uri
    body = storage.read_bytes(uri)
    assert body == b"content"


def test_stage_rejects_filename_that_strips_to_empty(tmp_path):
    storage = _storage(tmp_path)
    # PurePath.name of a whitespace-only filename may yield the original
    # whitespace string, but _validate_filename already rejects empty.
    # Test the primary empty rejection path directly.
    with pytest.raises(ValueError):
        storage.stage("t", "kb", "f", "", b"x")

def test_stage_accepts_filename_with_spaces(tmp_path):
    storage = _storage(tmp_path)
    staged = storage.stage("t", "kb", "f", "doc  with spaces.md", b"content")
    assert staged.sha256 is not None
    assert staged.size_bytes == 7


def test_staging_orphans_keep_full_scope_when_file_uids_collide(tmp_path):
    from datetime import datetime, timedelta
    storage = _storage(tmp_path)
    first = storage.stage("tenant-a", "kb-a", "same-file", "a.md", b"a")
    second = storage.stage("tenant-b", "kb-b", "same-file", "b.md", b"b")
    old = (datetime.now() - timedelta(days=2)).timestamp()
    import os
    os.utime(first.path, (old, old))
    os.utime(second.path, (old, old))

    identities = storage.stale_unreferenced(
        {("tenant-a", "kb-a", "same-file")}, datetime.now() - timedelta(days=1)
    )
    assert identities == [("tenant-b", "kb-b", "same-file")]
    storage.remove_staging(identities[0])
    assert first.path.exists()
    assert not second.path.exists()
