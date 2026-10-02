"""YouTube ingestion: metadata + transcript via yt-dlp / faster-whisper.

Two-tier transcript chain:
    1. yt-dlp auto-captions (TR/EN priority) — instant, free
    2. faster-whisper download-and-transcribe — slow (~30s/video minute on
       CPU) but reliable; medium model recommended for Türkçe.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import structlog
import yt_dlp

log = structlog.get_logger()

# Phase 27: tasarım kuralı — orijinal dil > İngilizce > Türkçe (fallback).
# Sabit liste olarak değil, video metadata'sına göre dinamik priority.
# `_resolve_caption_priority` ile her video için ayrı sıra üretilir.
_FALLBACK_LANG_PRIORITY = ["en", "en-US", "en-GB", "tr", "tr-TR"]


def _normalize_lang_code(code: str) -> str:
    """`tr-TR` → `tr`, `en-US` → `en` — bölge varyantlarını temel dile indirger.

    YouTube manuel altyazıyı bazen `tr-TR` olarak işaretliyor ama auto'yu
    `tr` olarak — priority match'te bunu tek noktaya getirir.
    """
    return code.split("-")[0].lower() if code else ""


def _resolve_caption_priority(
    *,
    language: str | None,
    manual_langs: list[str],
    auto_langs: list[str],
) -> list[str]:
    """Phase 27: video metadata'sına dayalı dinamik altyazı priority listesi.

    Sıralama kuralları:
      1. Manuel altyazı > otomatik altyazı (creator-yüklenmiş kalite ↑)
      2. Orijinal dil > İngilizce > Türkçe (orijinal'den translation kaybı önle)
      3. Bölge varyantı eşleşirse onu tut (örn. `tr-TR` priority `tr`'den önce)

    Returns: yt-dlp'nin ``subtitleslangs`` parametresine geçilecek dil
    kodu listesi. Boş liste → hiç altyazı yok (caller None döner).
    """
    out: list[str] = []
    seen: set[str] = set()

    def _push(lang: str | None, available: list[str]) -> None:
        """Dil + bölge varyantlarını priority'ye ekle (mevcutsa)."""
        if not lang:
            return
        norm = _normalize_lang_code(lang)
        # Önce exact match (örn. "tr-TR")
        for candidate in available:
            if candidate == lang and candidate not in seen:
                out.append(candidate)
                seen.add(candidate)
        # Sonra normalize match (örn. "tr")
        for candidate in available:
            if _normalize_lang_code(candidate) == norm and candidate not in seen:
                out.append(candidate)
                seen.add(candidate)

    # 1. Manuel altyazı: orijinal → en → tr
    targets = [language, "en", "tr"]
    for lang in targets:
        _push(lang, manual_langs)

    # 2. Auto-captions: orijinal → en → tr
    for lang in targets:
        _push(lang, auto_langs)

    # 3. Hiçbiri tutmadıysa fallback (eski hardcoded liste)
    if not out:
        for lang in _FALLBACK_LANG_PRIORITY:
            if (lang in manual_langs or lang in auto_langs) and lang not in seen:
                out.append(lang)
                seen.add(lang)

    return out


@dataclass(frozen=True)
class VideoMetadata:
    video_id: str
    title: str
    channel: str
    duration_seconds: int
    url: str


@dataclass(frozen=True)
class Transcript:
    text: str
    source: str  # "yt-dlp" | "whisper"


_VTT_TIMESTAMP_RE = re.compile(r"-->")
_VTT_TAG_RE = re.compile(r"<[^>]+>")
_VTT_CUE_ID_RE = re.compile(r"^[0-9a-zA-Z_-]+$")
_WHITESPACE_RE = re.compile(r"\s+")


def _extract_text_from_vtt(vtt_text: str) -> str:
    """Strip VTT/WEBVTT metadata + tags, return plain prose."""
    lines: list[str] = []
    for raw in vtt_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        if _VTT_TIMESTAMP_RE.search(line):
            continue
        if _VTT_CUE_ID_RE.match(line) and len(line) < 8:
            continue
        clean = _VTT_TAG_RE.sub("", line)
        if clean.strip():
            lines.append(clean.strip())
    return _WHITESPACE_RE.sub(" ", " ".join(lines)).strip()


async def fetch_metadata(url: str) -> VideoMetadata:
    """Get video info via yt-dlp Python API (no subprocess)."""

    def _extract() -> dict:
        opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    info = await asyncio.to_thread(_extract)
    return VideoMetadata(
        video_id=info["id"],
        title=info.get("title") or "(başlıksız)",
        channel=info.get("uploader") or info.get("channel") or "(bilinmeyen)",
        duration_seconds=int(info.get("duration") or 0),
        url=url,
    )


async def fetch_subs_via_ytdlp(url: str) -> Transcript | None:
    """Phase 27: video orijinal diline-duyarlı altyazı çekimi.

    İki adımlı stratejide:
      1. Metadata fetch (ucuz, no download): video dili + mevcut altyazı
         dilleri (manuel + auto) öğrenilir.
      2. ``_resolve_caption_priority`` ile bu video'ya özel priority
         hesaplanır (orig > en > tr; manuel > auto).
      3. Sadece priority listesindeki diller indirilir → bandwidth ↓ +
         429 riski ↓ (eskiden tüm "tr*, en*" varyantlarını isterdi).

    Hiç altyazı yoksa None döner (caller whisper'a düşmez — Phase 27:
    whisper opt-in only).
    """

    def _fetch() -> tuple[str | None, str | None]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Step 1: metadata + altyazı index (cheap)
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as y:
                info = y.extract_info(url, download=False)
            video_lang = info.get("language") or info.get("original_language")
            manual_langs = list((info.get("subtitles") or {}).keys())
            auto_langs = list((info.get("automatic_captions") or {}).keys())

            priority = _resolve_caption_priority(
                language=video_lang,
                manual_langs=manual_langs,
                auto_langs=auto_langs,
            )
            if not priority:
                log.info(
                    "youtube.subs.no_captions",
                    url=url,
                    video_lang=video_lang,
                    manual_count=len(manual_langs),
                    auto_count=len(auto_langs),
                )
                return None, None

            log.info(
                "youtube.subs.priority_resolved",
                url=url,
                video_lang=video_lang,
                priority=priority[:5],
            )

            # Step 2 (Phase 28-i): sequential per-language download.
            # yt-dlp `subtitleslangs=[a, b, c]` semantiği BATCH (hepsini
            # indirmeye çalışır); ilk dil 429 alırsa exception fırlar ve
            # diğer dillere geçilmiyor. Çözüm: tek tek dene, ilk başarılı
            # dur. Plus `sleep_interval_subtitles=2` ile rate-limit'i evade.
            for idx, lang in enumerate(priority):
                opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "skip_download": True,
                    "writesubtitles": True,
                    "writeautomaticsub": True,
                    "subtitleslangs": [lang],  # tek dil
                    "subtitlesformat": "vtt",
                    "outtmpl": str(tmp_path / "%(id)s.%(ext)s"),
                    "retries": 10,  # HTTP retry (429/network için)
                    "fragment_retries": 10,
                    "sleep_interval_subtitles": 2,  # altyazı istekleri arası bekle
                    "socket_timeout": 30,
                }
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                except Exception as e:
                    err_str = str(e)
                    log.warning(
                        "youtube.subs.lang_failed",
                        lang=lang,
                        attempt=idx + 1,
                        is_429="429" in err_str,
                        err=err_str[:200],
                    )
                    continue  # diğer dile geç

                # Bu denemenin dosyası var mı?
                for f in tmp_path.glob(f"*.{lang}.vtt"):
                    return f.read_text(encoding="utf-8"), lang

            log.warning(
                "youtube.subs.all_languages_failed",
                url=url,
                tried=priority[:5],
            )
            return None, None

    vtt_text, lang = await asyncio.to_thread(_fetch)
    if not vtt_text:
        return None
    text = _extract_text_from_vtt(vtt_text)
    if not text:
        return None
    log.info("youtube.subs.ytdlp_ok", lang=lang, chars=len(text))
    return Transcript(text=text, source=f"yt-dlp:{lang}")


async def fetch_audio_only(url: str) -> Path:
    """Phase 26: yt-dlp ile sadece sesi indir (transcribe etme).

    Subtitle API'sine hiç gitmez — sadece `format=bestaudio` indirir.
    Returns: çağrıldığı temp dizinde mp3 path. Caller sorumlu: dizini
    sil veya `tempfile.TemporaryDirectory()` ile sarmala.

    NOT: bu fonksiyon temp dizinini caller'a verir. Caller işi bittiğinde
    `audio_path.parent` dizinini silmeli; aksi halde disk dolar.
    """

    def _do() -> Path:
        # Caller TemporaryDirectory yönetsin diye burada cleanup yok
        tmp_path = Path(tempfile.mkdtemp(prefix="rasathane-audio-"))
        opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio/best",
            "outtmpl": str(tmp_path / "%(id)s.%(ext)s"),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }
            ],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            audio_path = tmp_path / f"{info['id']}.mp3"
        if not audio_path.exists():
            candidates = list(tmp_path.glob("*.mp3"))
            if not candidates:
                raise RuntimeError("audio download produced no mp3")
            audio_path = candidates[0]
        return audio_path

    return await asyncio.to_thread(_do)


