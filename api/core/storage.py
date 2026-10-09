"""Object storage behind one small interface: GCS in deployment, memory in tests."""

from __future__ import annotations

import gzip
import json
from typing import Any, Protocol

from core.config import CONFIG


class ObjectStore(Protocol):
    name: str
    bucket: str

    async def put_bytes(self, key: str, data: bytes, content_type: str, content_encoding: str | None = None) -> None: ...

    async def get_bytes(self, key: str) -> bytes | None: ...

    async def exists(self, key: str) -> bool: ...

    async def list_keys(self, prefix: str) -> list[str]: ...


def gunzip_if_needed(data: bytes) -> bytes:
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


class MemoryStore:
    """In-process object store for the test suite. Not for deployment."""

    name = "memory"

    def __init__(self, bucket: str = "memory") -> None:
        self.bucket = bucket
        self.objects: dict[str, tuple[bytes, str, str | None]] = {}

    async def put_bytes(self, key: str, data: bytes, content_type: str, content_encoding: str | None = None) -> None:
        self.objects[key] = (bytes(data), content_type, content_encoding)

    async def get_bytes(self, key: str) -> bytes | None:
        entry = self.objects.get(key)
        return entry[0] if entry else None

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))


class GcsStore:
    name = "gcs"

    def __init__(self, bucket: str, project: str = CONFIG.gcp_project) -> None:
        self.bucket = bucket
        self.project = project
        self._client = None

    def _bucket(self):
        if self._client is None:
            from google.cloud import storage

            self._client = storage.Client(project=self.project)
        return self._client.bucket(self.bucket)

    async def put_bytes(self, key: str, data: bytes, content_type: str, content_encoding: str | None = None) -> None:
        import asyncio

        def _put() -> None:
            blob = self._bucket().blob(key)
            if content_encoding:
                blob.content_encoding = content_encoding
            blob.upload_from_string(data, content_type=content_type)

        await asyncio.to_thread(_put)

    async def get_bytes(self, key: str) -> bytes | None:
        import asyncio

        from google.api_core.exceptions import NotFound

        def _get() -> bytes | None:
            try:
                return self._bucket().blob(key).download_as_bytes(raw_download=True)
            except NotFound:
                return None

        return await asyncio.to_thread(_get)

    async def exists(self, key: str) -> bool:
        import asyncio

        return await asyncio.to_thread(lambda: self._bucket().blob(key).exists())

    async def list_keys(self, prefix: str) -> list[str]:
        import asyncio

        return await asyncio.to_thread(lambda: [b.name for b in self._bucket().list_blobs(prefix=prefix)])


# --- helpers ------------------------------------------------------------------

async def put_raw_gzip(store: ObjectStore, key: str, raw: bytes) -> None:
    """Store a response body exactly as received, gzip-compressed, served as JSON."""
    await store.put_bytes(key, gzip.compress(raw), "application/json", "gzip")


async def put_json(store: ObjectStore, key: str, document: Any) -> None:
    await store.put_bytes(key, json.dumps(document, indent=1, default=str).encode("utf-8"), "application/json")


async def get_json(store: ObjectStore, key: str) -> Any | None:
    data = await store.get_bytes(key)
    if data is None:
        return None
    return json.loads(gunzip_if_needed(data).decode("utf-8"))
