# backend/app/storage/files.py
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol
import os


class InvalidStorageUri(ValueError):
    pass


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


class LocalFileStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.staging = self.root / ".staging"

    def stage(self, tenant_id: str, kb_uid: str, file_uid: str, filename: str, content: bytes) -> StagedFile:
        safe_name = Path(filename).name
        staged_path = self.staging / f"{file_uid}.part"
        final_path = self.root / tenant_id / kb_uid / file_uid / safe_name
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_bytes(content)
        return StagedFile(staged_path, final_path, sha256(content).hexdigest(), len(content))

    def commit(self, staged: StagedFile) -> str:
        staged.final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged.path, staged.final_path)
        return f"local://{staged.final_path.relative_to(self.root).as_posix()}"

    def _resolve(self, storage_uri: str) -> Path:
        if not storage_uri.startswith("local://"):
            raise InvalidStorageUri(storage_uri)
        path = (self.root / storage_uri.removeprefix("local://")).resolve()
        if path != self.root and self.root not in path.parents:
            raise InvalidStorageUri(storage_uri)
        return path

    def read_bytes(self, storage_uri: str) -> bytes:
        return self._resolve(storage_uri).read_bytes()

    def delete(self, storage_uri: str) -> None:
        self._resolve(storage_uri).unlink(missing_ok=True)

    def exists(self, storage_uri: str) -> bool:
        return self._resolve(storage_uri).exists()