async def transcribe_via_whisper_api(
    audio_path: Path,
    *,
    api_url: str,
    language: str = "tr",
    timeout_seconds: float = 600.0,
) -> Transcript:
    """Phase 26: lokal Docker whisper service'ine sesi POST'la.

    `onerahmet/openai-whisper-asr-webservice` image'inin
    `POST /asr?task=transcribe&language=tr&output=json&vad_filter=true`
    endpoint'ini kullanır. Multipart form-data: `audio_file=<binary>`.

    Eventloop güvenli: httpx.AsyncClient, dosya stream'le yüklenir.
    Timeout 10 dk default — uzun video + GPU bile bunu aşmamalı.

    Args:
        audio_path: indirilmiş mp3 (fetch_audio_only sonucu)
        api_url: container endpoint, örn ``http://localhost:9000``
        language: ISO code; ``tr`` Türkçe, ``en`` İngilizce, ``None`` auto-detect
        timeout_seconds: HTTP timeout (model + transcription dahil)
    """
    import httpx

    asr_url = api_url.rstrip("/") + "/asr"
    params = {
        "task": "transcribe",
        "output": "json",
        "vad_filter": "true",  # boş ses bölgelerini atla — kalite + hız
    }
    if language:
        params["language"] = language

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        with audio_path.open("rb") as f:
            files = {"audio_file": (audio_path.name, f, "audio/mpeg")}
            resp = await client.post(asr_url, params=params, files=files)
            resp.raise_for_status()

    data = resp.json()
    text = (data.get("text") or "").strip()
    detected_lang = data.get("language") or language or "tr"
    if not text:
        raise RuntimeError("whisper_api: empty transcript returned")
    log.info(
        "youtube.subs.whisper_api_ok",
        api=api_url,
        lang=detected_lang,
        chars=len(text),
    )
    return Transcript(text=text, source="whisper-api")


