"""Phase 36-iii: Ek analiz (addendum) altyapısı.

3 tür: angle (otomatik açı önerisi), freeform (serbest soru + tag),
compare (mukayeseli kaynak). Her addendum kendi .md dosyası;
addendum_index.json metadata listesi.

Storage:
    archive/deep/{job_id}/
        addendum_{slug}.md
        addendum_index.json
        addendum_angles_suggestions.json   (cache)
        addendum_{slug}_audio.mp3          (Task 14)

Prompt rendering: ``llm.prompts.render()`` regex-only {{var}} substitution.
``{% if %}`` / ``{% for %}`` blokları desteklenmediği için freeform/compare
prompt'larında dinamik bloklar (`tag_context_block`, `sources_block`)
server-side pre-render edilip plain string olarak inject ediliyor.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import structlog
from llm.claude_client import synthesize_with_claude
from llm.prompts import load_prompt, render

from rasathane_mcp.core.deep_analyze import DEEP_DIR, _atomic_write_text

log = structlog.get_logger()

AddendumType = Literal["angle", "freeform", "compare"]

INDEX_FILENAME = "addendum_index.json"
ANGLES_CACHE = "addendum_angles_suggestions.json"

# Tag label haritası — UI'da kullanıcıya göstermek için
TAG_LABELS: dict[str, str] = {
    "tr_hukuk": "Türk Hukuku",
    "tr_avukat": "Avukatlık",
    "tr_ai": "Türkiye AI",
    "dunya_ai": "Dünya AI",
    "acik_kaynak_ai": "Açık Kaynak AI",
    "legaltech": "Legaltech",
    "resmi_mevzuat": "Resmi Mevzuat",
}

_SLUG_PATTERN = re.compile(r"[^a-z0-9_]")


def _safe_slug(raw: str, max_len: int = 30) -> str:
    """Çıktıyı ASCII snake_case'e indir + max len."""
    s = raw.lower().replace(" ", "_").replace("-", "_")
    s = _SLUG_PATTERN.sub("", s)
    return s[:max_len] or "addendum"


def _job_dir(job_id: str) -> Path:
    return DEEP_DIR / job_id


def _index_path(job_id: str) -> Path:
    return _job_dir(job_id) / INDEX_FILENAME


def load_index(job_id: str) -> list[dict[str, Any]]:
    """addendum_index.json — yoksa boş list (sorunsuz)."""
    p = _index_path(job_id)
    if not p.is_file():
        return []
    try:
        raw = p.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("addendum.index_load_failed", job_id=job_id, error=str(e))
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def save_index(job_id: str, entries: list[dict[str, Any]]) -> None:
    """addendum_index.json yaz (atomik)."""
    _atomic_write_text(
        _index_path(job_id),
        json.dumps(entries, ensure_ascii=False, indent=2),
    )


def _upsert_index_entry(job_id: str, entry: dict[str, Any]) -> None:
    """slug'ı varsa overwrite, yoksa append."""
    entries = load_index(job_id)
    entries = [e for e in entries if e.get("slug") != entry["slug"]]
    entries.append(entry)
    save_index(job_id, entries)


async def suggest_angles(job_id: str) -> list[dict[str, str]]:
    """Otomatik açı önerileri (Claude call). Sonuç cache'lenir."""
    cache_path = _job_dir(job_id) / ANGLES_CACHE
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8-sig"))
            if isinstance(cached, list):
                return cached
        except (json.JSONDecodeError, OSError):
            pass
    summary_path = _job_dir(job_id) / "summary.md"
    if not summary_path.is_file():
        raise RuntimeError(f"summary missing for job {job_id}")
    summary = summary_path.read_text(encoding="utf-8")
    prompt = render(load_prompt("addendum_angles"), summary=summary)
    raw = (await synthesize_with_claude(prompt)).strip()
    if not raw:
        raise RuntimeError("addendum_angles: claude empty output")
    # JSON array bulmaya çalış (defansif — model bazen önüne text ekler)
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end < 0:
        raise RuntimeError(
            f"addendum_angles: no JSON array; preview {raw[:200]!r}"
        )
    try:
        angles = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"addendum_angles: JSON parse fail: {e}") from e
    if not isinstance(angles, list):
        raise RuntimeError("addendum_angles: response not a list")
    cleaned: list[dict[str, str]] = []
    for a in angles:
        if not isinstance(a, dict):
            continue
        slug = _safe_slug(str(a.get("slug", "")))
        title = str(a.get("title", "")).strip()[:80]
        why = str(a.get("why", "")).strip()[:200]
        if slug and title:
            cleaned.append({"slug": slug, "title": title, "why": why})
    _atomic_write_text(
        cache_path, json.dumps(cleaned, ensure_ascii=False, indent=2)
    )
    return cleaned


