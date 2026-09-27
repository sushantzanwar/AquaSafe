"""Minimal image storage for field submissions: local files, addressed by an opaque key.

The database stores only the key; swapping this for object storage later only changes this module.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from db.config import uploads_dir

_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic"}
_KEY_RE = re.compile(r"^submissions/\d{4}/\d{2}/[0-9a-f]{32}\.[a-z0-9]{2,5}$")


@dataclass(frozen=True)
class StoredImage:
    key: str
    sha256: str
    size_bytes: int
    content_type: str | None


class LocalImageStorage:
    def __init__(self, root: Path | None = None):
        self.root = (root or uploads_dir()).resolve()

    def save(self, data: bytes, content_type: str | None = None, *, when=None) -> StoredImage:
        from datetime import datetime, timezone

        when = when or datetime.now(timezone.utc)
        key = f"submissions/{when:%Y}/{when:%m}/{uuid.uuid4().hex}{_EXTENSIONS.get(content_type or '', '.bin')}"
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredImage(key, hashlib.sha256(data).hexdigest(), len(data), content_type)

    def path(self, key: str) -> Path:
        if not _KEY_RE.match(key):
            raise ValueError("invalid storage key")
        return self.root / key

    def read(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)
