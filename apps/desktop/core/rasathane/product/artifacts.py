"""Eski çalışma köklerinin yalnız kayıtlı ve değişmemiş çıktılarını önizle."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from pathlib import Path

from rasathane.product.store import ProductStore

_MAX_PREVIEW_BYTES = 32 * 1024 * 1024


def _plain_path(path: Path) -> bool:
    """Symlink/junction hedeflerine yetki aktarımı yapma; ../ yalnız normalize edilir."""
    absolute = Path(os.path.abspath(path))
    try:
        if any(part.is_symlink() or part.is_junction() for part in (absolute, *absolute.parents)):
            return False
        return os.path.normcase(str(absolute)) == os.path.normcase(str(path.resolve(strict=True)))
    except (OSError, RuntimeError, ValueError):
        return False


def recorded_preview(store: ProductStore, requested: Path) -> bytes | None:
    """Completed analysis makbuzu + byte/SHA eşleşmesi ile sınırlı, sabit snapshot oku.

    Response aynı doğrulanmış byte'ları taşır; FileResponse gibi ikinci kez açılıp
    doğrulama ile sunum arasında farklı bir dosya okunmaz. Dosya ve klasör değiştirilemez.
    """
    if not _plain_path(requested):
        return None
    target = requested.resolve(strict=True)
    receipt = store.completed_artifact(str(target))
    if receipt is None:
        return None
    expected_path = receipt.get("path")
    expected_folder = receipt.get("folder")
    expected_hash = receipt.get("sha256")
    expected_bytes = receipt.get("bytes")
    if (
        not isinstance(expected_path, str)
        or not isinstance(expected_folder, str)
        or not isinstance(expected_hash, str)
        or not re.fullmatch(r"[a-fA-F0-9]{64}", expected_hash)
        or type(expected_bytes) is not int
        or not 0 < expected_bytes <= _MAX_PREVIEW_BYTES
    ):
        return None
    recorded = Path(expected_path)
    folder = Path(expected_folder)
    if not recorded.is_absolute() or not folder.is_absolute():
        return None
    if not _plain_path(recorded) or not _plain_path(folder):
        return None
    if recorded.resolve(strict=True) != target or target.parent != folder.resolve(strict=True):
        return None
    if receipt.get("name") != target.name:
        return None
    try:
        with target.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if before.st_size != expected_bytes:
                return None
            content = handle.read(_MAX_PREVIEW_BYTES + 1)
            after = os.fstat(handle.fileno())
    except OSError:
        return None
    if (
        len(content) != expected_bytes
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or not secrets.compare_digest(hashlib.sha256(content).hexdigest(), expected_hash.lower())
    ):
        return None
    return content
