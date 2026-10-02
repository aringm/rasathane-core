"""Phase 19-v: kütüphane → kişisel geliştirme planı + yapılacaklar listesi.

Kullanıcı kütüphanesinde biriken makaleler/brief'ler/analizler claude'a
verilir, kişiye özel bir plan üretilir. Plan filesystem-authoritative
(``archive/plans/{plan_id}/plan.md``); to-do'lar markdown checklist
biçiminde — kullanıcı UI'dan tıklayınca dosyada `- [ ]` ↔ `- [x]`
toggle olur.

State machine (mirrors deep_analyze):
- ``not_found``: dizin yok
- ``running``: lockfile fresh
- ``done``: plan.md var
- ``failed``: .last-error.txt var

Plan_id: SHA256(saved_at_window + types_filter + q)[:16] — aynı seçim
ikinci kez aynı plan'a düşer (cache).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from llm.claude_client import synthesize_with_claude
from llm.prompts import load_prompt, render
from sqlalchemy import select
from store.database import session_factory
from store.models import LibraryItem

log = structlog.get_logger()

PLANS_SUBDIR = "plans"
PLAN_NAME = "plan.md"
LOCKFILE_NAME = ".lock"
LAST_ERROR_NAME = ".last-error.txt"
META_NAME = "meta.json"
LOCKFILE_STALE_SECONDS = 600
PER_ITEM_BODY_LIMIT = 1500  # snapshot_md karakteri/item
MAX_ITEMS = 30  # claude prompt boyutunu sınırla


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def compute_plan_id(item_ids: list[str]) -> str:
    """Deterministic 16-hex; aynı item set'i → aynı plan_id (cache key)."""
    sorted_ids = sorted(item_ids)
    digest = hashlib.sha256("|".join(sorted_ids).encode()).hexdigest()
    return digest[:16]


def plan_dir(*, archive_root: Path, plan_id: str) -> Path:
    return archive_root / PLANS_SUBDIR / plan_id


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


def _acquire_lockfile(target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    lockfile = target_dir / LOCKFILE_NAME
    if lockfile.is_file():
        try:
            lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
            started_at = datetime.fromisoformat(lock_data["started_at"])
            elapsed = (datetime.now(UTC) - started_at).total_seconds()
            if elapsed >= LOCKFILE_STALE_SECONDS:
                lockfile.unlink(missing_ok=True)
        except (json.JSONDecodeError, KeyError, ValueError):
            lockfile.unlink(missing_ok=True)
    fd = os.open(str(lockfile), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"started_at": _now_iso(), "pid": os.getpid()}, f)
    return lockfile


def lookup_status(*, archive_root: Path, plan_id: str) -> dict[str, Any]:
    target = plan_dir(archive_root=archive_root, plan_id=plan_id)
    if not target.is_dir():
        return {"plan_id": plan_id, "status": "not_found"}

    lockfile = target / LOCKFILE_NAME
    plan_path = target / PLAN_NAME
    last_error = target / LAST_ERROR_NAME
    meta_path = target / META_NAME

    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}

    if lockfile.is_file():
        try:
            lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
            started = datetime.fromisoformat(lock_data["started_at"])
            elapsed = int((datetime.now(UTC) - started).total_seconds())
            if elapsed < LOCKFILE_STALE_SECONDS:
                return {
                    "plan_id": plan_id,
                    "status": "running",
                    "started_at": lock_data["started_at"],
                    "elapsed_sec": elapsed,
                    "meta": meta,
                }
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    if plan_path.is_file():
        return {
            "plan_id": plan_id,
            "status": "done",
            "plan_md": plan_path.read_text(encoding="utf-8"),
            "generated_at": datetime.fromtimestamp(plan_path.stat().st_mtime, UTC).isoformat(),
            "meta": meta,
        }

    if last_error.is_file():
        return {
            "plan_id": plan_id,
            "status": "failed",
            "error": last_error.read_text(encoding="utf-8")[:500],
            "meta": meta,
        }

    return {"plan_id": plan_id, "status": "not_found", "meta": meta}


def _format_library_items_for_prompt(items: list[LibraryItem]) -> str:
    """Kütüphane item'larını claude prompt'una uygun düz metne çevir."""
    parts = []
    for i, item in enumerate(items, 1):
        meta = item.snapshot_meta or {}
        title = meta.get("title") or meta.get("date") or "(başlıksız)"
        url = meta.get("url", "")
        parts.append(f"### {i}. [{item.item_type}] {title}")
        if url:
            parts.append(f"URL: {url}")
        if meta.get("source_name"):
            parts.append(f"Kaynak: {meta['source_name']}")
        if meta.get("category"):
            parts.append(f"Kategori: {meta['category']}")
        if item.note:
            parts.append(f"Not: {item.note}")
        body = (item.snapshot_md or "")[:PER_ITEM_BODY_LIMIT]
        parts.append(f"İçerik:\n{body}\n")
        parts.append("---")
    return "\n".join(parts)


