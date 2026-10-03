"""FastAPI app for the Rasathane dashboard.

Phase 11-ii.4 scope: HTML pages (Jinja2 templates + Alpine.js client).
The three pages — ``/``, ``/sources``, ``/analyze`` — render server-side
shells that hydrate via the JSON endpoints introduced in 11-ii.3. No
Next.js, no build step, fully self-contained inside the MCP wheel.

Static assets (Alpine vendored) are served from ``static/`` so the
dashboard works offline once the MCP package is installed. Tests cover
that the routes return 200 + the expected page markers.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Literal

# Phase 35-iii: Dashboard standalone uvicorn olarak çalıştırılır (Claude
# Desktop spawn'lı MCP server değil) → ELEVENLABS_API_KEY ve diğer env'ler
# `.env` dosyasından otomatik yüklenmeli. Sessiz fallback: dotenv yoksa veya
# .env yoksa, normal `os.environ` zaten okunmaya devam eder.
try:
    from dotenv import load_dotenv

    # Repo root'tan .env'i bul (apps/mcp/src/rasathane_mcp/dashboard/app.py
    # → parents[5] = repo root). override=False: shell env > .env.
    _DOTENV_PATH = Path(__file__).resolve().parents[5] / ".env"
    if _DOTENV_PATH.is_file():
        load_dotenv(_DOTENV_PATH, override=False)
except ImportError:
    pass

import structlog
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from llm.presets import (
    DEFAULT_PRESETS,
    AudioPreset,
    get_active_presets,
    load_user_presets,
    save_user_presets,
)
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from store.database import session_factory
from store.models import Source
from store.repository import set_user_disabled

from rasathane_mcp.core import articles as core_articles
from rasathane_mcp.core import brief as core_brief
from rasathane_mcp.core import library as core_library
from rasathane_mcp.core import sources as core_sources
from rasathane_mcp.core import stats as core_stats
from rasathane_mcp.core.paths import ARCHIVE_ROOT
from rasathane_mcp.core.serializers import serialize_article, serialize_source

log = structlog.get_logger()

_DASHBOARD_DIR = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=str(_DASHBOARD_DIR / "templates"))
_STATIC_DIR = _DASHBOARD_DIR / "static"

# Phase 32-v: ElevenLabs /v1/voices response cache path (1h TTL).
# Module-level computed once → async voice endpoint sync IO yapmasın.
# parents[4] = repo root (apps/mcp/src/rasathane_mcp/dashboard → repo).
_ELEVENLABS_VOICES_CACHE_PATH = _DASHBOARD_DIR.parents[4] / "data" / "elevenlabs_voices_cache.json"


class ToggleBody(BaseModel):
    """``POST /api/sources/{id}/toggle`` body."""

    disabled: bool = Field(..., description="True to mute the source, False to unmute.")


class GenerateBriefBody(BaseModel):
    """``POST /api/brief/generate`` body."""

    force: bool = Field(False, description="True to overwrite today's brief.")


class LibrarySaveBody(BaseModel):
    """``POST /api/library`` body."""

    item_type: str = Field(..., description="'article' | 'brief' | 'deep_analysis'")
    article_id: uuid.UUID | None = None
    brief_date: str | None = Field(None, description="YYYY-MM-DD; required for brief")
    deep_analysis_job_id: str | None = Field(
        None,
        description="16-hex job_id; required for deep_analysis",
        pattern=r"^[0-9a-f]{16}$",
    )
    note: str | None = None


class LibraryNoteBody(BaseModel):
    """``PATCH /api/library/{id}`` body."""

    note: str | None = None


class AnalyzeBody(BaseModel):
    """``POST /api/analyze`` body — Phase 11-iii backend will consume this."""

    url: str = Field(..., min_length=1, description="URL to analyse (yt/gh/arxiv/etc).")
    use_whisper: bool = Field(
        False,
        description="Phase 21-i: YouTube'da yt-dlp altyazı yoksa whisper-medium "
        "ile transcribe et (5-10 dk pahalı). Default off.",
    )
    force: bool = Field(
        False,
        description="True ise mevcut cache'i yok say, baştan üret (artifact'ları "
        "atomic write ile üzerine yazar).",
    )


class AddendumIn(BaseModel):
    """``POST /api/analyze/deep/{job_id}/addendum`` body (Phase 36-iii).

    Üç addendum türü tek endpoint'ten gider; type'a göre farklı alanlar
    zorunlu: angle ⇒ slug+title, freeform ⇒ question, compare ⇒ source_ids
    (2-5 adet). Doğrulama endpoint içinde 422'lerle yapılır.
    """

    type: Literal["angle", "freeform", "compare"]
    slug: str | None = None
    title: str | None = None
    question: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class AddSourceBody(BaseModel):
    """``POST /api/sources`` body — Phase 15-iv user-added source.

    Pydantic Literal enforce: ``category`` ve ``type`` 422 reject if
    unknown. URL en az http(s) prefix isteniyor; gerçek erişilebilirlik
    pulse sync sırasında doğrulanır.

    Phase 32-i: 5 yeni kategori (china_ai_models, east_asia_ai_models,
    open_weight_models, model_infra, social_watch) ve ``social_person``
    type eklendi. ``social_person`` tipinin INGESTER_REGISTRY'de
    karşılığı yok — sync sırasında graceful skip eder; katalog olarak
    yaşamaya devam eder.
    """

    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(
        ...,
        pattern=(
            r"^(turk_hukuku|dunya_ai|turkiye_ai|legaltech|muhakeme_stack"
            r"|china_ai_models|east_asia_ai_models|open_weight_models"
            r"|model_infra|social_watch)$"
        ),
    )
    type: str = Field(
        ...,
        pattern=r"^(rss|arxiv|reddit|youtube_channel|social_person)$",
    )
    url: str = Field(..., pattern=r"^https?://.+", min_length=8)
    fetch_interval_minutes: int = Field(60, ge=5, le=1440)
    metadata: dict[str, Any] | None = Field(
        None,
        description="Opsiyonel metadata; reliability/region/topics/notes vb. (Phase 32-i).",
    )


# Phase 36-ii: preset format whitelist + Pydantic body
_VALID_FORMATS = frozenset(
    {"panel_3", "duo_expert_critic", "solo_narrator", "debate"}
)


class PresetIn(BaseModel):
    """``POST /api/tts/presets`` body — kullanıcı tanımlı audio preset."""

    id: str = Field(..., min_length=1, max_length=40, pattern=r"^[a-z0-9_]+$")
    name: str = Field(..., min_length=1, max_length=40)
    description: str = Field(default="", max_length=200)
    format: str
    prompt_variant: str = Field(..., min_length=1, max_length=80)
    target_minutes: list[float]
    voices: dict[str, str] = Field(default_factory=dict)
    voice_settings: dict[str, dict[str, float]] = Field(default_factory=dict)

    @field_validator("format")
    @classmethod
    def _validate_format(cls, v: str) -> str:
        if v not in _VALID_FORMATS:
            raise ValueError(f"format must be one of {sorted(_VALID_FORMATS)}")
        return v

    @field_validator("target_minutes")
    @classmethod
    def _validate_target_minutes(cls, v: list[float]) -> list[float]:
        if len(v) != 2 or not (0 < v[0] < v[1] <= 12):
            raise ValueError(
                "target_minutes must be [min, max], 0 < min < max <= 12"
            )
        return v


def _preset_to_dict(p: AudioPreset) -> dict[str, Any]:
    """Phase 36-ii: AudioPreset -> JSON-safe dict (tuple -> list)."""
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "format": p.format,
        "prompt_variant": p.prompt_variant,
        "target_minutes": list(p.target_minutes),
        "voices": dict(p.voices),
        "voice_settings": {k: dict(v) for k, v in p.voice_settings.items()},
        "is_default": p.is_default,
    }


async def _sync_source_in_background(source_id: uuid.UUID) -> None:
    """Off-thread fetch trigger — never raises so BackgroundTasks doesn't poison the loop."""
    # Late import: avoids pulling ingester deps (httpx pools, etc) at module
    # import time when the dashboard never receives a sync request.
    from ingestion.sync import sync_one_source

    try:
        async with session_factory() as session:
            src = (
                await session.execute(select(Source).where(Source.id == source_id))
            ).scalar_one_or_none()
            if src is None:
                log.warning("dashboard.sync.unknown_source", source_id=str(source_id))
                return
            inserted = await sync_one_source(session, src)
            await session.commit()
            log.info(
                "dashboard.sync.ok",
                source=src.name,
                source_id=str(source_id),
                inserted=inserted,
            )
    except Exception as e:
        log.error(
            "dashboard.sync.failed",
            source_id=str(source_id),
            error=str(e),
            error_type=type(e).__name__,
        )


async def _sync_all_in_background() -> None:
    """Phase 20-i: tüm efektif aktif kaynakları paralel olarak fetch et.

    Hourly cron'un eşdeğeri (worker.main._hourly_sync_job). Sync round
    sonrası translate_short_pending tetiklenir, ardından brief auto-regen
    (Phase 32-ii) — eski "Yeniden üret" confirm akışını bertaraf eder.

    Brief auto-regen 'sessiz' modda: lockfile ya da fresh brief varsa
    skip eder; hatayı log'a yazar, sync sonucunu bozmaz.
    """
    from worker.sync import sync_all_enabled

    try:
        async with session_factory() as session:
            results = await sync_all_enabled(session)
        log.info("dashboard.sync_all.ok", results=results)

        # Post-sync translate (cron pattern): yeni eklenen + birikmiş NULL'lar
        try:
            from llm.translate import translate_short_pending

            async with session_factory() as session:
                success, fail = await translate_short_pending(session, limit=100)
            log.info("dashboard.sync_all.translate_done", success=success, fail=fail)
        except Exception as e:
            log.error("dashboard.sync_all.translate_failed", err=str(e)[:200])

        # Phase 32-ii: title TR çevirisi (akış-time) — summary çevirisinden sonra
        # çünkü prompt template'i title + summary'yi birlikte kullanırsa cache hit.
        # Hata olursa brief üretimini bloklamaz.
        try:
            from llm.translate import translate_titles_pending

            async with session_factory() as session:
                t_success, t_fail = await translate_titles_pending(session, limit=50)
            log.info("dashboard.sync_all.title_tr_done", success=t_success, fail=t_fail)
        except Exception as e:
            log.error("dashboard.sync_all.title_tr_failed", err=str(e)[:200])

        # Phase 32-ii: Akış yenilendikten sonra brief otomatik güncellensin.
        # Eski Phase 20'deki RASATHANE_AUTO_BRIEF env-gated davranıştan
        # farkı: UI'dan tıklanan "Akışı yenile" daima brief'i tazeler
        # (kullanıcı niyeti belli). Cron'daki davranış env-gated kalır.
        try:
            from rasathane_mcp.core.brief import generate_brief

            async with session_factory() as session:
                # force=True: mevcut brief'in üzerine yaz (kullanıcı yenile dedi).
                # Eski audio dosyaları purge_audio_artifacts ile temizlenir.
                result = await generate_brief(session, archive_root=ARCHIVE_ROOT, force=True)
            log.info("dashboard.sync_all.brief_auto", result=result)
        except Exception as e:
            log.error("dashboard.sync_all.brief_auto_failed", err=str(e)[:200])
    except Exception as e:
        log.error(
            "dashboard.sync_all.failed",
            error=str(e)[:300],
            error_type=type(e).__name__,
        )