async def generate_angle_addendum(
    job_id: str, slug: str, title: str
) -> dict[str, Any]:
    """Bir otomatik açı için derin analiz üret."""
    summary_path = _job_dir(job_id) / "summary.md"
    if not summary_path.is_file():
        raise RuntimeError(f"summary missing for job {job_id}")
    summary = summary_path.read_text(encoding="utf-8")
    safe_slug = _safe_slug(slug)
    prompt = (
        f"Bu video özetine dayanarak şu açıdan derin analiz yap: **{title}**.\n\n"
        f"## Video özeti\n\n{summary}\n\n"
        f"Yapı: 1 cümle özet → 3-4 paragraf analiz → 1 paragraf pratik çıkarım. "
        f"500-900 kelime. Türkçe, modern profesyonel ton (arkaik kelime yok). "
        f"Markdown formatlama OK.\n\nÇIKTI: Markdown."
    )
    body = (await synthesize_with_claude(prompt)).strip()
    if not body:
        raise RuntimeError("angle addendum: claude empty output")
    md_path = _job_dir(job_id) / f"addendum_{safe_slug}.md"
    _atomic_write_text(md_path, body)
    entry = {
        "slug": safe_slug,
        "type": "angle",
        "title": title,
        "created_at": datetime.now(UTC).isoformat(),
        "char_count": len(body),
        "has_audio": False,
    }
    _upsert_index_entry(job_id, entry)
    return entry


async def generate_freeform_addendum(
    job_id: str, question: str, tags: list[str]
) -> dict[str, Any]:
    """Serbest soru + tag context ile addendum."""
    if not question or not question.strip():
        raise ValueError("question required")
    summary_path = _job_dir(job_id) / "summary.md"
    if not summary_path.is_file():
        raise RuntimeError(f"summary missing for job {job_id}")
    summary = summary_path.read_text(encoding="utf-8")
    tags_label = ", ".join(TAG_LABELS.get(t, t) for t in tags) or "(belirsiz)"
    tag_context = await _fetch_tag_context(tags, limit=5)
    if tag_context:
        tag_context_block = (
            "**Son 7 günde ilgili tag'lerde yer alan haber başlıkları "
            "(referans olarak):**\n"
            f"{tag_context}\n"
        )
    else:
        tag_context_block = ""
    prompt = render(
        load_prompt("addendum_freeform"),
        summary=summary,
        question=question,
        tags_label=tags_label,
        tag_context_block=tag_context_block,
    )
    body = (await synthesize_with_claude(prompt)).strip()
    if not body:
        raise RuntimeError("freeform addendum: claude empty output")
    slug = "freeform_" + hashlib.md5(question.encode("utf-8")).hexdigest()[:8]
    md_path = _job_dir(job_id) / f"addendum_{slug}.md"
    _atomic_write_text(md_path, body)
    entry = {
        "slug": slug,
        "type": "freeform",
        "title": question[:60] + ("…" if len(question) > 60 else ""),
        "question": question,
        "tags": list(tags),
        "created_at": datetime.now(UTC).isoformat(),
        "char_count": len(body),
        "has_audio": False,
    }
    _upsert_index_entry(job_id, entry)
    return entry


async def generate_compare_addendum(
    job_id: str, source_ids: list[Any]
) -> dict[str, Any]:
    """Mukayeseli analiz — DB'den source'ları çek + Claude."""
    if not (2 <= len(source_ids) <= 5):
        raise ValueError("source_ids must be 2-5 items")
    summary_path = _job_dir(job_id) / "summary.md"
    if not summary_path.is_file():
        raise RuntimeError(f"summary missing for job {job_id}")
    summary = summary_path.read_text(encoding="utf-8")
    sources = await _fetch_articles_by_ids(source_ids)
    if not sources:
        raise RuntimeError("no sources resolved for given ids")
    sources_block = _render_sources_block(sources)
    prompt = render(
        load_prompt("addendum_compare"),
        summary=summary,
        sources_block=sources_block,
        source_count=str(len(sources)),
    )
    body = (await synthesize_with_claude(prompt)).strip()
    if not body:
        raise RuntimeError("compare addendum: claude empty output")
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M")
    slug = f"compare_{timestamp}"
    md_path = _job_dir(job_id) / f"addendum_{slug}.md"
    _atomic_write_text(md_path, body)
    entry = {
        "slug": slug,
        "type": "compare",
        "title": f"Mukayese — {len(sources)} kaynak",
        "source_ids": [str(s) for s in source_ids],
        "created_at": datetime.now(UTC).isoformat(),
        "char_count": len(body),
        "has_audio": False,
    }
    _upsert_index_entry(job_id, entry)
    return entry