async def generate_plan(
    *,
    archive_root: Path,
    item_types: list[str] | None = None,
    q: str | None = None,
    plan_title: str = "Geliştirme Planı",
) -> dict[str, Any]:
    """Kütüphaneyi oku, claude ile plan üret, plan.md atomik yaz.

    item_types: ["article", "brief", "deep_analysis"] alt seçimi.
                None → tümü.
    q: snapshot_meta.title + note + snapshot_md ILIKE filter.
    plan_title: claude'a verilen başlık (kullanıcı dilerse override eder).

    Returns: {plan_id, status: 'done'|'in_progress'|'failed'|'empty_library',
              detail?, meta?}
    """
    from sqlalchemy import or_

    async with session_factory() as session:
        stmt = select(LibraryItem)
        if item_types:
            valid = [t for t in item_types if t in ("article", "brief", "deep_analysis")]
            if valid:
                stmt = stmt.where(LibraryItem.item_type.in_(valid))
        if q:
            pat = f"%{q}%"
            stmt = stmt.where(
                or_(
                    LibraryItem.note.ilike(pat),
                    LibraryItem.snapshot_md.ilike(pat),
                    LibraryItem.snapshot_meta["title"].astext.ilike(pat),
                )
            )
        stmt = stmt.order_by(LibraryItem.saved_at.desc()).limit(MAX_ITEMS)
        items = list((await session.execute(stmt)).scalars().all())

    if not items:
        return {
            "plan_id": None,
            "status": "empty_library",
            "detail": "Kütüphane boş veya seçim filtresine uyan kayıt yok.",
        }

    plan_id = compute_plan_id([str(i.id) for i in items])
    target_dir = plan_dir(archive_root=archive_root, plan_id=plan_id)
    plan_path = target_dir / PLAN_NAME

    # Cache hit
    if plan_path.is_file():
        return {
            "plan_id": plan_id,
            "status": "already_exists",
            "generated_at": datetime.fromtimestamp(plan_path.stat().st_mtime, UTC).isoformat(),
        }

    # Lockfile
    try:
        lockfile = _acquire_lockfile(target_dir)
    except FileExistsError:
        return {"plan_id": plan_id, "status": "in_progress"}

    last_error_path = target_dir / LAST_ERROR_NAME
    last_error_path.unlink(missing_ok=True)
    started_at = _now_iso()

    try:
        log.info("plan.generate.start", plan_id=plan_id, items=len(items))
        items_text = _format_library_items_for_prompt(items)
        prompt = render(
            load_prompt("library_plan"),
            library_items=items_text,
            plan_title=plan_title,
        )
        plan_md = (await synthesize_with_claude(prompt)).strip()
        if not plan_md:
            raise RuntimeError("plan: claude empty output")

        _atomic_write_text(plan_path, plan_md)

        # Meta.json
        meta = {
            "plan_id": plan_id,
            "started_at": started_at,
            "items_used": len(items),
            "filters": {
                "item_types": item_types,
                "q": q,
            },
            "title": plan_title,
            "item_ids": [str(i.id) for i in items],
        }
        _atomic_write_text(target_dir / META_NAME, json.dumps(meta, ensure_ascii=False))

        log.info("plan.generate.done", plan_id=plan_id, chars=len(plan_md))
        return {
            "plan_id": plan_id,
            "status": "done",
            "started_at": started_at,
        }
    except Exception as e:
        err_text = str(e)[:2000]
        last_error_path.write_text(err_text, encoding="utf-8")
        log.error("plan.generate.failed", plan_id=plan_id, err=err_text[:200])
        return {
            "plan_id": plan_id,
            "status": "failed",
            "detail": err_text[:500],
        }
    finally:
        lockfile.unlink(missing_ok=True)


def toggle_todo(
    *,
    archive_root: Path,
    plan_id: str,
    line_index: int,
) -> dict[str, Any]:
    """Plan.md'deki bir to-do checkbox'ını toggle et.

    line_index: dosyadaki 0-bazlı satır numarası. Yalnız `- [ ]` veya
    `- [x]` ile başlayan satırlar değişir; aksi halde noop.
    """
    target = plan_dir(archive_root=archive_root, plan_id=plan_id)
    plan_path = target / PLAN_NAME
    if not plan_path.is_file():
        return {"error": "not_found"}

    text = plan_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    if line_index < 0 or line_index >= len(lines):
        return {"error": "invalid_line"}

    line = lines[line_index]
    stripped = line.lstrip()
    indent = line[: len(line) - len(stripped)]
    if stripped.startswith("- [ ]"):
        lines[line_index] = indent + "- [x]" + stripped[5:]
    elif stripped.startswith("- [x]") or stripped.startswith("- [X]"):
        lines[line_index] = indent + "- [ ]" + stripped[5:]
    else:
        return {"error": "not_a_checkbox", "line": line[:80]}

    new_text = "\n".join(lines)
    _atomic_write_text(plan_path, new_text)
    return {"ok": True, "line": lines[line_index]}
