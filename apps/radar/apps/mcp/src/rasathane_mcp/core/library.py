"""Phase 12-iii: kütüphane core layer.

Dashboard endpoint'leri ve MCP tool'ları bu modülü ortak kullanır
(repository helper'larını sarıp serializer ekler). Snapshot stratejisi:
makale veya brief kayıt anında ``snapshot_md`` (içerik) + ``snapshot_meta``
(başlık/url/kategori) ile dondurulur — sonradan article DB'den silinse
bile kütüphane okunabilir.
"""

from __future__ import annotations

import uuid
from datetime import date as date_type
from pathlib import Path
from typing import Any

from sqlalchemy import select
from store.database import session_factory
from store.models import Article, LibraryItem
from store.repository import (
    AlreadySavedError,
    save_article_to_library,
    save_brief_to_library,
    save_deep_analysis_to_library,
)
from store.repository import (
    delete_library_item as repo_delete,
)
from store.repository import (
    get_library_item as repo_get,
)
from store.repository import (
    list_library_items as repo_list,
)
from store.repository import (
    update_library_note as repo_update_note,
)


def serialize_library_item(item: LibraryItem) -> dict[str, Any]:
    """Library item → JSON dict; UI ve MCP ortak shape.

    is_dead_link: article kaydedilmiş ama article_id NULL olmuş (article
    DB'den silinmiş). Snapshot okunabilir kalır.
    """
    snapshot_md = item.snapshot_md or ""
    is_dead_link = item.item_type == "article" and item.article_id is None
    return {
        "id": str(item.id),
        "item_type": item.item_type,
        "saved_at": item.saved_at.isoformat() if item.saved_at else None,
        "note": item.note,
        "snapshot_meta": item.snapshot_meta or {},
        "snapshot_preview": snapshot_md[:240] + ("…" if len(snapshot_md) > 240 else ""),
        "is_dead_link": is_dead_link,
    }


