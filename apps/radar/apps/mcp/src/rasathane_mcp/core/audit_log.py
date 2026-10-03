"""Kaynak yönetim ajanı için audit log — kalıcı değişiklik geçmişi.

Phase 32-i: Ajan üzerinden gelen kaynak ekleme, güncelleme, pasifleştirme
veya silme işlemleri bu log'a yazılır. Filesystem-authoritative (plans/
brief pattern'iyle simetrik): ``archive/audit/YYYY-MM-DD.jsonl``.

Tasarım prensipleri:
  - JSONL: line-append'lenebilir, tail'lemesi kolay.
  - Per-day file: log rotasyonu otomatik (her gün yeni dosya).
  - Atomic append: tek dosya/tek satır yazımı; çakışma riski yok
    (FastAPI background tasks kısa görevler; lock yok).
  - Hassas veri taşımaz: yalnız işlem, aktör, hedef ve özet.
  - DB dependency yok: dosya silinse bile sistem çalışır.

JSONL satır formatı:
    {
      "ts": "2026-05-14T20:30:00+00:00",
      "actor": "user" | "agent" | "system",
      "action": "source.add" | "source.update" | "source.pause" |
                "source.unpause" | "source.delete" |
                "social.add" | "social.update" | "social.pause",
      "target": "<source_id or person_id>",
      "target_name": "<display name>",
      "before": {...} | null,
      "after": {...} | null,
      "summary": "<short description>",
      "request_id": "<trace id, optional>"
    }
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import structlog

log = structlog.get_logger()

AuditAction = Literal[
    "source.add",
    "source.update",
    "source.pause",
    "source.unpause",
    "source.delete",
    "social.add",
    "social.update",
    "social.pause",
    "social.delete",
    "chat.intent",
]


def audit_dir(archive_root: Path) -> Path:
    """``<archive>/audit/`` — yoksa oluştur."""
    p = archive_root / "audit"
    p.mkdir(parents=True, exist_ok=True)
    return p


def today_log_path(archive_root: Path, *, now: datetime | None = None) -> Path:
    """Bugünün audit log dosyası (``YYYY-MM-DD.jsonl``)."""
    now = now or datetime.now(UTC)
    return audit_dir(archive_root) / f"{now.strftime('%Y-%m-%d')}.jsonl"


def append_entry(
    archive_root: Path,
    *,
    actor: str,
    action: AuditAction,
    target: str,
    target_name: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    summary: str = "",
    request_id: str | None = None,
    now: datetime | None = None,
) -> Path:
    """Append a single audit entry. Returns the log path written to.

    Atomic-ish: open in 'a' mode, write one line, close. POSIX append is
    atomic for writes < PIPE_BUF (4096 bytes); our entries are tens of
    bytes to a few hundred typically. Windows behavior is similar in
    practice (small appends don't interleave).
    """
    entry = {
        "ts": (now or datetime.now(UTC)).isoformat(),
        "actor": actor,
        "action": action,
        "target": target,
        "target_name": target_name,
        "before": before,
        "after": after,
        "summary": summary,
        "request_id": request_id,
    }
    path = today_log_path(archive_root, now=now)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
    log.info("audit.append", action=action, target=target, actor=actor)
    return path


def read_recent(
    archive_root: Path,
    *,
    limit: int = 100,
    action_filter: str | None = None,
    actor_filter: str | None = None,
) -> list[dict[str, Any]]:
    """En son ``limit`` audit satırını döndür (en yeni önce).

    Bugünün dosyasından geriye doğru gün-gün okur. ``action_filter``
    prefix match'tir: ``"source"`` → tüm source.* satırları döner.
    """
    rows: list[dict[str, Any]] = []
    base = audit_dir(archive_root)
    if not base.is_dir():
        return rows
    files = sorted(base.glob("*.jsonl"), reverse=True)
    for fp in files:
        try:
            content = fp.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in reversed(content.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if action_filter and not str(entry.get("action", "")).startswith(action_filter):
                continue
            if actor_filter and entry.get("actor") != actor_filter:
                continue
            rows.append(entry)
            if len(rows) >= limit:
                return rows
    return rows
