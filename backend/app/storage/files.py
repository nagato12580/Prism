# backend/app/storage/files.py
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePath
from typing import Protocol
import os
import re


class InvalidStorageUri(ValueError):
    """Raised when a storage URI is malformed, uses an unsupported scheme,
    or resolves outside the storage root."""


class StorageValidationError(ValueError):
    """Raised when a path component or StagedFile fails security validation."""


@dataclass(frozen=True)
class StagedFile:
    path: Path
    final_path: Path
    sha256: str
    size_bytes: int


class FileStorage(Protocol):
    def stage(self, tenant_id: str, kb_uid: str, file_uid: str, filename: str, content: bytes) -> StagedFile: ...
    def commit(self, staged: StagedFile) -> str: ...
    def read_bytes(self, storage_uri: str) -> bytes: ...
    def delete(self, storage_uri: str) -> None: ...


# Characters and patterns forbidden in path components.
# We use a simple, strict allowlist approach:
# components must be non-empty and must not contain path separators,
# must not be "." or "..", and must not look like absolute/UNC/drive paths.
_PATH_SEPARATOR_CHARS = re.compile(r"[/\\]")

# Matches a Windows drive letter prefix (e.g. "C:", "D:").
_DRIVE_LETTER = re.compile(r"^[a-zA-Z]:$")

# Matches UNC-ish prefixes like "\\server" or "//server".
_UNC_PREFIX = re.compile(r"^[/\\]{2}")


def _validate_path_component(value: str, label: str) -> None:
    """Reject path components that could escape their intended directory."""
    if not value:
        raise StorageValidationError(f"{label} must not be empty")
    if value in (".", ".."):
        raise StorageValidationError(f"{label} must not be '.' or '..'")
    if _PATH_SEPARATOR_CHARS.search(value):
        raise StorageValidationError(
            f"{label} must not contain path separators: {value!r}"
        )
    if _DRIVE_LETTER.match(value):
        raise StorageValidationError(
            f"{label} must not be a Windows drive letter: {value!r}"
        )
    # Reject components that start with separator-like patterns (absolute/UNC).
    # After the separator check above, remaining concerns are Windows drive
    # paths like "C:foo" which use colon as a relative-drive indicator.
    if ":" in value:
        raise StorageValidationError(
            f"{label} must not contain colon: {value!r}"
        )


def _validate_containment(path: Path, root: Path, label: str) -> Path:
    """Resolve *path* and verify it is inside *root*.  Returns the resolved path.

    Raises StorageValidationError if the resolved path escapes *root*.
    """
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise StorageValidationError(
            f"{label} escapes its root: {path}"
        )
    return resolved


def _validate_filename(filename: str) -> str:
    """Validate and sanitize a filename. Returns the safe name portion only."""
    if not filename:
        raise StorageValidationError("filename must not be empty")
    if _PATH_SEPARATOR_CHARS.search(filename):
        raise StorageValidationError(
            f"filename must not contain path separators: {filename!r}"
        )
    safe = PurePath(filename).name
    if not safe or safe in (".", ".."):
        raise StorageValidationError(f"filename resolves to unsafe value: {filename!r}")
    return safe


class LocalFileStorage:
    """Volume-local file storage.

    Files are staged into ``<root>/.staging/`` and committed into
    ``<root>/<tenant_id>/<kb_uid>/<file_uid>/<safe_filename>``.

    All path components are validated before any filesystem operation.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.staging = self.root / ".staging"

    # ---- stage ----

    def stage(
        self,
        tenant_id: str,
        kb_uid: str,
        file_uid: str,
        filename: str,
        content: bytes,
    ) -> StagedFile:
        _validate_path_component(tenant_id, "tenant_id")
        _validate_path_component(kb_uid, "kb_uid")
        _validate_path_component(file_uid, "file_uid")
        safe_name = _validate_filename(filename)

        staged_path = self.staging / f"{file_uid}.part"
        final_path = self.root / tenant_id / kb_uid / file_uid / safe_name

        # Pre-validate that final_path (before resolution) does not escape.
        # Building it from validated components makes this deterministic, but
        # resolve-and-contain is the real enforcement.
        _validate_containment(final_path, self.root, "final_path")
        _validate_containment(staged_path, self.staging, "staged_path")

        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_bytes(content)
        return StagedFile(
            staged_path,
            final_path,
            sha256(content).hexdigest(),
            len(content),
        )

    # ---- commit ----

    def commit(self, staged: StagedFile) -> str:
        """Atomically move a staged file to its final location.

        Re-validates both paths in the StagedFile against the storage roots.
        """
        # Re-validate containment — never trust a StagedFile that could have
        # been forged after stage().
        _validate_containment(staged.path, self.staging, "staged.path")
        resolved_final = _validate_containment(staged.final_path, self.root, "final_path")

        resolved_final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged.path, resolved_final)
        return f"local://{resolved_final.relative_to(self.root).as_posix()}"

    # ---- resolve ----

    def _resolve(self, storage_uri: str) -> Path:
        if not storage_uri.startswith("local://"):
            raise InvalidStorageUri(storage_uri)
        relative = storage_uri.removeprefix("local://")
        # Prevent embedded absolute paths in the URI.
        if relative.startswith("/") or PurePath(relative).is_absolute():
            raise InvalidStorageUri(storage_uri)
        path = (self.root / relative).resolve()
        try:
            path.relative_to(self.root)
        except ValueError:
            raise InvalidStorageUri(storage_uri)
        return path

    # ---- I/O ----

    def read_bytes(self, storage_uri: str) -> bytes:
        return self._resolve(storage_uri).read_bytes()

    def delete(self, storage_uri: str) -> None:
        self._resolve(storage_uri).unlink(missing_ok=True)

    def exists(self, storage_uri: str) -> bool:
        return self._resolve(storage_uri).exists()