def _render_sources_block(sources: list[dict[str, Any]]) -> str:
    """``addendum_compare.md`` içine yerleştirilecek kaynak listesi (markdown)."""
    parts: list[str] = []
    for i, src in enumerate(sources, start=1):
        title = src.get("title", "(başlıksız)")
        source_name = src.get("source_name", "")
        published_at = src.get("published_at", "")
        url = src.get("url", "")
        summary = src.get("summary", "")
        parts.append(
            f"### Kaynak {i}: {title}\n"
            f"- **Yayıncı:** {source_name}\n"
            f"- **Tarih:** {published_at}\n"
            f"- **URL:** {url}\n"
            f"- **Özet:** {summary}\n"
        )
    return "\n".join(parts)


async def _fetch_tag_context(tags: list[str], limit: int = 5) -> str:
    """Son 7 günde verilen tag'lerde geçen makale başlıkları (markdown bullet list).

    Mevcut articles tablosundan en yeni N başlık. DB sorgu hatasında boş döner
    (silent-skip — addendum üretimi DB outage'ında durmaz).
    """
    if not tags:
        return ""
    try:
        from rasathane_mcp.core.articles import list_recent_titles_by_tags

        rows = await list_recent_titles_by_tags(tags, days=7, limit=limit)
    except Exception as e:
        log.warning("addendum.tag_context_failed", error=str(e))
        return ""
    if not rows:
        return ""
    return "\n".join(
        f"- {r['title']} ({r.get('source_name', '')})" for r in rows
    )


async def _fetch_articles_by_ids(source_ids: list[Any]) -> list[dict[str, Any]]:
    """DB'den seçili makaleleri çek (id, title, source_name, published_at, url, summary)."""
    try:
        from rasathane_mcp.core.articles import list_articles_by_ids

        return await list_articles_by_ids(source_ids)
    except Exception as e:
        log.warning("addendum.fetch_sources_failed", error=str(e))
        return []


def delete_addendum(job_id: str, slug: str) -> bool:
    """Addendum .md + index entry'sini sil. True döner silindi/silinemedi'ye göre."""
    md_path = _job_dir(job_id) / f"addendum_{slug}.md"
    audio_path = _job_dir(job_id) / f"addendum_{slug}_audio.mp3"
    deleted = False
    if md_path.is_file():
        md_path.unlink()
        deleted = True
    if audio_path.is_file():
        audio_path.unlink()
    entries = load_index(job_id)
    new_entries = [e for e in entries if e.get("slug") != slug]
    if len(new_entries) != len(entries):
        save_index(job_id, new_entries)
        deleted = True
    return deleted


async def synthesize_addendum_audio(job_id: str, slug: str) -> dict[str, Any]:
    """Bir addendum'un .md içeriğinden tek-sesli MP3 üret.

    Voice: Filiz (default tek-narrator). Pipeline brief.py
    synthesize_to_mp3 ile aynı (single-voice ElevenLabs).
    """
    md_path = _job_dir(job_id) / f"addendum_{slug}.md"
    if not md_path.is_file():
        raise RuntimeError(f"addendum md not found: {slug}")
    audio_path = _job_dir(job_id) / f"addendum_{slug}_audio.mp3"
    from llm.tts import synthesize_to_mp3

    text = md_path.read_text(encoding="utf-8")
    # Basit markdown strip — TTS için plain text yeterli
    text = re.sub(r"#{1,6}\s+", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    # Phase 36-iii: tablo satırlarını sil (compare addendum'larında çok yaygın)
    text = re.sub(r"^\|.*\|$", "", text, flags=re.MULTILINE)
    # Blockquote prefix
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    # Ordered list prefix (1. 2. 3.)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise RuntimeError("addendum text empty after strip")
    await synthesize_to_mp3(text, output_path=audio_path)
    # Index güncelle (has_audio: True)
    entries = load_index(job_id)
    for e in entries:
        if e.get("slug") == slug:
            e["has_audio"] = True
            break
    save_index(job_id, entries)
    return {
        "ok": True,
        "audio_url": f"/archive/deep/{job_id}/addendum_{slug}_audio.mp3",
        "bytes": audio_path.stat().st_size,
    }