def create_app() -> FastAPI:
    """Build a fresh FastAPI app instance.

    Factory (not a module-level singleton) so tests can spin up isolated
    apps and uvicorn picks up a clean state per lifespan invocation.
    """
    app = FastAPI(title="Rasathane Dashboard", docs_url=None, redoc_url=None)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "rasathane-dashboard"}

    @app.get("/api/system/whisper")
    async def whisper_status() -> dict[str, Any]:
        """Phase 26: UI'a Docker whisper service'in durumu.

        ``WHISPER_API_URL`` env varsa enabled=True dönülür; bu durumda
        deep-dive YouTube path'i otomatik whisper fallback yapar (yt-dlp
        altyazı 429 alırsa). UI bu bilgiye göre checkbox'ı bilgi mesajına
        çevirir.

        URL'in gerçekten ulaşılır olup olmadığını ping etmiyoruz — env
        var "kullanıcı niyeti" olarak sayılır; ping background'da fail
        ederse fetch_transcript fallback'i gerçek hatayı log'lar.
        """
        api_url = os.environ.get("WHISPER_API_URL", "").strip()
        return {"enabled": bool(api_url), "api_url": api_url or None}

    @app.get("/api/brief")
    async def brief(date: str | None = None) -> dict[str, Any]:
        payload = core_brief.load_brief(archive_root=ARCHIVE_ROOT, date=date)
        # Phase 13: kütüphane bookmark state — yalnız geçerli brief okunduğunda
        if payload.get("date") and not payload.get("error") and not payload.get("generating"):
            from datetime import date as _d

            try:
                bdate = _d.fromisoformat(payload["date"])
            except ValueError:
                bdate = None
            if bdate is not None:
                status = await core_library.lookup_brief_status(bdate)
                payload["in_library"] = status is not None
                payload["library_item_id"] = status["library_item_id"] if status else None
        return payload

    @app.get("/api/briefs")
    async def briefs(limit: int = 20) -> dict[str, Any]:
        """Geçmiş gündem listesi (en yeni önce). Filesystem-authoritative."""
        capped = max(1, min(limit, 100))
        items = core_brief.list_briefs(ARCHIVE_ROOT, limit=capped)
        return {"items": items, "limit": capped}

    @app.post("/api/brief/generate", status_code=202)
    async def brief_generate(
        body: GenerateBriefBody, background: BackgroundTasks
    ) -> dict[str, Any]:
        """Bugünün gündemini üretir (background task'le subprocess başlatır).

        202 Accepted: tetiklendi (dosya henüz yazılmadı, polling /api/brief).
        409 in_progress / already_exists: çakışma.
        503 cli_not_found: claude CLI PATH'te yok.
        """
        # Pre-flight: bugünün brief'i var mı + force?
        from datetime import UTC
        from datetime import datetime as _dt

        today = _dt.now(UTC).strftime("%Y-%m-%d")
        existing = ARCHIVE_ROOT / today / "00-brief.md"
        if existing.is_file() and not body.force:
            mtime = _dt.fromtimestamp(existing.stat().st_mtime, UTC).isoformat()
            raise HTTPException(
                status_code=409,
                detail={"error": "already_exists", "generated_at": mtime},
            )

        # Lockfile fresh mı?
        from rasathane_mcp.core.brief import LOCKFILE_NAME, LOCKFILE_STALE_SECONDS

        lockfile = ARCHIVE_ROOT / today / LOCKFILE_NAME
        if lockfile.is_file():
            try:
                import json as _json

                lock_data = _json.loads(lockfile.read_text(encoding="utf-8"))
                started = _dt.fromisoformat(lock_data["started_at"])
                elapsed = (_dt.now(UTC) - started).total_seconds()
                if elapsed < LOCKFILE_STALE_SECONDS:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "in_progress",
                            "started_at": lock_data["started_at"],
                        },
                    )
            except (Exception, HTTPException) as e:
                if isinstance(e, HTTPException):
                    raise

        # CLI present?
        import shutil as _sh

        if _sh.which("claude") is None:
            raise HTTPException(
                status_code=503,
                detail={"error": "cli_not_found", "cli": "claude"},
            )

        async def _run_in_background() -> None:
            async with session_factory() as session:
                await core_brief.generate_brief(
                    session, archive_root=ARCHIVE_ROOT, force=body.force
                )

        background.add_task(_run_in_background)
        return {"started_at": _dt.now(UTC).isoformat(), "date": today}

    @app.post("/api/brief/audio", status_code=202)
    async def brief_audio(
        body: dict[str, Any] | None,
        background: BackgroundTasks,
        force: bool = False,
    ) -> dict[str, Any]:
        """Phase 22-iii: günün brief'ini sesli özete dönüştür (claude → TTS).

        Body opsiyonel: {"date": "YYYY-MM-DD"} (default bugün).
        Query: ``force=true`` → mevcut mp3'ü sil + yeniden üret (Phase 32-v.1
        düzeltme — önceden force iletildiği halde göz ardı ediliyordu).
        202 + queued / 200 + already_exists / 404 brief_missing.
        """
        date = (body or {}).get("date")

        # Pre-flight: brief var mı + audio.mp3 var mı?
        from datetime import UTC
        from datetime import datetime as _dt

        target_date = date or _dt.now(UTC).strftime("%Y-%m-%d")
        target_dir = ARCHIVE_ROOT / target_date
        if not (target_dir / "00-brief.md").is_file():
            raise HTTPException(
                status_code=404,
                detail={"error": "brief_missing", "date": target_date},
            )
        audio_path = target_dir / "00-brief.mp3"
        if audio_path.is_file() and not force:
            return {
                "status": "already_exists",
                "audio_url": f"/archive/{target_date}/00-brief.mp3",
                "bytes": audio_path.stat().st_size,
            }
        # Phase 32-v.1: force=true → eski mp3 + audio script JSON sil.
        # generate_brief_audio cache miss'ten Claude'a gider, baştan üretir.
        if audio_path.is_file() and force:
            audio_path.unlink(missing_ok=True)
            (target_dir / "00-brief.audio.json").unlink(missing_ok=True)
            log.info("brief.audio.force_regen", date=target_date)

        background.add_task(
            core_brief.generate_brief_audio,
            archive_root=ARCHIVE_ROOT,
            date=date,
        )
        return {"status": "queued", "date": target_date}

    @app.get("/api/articles")
    async def articles(
        category: str | None = None,
        type_: str | None = Query(None, alias="type"),
        source_name: str | None = None,
        since_hours: int = core_articles.DEFAULT_RECENT_HOURS,
        limit: int = core_articles.DEFAULT_RECENT_LIMIT,
        offset: int = 0,
        with_library: bool = False,
    ) -> dict[str, Any]:
        rows = await core_articles.list_recent(
            category=category,
            type_=type_,
            source_name=source_name,
            since_hours=since_hours,
            limit=limit,
            offset=offset,
        )
        # Phase 12-iii: opt-in library state — tek SQL ile id→library_item_id map
        library_map: dict[str, str] = {}
        if with_library and rows:
            from store.models import LibraryItem

            article_ids = [a.id for a in rows]
            async with session_factory() as session:
                lib_rows = (
                    await session.execute(
                        select(LibraryItem.id, LibraryItem.article_id).where(
                            LibraryItem.article_id.in_(article_ids)
                        )
                    )
                ).all()
            library_map = {str(art_id): str(item_id) for item_id, art_id in lib_rows}

        articles = []
        for a in rows:
            kwargs: dict[str, Any] = {}
            if with_library:
                aid = str(a.id)
                kwargs["in_library"] = aid in library_map
                kwargs["library_item_id"] = library_map.get(aid)
            articles.append(serialize_article(a, **kwargs))

        return {
            "articles": articles,
            "offset": offset,
            "limit": limit,
            "has_more": len(rows) == limit,
        }

    @app.get("/api/sources")
    async def sources(
        category: str | None = None,
        type_: str | None = Query(None, alias="type"),
        enabled_only: bool = False,
    ) -> list[dict[str, Any]]:
        rows = await core_sources.list_sources(
            category=category, type_=type_, enabled_only=enabled_only
        )
        return [serialize_source(s) for s in rows]

    @app.get("/api/stats")
    async def stats() -> dict[str, Any]:
        return await core_stats.compute_stats()

    @app.post("/api/sources", status_code=201)
    async def add_source(body: AddSourceBody) -> dict[str, Any]:
        """Phase 15-iv: Yeni kaynak ekleme (user-added).

        201 created + serialized source. 409 (name, type, url) çakışırsa.
        feeds.yaml'a dokunulmaz; ``metadata.added_by="user"`` flag'i
        ile yaml-managed satırlardan ayrılır.

        Phase 32-i: Opsiyonel ``metadata`` body alanı; reliability/region/
        topics gibi kayıt zenginleştirme alanları taşır. ``added_by`` her
        zaman "user" ile override edilir (kaynak izlenebilirliği).
        """
        from store.repository import DuplicateSourceError, add_user_source

        try:
            async with session_factory() as session:
                src = await add_user_source(
                    session,
                    name=body.name,
                    category=body.category,
                    type=body.type,
                    url=body.url,
                    fetch_interval_minutes=body.fetch_interval_minutes,
                    extra_metadata=body.metadata,
                )
                await session.commit()
                # Refresh to read back generated id + defaults
                await session.refresh(src)
                payload = serialize_source(src)
        except DuplicateSourceError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        return payload

    @app.delete("/api/sources/{source_id}")
    async def delete_source(source_id: uuid.UUID) -> dict[str, Any]:
        """Phase 15-iv: User-added kaynağı sil.

        404 not found. 403 forbidden (yaml-managed; toggle ile sustur).
        Başarıda 200 + ``{"deleted": true}``. Cascade ile articles da gider.
        """
        from store.repository import NotUserAddedError, delete_user_source

        try:
            async with session_factory() as session:
                await delete_user_source(session, source_id)
                await session.commit()
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except NotUserAddedError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        return {"deleted": True, "id": str(source_id)}

    @app.post("/api/sources/{source_id}/toggle")
    async def toggle(source_id: uuid.UUID, body: ToggleBody) -> dict[str, Any]:
        try:
            async with session_factory() as session:
                effective = await set_user_disabled(session, source_id, disabled=body.disabled)
                await session.commit()
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return {
            "id": str(source_id),
            "is_user_disabled": body.disabled,
            "effective_enabled": effective,
        }

    @app.post("/api/sources/{source_id}/sync")
    async def sync(source_id: uuid.UUID, background_tasks: BackgroundTasks) -> dict[str, Any]:
        # Verify the source exists before accepting the trigger so the
        # 404 lands synchronously, not silently in the background.
        async with session_factory() as session:
            exists = (
                await session.execute(select(Source.id).where(Source.id == source_id))
            ).scalar_one_or_none()
        if exists is None:
            raise HTTPException(status_code=404, detail=f"source {source_id} not found")
        background_tasks.add_task(_sync_source_in_background, source_id)
        return {"status": "queued", "id": str(source_id)}

    @app.post("/api/sources/sync-all", status_code=202)
    async def sync_all(background_tasks: BackgroundTasks) -> dict[str, Any]:
        """Phase 20-i: tüm efektif aktif kaynakları paralel olarak yenile.

        Hourly cron'un manuel eşdeğeri. UI'dan tek-tık ile çalıştırılır;
        kullanıcı saatin gelmesini beklemeden akışı tazeler. Background
        task: ``_sync_all_in_background`` → ``sync_all_enabled``.
        """
        background_tasks.add_task(_sync_all_in_background)
        return {"status": "queued", "scope": "all_enabled"}

    @app.post("/api/analyze")
    async def analyze(body: AnalyzeBody) -> dict[str, Any]:
        """URL'i tespit eder, ingestion modülünden ham metadata çeker.

        Phase 11-iii: youtube + github + arxiv metadata. Heavy fetches
        (transcript via whisper, repomix dump) henüz yok — Phase 12-iv
        adayı. Claude Desktop bu metadata'yı kendi context'inde analiz
        edebilir.
        """
        from rasathane_mcp.core.deep_analyze import detect_url_type

        detected = detect_url_type(body.url)
        if detected == "unknown":
            return {
                "url": body.url,
                "detected_type": "unknown",
                "error": "Bilinmeyen URL türü; youtube/github/arxiv bekleniyor",
            }

        try:
            if detected == "youtube":
                from ingestion.youtube import fetch_metadata as fetch_yt

                meta = await fetch_yt(body.url)
                return {
                    "url": body.url,
                    "detected_type": "youtube",
                    "metadata": {
                        "video_id": meta.video_id,
                        "title": meta.title,
                        "channel": meta.channel,
                        "duration_seconds": meta.duration_seconds,
                    },
                }

            if detected == "github":
                from ingestion.github import fetch_repo_metadata

                repo = await fetch_repo_metadata(body.url)
                return {
                    "url": body.url,
                    "detected_type": "github",
                    "metadata": {
                        "full_name": repo.full_name,
                        "description": repo.description,
                        "primary_language": repo.primary_language,
                        "stars": repo.stars,
                        "forks": repo.forks,
                        "default_branch": repo.default_branch,
                    },
                }

            if detected == "arxiv":
                # arxiv.org/abs/<id> → Atom API export tek paper fetch
                import re as _re
                import xml.etree.ElementTree as _ET  # noqa: N814 — local alias

                import httpx as _httpx

                m = _re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", body.url)
                if not m:
                    return {
                        "url": body.url,
                        "detected_type": "arxiv",
                        "error": "arxiv ID çıkarılamadı (URL formatı?)",
                    }
                arxiv_id = m.group(1).removesuffix(".pdf")
                api_url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
                async with _httpx.AsyncClient(timeout=20.0) as c:
                    r = await c.get(api_url)
                    r.raise_for_status()
                ns = {"a": "http://www.w3.org/2005/Atom"}
                root = _ET.fromstring(r.text)
                entry = root.find("a:entry", ns)
                if entry is None:
                    return {
                        "url": body.url,
                        "detected_type": "arxiv",
                        "error": f"arxiv ID {arxiv_id} bulunamadı",
                    }
                title_el = entry.find("a:title", ns)
                summary_el = entry.find("a:summary", ns)
                authors = [
                    (a_name.text or "").strip()
                    for a in entry.findall("a:author", ns)
                    if (a_name := a.find("a:name", ns)) is not None
                ]
                return {
                    "url": body.url,
                    "detected_type": "arxiv",
                    "metadata": {
                        "arxiv_id": arxiv_id,
                        "title": (title_el.text or "").strip() if title_el is not None else "",
                        "authors": authors,
                        "abstract": (summary_el.text or "").strip()[:1500]
                        if summary_el is not None
                        else "",
                    },
                }
        except Exception as e:
            log.warning("analyze.fetch_failed", url=body.url, err=str(e)[:200])
            raise HTTPException(
                status_code=502,
                detail={"error": "fetch_failed", "detail": str(e)[:300]},
            ) from e

        return {"url": body.url, "detected_type": detected, "error": "unhandled"}

    # ── Phase 14: deep-dive analyze ───────────────────────────────────

    @app.post("/api/analyze/deep", status_code=202)
    async def analyze_deep(body: AnalyzeBody, background: BackgroundTasks) -> dict[str, Any]:
        """Heavy fetch (yt-dlp transcript / repomix / arxiv) + claude synth.

        202 Accepted: tetiklendi, polling /api/analyze/deep/{job_id}.
        200 + cache-hit response: aynı URL daha önce analiz edilmiş.
        409 in_progress: lockfile aktif.
        422 unsupported: URL türü tanınmadı.
        """
        from rasathane_mcp.core import deep_analyze as core_deep

        detected = core_deep.detect_url_type(body.url)
        if detected == "unknown":
            raise HTTPException(
                status_code=422,
                detail={"error": "unsupported_url_type"},
            )

        job_id = core_deep.compute_job_id(body.url, detected)
        status = core_deep.lookup_status(archive_root=ARCHIVE_ROOT, job_id=job_id)

        if status["status"] == "running":
            raise HTTPException(
                status_code=409,
                detail={"error": "in_progress", "job_id": job_id, **status},
            )
        if status["status"] == "done" and not body.force:
            return {"job_id": job_id, "status": "already_exists", **status}

        # Tetikle: background task'e at, hemen 202 dön
        background.add_task(
            core_deep.run_deep_analyze,
            body.url,
            archive_root=ARCHIVE_ROOT,
            force=body.force,
            use_whisper=body.use_whisper,
        )
        return {
            "job_id": job_id,
            "status": "queued",
            "detected_type": detected,
            "use_whisper": body.use_whisper,
        }

    @app.post("/api/analyze/deep/{job_id}/audio", status_code=202)
    async def analyze_deep_audio(
        job_id: str,
        background: BackgroundTasks,
        force: bool = False,
        preset_id: str = "klasik_panel",
    ) -> dict[str, Any]:
        """Phase 21-i: mevcut deep-dive job'una sesli özet ekle.

        Phase 36-ii: `preset_id` query param (default `klasik_panel`).
        Bilinmeyen ID `klasik_panel`'a fallback (warning log).
        `force=True` ise mevcut audio.mp3'ü silip yeniden üretir
        (preset değişikliği için kritik — cache hit'i bypass eder).

        Önkoşul: summary.md (veya legacy result.md) var. Idempotent —
        force=False + audio.mp3 zaten varsa cache döner. Background
        task'le tetiklenir; polling /api/analyze/deep/{job_id} ile
        audio_url izlenir; preset metadata için /archive/deep/{job_id}/
        audio_meta.json izlenir.
        """
        if len(job_id) != 16 or not all(c in "0123456789abcdef" for c in job_id):
            raise HTTPException(status_code=404, detail="invalid job_id format")
        from rasathane_mcp.core import deep_analyze as core_deep

        # Pre-flight: summary var mı?
        target_dir = ARCHIVE_ROOT / "deep" / job_id
        summary_ok = (target_dir / "summary.md").is_file() or (target_dir / "result.md").is_file()
        if not summary_ok:
            raise HTTPException(
                status_code=404,
                detail={"error": "summary_missing", "job_id": job_id},
            )

        # Cache hit (sadece force=False ise)
        audio_path = target_dir / "audio.mp3"
        if audio_path.is_file() and not force:
            return {
                "job_id": job_id,
                "status": "already_exists",
                "audio_url": f"/archive/deep/{job_id}/audio.mp3",
                "bytes": audio_path.stat().st_size,
            }

        # Phase 36-ii: DEEP_DIR'i ARCHIVE_ROOT'a uyumla + audio_only doğrudan
        # çağrılır (preset_id desteği). run_audio_only_for_existing_job shim
        # geriye dönük kompat için korunur — sonraki phase'de cleanup.
        async def _bg() -> None:
            saved_deep_dir = core_deep.DEEP_DIR
            try:
                core_deep.DEEP_DIR = ARCHIVE_ROOT / "deep"
                await core_deep.audio_only(
                    job_id, force=force, preset_id=preset_id
                )
            finally:
                core_deep.DEEP_DIR = saved_deep_dir

        background.add_task(_bg)
        return {
            "job_id": job_id,
            "status": "queued",
            "preset_id": preset_id,
        }

    @app.post("/api/analyze/deep/{job_id}/mindmap", status_code=202)
    async def analyze_deep_mindmap(job_id: str, background: BackgroundTasks) -> dict[str, Any]:
        """Phase 28-ii: mevcut deep-dive job'una zihin haritası ekle.

        Audio endpoint'iyle simetrik. Önkoşul: summary.md (veya legacy
        result.md) var. Idempotent — mindmap.html zaten varsa cache döner.
        Background task'le tetiklenir; polling /api/analyze/deep/{job_id}
        ile artifacts.mindmap izlenir.
        """
        if len(job_id) != 16 or not all(c in "0123456789abcdef" for c in job_id):
            raise HTTPException(status_code=404, detail="invalid job_id format")
        from rasathane_mcp.core import deep_analyze as core_deep

        target_dir = ARCHIVE_ROOT / "deep" / job_id
        summary_ok = (target_dir / "summary.md").is_file() or (target_dir / "result.md").is_file()
        if not summary_ok:
            raise HTTPException(
                status_code=404,
                detail={"error": "summary_missing", "job_id": job_id},
            )

        mindmap_path = target_dir / "mindmap.html"
        if mindmap_path.is_file():
            return {
                "job_id": job_id,
                "status": "already_exists",
                "mindmap_url": f"/archive/deep/{job_id}/mindmap.html",
                "bytes": mindmap_path.stat().st_size,
            }

        background.add_task(
            core_deep.run_mindmap_only_for_existing_job,
            archive_root=ARCHIVE_ROOT,
            job_id=job_id,
        )
        return {"job_id": job_id, "status": "queued"}

    # ── Phase 23: geçmiş analizler listesi + silme ────────────────────

    @app.get("/api/analyze/deep")
    async def analyze_deep_list() -> dict[str, Any]:
        """archive/deep/ altındaki tüm job'ları listele.

        Liste mtime DESC sıralı; in_library rozeti DB'den compose edilir.
        UI bu payload'u "Önceki Analizler" kart bölümünde render eder.
        """
        from rasathane_mcp.core import deep_analyze as core_deep

        jobs = core_deep.list_all_jobs(archive_root=ARCHIVE_ROOT)
        if not jobs:
            return {"jobs": []}

        job_ids = [j["job_id"] for j in jobs]
        library_map = await core_library.lookup_deep_analysis_library_items(job_ids)
        for job in jobs:
            lib = library_map.get(job["job_id"])
            job["in_library"] = lib is not None
            job["library_item_id"] = lib["library_item_id"] if lib else None
        return {"jobs": jobs}

    @app.delete("/api/analyze/deep/{job_id}")
    async def analyze_deep_delete(job_id: str) -> dict[str, Any]:
        """Bir deep-dive job dizinini kalıcı sil.

        404: job_id formatı geçersiz veya dizin yok.
        409: job çalışıyor (lockfile taze) — UI butonu da disabled.
        200: silindi.
        """
        if len(job_id) != 16 or not all(c in "0123456789abcdef" for c in job_id):
            raise HTTPException(status_code=404, detail="invalid job_id format")
        from rasathane_mcp.core import deep_analyze as core_deep

        result = core_deep.delete_job(archive_root=ARCHIVE_ROOT, job_id=job_id)
        if result == "not_found":
            raise HTTPException(
                status_code=404,
                detail={"error": "job_not_found", "job_id": job_id},
            )
        if result == "running":
            raise HTTPException(
                status_code=409,
                detail={"error": "job_running", "job_id": job_id},
            )
        return {"job_id": job_id, "status": "deleted"}

    @app.get("/api/analyze/deep/{job_id}")
    async def analyze_deep_status(job_id: str) -> dict[str, Any]:
        """Polling endpoint — job_id durumunu döner.

        404: job_id formatı geçersiz (16 hex değil).
        200: status payload (not_found / running / done / failed).
        """
        if len(job_id) != 16 or not all(c in "0123456789abcdef" for c in job_id):
            raise HTTPException(status_code=404, detail="invalid job_id format")
        from rasathane_mcp.core import deep_analyze as core_deep

        return core_deep.lookup_status(archive_root=ARCHIVE_ROOT, job_id=job_id)

    # ── Phase 36-iii: Ek Analiz (addendum) — 5 endpoint ───────────────

    @app.get("/api/analyze/deep/{job_id}/addendum")
    async def get_addendum_index(job_id: str) -> dict[str, Any]:
        """Bir deep job'ın addendum_index.json içeriği (yoksa boş list)."""
        from rasathane_mcp.core import addendum as _addendum

        return {"entries": _addendum.load_index(job_id)}

    @app.post("/api/analyze/deep/{job_id}/addendum/angles")
    async def post_addendum_angles(job_id: str) -> dict[str, Any]:
        """Claude'dan 4-5 otomatik açı önerisi (sonuç dosya cache'lenir)."""
        from rasathane_mcp.core import addendum as _addendum

        try:
            angles = await _addendum.suggest_angles(job_id)
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
        return {"angles": angles}

    @app.post("/api/analyze/deep/{job_id}/addendum")
    async def post_addendum(job_id: str, body: AddendumIn) -> dict[str, Any]:
        """type'a göre angle/freeform/compare addendum üret."""
        from rasathane_mcp.core import addendum as _addendum

        try:
            if body.type == "angle":
                if not (body.slug and body.title):
                    raise HTTPException(
                        status_code=422, detail="angle requires slug+title"
                    )
                entry = await _addendum.generate_angle_addendum(
                    job_id, body.slug, body.title
                )
            elif body.type == "freeform":
                if not body.question:
                    raise HTTPException(
                        status_code=422, detail="freeform requires question"
                    )
                entry = await _addendum.generate_freeform_addendum(
                    job_id, body.question, body.tags
                )
            else:  # compare
                entry = await _addendum.generate_compare_addendum(
                    job_id, body.source_ids
                )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
        return {"ok": True, "entry": entry}

    @app.delete("/api/analyze/deep/{job_id}/addendum/{slug}")
    async def delete_addendum_endpoint(job_id: str, slug: str) -> dict[str, Any]:
        """Addendum .md + index entry + ilişkili audio'yu sil."""
        from rasathane_mcp.core import addendum as _addendum

        deleted = _addendum.delete_addendum(job_id, slug)
        return {"ok": deleted}

    @app.post("/api/analyze/deep/{job_id}/addendum/{slug}/audio")
    async def post_addendum_audio(job_id: str, slug: str) -> dict[str, Any]:
        """Addendum .md → tek-sesli MP3 (ElevenLabs, Filiz default)."""
        from rasathane_mcp.core import addendum as _addendum

        try:
            return await _addendum.synthesize_addendum_audio(job_id, slug)
        except RuntimeError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    # ── Phase 36-iii: ilgili kaynak (pgvector related search) ──────────

    @app.get("/api/articles/related")
    async def get_related_articles(
        job_id: str, limit: int = 5
    ) -> dict[str, Any]:
        """Bir deep job'un summary embedding'ine en yakın N makale."""
        from rasathane_mcp.core import articles as _articles

        try:
            sources = await _articles.find_related_to_deep_job(
                job_id, limit=limit
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
        return {"sources": sources}

    # ── Phase 12-iii: kütüphane + uzun özet ───────────────────────────

    @app.get("/api/library")
    async def library_list(
        type: str | None = None,  # noqa: A002 (FastAPI query param shadowing built-in)
        q: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        if limit < 1:
            limit = 1
        if limit > 200:
            limit = 200
        return await core_library.list_items(
            item_type=type if type in ("article", "brief") else None,
            q=q,
            offset=offset,
            limit=limit,
        )

    @app.post("/api/library", status_code=201)
    async def library_save(body: LibrarySaveBody) -> dict[str, Any]:
        if body.item_type == "article":
            if body.article_id is None:
                raise HTTPException(
                    status_code=422, detail="article_id required for item_type=article"
                )
            result = await core_library.save_article(article_id=body.article_id, note=body.note)
        elif body.item_type == "brief":
            if not body.brief_date:
                raise HTTPException(
                    status_code=422, detail="brief_date required for item_type=brief"
                )
            from datetime import date as _d

            try:
                bdate = _d.fromisoformat(body.brief_date)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=f"invalid brief_date: {e}") from e
            result = await core_library.save_brief(
                brief_date=bdate, note=body.note, archive_root=ARCHIVE_ROOT
            )
        elif body.item_type == "deep_analysis":
            if not body.deep_analysis_job_id:
                raise HTTPException(
                    status_code=422,
                    detail="deep_analysis_job_id required for item_type=deep_analysis",
                )
            result = await core_library.save_deep_analysis(
                job_id=body.deep_analysis_job_id,
                note=body.note,
                archive_root=ARCHIVE_ROOT,
            )
        else:
            raise HTTPException(
                status_code=422,
                detail="item_type must be 'article', 'brief', or 'deep_analysis'",
            )

        if result.get("error") in ("not_found", "brief_not_found", "deep_not_found"):
            raise HTTPException(status_code=404, detail=result["error"])
        if result.get("error") == "already_saved":
            raise HTTPException(status_code=409, detail=result)
        return result

    # ── Phase 19-v: kütüphane → plan + to-do list ────────────────────

    @app.post("/api/plans", status_code=202)
    async def plan_generate(body: dict[str, Any], background: BackgroundTasks) -> dict[str, Any]:
        """Kütüphane içeriğinden geliştirme planı + yapılacaklar listesi üret.

        Body:
          - item_types: ["article", "brief", "deep_analysis"] (opt)
          - q: search filter (opt)
          - plan_title: başlık (default: "Geliştirme Planı")

        Eş zamanlı (synchronous) çalışır: plan üretimi 60-90 sn.
        Hızlı: lockfile var → 409 in_progress; cache var → 200 already_exists.
        """
        from rasathane_mcp.core import plans as core_plans

        item_types = body.get("item_types") or None
        q = body.get("q") or None
        plan_title = body.get("plan_title") or "Geliştirme Planı"

        # Background task'a at, hemen 202 dön
        background.add_task(
            core_plans.generate_plan,
            archive_root=ARCHIVE_ROOT,
            item_types=item_types,
            q=q,
            plan_title=plan_title,
        )
        # Pre-compute plan_id ki UI polling yapabilsin (item set'e göre)
        # Burada item set'i bilmediğimiz için canonical id veremeyiz; bunun
        # yerine status endpoint'i "list all plans" şeklinde de erişilebilir.
        return {"status": "queued"}

    @app.get("/api/plans")
    async def plans_list() -> dict[str, Any]:
        """Mevcut tüm plan dizinlerini listele (en yeniden eskiye)."""
        plans_root = ARCHIVE_ROOT / "plans"
        if not plans_root.is_dir():
            return {"plans": []}

        rows = []
        for d in sorted(plans_root.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            plan_md = d / "plan.md"
            meta_path = d / "meta.json"
            if not plan_md.is_file():
                continue
            meta = {}
            if meta_path.is_file():
                try:
                    import json as _json

                    meta = _json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            from datetime import UTC
            from datetime import datetime as _dt

            rows.append(
                {
                    "plan_id": d.name,
                    "title": meta.get("title", "Plan"),
                    "items_used": meta.get("items_used"),
                    "generated_at": _dt.fromtimestamp(plan_md.stat().st_mtime, UTC).isoformat(),
                }
            )
        return {"plans": rows}

    @app.get("/api/plans/{plan_id}")
    async def plan_get(plan_id: str) -> dict[str, Any]:
        """Tek plan'ın tam içeriği + meta + status."""
        if len(plan_id) != 16 or not all(c in "0123456789abcdef" for c in plan_id):
            raise HTTPException(status_code=404, detail="invalid plan_id format")
        from rasathane_mcp.core import plans as core_plans

        return core_plans.lookup_status(archive_root=ARCHIVE_ROOT, plan_id=plan_id)

    @app.patch("/api/plans/{plan_id}/todo")
    async def plan_toggle_todo(plan_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Bir to-do checkbox'ını toggle et.

        Body: {"line_index": N}.
        """
        if len(plan_id) != 16 or not all(c in "0123456789abcdef" for c in plan_id):
            raise HTTPException(status_code=404, detail="invalid plan_id format")
        line_index = body.get("line_index")
        if not isinstance(line_index, int):
            raise HTTPException(status_code=422, detail="line_index (int) required")
        from rasathane_mcp.core import plans as core_plans

        result = core_plans.toggle_todo(
            archive_root=ARCHIVE_ROOT, plan_id=plan_id, line_index=line_index
        )
        if result.get("error") == "not_found":
            raise HTTPException(status_code=404, detail="plan not found")
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result)
        return result

    @app.get("/api/library/{item_id}")
    async def library_get(item_id: uuid.UUID) -> dict[str, Any]:
        """Phase 19-iii: tek item için tam snapshot_md + meta dön.

        list_items endpoint'i snapshot_preview (240 char) döner; bu endpoint
        kart tıklandığında full content gösterimi için kullanılır.
        """
        from store.repository import get_library_item

        async with session_factory() as session:
            item = await get_library_item(session, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="not_found")
        return {
            "id": str(item.id),
            "item_type": item.item_type,
            "saved_at": item.saved_at.isoformat() if item.saved_at else None,
            "note": item.note,
            "snapshot_md": item.snapshot_md or "",
            "snapshot_meta": item.snapshot_meta or {},
            "is_dead_link": item.item_type == "article" and item.article_id is None,
        }

    @app.delete("/api/library/{item_id}")
    async def library_delete(item_id: uuid.UUID) -> dict[str, Any]:
        ok = await core_library.delete_item(item_id)
        if not ok:
            raise HTTPException(status_code=404, detail="not_found")
        # Phase 28-iv: ilgili audio dosyasını da temizle (varsa)
        audio_path = ARCHIVE_ROOT / "library" / f"{item_id}.mp3"
        script_path = ARCHIVE_ROOT / "library" / f"{item_id}.script.txt"
        audio_path.unlink(missing_ok=True)
        script_path.unlink(missing_ok=True)
        return {"deleted": True}

    @app.get("/api/library/{item_id}/audio")
    async def library_audio_status(item_id: uuid.UUID) -> dict[str, Any]:
        """Phase 28-iv: kütüphane item için sesli özet durumunu döner.

        UI polling endpoint'i. Üretilmemişse status="not_generated" döner;
        UI buton gösterir. Üretiliyorsa "in_progress", varsa "done".
        """
        audio_path = ARCHIVE_ROOT / "library" / f"{item_id}.mp3"
        lock_path = ARCHIVE_ROOT / "library" / f".{item_id}.lock"
        if audio_path.is_file():
            return {
                "status": "done",
                "audio_url": f"/archive/library/{item_id}.mp3",
                "bytes": audio_path.stat().st_size,
            }
        if lock_path.is_file():
            return {"status": "in_progress"}
        return {"status": "not_generated"}

    @app.post("/api/library/{item_id}/audio", status_code=202)
    async def library_audio_generate(
        item_id: uuid.UUID, background: BackgroundTasks
    ) -> dict[str, Any]:
        """Phase 28-iv: kütüphane item için sesli özet üret.

        Generic — article/brief/deep_analysis/plan tüm türler için tek
        pattern. Idempotent — mp3 varsa "already_exists" döner. Background
        task'le başlatılır; UI 3 sn polling ile bitiş'i bekler.
        """
        # Pre-flight: item var mı?
        async with session_factory() as session:
            from store.repository import get_library_item

            item = await get_library_item(session, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "not_found"})

        audio_path = ARCHIVE_ROOT / "library" / f"{item_id}.mp3"
        if audio_path.is_file():
            return {
                "item_id": str(item_id),
                "status": "already_exists",
                "audio_url": f"/archive/library/{item_id}.mp3",
                "bytes": audio_path.stat().st_size,
            }

        background.add_task(
            core_library.generate_library_audio,
            item_id=item_id,
            archive_root=ARCHIVE_ROOT,
        )
        return {"item_id": str(item_id), "status": "queued"}

    @app.patch("/api/library/{item_id}")
    async def library_patch(item_id: uuid.UUID, body: LibraryNoteBody) -> dict[str, Any]:
        result = await core_library.update_note(item_id, body.note)
        if result is None:
            raise HTTPException(status_code=404, detail="not_found")
        return result

    @app.post("/api/articles/{article_id}/summary/short")
    async def article_short_summary(article_id: uuid.UUID) -> dict[str, Any]:
        """Phase 19-i: tek makale için on-demand kısa Türkçe özet.

        Akış'ta kullanıcı bir makaleye tıklayınca, summary_tr_short
        NULL ise UI bu endpoint'i çağırır → claude/gemini ile özet üretir.
        Idempotent: zaten varsa cache döner.
        """
        from datetime import UTC
        from datetime import datetime as _dt

        from sqlalchemy.orm import selectinload as _sel
        from store.models import Article

        async with session_factory() as session:
            art = (
                await session.execute(
                    select(Article).options(_sel(Article.source)).where(Article.id == article_id)
                )
            ).scalar_one_or_none()
            if art is None:
                raise HTTPException(status_code=404, detail="article_not_found")

            if art.summary_tr_short:
                return {
                    "article_id": str(article_id),
                    "summary_tr_short": art.summary_tr_short,
                    "cached": True,
                }

            from llm.prompts import load_prompt, render
            from llm.translate import _generate_short_with_fallback

            template = load_prompt("short_summary")
            prompt = render(
                template,
                title=art.title,
                summary=(art.summary or "(orijinal özet yok)"),
                url=art.url,
            )
            try:
                text = await _generate_short_with_fallback(prompt, art.title)
            except FileNotFoundError as e:
                raise HTTPException(
                    status_code=503,
                    detail={"error": "cli_not_found", "detail": str(e)},
                ) from e
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail={"error": "generation_failed", "detail": str(e)[:300]},
                ) from e

            art.summary_tr_short = text
            await session.commit()
            return {
                "article_id": str(article_id),
                "summary_tr_short": text,
                "cached": False,
                "generated_at": _dt.now(UTC).isoformat(),
            }

    @app.post("/api/articles/{article_id}/summary/long")
    async def article_long_summary(article_id: uuid.UUID) -> dict[str, Any]:
        """Uzun Türkçe analiz üret (idempotent: cached varsa döner).

        Routing: claude primary + gemini fallback (translate.py ile aynı
        env override RASATHANE_TRANSLATE_CLI). FSEK iktibas sınırı (~200
        kelime) prompt seviyesinde uygulanır.
        """
        from datetime import UTC
        from datetime import datetime as _dt

        from sqlalchemy.orm import selectinload as _sel
        from store.models import Article

        async with session_factory() as session:
            art = (
                await session.execute(
                    select(Article).options(_sel(Article.source)).where(Article.id == article_id)
                )
            ).scalar_one_or_none()
            if art is None:
                raise HTTPException(status_code=404, detail="article_not_found")

            # Cache hit
            if art.summary_tr_long:
                return {
                    "article_id": str(article_id),
                    "summary_tr_long": art.summary_tr_long,
                    "cached": True,
                }

            # Generate via shared CLI router
            from llm.prompts import load_prompt, render
            from llm.translate import _generate_short_with_fallback

            template = load_prompt("long_summary")
            prompt = render(
                template,
                title=art.title,
                summary=(art.summary or "(orijinal özet yok)"),
                url=art.url,
            )
            try:
                text = await _generate_short_with_fallback(prompt, art.title)
            except FileNotFoundError as e:
                raise HTTPException(
                    status_code=503,
                    detail={"error": "cli_not_found", "detail": str(e)},
                ) from e
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail={"error": "generation_failed", "detail": str(e)[:300]},
                ) from e

            art.summary_tr_long = text
            await session.commit()
            return {
                "article_id": str(article_id),
                "summary_tr_long": text,
                "cached": False,
                "generated_at": _dt.now(UTC).isoformat(),
            }

    # ── Phase 32-i: Kaynak Yönetim Ajanı + Sosyal Radar ───────────────

    @app.get("/api/social-watch")
    async def social_watch_list_endpoint(
        risk_level: str | None = None,
        region: str | None = None,
        enabled_only: bool = False,
    ) -> dict[str, Any]:
        """Sosyal izleme listesi (data/social_watch.yaml)."""
        from rasathane_mcp.core import source_agent

        rows = source_agent.list_social_watch_people_tool(
            risk_level=risk_level, region=region, enabled_only=enabled_only
        )
        return {"people": rows, "total": len(rows)}

    @app.get("/api/social-watch/feed")
    async def social_watch_feed_endpoint(
        limit: int = 50,
        tag: str | None = None,
        offset: int = 0,
        since_hours: int = 168,
    ) -> dict[str, Any]:
        """Tüm enabled handle'ların son post/release'lerini time-sorted feed.

        Phase 33-ii. Cache-first: per-handle cache dosyalarını okur
        (``archive/social_watch_cache/*.json``), fresh fetch YAPMAZ.
        ``pulse sync`` cron responsible.

        Query:
          - ``tag``: yalnız bu tag'i içeren post'ları döner (canonical
            tag namespace ile uyumlu, örn. ``acik_kaynak_ai``).
          - ``limit``: 1-200 arası clamped (default 50).
          - ``offset``: sayfalama (default 0).
          - ``since_hours``: yalnız son N saat içinde yayınlanmış post'lar.
            Phase 35-xv: default 168 (1 hafta) — HF model release cadence'i
            ve GitHub release sıklığı için Canlı Akış semantic'i. ``0`` →
            filter atlanır (tüm cache history).

        Phase 35-xv: Response'a ``stale_handles`` field eklendi —
        time window dışında kalan ama cache'te son post'u olan
        ``platform:handle`` çiftleri (her biri için son post + days_ago).
        UI "Sessiz Kaynaklar" section'ında render edilir; kullanıcı 1+
        hafta sessiz kaynakların hâlâ var olduğunu görür, kaynak "dead"
        algılanmaz.
        """
        import json as _json
        from datetime import UTC, datetime, timedelta

        capped = max(1, min(int(limit), 200))
        capped_offset = max(0, int(offset))
        now = datetime.now(UTC)
        # Phase 35-xii: time window cutoff (0/negatif → no filter)
        cutoff_iso: str | None = None
        if since_hours and since_hours > 0:
            cutoff_dt = now - timedelta(hours=int(since_hours))
            cutoff_iso = cutoff_dt.isoformat().replace("+00:00", "Z")

        cache_dir = ARCHIVE_ROOT / "social_watch_cache"
        if not cache_dir.is_dir():
            return {
                "posts": [],
                "count": 0,
                "total": 0,
                "next_offset": None,
                "stale_handles": [],
                "since_hours": int(since_hours) if since_hours > 0 else 0,
            }

        # Phase 35-xv: tüm post'ları handle bazında grupla (stale_handles için)
        # Phase 35-xix: Nitter/X eski cache schema normalize
        #   karpathy.json gibi eski format: `published_at` (yeni: `posted_at`),
        #   `author` (yeni: `handle`), `text` (yeni: `title`+`text`), platform yok.
        #   Defansif fallback: yeni schema field'ları yoksa eski'lere geç.
        def _normalize_post(p: dict[str, Any]) -> dict[str, Any]:
            """Eski Nitter cache schema → standart sosyal medya post şeması."""
            norm = dict(p)
            if not norm.get("posted_at"):
                norm["posted_at"] = p.get("published_at")
            if not norm.get("platform"):
                # Karpathy/Nitter cache → X post
                norm["platform"] = "x"
            if not norm.get("handle"):
                # Eski Nitter `author` field handle olarak kullanılır
                norm["handle"] = p.get("author") or "?"
            if not norm.get("title"):
                # Title yoksa text'in ilk satırı
                text = (p.get("text") or "").strip()
                norm["title"] = text.split("\n", 1)[0][:140] if text else ""
            if not norm.get("tags"):
                # Default X tag — UI filter'ı için
                norm["tags"] = ["dunya_ai"]
            return norm

        all_posts: list[dict[str, Any]] = []
        by_handle: dict[str, list[dict[str, Any]]] = {}
        for cache_file in cache_dir.glob("*.json"):
            try:
                data = _json.loads(cache_file.read_text(encoding="utf-8-sig"))
            except (_json.JSONDecodeError, OSError):
                continue
            posts = data.get("posts", []) or []
            for raw in posts:
                p = _normalize_post(raw)
                if tag and tag not in (p.get("tags") or []):
                    continue
                # Group by platform:handle (stale_handles için lazım)
                handle_key = f"{p.get('platform', '?')}:{p.get('handle', '?')}"
                by_handle.setdefault(handle_key, []).append(p)
                # Time window filter (recent set'i)
                if cutoff_iso is not None:
                    posted_at = p.get("posted_at") or ""
                    if posted_at < cutoff_iso:
                        continue
                all_posts.append(p)

        all_posts.sort(key=lambda p: p.get("posted_at") or "", reverse=True)
        total = len(all_posts)
        sliced = all_posts[capped_offset : capped_offset + capped]
        next_offset = capped_offset + len(sliced) if (capped_offset + len(sliced)) < total else None

        # Phase 35-xv: stale_handles — recent dışı kalan handle'ların son post'u
        stale_handles: list[dict[str, Any]] = []
        if cutoff_iso is not None:
            recent_handle_keys = {
                f"{p.get('platform', '?')}:{p.get('handle', '?')}" for p in all_posts
            }
            for key, posts in by_handle.items():
                if key in recent_handle_keys:
                    continue  # bu handle'ın recent post'u var, stale değil
                # En yeni post (posted_at varsa)
                dated = [p for p in posts if p.get("posted_at")]
                if not dated:
                    continue  # hiç tarih bilgisi yok — atla (Nitter/X bug)
                newest = max(dated, key=lambda x: x.get("posted_at") or "")
                try:
                    posted_dt = datetime.fromisoformat(
                        newest["posted_at"].replace("Z", "+00:00")
                    )
                    days_ago = (now - posted_dt).days
                except (ValueError, TypeError):
                    continue
                stale_handles.append(
                    {
                        "handle": newest.get("handle"),
                        "platform": newest.get("platform"),
                        "last_post": newest,
                        "days_ago": max(0, days_ago),
                    }
                )
            # En az eski (en yakın aktivite) en üstte
            stale_handles.sort(key=lambda x: x["days_ago"])

        return {
            "posts": sliced,
            "count": len(sliced),
            "total": total,
            "next_offset": next_offset,
            "since_hours": int(since_hours) if since_hours and since_hours > 0 else 0,
            "stale_handles": stale_handles,
        }

    @app.get("/api/social-watch/{person_id}/posts")
    async def social_watch_posts_endpoint(
        person_id: str,
        limit: int = 10,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Phase 32-i.3: Bir sosyal izleme kişisinin son N paylaşımı.

        ``limit`` 1-30 arası clamped. Default cache-first (30dk TTL);
        ``force_refresh=true`` Nitter'a doğrudan gider, cache'i yazar.

        Status:
          - 200 + ``source: "cache"``       — fresh cache (TTL içinde)
          - 200 + ``source: "nitter"``      — canlı fetch başarılı
          - 200 + ``source: "stale_cache"`` — Nitter down, eski cache (≤24h)
          - 200 + ``source: "unavailable"`` — hiçbir veri yok (warning string)
          - 422 person_id format hatalı
          - 404 kişi yaml'da bulunamadı
        """
        # person_id pattern: lowercase + underscore + digit (yaml validator ile aynı)
        if (
            not person_id
            or not all(c.isalnum() or c == "_" for c in person_id)
            or len(person_id) > 64
        ):
            raise HTTPException(status_code=422, detail="invalid person_id format")
        capped = max(1, min(int(limit), 30))

        from rasathane_mcp.core import social_posts

        result = await social_posts.get_recent_posts(
            person_id=person_id,
            archive_root=ARCHIVE_ROOT,
            limit=capped,
            force_refresh=bool(force_refresh),
        )
        if (
            result["source"] == "unavailable"
            and "not found" in (result.get("warning") or "").lower()
        ):
            raise HTTPException(status_code=404, detail=result)
        return result

    @app.post("/api/social-watch/evaluate")
    async def social_watch_evaluate_endpoint(body: dict[str, Any]) -> dict[str, Any]:
        """Yeni bir sosyal medya adayını değerlendir (heuristic, LLM yok).

        Body:
          - display_name, handle (required)
          - affiliation, verification_links, role_hint, sample_posts (optional)
        """
        from rasathane_mcp.core import source_agent

        if not body.get("display_name") or not body.get("handle"):
            raise HTTPException(
                status_code=422,
                detail="display_name ve handle zorunlu",
            )
        return source_agent.evaluate_social_watch_candidate_tool(
            display_name=str(body["display_name"]),
            handle=str(body["handle"]),
            affiliation=body.get("affiliation"),
            verification_links=body.get("verification_links") or [],
            role_hint=body.get("role_hint"),
            sample_posts=body.get("sample_posts") or [],
        )

    @app.post("/api/agent/chat")
    async def agent_chat_endpoint(body: dict[str, Any]) -> dict[str, Any]:
        """Chatbox endpoint — kullanıcı mesajını alır, yapılandırılmış yanıt döner.

        Body: ``{"text": "kaynakları listele"}``.

        Cevap: AgentResponse JSON (intent + message + data + proposals).
        Yıkıcı niyetler proposals listesi olarak döner; execute için
        ``/api/agent/execute`` çağrılır.
        """
        from rasathane_mcp.core import source_agent

        text = (body or {}).get("text", "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="'text' boş olamaz")
        if len(text) > 4000:
            raise HTTPException(status_code=413, detail="'text' max 4000 karakter")
        resp = await source_agent.handle_chat_message(text, archive_root=ARCHIVE_ROOT)
        return resp.model_dump(mode="json")

    @app.post("/api/agent/execute")
    async def agent_execute_endpoint(body: dict[str, Any]) -> dict[str, Any]:
        """Onaylanmış bir AgentProposal'ı uygula.

        Body: bir AgentProposal JSON (proposal_id + action + payload + ...).
        UI Onayla butonunda chat response'taki proposal'ı buraya yollar.
        """
        from rasathane_mcp.core import source_agent

        try:
            proposal = source_agent.AgentProposal.model_validate(body)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Geçersiz proposal: {e}") from e
        result = await source_agent.execute_proposal(
            proposal,
            archive_root=ARCHIVE_ROOT,
            actor="agent",
            request_id=body.get("request_id"),
        )
        if result.get("status") == "ok":
            return result
        if result.get("status") == "duplicate":
            raise HTTPException(status_code=409, detail=result)
        if result.get("status") == "not_found":
            raise HTTPException(status_code=404, detail=result)
        if result.get("status") == "forbidden_yaml_managed":
            raise HTTPException(status_code=403, detail=result)
        if result.get("status") == "invalid_id":
            raise HTTPException(status_code=422, detail=result)
        raise HTTPException(status_code=400, detail=result)

    @app.get("/api/agent/audit-log")
    async def agent_audit_log_endpoint(
        limit: int = 50,
        action_prefix: str | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Audit log — son N değişikliği döner (en yeni önce)."""
        from rasathane_mcp.core import audit_log as _audit

        capped = max(1, min(limit, 500))
        rows = _audit.read_recent(
            ARCHIVE_ROOT,
            limit=capped,
            action_filter=action_prefix,
            actor_filter=actor,
        )
        return {"entries": rows, "limit": capped}

    @app.post("/api/sources/{source_id}/health")
    async def source_health_endpoint(source_id: uuid.UUID) -> dict[str, Any]:
        """Tek kaynak için HTTP probe — network gerçekleşir, 502'ye düşmez."""
        from rasathane_mcp.core import source_agent

        return await source_agent.check_source_health_tool(source_id=source_id)

    @app.get("/api/sources/duplicates")
    async def source_duplicates_endpoint(
        category: str | None = None,
        fuzzy_threshold: float = 0.85,
    ) -> dict[str, Any]:
        """Duplicate olabilecek kaynak gruplarını döner (name/URL benzerliği)."""
        from rasathane_mcp.core import source_agent

        if not 0.0 < fuzzy_threshold <= 1.0:
            raise HTTPException(status_code=422, detail="fuzzy_threshold 0-1 arası olmalı")
        groups = await source_agent.find_duplicate_sources_tool(
            category=category, fuzzy_threshold=fuzzy_threshold
        )
        return {"groups": groups, "total": len(groups)}

    @app.get("/api/sources/{source_id}/score")
    async def source_score_endpoint(source_id: uuid.UUID) -> dict[str, Any]:
        """Statik kaynak skoru + bileşen breakdown."""
        from rasathane_mcp.core import source_agent

        result = await source_agent.explain_source_score_tool(source_id)
        if result is None:
            raise HTTPException(status_code=404, detail="source not found")
        return result

    # ── Static assets (Alpine vendored) ───────────────────────────────
    app.mount(
        "/static",
        StaticFiles(directory=str(_STATIC_DIR)),
        name="static",
    )

    # ── Phase 17-iv: archive/ erişimi (deep-dive artifact'leri) ───────
    # mp3 player + iframe mindmap için /archive/deep/{job_id}/{file}.
    # ARCHIVE_ROOT path traversal'a karşı StaticFiles tarafından sandbox'lı.
    if ARCHIVE_ROOT.exists():
        app.mount(
            "/archive",
            StaticFiles(directory=str(ARCHIVE_ROOT)),
            name="archive",
        )

    # ── HTML pages ────────────────────────────────────────────────────
    @app.get("/")
    async def index(request: Request) -> Any:
        return _TEMPLATES.TemplateResponse(request, "index.html")

    @app.get("/sources")
    async def sources_page(request: Request) -> Any:
        return _TEMPLATES.TemplateResponse(request, "sources.html")

    @app.get("/library")
    async def library_page(request: Request) -> Any:
        return _TEMPLATES.TemplateResponse(request, "library.html")

    @app.get("/plans")
    async def plans_page(request: Request) -> Any:
        return _TEMPLATES.TemplateResponse(request, "plans.html")

    @app.get("/analyze")
    async def analyze_page(request: Request) -> Any:
        return _TEMPLATES.TemplateResponse(request, "analyze.html")

    @app.get("/canli-akis")
    async def canli_akis_page(request: Request) -> Any:
        """Phase 34-ii: Canlı Akış standalone sayfası.

        Kaynak Akışı (article feed) + Sosyal Medya Akışı sub-tab'larıyla aynı
        ``liveStreamPage()`` Alpine bileşenini kullanır; index.html'den taşındı.
        """
        return _TEMPLATES.TemplateResponse(request, "canli-akis.html")

    @app.get("/social-watch")
    async def social_watch_redirect() -> Any:
        """Phase 34-ii: /social-watch içeriği /sources#sosyal sub-tab'a taşındı.

        Eski URL'leri kıran 301 redirect. Sosyal medya UI (filter + modal +
        Nitter post fetch) artık ``sources.html``'de nested Alpine scope.
        """
        return RedirectResponse(url="/sources#sosyal", status_code=301)

    @app.get("/voices")
    async def voices_page(request: Request) -> Any:
        """Phase 32-v: ElevenLabs voice picker UI.

        Her speaker rolü (Filiz/Mehmet/Burak — brief, Filiz/Burak/Esra — youtube)
        için dropdown + preview butonu. Override'lar
        ``data/voice_overrides.json``'a yazılır.
        """
        return _TEMPLATES.TemplateResponse(request, "voices.html")

    # ── Phase 33-ii: Canonical tag namespace ───────────────────────
    @app.get("/api/tags")
    async def get_tags() -> dict:
        """UI filter pill'leri için canonical tag listesi."""
        from store.tags import all_tags

        return {"tags": all_tags()}

    # ── Phase 32-v: Voice picker API ──────────────────────────────────

    @app.get("/api/tts/voices")
    async def tts_voices_endpoint() -> dict[str, Any]:
        """ElevenLabs hesabındaki kullanılabilir voice'ları döner.

        Cache: ``data/elevenlabs_voices_cache.json``, 1 saat TTL.
        ELEVENLABS_API_KEY yoksa 503 + açıklayıcı detail.

        Return:
            {"voices": [{"voice_id", "name", "category", "labels": {...}}, ...]}
        """
        import json as _json
        import time

        api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="ELEVENLABS_API_KEY env tanımlı değil — "
                "Claude Desktop config veya shell env'e ekleyin.",
            )

        # Cache check (1h TTL) — sync IO off-thread (ASYNC240).
        import asyncio as _asyncio

        cache_path = _ELEVENLABS_VOICES_CACHE_PATH

        def _read_cache_if_fresh() -> dict[str, Any] | None:
            if not cache_path.is_file():
                return None
            try:
                mtime = cache_path.stat().st_mtime
                if (time.time() - mtime) >= 3600:
                    return None
                cached = _json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and "voices" in cached:
                    return cached
            except (OSError, _json.JSONDecodeError):
                return None
            return None

        cached_data = await _asyncio.to_thread(_read_cache_if_fresh)
        if cached_data is not None:
            return cached_data

        # Cache miss / stale → ElevenLabs API
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                r = await client.get(
                    "https://api.elevenlabs.io/v1/voices",
                    headers={"xi-api-key": api_key},
                )
            except httpx.HTTPError as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"ElevenLabs API erişim hatası: {str(e)[:200]}",
                ) from e
            if r.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"ElevenLabs API {r.status_code}: {r.text[:200]}",
                )
            data = r.json()

        # Trim — UI'a sadece gerekli alanları gönder.
        # Phase 35-xi: Stüdyo whitelist filter — sadece pipeline-validated
        # voice'lar (TR-native + Matilda) UI'a gönderilir. `SELECTABLE_VOICE_IDS`
        # tts.py'de tanımlı; ileride genişletilirse otomatik yansır.
        from llm.tts import SELECTABLE_VOICE_IDS

        trimmed = {
            "voices": [
                {
                    "voice_id": v.get("voice_id"),
                    "name": v.get("name"),
                    "category": v.get("category"),
                    "labels": v.get("labels") or {},
                    "preview_url": v.get("preview_url"),
                }
                for v in data.get("voices", [])
                if v.get("voice_id") in SELECTABLE_VOICE_IDS
            ],
            "fetched_at": int(time.time()),
        }
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                _json.dumps(trimmed, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as e:
            log.warning("voices_cache.write_failed", err=str(e)[:200])
        return trimmed

    # ── Phase 36-ii: audio preset CRUD ──────────────────────────────────

    @app.get("/api/tts/presets")
    async def get_tts_presets() -> dict[str, Any]:
        """4 default preset + kullanıcı tanımlı preset listesi.

        Returns:
            {
                "defaults": [...],  # kod sabit 4 preset
                "custom": [...],    # data/audio_presets.json'dan
                "active": [...],    # defaults + custom (ID-unique merge)
            }
        """
        defaults = [_preset_to_dict(p) for p in DEFAULT_PRESETS]
        custom = [_preset_to_dict(p) for p in load_user_presets()]
        active = [_preset_to_dict(p) for p in get_active_presets()]
        return {"defaults": defaults, "custom": custom, "active": active}

    @app.post("/api/tts/presets")
    async def post_tts_preset(body: PresetIn) -> dict[str, Any]:
        """Yeni user preset oluştur veya mevcut user preset'i güncelle.

        Aynı ID varsa overwrite; default preset ID'leri 403.
        """
        default_ids = {p.id for p in DEFAULT_PRESETS}
        if body.id in default_ids:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"id '{body.id}' default preset; clone et ve "
                    "farklı ID kullan"
                ),
            )
        new_preset = AudioPreset(
            id=body.id,
            name=body.name,
            description=body.description,
            format=body.format,
            prompt_variant=body.prompt_variant,
            target_minutes=(body.target_minutes[0], body.target_minutes[1]),
            voices=dict(body.voices),
            voice_settings={k: dict(v) for k, v in body.voice_settings.items()},
            is_default=False,
        )
        existing = load_user_presets()
        existing = [p for p in existing if p.id != body.id]
        existing.append(new_preset)
        save_user_presets(existing)
        return {"ok": True, "id": body.id}

    @app.delete("/api/tts/presets/{preset_id}")
    async def delete_tts_preset(preset_id: str) -> dict[str, Any]:
        """User preset sil; default preset ID'leri 403."""
        default_ids = {p.id for p in DEFAULT_PRESETS}
        if preset_id in default_ids:
            raise HTTPException(
                status_code=403, detail="default preset silinemez"
            )
        existing = load_user_presets()
        new_list = [p for p in existing if p.id != preset_id]
        save_user_presets(new_list)
        return {"ok": True}

    @app.get("/api/tts/usage")
    async def tts_usage_endpoint() -> dict[str, Any]:
        """Phase 35-xi: ElevenLabs subscription bilgisi — provider/tier/usage.

        Stüdyo UI'da info card render edilir. ``next_reset_unix`` epoch
        seconds; UI tarafında local time'a çevrilir.

        Returns:
            ``{provider, tier, character_count, character_limit,
            character_remaining, percent_used, next_reset_unix}``

        TODO (Phase 36+): local TTS (Coqui XTTS-v2 / Piper / Bark) +
        alternatif provider'lar (OpenAI TTS, Microsoft Azure) eklendiğinde
        bu endpoint provider list'i döndürebilir; UI seçim sunabilir.
        """
        api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="ELEVENLABS_API_KEY env tanımlı değil",
            )
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                r = await client.get(
                    "https://api.elevenlabs.io/v1/user/subscription",
                    headers={"xi-api-key": api_key},
                )
            except httpx.HTTPError as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"ElevenLabs API erişim hatası: {str(e)[:200]}",
                ) from e
            if r.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"ElevenLabs API {r.status_code}: {r.text[:200]}",
                )
            data = r.json()
        char_used = int(data.get("character_count", 0))
        char_limit = int(data.get("character_limit", 0))
        char_remaining = max(0, char_limit - char_used)
        percent_used = (
            round(100.0 * char_used / char_limit, 1) if char_limit > 0 else 0.0
        )
        return {
            "provider": "ElevenLabs",
            "tier": data.get("tier", "unknown"),
            "character_count": char_used,
            "character_limit": char_limit,
            "character_remaining": char_remaining,
            "percent_used": percent_used,
            "next_reset_unix": int(data.get("next_character_count_reset_unix", 0)),
        }

    @app.post("/api/tts/preview")
    async def tts_preview_endpoint(body: dict[str, Any]) -> Any:
        """Tek bir ElevenLabs voice'tan kısa örnek synth → audio/mpeg byte.

        Body:
          - ``voice_id`` (zorunlu) — ElevenLabs voice ID.
          - ``text`` (opsiyonel) — preview metni. Default kullanıcının TR
            şikayet kelimelerini içeren standart cümle (yaklaşık 90 char).

        Quota tüketir (~50-90 char × selection sayısı). Free tier'da
        21 voice × 90 char = ~1900 char (%19 quota — bilinçli).
        """
        from fastapi.responses import Response as FastAPIResponse
        from llm.tts import _synthesize_elevenlabs_segment, transliterate_short_acronyms

        voice_id = (body.get("voice_id") or "").strip()
        if not voice_id:
            raise HTTPException(status_code=422, detail="voice_id zorunlu")
        if len(voice_id) > 64:
            raise HTTPException(status_code=422, detail="voice_id geçersiz format")

        api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="ELEVENLABS_API_KEY env tanımlı değil",
            )

        # Default preview: kullanıcının TR fonetik şikayetleri test eden cümle.
        text = (body.get("text") or "").strip()
        if not text:
            text = (
                "Yargıtay Dokuzuncu Hukuk Dairesi, davalı tarafın "
                "tedarik özen yükümlülüğünü genişletti."
            )
        # Phase 32-v.1: Preview de podcast üretiminde olduğu gibi transliterate
        # uygulanmalı. Kullanıcı "Anthropic" cümlesi gönderirse podcast'te
        # nasıl ("entropik") duyacağını görmek için aynı pipeline geçer.
        text = transliterate_short_acronyms(text)
        text = text[:280]  # quota koruma (transliterate sonrası cap)

        import asyncio as _asyncio
        import os as _os
        import tempfile

        # Windows file lock fix: mkstemp() açtığı fd'yi hemen kapat.
        # Aksi halde Windows'ta sonradan unlink "[WinError 32] başka bir
        # işlem tarafından kullanılıyor" hatası verir.
        fd, name = tempfile.mkstemp(suffix=".mp3", prefix="voice_preview_")
        _os.close(fd)
        tmp_path = Path(name)
        try:
            await _synthesize_elevenlabs_segment(
                text=text,
                output_path=tmp_path,
                voice_id=voice_id,
                api_key=api_key,
                stability=0.55,
                similarity_boost=0.75,
                style=0.2,
            )
            audio_bytes = await _asyncio.to_thread(tmp_path.read_bytes)
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e)[:300]) from e
        finally:
            await _asyncio.to_thread(tmp_path.unlink, missing_ok=True)

        return FastAPIResponse(content=audio_bytes, media_type="audio/mpeg")

    @app.get("/api/tts/voice-config")
    async def tts_voice_config_get() -> dict[str, Any]:
        """Mevcut voice override'larını + default mapping'leri döner.

        UI'da "default vs override" karşılaştırması için her ikisi gönderilir.
        """
        from llm.tts import (
            PODCAST_VOICES_ELEVENLABS_BRIEF,
            PODCAST_VOICES_ELEVENLABS_YOUTUBE,
            load_voice_overrides,
        )

        overrides = load_voice_overrides()
        return {
            "overrides": overrides,
            "defaults": {
                "elevenlabs": {
                    "brief": {
                        speaker: cfg["voice_id"]
                        for speaker, cfg in PODCAST_VOICES_ELEVENLABS_BRIEF.items()
                    },
                    "youtube": {
                        speaker: cfg["voice_id"]
                        for speaker, cfg in PODCAST_VOICES_ELEVENLABS_YOUTUBE.items()
                    },
                }
            },
        }

    @app.get("/api/tts/agent-profiles")
    async def tts_agent_profiles_get() -> dict[str, Any]:
        """Phase 32-v.4: Agent profilleri — merkezi havuz + mode mapping.

        Yeni schema:
            {
              "agents": {agent_id: {name, voice_id}},
              "modes":  {brief: [{agent_id, role}], youtube: [...]}
            }

        Return:
            {
              "defaults": {agents, modes},   # backend defaults
              "current":  {agents, modes},   # user override (yoksa defaults)
              "active":   {brief: [...], youtube: [...]}  # resolved mode listesi
            }
        """
        from llm.tts import (
            _agent_profile_defaults,
            get_active_agent_profiles,
            load_agent_profiles,
        )

        defaults = _agent_profile_defaults()
        current = load_agent_profiles() or defaults

        return {
            "defaults": defaults,
            "current": current,
            "active": {
                "brief": get_active_agent_profiles("brief"),
                "youtube": get_active_agent_profiles("youtube"),
            },
        }

    @app.post("/api/tts/agent-profiles")
    async def tts_agent_profiles_post(body: dict[str, Any]) -> dict[str, Any]:
        """Agent profilleri güncelle (replace semantik, yeni schema).

        Body::
            {
              "agents": {agent_id: {name, voice_id}, ...},
              "modes":  {brief: [{agent_id, role}], youtube: [...]}
            }

        Validation: agent_id slug (alphanumeric+dash, max 40), name 80 char,
        voice_id 64 char, role 80 char, mode whitelist brief/youtube,
        modes.X içindeki agent_id'ler agents havuzunda olmalı.
        """
        from llm.tts import save_agent_profiles

        agents = body.get("agents")
        modes = body.get("modes")

        if not isinstance(agents, dict):
            raise HTTPException(status_code=422, detail="agents dict olmalı")
        if not isinstance(modes, dict):
            raise HTTPException(status_code=422, detail="modes dict olmalı")

        # Agents pool validation
        cleaned_agents: dict[str, dict[str, str]] = {}
        for agent_id, agent in agents.items():
            if not isinstance(agent_id, str) or not agent_id.strip():
                raise HTTPException(status_code=422, detail=f"Boş agent_id: {agent_id!r}")
            if len(agent_id) > 40:
                raise HTTPException(status_code=422, detail=f"{agent_id} 40 char altı olmalı")
            if not isinstance(agent, dict):
                raise HTTPException(status_code=422, detail=f"{agent_id} value dict olmalı")
            name = agent.get("name", "")
            voice_id = agent.get("voice_id", "")
            if not isinstance(name, str) or len(name) > 80 or not name.strip():
                raise HTTPException(
                    status_code=422,
                    detail=f"{agent_id} name boş veya 80 char üzeri",
                )
            if not isinstance(voice_id, str) or len(voice_id) > 64:
                raise HTTPException(
                    status_code=422,
                    detail=f"{agent_id} voice_id 64 char altı olmalı",
                )
            cleaned_agents[agent_id.strip()] = {
                "name": name.strip(),
                "voice_id": voice_id.strip(),
            }

        # Modes validation
        cleaned_modes: dict[str, list[dict[str, str]]] = {}
        for mode_name in ("brief", "youtube"):
            slots = modes.get(mode_name)
            if slots is None:
                continue
            if not isinstance(slots, list):
                raise HTTPException(status_code=422, detail=f"{mode_name} list olmalı")
            cleaned_slots: list[dict[str, str]] = []
            for i, slot in enumerate(slots):
                if not isinstance(slot, dict):
                    raise HTTPException(
                        status_code=422,
                        detail=f"{mode_name}[{i}] dict olmalı",
                    )
                agent_id = slot.get("agent_id", "")
                role = slot.get("role", "")
                if not isinstance(agent_id, str) or agent_id not in cleaned_agents:
                    raise HTTPException(
                        status_code=422,
                        detail=f"{mode_name}[{i}] agent_id '{agent_id}' havuzda yok",
                    )
                if not isinstance(role, str) or len(role) > 80:
                    raise HTTPException(
                        status_code=422,
                        detail=f"{mode_name}[{i}] role 80 char altı string olmalı",
                    )
                cleaned_slots.append({"agent_id": agent_id, "role": role.strip()})
            cleaned_modes[mode_name] = cleaned_slots

        payload = {"agents": cleaned_agents, "modes": cleaned_modes}
        if not save_agent_profiles(payload):
            raise HTTPException(status_code=500, detail="Agent profiles yazma başarısız")
        return {"status": "ok", "saved": payload}

    @app.get("/api/youtube/unanalyzed")
    async def youtube_unanalyzed_endpoint(
        limit: int = 20,
        days: int = 14,
    ) -> dict[str, Any]:
        """Phase 32-v.3: Henüz deep-analyze edilmemiş YouTube videoları.

        DB'den son ``days`` gün YouTube article'ları + ``archive/deep/*/meta.json``
        URL set'i diff. Analyze sayfasında "Yeni Videolar" panelinde gösterilir.
        """
        from rasathane_mcp.core.deep_analyze import list_unanalyzed_youtube_videos

        capped = max(1, min(int(limit), 50))
        capped_days = max(1, min(int(days), 60))
        async with session_factory() as session:
            videos = await list_unanalyzed_youtube_videos(
                session,
                archive_root=ARCHIVE_ROOT,
                limit=capped,
                days=capped_days,
            )
        return {"videos": videos, "count": len(videos)}

    @app.post("/api/tts/voice-config")
    async def tts_voice_config_post(body: dict[str, Any]) -> dict[str, Any]:
        """Voice override'ları güncelle. Tüm config replace eder (UI tüm
        state'i gönderir; partial update sorumluluğu client'ta).

        Body schema:
            {
              "elevenlabs": {
                "brief":   {"Filiz": "<voice_id>", ...},
                "youtube": {"Filiz": "<voice_id>", ...}
              }
            }

        Validation: provider ``elevenlabs`` whitelist; role ``brief|youtube``;
        voice_id non-empty string. Bilinmeyen alan reject 422.
        """
        from llm.tts import save_voice_overrides

        allowed_providers = {"elevenlabs"}
        allowed_roles = {"brief", "youtube"}
        cleaned: dict[str, Any] = {}
        for provider, roles in body.items():
            if provider not in allowed_providers:
                raise HTTPException(
                    status_code=422,
                    detail=f"Bilinmeyen provider: {provider!r}",
                )
            if not isinstance(roles, dict):
                raise HTTPException(
                    status_code=422,
                    detail=f"{provider} altında dict bekleniyor",
                )
            cleaned[provider] = {}
            for role, speakers in roles.items():
                if role not in allowed_roles:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Bilinmeyen role: {role!r}",
                    )
                if not isinstance(speakers, dict):
                    raise HTTPException(
                        status_code=422,
                        detail=f"{provider}.{role} altında dict bekleniyor",
                    )
                cleaned[provider][role] = {}
                for speaker, voice_id in speakers.items():
                    if not isinstance(voice_id, str) or not voice_id.strip():
                        # Boş voice_id = override kaldırma sinyali; atla
                        continue
                    if len(voice_id) > 64:
                        raise HTTPException(
                            status_code=422,
                            detail=f"{speaker} voice_id çok uzun",
                        )
                    cleaned[provider][role][speaker] = voice_id.strip()

        if not save_voice_overrides(cleaned):
            raise HTTPException(status_code=500, detail="Override yazma başarısız")
        return {"status": "ok", "saved": cleaned}

    return app
