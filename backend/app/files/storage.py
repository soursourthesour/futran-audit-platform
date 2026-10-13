"""File storage behind one interface. Keys are `{org_id}/{yyyy}/{uuid}-{safe_name}` (per-tenant prefixes, spec §15)."""
import re
import uuid
from pathlib import Path
from typing import Protocol

from app.core.clock import today
from app.core.config import Settings


def safe_name(filename: str) -> str:
    name = Path(filename.replace("\\", "/")).name.strip() or "file"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "file"
    return name[:120]


class Storage(Protocol):
    def put(self, org_id: str, data: bytes, filename: str) -> str: ...
    def get(self, key: str) -> bytes: ...


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise ValueError("Storage key outside the file store.")
        return p

    def put(self, org_id: str, data: bytes, filename: str) -> str:
        key = f"{org_id}/{today().year}/{uuid.uuid4()}-{safe_name(filename)}"
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()


class AzureBlobStorage:
    """Placeholder for the Azure deployment (schematic §14, post-build). Configure with `azure:<container-url>`."""

    def __init__(self, url: str):
        self.url = url

    def put(self, org_id: str, data: bytes, filename: str) -> str:
        raise NotImplementedError("Azure Blob storage is set up at the Azure deployment stage.")

    def get(self, key: str) -> bytes:
        raise NotImplementedError("Azure Blob storage is set up at the Azure deployment stage.")


def get_storage(settings: Settings) -> Storage:
    kind, _, target = settings.file_store.partition(":")
    if kind == "local":
        return LocalStorage(target or "./data/files")
    if kind == "azure":
        return AzureBlobStorage(target)
    raise ValueError(f"Unknown file store {settings.file_store!r}")