async def list_items(
    *,
    item_type: str | None,
    q: str | None,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    async with session_factory() as session:
        items, total = await repo_list(
            session, item_type=item_type, q=q, offset=offset, limit=limit
        )
        rows = [serialize_library_item(i) for i in items]
    return {
        "items": rows,
        "offset": offset,
        "limit": limit,
        "total": total,
        "has_more": (offset + len(rows)) < total,
    }


async def save_article(*, article_id: uuid.UUID, note: str | None) -> dict[str, Any]:
    """Bir makaleyi kütüphaneye kaydet. Snapshot anında dondurulur.

    Returns ``{"id": ...}`` veya ``{"error": "already_saved" | "not_found"}``.
    """
    async with session_factory() as session:
        # Snapshot için article'ı çek
        art = (
            await session.execute(
                select(Article)
                .options(
                    __import__("sqlalchemy.orm", fromlist=["selectinload"]).selectinload(
                        Article.source
                    )
                )
                .where(Article.id == article_id)
            )
        ).scalar_one_or_none()
        if art is None:
            return {"error": "not_found"}

        # Precedence: long ?? short ?? raw RSS ?? ""
        snapshot_md = art.summary_tr_long or art.summary_tr_short or art.summary or ""
        snapshot_meta = {
            "title": art.title,
            "url": art.url,
            "source_name": art.source.name,
            "category": art.source.category,
            "published_at": art.published_at.isoformat() if art.published_at else None,
        }

        try:
            item = await save_article_to_library(
                session,
                article_id=article_id,
                note=note,
                snapshot_md=snapshot_md,
                snapshot_meta=snapshot_meta,
            )
            await session.commit()
            return {"id": str(item.id), "saved_at": item.saved_at.isoformat()}
        except AlreadySavedError as e:
            await session.rollback()
            return {"error": "already_saved", "id": str(e)}


async def lookup_brief_status(brief_date: date_type) -> dict[str, Any] | None:
    """Belirli bir tarihin brief'i kütüphanede var mı? Varsa id döndür.

    Dashboard ``GET /api/brief`` endpoint'i bunu compose eder; UI
    bookmark ikonunun outline/filled state'ini buradan öğrenir.
    """
    async with session_factory() as session:
        item = (
            await session.execute(
                select(LibraryItem).where(
                    LibraryItem.item_type == "brief",
                    LibraryItem.brief_date == brief_date,
                )
            )
        ).scalar_one_or_none()
    if item is None:
        return None
    return {"library_item_id": str(item.id), "saved_at": item.saved_at.isoformat()}


async def save_brief(
    *,
    brief_date: date_type,
    note: str | None,
    archive_root: Path,
) -> dict[str, Any]:
    """Bir günün brief'ini kütüphaneye kaydet (filesystem snapshot)."""
    target_dir = archive_root / brief_date.isoformat()
    top_path = target_dir / "00-brief.md"
    if not top_path.is_file():
        return {"error": "brief_not_found"}

    snapshot_md = top_path.read_text(encoding="utf-8")
    snapshot_meta = {
        "date": brief_date.isoformat(),
        "generated_at": top_path.stat().st_mtime,
        "category_files": [
            p.name
            for p in sorted(target_dir.iterdir())
            if p.suffix == ".md" and p.name != "00-brief.md"
        ],
    }

    async with session_factory() as session:
        try:
            item = await save_brief_to_library(
                session,
                brief_date=brief_date,
                note=note,
                snapshot_md=snapshot_md,
                snapshot_meta=snapshot_meta,
            )
            await session.commit()
            return {"id": str(item.id), "saved_at": item.saved_at.isoformat()}
        except AlreadySavedError as e:
            await session.rollback()
            return {"error": "already_saved", "id": str(e)}


async def lookup_deep_analysis_library_items(
    job_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Phase 23: Verilen job_id'lerden hangileri kütüphanede?

    Map: ``job_id`` → ``{"library_item_id": str, "saved_at": ISO str}``.
    Liste boşsa ya da hiç eşleşme yoksa boş dict döner — analyze sayfasında
    `in_library` rozeti compose etmek için.
    """
    if not job_ids:
        return {}
    async with session_factory() as session:
        result = await session.execute(
            select(LibraryItem).where(
                LibraryItem.item_type == "deep_analysis",
                LibraryItem.deep_analysis_job_id.in_(job_ids),
            )
        )
        items = result.scalars().all()
    return {
        item.deep_analysis_job_id: {
            "library_item_id": str(item.id),
            "saved_at": item.saved_at.isoformat() if item.saved_at else None,
        }
        for item in items
        if item.deep_analysis_job_id
    }


async def save_deep_analysis(
    *,
    job_id: str,
    note: str | None,
    archive_root: Path,
) -> dict[str, Any]:
    """Phase 17-v: deep-analyze job'unu kütüphaneye kaydet.

    Job dizininden 4 artifact okunur, snapshot_md = transcript+summary
    birleşik markdown + snapshot_meta = url/title/channel/audio_path/
    mindmap_path. mindmap+audio dosyaları DB'de tutulmaz, archive/deep/
    içinde durur (live link).
    """
    target_dir = archive_root / "deep" / job_id
    if not target_dir.is_dir():
        return {"error": "deep_not_found"}

    summary_path = target_dir / "summary.md"
    transcript_path = target_dir / "transcript.md"
    if not summary_path.is_file():
        return {"error": "deep_not_found"}

    summary_md = summary_path.read_text(encoding="utf-8")
    transcript_md = transcript_path.read_text(encoding="utf-8") if transcript_path.is_file() else ""
    # Birleşik snapshot — Türkçe okuyucu için tek dokuman
    parts = [
        "# Özet\n\n" + summary_md,
    ]
    if transcript_md:
        parts.append("\n\n# Transkript\n\n" + transcript_md)
    snapshot_md = "\n".join(parts)

    # meta.json'dan title/url/channel oku
    meta_path = target_dir / "meta.json"
    raw_meta = {}
    if meta_path.is_file():
        try:
            import json as _json

            raw_meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            raw_meta = {}

    base = f"/archive/deep/{job_id}"
    snapshot_meta = {
        "job_id": job_id,
        "title": raw_meta.get("title"),
        "url": raw_meta.get("url"),
        "channel": raw_meta.get("channel"),
        "type": raw_meta.get("type", "youtube"),
        "transcript_url": f"{base}/transcript.md" if transcript_path.is_file() else None,
        "mindmap_url": f"{base}/mindmap.html" if (target_dir / "mindmap.html").is_file() else None,
        "audio_url": f"{base}/audio.mp3" if (target_dir / "audio.mp3").is_file() else None,
    }

    async with session_factory() as session:
        try:
            item = await save_deep_analysis_to_library(
                session,
                job_id=job_id,
                note=note,
                snapshot_md=snapshot_md,
                snapshot_meta=snapshot_meta,
            )
            await session.commit()
            return {"id": str(item.id), "saved_at": item.saved_at.isoformat()}
        except AlreadySavedError as e:
            await session.rollback()
            return {"error": "already_saved", "id": str(e)}


async def generate_library_audio(
    *,
    item_id: uuid.UUID,
    archive_root: Path,
) -> dict[str, Any]:
    """Phase 28-iv + 35-i: kütüphane item'ının snapshot_md'ından sesli özet üret.

    Generic — tüm item türleri (article/brief/deep_analysis/plan) için
    tek pattern. snapshot_md → ``library_audio_script`` prompt → claude
    konuşma scripti → ElevenLabs (tek-spiker Filiz/İrem) → mp3. Çıktı:
    ``archive/library/{item_id}.mp3``.

    Idempotent: dosya zaten varsa cache döner. ``.lock`` taze ise
    "in_progress" döner (Phase 21-i pattern'iyle simetrik).

    Returns: {"status": "done" | "already_exists" | "in_progress" |
              "not_found" | "failed", ...}
    """
    import json as _json

    # Item'ı DB'den çek
    async with session_factory() as session:
        item = await repo_get(session, item_id)
    if item is None:
        return {"status": "not_found", "detail": "library item bulunamadı"}

    snapshot_md = item.snapshot_md or ""
    if not snapshot_md.strip():
        return {"status": "failed", "detail": "snapshot_md boş; ses üretilemez"}

    # Audio path: archive/library/{item_id}.mp3
    library_audio_dir = archive_root / "library"
    library_audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = library_audio_dir / f"{item_id}.mp3"

    if audio_path.is_file():
        return {
            "status": "already_exists",
            "audio_url": f"/archive/library/{item_id}.mp3",
            "bytes": audio_path.stat().st_size,
        }

    # Lockfile: concurrent generation guard
    lock_path = library_audio_dir / f".{item_id}.lock"
    if lock_path.is_file():
        try:
            from datetime import UTC
            from datetime import datetime as _dt

            data = _json.loads(lock_path.read_text(encoding="utf-8"))
            started = _dt.fromisoformat(data["started_at"])
            elapsed = (_dt.now(UTC) - started).total_seconds()
            if elapsed < 600:  # 10 dk stale threshold
                return {"status": "in_progress", "elapsed_sec": int(elapsed)}
            lock_path.unlink(missing_ok=True)
        except (_json.JSONDecodeError, KeyError, ValueError):
            lock_path.unlink(missing_ok=True)

    try:
        import os as _os
        from datetime import UTC
        from datetime import datetime as _dt

        fd = _os.open(str(lock_path), _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY)
        with _os.fdopen(fd, "w", encoding="utf-8") as f:
            _json.dump({"started_at": _dt.now(UTC).isoformat(), "pid": _os.getpid()}, f)
    except FileExistsError:
        return {"status": "in_progress"}

    # Claude → konuşma scripti → ElevenLabs (Phase 35-i)
    try:
        from llm.claude_client import synthesize_with_claude
        from llm.prompts import load_prompt, render
        from llm.tts import synthesize_to_mp3

        snapshot_meta = item.snapshot_meta or {}
        title = (
            snapshot_meta.get("title")
            or snapshot_meta.get("date")
            or snapshot_meta.get("full_name")
            or "Kayıt"
        )
        type_label = {
            "article": "makale",
            "brief": "günlük gündem",
            "deep_analysis": "derinlemesine analiz",
            "plan": "geliştirme planı",
        }.get(item.item_type, "kayıt")

        prompt = render(
            load_prompt("library_audio_script"),
            title=str(title),
            type_label=type_label,
            content=snapshot_md,
        )
        audio_script = (await synthesize_with_claude(prompt)).strip()
        if not audio_script:
            raise RuntimeError("library_audio: claude empty output")

        # Script dosyası (debug + traceability)
        script_path = library_audio_dir / f"{item_id}.script.txt"
        script_path.write_text(audio_script, encoding="utf-8")

        await synthesize_to_mp3(audio_script, output_path=audio_path)
        return {
            "status": "done",
            "audio_url": f"/archive/library/{item_id}.mp3",
            "bytes": audio_path.stat().st_size,
            "script_chars": len(audio_script),
        }
    except Exception as e:
        err = str(e) or repr(e) or e.__class__.__name__
        return {"status": "failed", "detail": err[:500]}
    finally:
        lock_path.unlink(missing_ok=True)


async def delete_item(item_id: uuid.UUID) -> bool:
    async with session_factory() as session:
        ok = await repo_delete(session, item_id)
        if ok:
            await session.commit()
        return ok


async def update_note(item_id: uuid.UUID, note: str | None) -> dict[str, Any] | None:
    async with session_factory() as session:
        item = await repo_update_note(session, item_id, note)
        if item is None:
            return None
        await session.commit()
        # Refresh için yeniden çek
        item = await repo_get(session, item_id)
    if item is None:
        return None
    return {"id": str(item.id), "note": item.note}