async def fetch_audio_and_transcribe(url: str, *, model_name: str = "medium") -> Transcript:
    """Download best audio + transcribe via faster-whisper.

    Reads ``WHISPER_DEVICE`` from env (``cpu`` default; ``cuda`` if you
    have a GPU). On CPU expect ~2x video duration; on GPU ~0.1x.
    """
    from faster_whisper import WhisperModel

    def _do() -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            opts = {
                "quiet": True,
                "no_warnings": True,
                "format": "bestaudio/best",
                "outtmpl": str(tmp_path / "%(id)s.%(ext)s"),
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "128",
                    }
                ],
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                audio_path = tmp_path / f"{info['id']}.mp3"

            if not audio_path.exists():
                candidates = list(tmp_path.glob("*.mp3"))
                if not candidates:
                    raise RuntimeError("audio download produced no mp3")
                audio_path = candidates[0]

            device = os.environ.get("WHISPER_DEVICE", "cpu")
            compute_type = "int8" if device == "cpu" else "float16"
            model = WhisperModel(model_name, device=device, compute_type=compute_type)
            segments, info_obj = model.transcribe(
                str(audio_path),
                beam_size=5,
                vad_filter=True,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text, info_obj.language

    text, lang = await asyncio.to_thread(_do)
    log.info(
        "youtube.subs.whisper_ok",
        model=model_name,
        lang=lang,
        chars=len(text),
    )
    return Transcript(text=text, source="whisper")


async def fetch_transcript(
    url: str,
    *,
    whisper_model: str = "medium",
) -> Transcript | None:
    """Üç-tier transcript chain. None döner ikisi de fail ederse.

    Sıralama:
        1. yt-dlp auto-captions (en hızlı; YouTube 429 verirse atla)
        2. ``WHISPER_API_URL`` (Phase 26: Docker whisper service —
           ses indirip POST eder, GPU'da hızlı transcribe)
        3. lokal faster-whisper (legacy fallback; CPU/GPU process içinde)

    Phase 26: WHISPER_API_URL set'liyse 2. tier devreye girer; yoksa
    3. tier'a düşer (eski davranış).
    """
    try:
        result = await fetch_subs_via_ytdlp(url)
        if result:
            return result
    except Exception as e:
        log.warning("youtube.subs.ytdlp_failed", error=str(e))

    api_url = os.environ.get("WHISPER_API_URL", "").strip()
    if api_url:
        audio_dir: Path | None = None
        try:
            audio_path = await fetch_audio_only(url)
            audio_dir = audio_path.parent
            return await transcribe_via_whisper_api(audio_path, api_url=api_url)
        except Exception as e:
            log.warning("youtube.subs.whisper_api_failed", error=str(e), url=url)
        finally:
            if audio_dir and audio_dir.exists():
                import shutil

                shutil.rmtree(audio_dir, ignore_errors=True)

    try:
        return await fetch_audio_and_transcribe(url, model_name=whisper_model)
    except Exception as e:
        log.error("youtube.subs.whisper_failed", error=str(e))
        return None


# ─── Phase 12-iv: kanal listesi ingester ────────────────────────────────


async def list_channel_videos(channel_url: str, *, max_count: int = 25) -> list[dict]:
    """Liste recent videos on a YouTube channel via yt-dlp flat-playlist mode.

    Çalışan input formatları:
      - https://www.youtube.com/@handle
      - https://www.youtube.com/@handle/videos
      - https://www.youtube.com/channel/UC...

    Eski RSS endpoint (https://www.youtube.com/feeds/videos.xml?channel_id=UC...)
    2026-05-07 itibariyle 404 veriyor — bu fonksiyon onun yerine geçer.

    Returns ``[{"id", "title", "url", "upload_date", "duration"}, ...]``.
    yt-dlp'nin ``--flat-playlist`` modu olarak çalışır: video meta'sını
    indirmez (transcript/whisper YOK), sadece liste. ~50 video listesi
    için 3-8 sn beklenir.
    """

    def _extract() -> dict:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",  # full info çekme, sadece listele
            "playlistend": max_count,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(channel_url, download=False)

    info = await asyncio.to_thread(_extract)
    entries = info.get("entries") or []
    videos: list[dict] = []
    for e in entries:
        vid = e.get("id")
        if not vid:
            continue
        videos.append(
            {
                "id": vid,
                "title": e.get("title") or "(başlıksız)",
                "url": e.get("url") or f"https://www.youtube.com/watch?v={vid}",
                "upload_date": e.get("upload_date"),  # YYYYMMDD or None
                "duration": int(e.get("duration") or 0),
                "description": (e.get("description") or "")[:1500],
            }
        )
    return videos
