"""Daily brief loader + generator — `archive/YYYY-MM-DD/00-brief.md`.

Phase 12-ii: ``generate_brief`` toplar son 24 saat makalelerini, claude
CLI subprocess'iyle Türkçe brief sentezler, lockfile pattern'iyle
concurrent generation guard'ı ekler. ``load_brief`` mevcut brief'i okur
+ generation state (lockfile var/yok) bilgisini döner.

Phase 32-ii: ``generate_brief_audio`` 3-konuşmacı podcast moduna geçti
(Filiz/Mehmet/Burak). ``_parse_podcast_dialog`` + ``_format_date_tr``
yardımcıları deep_analyze.py'da YouTube podcast modunda da reuse edilir.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
# Phase 34-v: urllib.parse.quote import kaldırıldı (muhakeme inject silindi).

import structlog
from llm.claude_client import synthesize_with_claude
from llm.prompts import load_prompt, render
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from store.models import Article

log = structlog.get_logger()

LOCKFILE_NAME = ".generating"
LAST_ERROR_NAME = ".last-error.txt"
LOCKFILE_STALE_SECONDS = 600  # 10 dk; gerçek üretim 30-90 sn beklenir
ARTICLES_PER_BRIEF = 80
ARTICLES_PER_CATEGORY = 20
SINCE_HOURS = 24


# Phase 24: brief markdown'undan analizlenebilir link çıkarma
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_TRAILING_PUNCT = ".,;:!?"

# Phase 35-xxiv: Canonicalize patterns. `detect_url_type` sadece domain
# substring kontrol eder; bu regex'ler her tipin asıl canonical formuna
# çevirir. Niye gerekli: Brief markdown'ında Claude bazen release tag URL'i
# (`github.com/X/Y/releases/tag/Z`), arxiv PDF URL'i (`arxiv.org/pdf/ID`)
# veya YouTube shorts (`youtube.com/shorts/ID`) yazar. Backend
# `run_repomix --remote URL` veya yt-dlp tam URL'i bekler — non-canonical
# path geldiğinde patlar. Canonicalization downstream'i koruyor.
_YOUTUBE_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/|v/|live/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})"
)
_GITHUB_OWNER_REPO_RE = re.compile(r"github\.com/([^/?#]+)/([^/?#]+)")
_ARXIV_ID_RE = re.compile(r"arxiv\.org/(?:abs|pdf|html)/([^/?#]+)")

# `github.com/<reserved>/X` yolları repo değil, özellik sayfaları
_GITHUB_RESERVED_OWNERS = frozenset({
    "topics", "marketplace", "trending", "search", "settings",
    "notifications", "sponsors", "stars", "explore", "issues",
    "pulls", "discussions", "features", "about", "pricing",
    "enterprise", "site", "security", "readme", "events", "orgs",
    "collections", "codespaces", "advisories",
})

# Generic / düşük bilgi içeren label'lar — URL'den türetilen alternatife
# fallback için. "abs", "pdf", "açıldı" gibi anlamsız anchor metinleri
# Claude bazen yazar; o durumda canonical URL'den `owner/repo` türetelim.
_GENERIC_LABELS = frozenset({
    "buraya", "burada", "şurada", "tıkla", "link", "links",
    "abs", "pdf", "html", "açıldı", "yayınlandı", "github",
    "repo", "video", "makale", "paper", "kanal", "kaynak",
})


def _canonicalize_analyzable_url(url: str, detected_type: str) -> str | None:
    """URL'i type'ın canonical formuna çevir; çevirilemezse ``None``.

    - youtube: 11-karakter video ID → ``https://www.youtube.com/watch?v=ID``
    - github: owner/repo (reserved owner değil) → ``https://github.com/owner/repo``
    - arxiv: paper ID → ``https://arxiv.org/abs/ID``
    """
    if detected_type == "youtube":
        m = _YOUTUBE_VIDEO_ID_RE.search(url)
        if not m:
            return None
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    if detected_type == "github":
        m = _GITHUB_OWNER_REPO_RE.search(url)
        if not m:
            return None
        owner = m.group(1)
        repo = m.group(2).removesuffix(".git")
        if owner.lower() in _GITHUB_RESERVED_OWNERS:
            return None
        return f"https://github.com/{owner}/{repo}"
    if detected_type == "arxiv":
        m = _ARXIV_ID_RE.search(url)
        if not m:
            return None
        arxiv_id = m.group(1).removesuffix(".pdf").removesuffix(".html")
        return f"https://arxiv.org/abs/{arxiv_id}"
    return None


def _is_label_generic(label: str) -> bool:
    """Label çok kısa, salt-rakam, version-tag stili veya bilinen generic
    ise True. ``b9254`` / ``v1.2.3`` gibi version etiketleri (3'ten az
    harf içeren) URL'den türetilen meaningful versiyonla değiştirilir.
    """
    stripped = label.strip()
    if len(stripped) < 4:
        return True
    if all(c.isdigit() or c in "-._" for c in stripped):
        return True
    letter_count = sum(1 for c in stripped if c.isalpha())
    if letter_count < 3:
        return True
    return stripped.lower() in _GENERIC_LABELS


def _derive_analyzable_label(canonical_url: str, detected_type: str) -> str | None:
    """Canonical URL'ten anlamlı bir label türet — generic fallback için."""
    if detected_type == "github":
        m = _GITHUB_OWNER_REPO_RE.search(canonical_url)
        return f"{m.group(1)}/{m.group(2)}" if m else None
    if detected_type == "arxiv":
        m = _ARXIV_ID_RE.search(canonical_url)
        return f"arXiv:{m.group(1)}" if m else None
    if detected_type == "youtube":
        m = _YOUTUBE_VIDEO_ID_RE.search(canonical_url)
        return f"YouTube:{m.group(1)}" if m else None
    return None


def extract_analyzable_urls(brief_md: str) -> list[dict[str, str]]:
    """Brief markdown'undan deep-dive'a uygun URL'leri çıkar.

    Inline ``[label](url)`` linkleri taranır; ``detect_url_type`` ile tip
    belirlenir, ``_canonicalize_analyzable_url`` ile canonical forma
    çevrilir. Canonical URL bazında dedup yapılır (aynı repo'nun farklı
    path'lerinden gelen referanslar tek satıra iner). Label generic ise
    URL'den türetilen anlamlı versiyon kullanılır.

    Returns: ``[{"url": str, "type": str, "label": str}, ...]``.
    """
    # core_deep import'u burada — modüller arası döngüden kaçınmak için
    from rasathane_mcp.core.deep_analyze import detect_url_type

    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for match in _MARKDOWN_LINK_RE.finditer(brief_md):
        label = match.group(1).strip()
        raw_url = match.group(2).rstrip(_TRAILING_PUNCT)
        detected = detect_url_type(raw_url)
        if detected == "unknown":
            continue
        canonical = _canonicalize_analyzable_url(raw_url, detected)
        if canonical is None:
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        if _is_label_generic(label):
            derived = _derive_analyzable_label(canonical, detected)
            if derived:
                label = derived
        out.append({"url": canonical, "type": detected, "label": label})
    return out


def looks_like_date(name: str) -> bool:
    """``YYYY-MM-DD`` shape check; rejects ``../etc/passwd``-style attempts."""
    if len(name) != 10 or name[4] != "-" or name[7] != "-":
        return False
    return name[:4].isdigit() and name[5:7].isdigit() and name[8:10].isdigit()


def _today_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def load_brief(*, archive_root: Path, date: str | None = None) -> dict[str, Any]:
    """Read brief at ``archive_root / date`` + generation state.

    Lockfile varsa ``generating: true`` + elapsed döner. Yoksa dosya içeriği.
    ``date`` explicit verilirse o tarih zorunlu (fallback yok); None ise
    "bugün → en son üretilen" zinciri.
    """
    if date is not None:
        if not looks_like_date(date):
            return {"error": f"invalid date format {date!r}; expected YYYY-MM-DD"}
        target_dir = archive_root / date
        # Lockfile (yalnız bu date için)
        lock_state = _check_lockfile(target_dir, date)
        if lock_state is not None:
            return lock_state
        top_path = target_dir / "00-brief.md"
        if not top_path.is_file():
            return {"error": f"no brief found for date {date}"}
        return _build_brief_payload(target_dir, top_path)

    # date None → bugün → en son üretilen fallback
    today = _today_iso()
    today_dir = archive_root / today
    lock_state = _check_lockfile(today_dir, today)
    if lock_state is not None:
        return lock_state

    if not archive_root.exists():
        return {"error": "archive directory does not exist; click 'Üret' to generate"}
    candidates = sorted(
        (p for p in archive_root.iterdir() if p.is_dir() and looks_like_date(p.name)),
        reverse=True,
    )
    if not candidates:
        return {"error": "no briefs found in archive/; click 'Üret' to generate today's brief"}
    target_dir = candidates[0]
    top_path = target_dir / "00-brief.md"
    if not top_path.is_file():
        return {"error": f"00-brief.md missing in {target_dir.name}"}
    return _build_brief_payload(target_dir, top_path)


def _check_lockfile(target_dir: Path, date: str) -> dict[str, Any] | None:
    """``generating: true`` payload döndür eğer fresh lockfile varsa.

    Stale (>``LOCKFILE_STALE_SECONDS``) veya bozuk lockfile bulunursa
    sessizce silinir. Orphan senaryosu (claude subprocess çakıldı +
    dashboard restart) bir sonraki ``/api/brief`` GET'inde kendiliğinden
    iyileşir — yeni generate tetiklenmesini beklemeden.
    """
    lockfile = target_dir / LOCKFILE_NAME
    if not lockfile.is_file():
        return None
    try:
        lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
        started_at = datetime.fromisoformat(lock_data["started_at"])
        elapsed = int((datetime.now(UTC) - started_at).total_seconds())
        if elapsed < LOCKFILE_STALE_SECONDS:
            return {
                "date": date,
                "generating": True,
                "started_at": lock_data["started_at"],
                "elapsed_sec": elapsed,
                "top_brief": None,
            }
        lockfile.unlink(missing_ok=True)
        log.warning("brief.stale_lockfile_cleared_on_read", date=date, elapsed_sec=elapsed)
    except (json.JSONDecodeError, KeyError, ValueError):
        lockfile.unlink(missing_ok=True)
    return None


def _build_brief_payload(target_dir: Path, top_path: Path) -> dict[str, Any]:
    last_error_path = target_dir / LAST_ERROR_NAME
    last_error = (
        last_error_path.read_text(encoding="utf-8")[:500] if last_error_path.is_file() else None
    )
    # Phase 22-iii: brief audio (mp3) varsa URL'i payload'a ekle
    audio_path = target_dir / "00-brief.mp3"
    audio_url = None
    if audio_path.is_file():
        audio_url = f"/archive/{target_dir.name}/00-brief.mp3"
    top_brief = top_path.read_text(encoding="utf-8")

    # Phase 33-i: sources.json ham kaynak listesi
    sources_path = target_dir / "sources.json"
    sources: list[dict[str, Any]] = []
    if sources_path.is_file():
        try:
            sources = json.loads(sources_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("brief.sources_json_read_failed", date=target_dir.name)

    return {
        "date": target_dir.name,
        "top_brief": top_brief,
        # Phase 24: brief'te bahsedilen YouTube/GitHub/arXiv linklerini
        # deep-dive CTA olarak UI'da göstermek için
        "analyzable_urls": extract_analyzable_urls(top_brief),
        "category_files": [
            p.name
            for p in sorted(target_dir.iterdir())
            if p.suffix == ".md" and p.name != "00-brief.md"
        ],
        "has_mindmap": (target_dir / "mindmap.html").exists(),
        "audio_url": audio_url,
        "sources": sources,
        "generating": False,
        "generated_at": datetime.fromtimestamp(top_path.stat().st_mtime, UTC).isoformat(),
        "last_error": last_error,
    }


def _brief_preview(brief_md: str, max_chars: int = 220) -> str:
    """``00-brief.md``'in ilk anlamlı satırlarından kısa önizleme çıkar.

    Markdown başlık satırları (``#``, ``##``) atlanır; ilk düz paragraf
    ya da bullet'ın ilk cümleleri döner. Liste UI'sinde kart preview
    olarak gösterilir.
    """
    out: list[str] = []
    total = 0
    for raw in brief_md.split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Bullet işaretini at
        if line.startswith("- "):
            line = line[2:].strip()
        # Markdown link [label](url) → label
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        # Bold/italic işaretleri kalksın
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        out.append(line)
        total += len(line)
        if total >= max_chars:
            break
    text = " ".join(out)
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


# Phase 35-xxiv: `append_sources_to_brief` ve `_CATEGORY_LABELS_TR` kaldırıldı
# — brief markdown'ına inline "📎 Kullanılan Kaynaklar (N)" appendix eklemek
# UI'daki `data.sources` dropdown'u (80 kaynak) ile çelişiyordu (appendix
# sadece referenced URL'leri sayıp ~17 gösterirken dropdown tüm prompt
# input'unu listeliyor). Tek kaynak göstergesi olarak dropdown kaldı;
# sources.json hâlâ generate_brief tarafından yazılıyor.

# Phase 34-v: `inject_muhakeme_buttons` ve ilgili sabitleri tamamen kaldırıldı.
# muhakeme.ai entegrasyonu Phase 35'te yeniden ele alınacak (ayrı UI patika).

# Phase 34-vi: Defensive HTML strip — Claude prompt'a rağmen ara sıra inline
# HTML tag inject ediyor (özellikle muhakeme cross-link emoji buton'ları).
# `_INLINE_HTML_ANCHOR_RE` markdown linkleri korur, HTML <a>...</a> ve <span>,
# <button>, <div> gibi tagleri siler.
_INLINE_HTML_TAG_RE = re.compile(
    # `<a ...>label</a>` — kapanış tag'iyle
    r"\s*<a\b[^>]*>[^<]*</a>"
    r"|"
    # Self-closing veya orphan `<span>`, `<i>`, `<button>` vb.
    r"\s*</?(?:span|button|div|i|b|strong|em|a)\b[^>]*/?>"
)


def strip_inline_html_tags(markdown: str) -> str:
    """Phase 34-vi: Defensive — Claude HTML inject ettiyse temizle.

    Sadece HTML tag'leri siler; markdown sentaksı (`[label](url)`, `**bold**`,
    `## header`) etkilenmez. Brief'in render edilmiş halinde raw HTML
    görmemek için son hat savunması. Hatta prompt'ta açık yasak olsa
    bile LLM bazen drift'leyebiliyor — bu helper "garanti temiz output"
    sağlar.
    """
    return _INLINE_HTML_TAG_RE.sub("", markdown)


def list_briefs(archive_root: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    """Geçmiş brief'leri (en yeni önce) liste döndür.

    Filesystem-authoritative scan: ``archive/YYYY-MM-DD/00-brief.md``
    dosyası olan her dizin bir entry. Her entry için ``has_audio``
    flag'i + kısa önizleme + üretim zamanı.
    """
    if not archive_root.exists():
        return []
    entries: list[dict[str, Any]] = []
    for child in archive_root.iterdir():
        if not child.is_dir() or not looks_like_date(child.name):
            continue
        brief_path = child / "00-brief.md"
        if not brief_path.is_file():
            continue
        try:
            md = brief_path.read_text(encoding="utf-8")
        except OSError:
            continue
        entries.append(
            {
                "date": child.name,
                "preview": _brief_preview(md),
                "has_audio": (child / "00-brief.mp3").is_file(),
                "generated_at": datetime.fromtimestamp(brief_path.stat().st_mtime, UTC).isoformat(),
            }
        )
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries[:limit]


def _extract_anchor_topics(brief_md: str, max_topics: int = 8) -> list[str]:
    """Bir brief'in markdown'ından "anchor topic" cümlelerini çıkar.

    Anchor topic = section başlıklarının altındaki ilk bullet/cümle.
    Bu cümleler "devam eden konu" sinyali olarak yeni brief'e
    geri-besleme yapar — editör "Geçen gün başlayan X, bugün Y" gibi
    süreklilik kurar.

    Markdown link, bold/italic, emoji prefix sıyrılır; ham olay özeti
    döner. ``max_topics`` üst sınır (default 8 — son 3 brief × 8 = 24
    anchor max, prompt budget içinde).
    """
    out: list[str] = []
    in_section = False
    for raw in brief_md.split("\n"):
        line = raw.strip()
        if not line:
            in_section = False
            continue
        if line.startswith("##") or line.startswith("# "):
            in_section = True
            continue
        if not in_section:
            continue
        # İlk anlamlı cümle/bullet
        if line.startswith("- "):
            line = line[2:].strip()
        elif line.startswith(">"):
            continue  # quote bloğu atla
        # Markdown linkleri label'a indir
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        # Bold/italic
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        line = re.sub(r"\*([^*]+)\*", r"\1", line)
        # İlk cümleyi al (nokta veya ;'e kadar; 200 char cap)
        first_sentence = re.split(r"(?<=[.!?])\s+", line, maxsplit=1)[0][:200].strip()
        if len(first_sentence) >= 30:
            out.append(first_sentence)
            in_section = False  # section başına sadece 1 anchor
        if len(out) >= max_topics:
            break
    return out


def _gather_recent_brief_context(archive_root: Path, *, days: int = 3) -> str:
    """Son ``days`` günün brief'lerinden anchor topic list'i markdown döndür.

    Pre-flight: ``daily_brief.md`` prompt'unun ``{{recent_brief_context}}``
    placeholder'ına yerleşir. Editör bu listeyi okur ve bugünkü girdide
    aynı konu devam ediyorsa "Geçen gün başlayan X, bugün Y" diye bağlar
    (süreklilik = kopuk haber yığını değil, zaman çizgisi).

    Filesystem-only — DB sorgusu yok; Claude çağrısı yok. Bugünün brief
    klasörü (varsa) ATLA (kendi kendine reference olmasın).

    Format::

        ## 2026-05-17
        - Yargıtay 9. HD, davalı tedarik özeniyle ilgili karar verdi.
        - DeepSeek V3 açık kaynak yayımlandı.

        ## 2026-05-16
        - ...
    """
    if not archive_root.exists():
        return "(geçmiş brief yok — ilk üretim)"
    today = _today_iso()
    candidates: list[tuple[str, Path]] = []
    for child in archive_root.iterdir():
        if not child.is_dir() or not looks_like_date(child.name):
            continue
        if child.name >= today:
            continue  # bugünü atla (kendi kendine ref olmasın)
        brief_path = child / "00-brief.md"
        if brief_path.is_file():
            candidates.append((child.name, brief_path))
    candidates.sort(key=lambda x: x[0], reverse=True)
    candidates = candidates[:days]
    if not candidates:
        return "(geçmiş brief yok — ilk üretim)"

    blocks: list[str] = []
    for date_str, brief_path in candidates:
        try:
            md = brief_path.read_text(encoding="utf-8")
        except OSError:
            continue
        topics = _extract_anchor_topics(md, max_topics=8)
        if not topics:
            continue
        topic_lines = "\n".join(f"- {t}" for t in topics)
        blocks.append(f"## {date_str}\n{topic_lines}")
    return "\n\n".join(blocks) if blocks else "(geçmiş brief'lerde anchor topic bulunamadı)"


def _purge_audio_artifacts(target_dir: Path) -> None:
    """``force=True`` brief regen sırasında eski audio + script dosyalarını sil.

    Phase 33-i: ``00-brief.audio.json`` da purge listesine eklendi
    (yeni brief'in eski script ile tutarsız MP3 üretmemesi için).
    """
    for name in (
        "00-brief.mp3",
        "00-brief.audio.txt",
        "00-brief.audio.json",
        ".audio.lock",
    ):
        (target_dir / name).unlink(missing_ok=True)


async def _gather_articles_grouped(session: AsyncSession) -> tuple[str, list[Article]]:
    """Son 24 saatte fetch edilmiş makaleleri kategori bazlı gruplu metin + ham liste döndür.

    Phase 33-i: return type str → tuple[str, list[Article]] (kaynak appendix için).

    İlk eleman: prompt template'in ``{{articles_grouped}}`` placeholder'ına.
    İkinci eleman: ham Article list — kaynak appendix + sources.json için.
    """
    since = datetime.now(UTC).replace(microsecond=0) - _timedelta_hours(SINCE_HOURS)
    stmt = (
        select(Article)
        .options(selectinload(Article.source))
        .where(Article.fetched_at >= since)
        .order_by(Article.fetched_at.desc())
        .limit(500)  # Üst sınır: kategori başına 20 × 5 kategori = 100 hedefliyoruz
    )
    result = await session.execute(stmt)
    articles = list(result.scalars().all())

    by_cat: dict[str, list[Article]] = {}
    for art in articles:
        cat = art.source.category
        if cat not in by_cat:
            by_cat[cat] = []
        if len(by_cat[cat]) < ARTICLES_PER_CATEGORY:
            by_cat[cat].append(art)

    # Phase 32-iv: Resmî Gazete kategorisi (resmi_mevzuat) ayrı işle —
    # her madde için ``bolum`` (YÖNETMELİKLER/TEBLİĞLER/İLÂN BÖLÜMÜ) ön
    # ek olarak gösterilir. Diğer kategoriler standart formatta.
    lines: list[str] = []
    total = 0
    # Önce Resmî Gazete'yi en başa koy (editör için anchor: günün resmî
    # mevzuat olayları diğer haberleri çerçeveler).
    cat_order = sorted(
        by_cat.keys(),
        key=lambda c: (0 if c == "resmi_mevzuat" else 1, c),
    )
    selected_for_prompt: list[Article] = []
    for cat in cat_order:
        arts = by_cat[cat]
        if not arts:
            continue
        lines.append(f"\n## {cat}")
        for art in arts:
            if total >= ARTICLES_PER_BRIEF:
                break
            selected_for_prompt.append(art)
            summary_for_brief = (
                art.summary_tr_short or (art.summary[:240] if art.summary else "") or ""
            )
            # Resmî Gazete: bolum prefix + gazete_no, görsel ayırt edilebilir.
            if cat == "resmi_mevzuat":
                meta = art.metadata or {}
                bolum = meta.get("bolum") or "Bilinmeyen Bölüm"
                gazete_no = meta.get("gazete_no")
                gazete_date = meta.get("gazete_date") or ""
                no_str = f"#{gazete_no}" if gazete_no else ""
                head = f"[{bolum}] {art.title}"
                line = f"- {head} (Resmî Gazete {no_str} • {gazete_date})"
            else:
                line = f"- {art.title} ({art.source.name})"
            if summary_for_brief:
                line += f" — {summary_for_brief}"
            line += f"\n  {art.url}"
            lines.append(line)
            total += 1

    text = "\n".join(lines) if lines else "(son 24 saatte hiç makale yok)"
    return text, selected_for_prompt


def _timedelta_hours(h: int):  # type: ignore[no-untyped-def]
    """Local helper to avoid timedelta import noise in caller."""
    from datetime import timedelta

    return timedelta(hours=h)


def _acquire_lockfile(target_dir: Path) -> Path:
    """Atomik lockfile create. Stale (>10 dk) ise temizle + yeniden dene.

    Raises ``FileExistsError`` if lockfile var ve fresh.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    lockfile = target_dir / LOCKFILE_NAME

    # Stale lockfile cleanup
    if lockfile.is_file():
        try:
            lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
            started_at = datetime.fromisoformat(lock_data["started_at"])
            elapsed = (datetime.now(UTC) - started_at).total_seconds()
            if elapsed >= LOCKFILE_STALE_SECONDS:
                lockfile.unlink(missing_ok=True)
                log.warning("brief.stale_lockfile_cleared", elapsed_sec=int(elapsed))
        except (json.JSONDecodeError, KeyError, ValueError):
            lockfile.unlink(missing_ok=True)

    # Atomic create
    fd = os.open(str(lockfile), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(
            {"started_at": _now_iso(), "pid": os.getpid(), "cmd": "claude"},
            f,
        )
    return lockfile


async def generate_brief(
    session: AsyncSession,
    *,
    archive_root: Path,
    force: bool = False,
) -> dict[str, Any]:
    """Bugünün gündemini üretir; lockfile + atomik dosya yazımı.

    Returns:
        ``{"started_at": ..., "date": ...}`` başarılı tetikleme durumunda
        (asıl üretim background task tarafından devam eder).
        ``{"error": "in_progress" | "already_exists" | "cli_not_found", ...}``
        çakışmada.

    Caller bu fonksiyonu ``asyncio.create_task`` veya FastAPI
    BackgroundTasks ile çağırmalı — claude subprocess 30-90 sn beklenir.
    """
    today = _today_iso()
    target_dir = archive_root / today
    top_path = target_dir / "00-brief.md"

    # Bugünün brief'i zaten var mı?
    if top_path.is_file() and not force:
        generated_at = datetime.fromtimestamp(top_path.stat().st_mtime, UTC).isoformat()
        return {"error": "already_exists", "generated_at": generated_at}

    # force=True regen → eski audio yeni brief'e karşılık gelmiyor; temizle
    if force and top_path.is_file():
        _purge_audio_artifacts(target_dir)

    # Lockfile acquire (concurrent guard)
    try:
        lockfile = _acquire_lockfile(target_dir)
    except FileExistsError:
        # Fresh lockfile var — başka bir generation sürüyor
        try:
            lock_data = json.loads((target_dir / LOCKFILE_NAME).read_text(encoding="utf-8"))
            return {"error": "in_progress", "started_at": lock_data["started_at"]}
        except Exception:
            return {"error": "in_progress"}

    started_at = _now_iso()
    last_error_path = target_dir / LAST_ERROR_NAME

    # Last-error temizle (eski hatalı çalıştırmadan kalan)
    last_error_path.unlink(missing_ok=True)

    try:
        # Articles gather + prompt render
        articles_grouped, articles_used = await _gather_articles_grouped(session)
        # Phase 32-v: pre-flight — son 3 günün anchor topic'leri.
        # Filesystem-only, claude çağrısı yok (mimari prensip).
        recent_brief_context = await asyncio.to_thread(
            _gather_recent_brief_context, archive_root, days=3
        )
        template = load_prompt("daily_brief")
        prompt = render(
            template,
            articles_grouped=articles_grouped,
            recent_brief_context=recent_brief_context,
        )

        log.info(
            "brief.generate.starting",
            date=today,
            prompt_chars=len(prompt),
            recent_context_chars=len(recent_brief_context),
        )

        # Claude subprocess (30-90 sn)
        markdown = await synthesize_with_claude(prompt)
        markdown = markdown.strip()
        if not markdown:
            raise RuntimeError("claude returned empty output")

        # Phase 34-v: muhakeme cross-link inject KALDIRILDI.
        # Phase 34-vi: Defensive — Claude prompt'a rağmen ara sıra HTML inject
        # ediyor (özellikle "🔍 emsal ara" cross-link). Brief'i yazmadan önce
        # temizle.
        markdown = strip_inline_html_tags(markdown)
        # Phase 35-xxiv: inline "Kullanılan Kaynaklar" appendix kaldırıldı; UI
        # dropdown'u (data.sources) tek kaynak göstergesi. sources.json hâlâ
        # aşağıda yazılıyor.

        # Atomic write: tmp + os.replace
        tmp_path = target_dir / "00-brief.md.tmp"
        tmp_path.write_text(markdown, encoding="utf-8")
        os.replace(str(tmp_path), str(top_path))

        # Phase 33-i: sources.json — UI /api/brief response için ham kaynak listesi
        sources_payload = [
            {
                "title": a.title,
                "url": a.url,
                "source_name": a.source.name,
                "category": a.source.category,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "fetched_at": a.fetched_at.isoformat() if a.fetched_at else None,
            }
            for a in articles_used
        ]
        sources_path = target_dir / "sources.json"
        tmp_sources = sources_path.with_suffix(".json.tmp")
        tmp_sources.write_text(
            json.dumps(sources_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(str(tmp_sources), str(sources_path))

        log.info("brief.generate.done", date=today, chars_out=len(markdown))
        return {"started_at": started_at, "date": today}
    except Exception as e:
        # Failure: stderr log + .last-error.txt
        err_text = str(e)[:2000]
        last_error_path.write_text(err_text, encoding="utf-8")
        log.error("brief.generate.failed", date=today, err=err_text[:200])
        return {"error": "generation_failed", "detail": err_text[:500]}
    finally:
        # Lockfile her durumda temizle
        lockfile.unlink(missing_ok=True)


async def generate_brief_audio(
    *,
    archive_root: Path,
    date: str | None = None,
) -> dict[str, Any]:
    """Phase 22-iii + 32-ii + 35-i: belirli bir günün brief.md'sini sesli özete dönüştür.

    Pipeline (Phase 35-i: ElevenLabs-only 3-konuşmacı podcast):
      1. archive/{date}/00-brief.md oku
      2. brief_podcast_script.md prompt → claude → JSON dialog (Filiz/Mehmet/Burak)
      3. multi-voice ElevenLabs + ffmpeg concat → archive/{date}/00-brief.mp3

    Idempotent: 00-brief.mp3 zaten varsa cache döner. Lockfile pattern
    (.audio.lock) deep_analyze.audio_only ile simetrik.

    Returns: {"status": "done"|"already_exists"|"in_progress"|"brief_missing"|
              "failed", "audio_url"?, "bytes"?, "detail"?}
    """
    target_date = date or _today_iso()
    if not looks_like_date(target_date):
        return {"status": "failed", "detail": f"invalid date: {target_date!r}"}
    target_dir = archive_root / target_date
    brief_path = target_dir / "00-brief.md"
    if not brief_path.is_file():
        return {"status": "brief_missing", "detail": f"no brief for {target_date}"}

    audio_path = target_dir / "00-brief.mp3"
    if audio_path.is_file():
        return {
            "status": "already_exists",
            "audio_url": f"/archive/{target_date}/00-brief.mp3",
            "bytes": audio_path.stat().st_size,
        }

    audio_lock = target_dir / ".audio.lock"
    if audio_lock.is_file():
        try:
            data = json.loads(audio_lock.read_text(encoding="utf-8"))
            started = datetime.fromisoformat(data["started_at"])
            elapsed = (datetime.now(UTC) - started).total_seconds()
            if elapsed < LOCKFILE_STALE_SECONDS:
                return {"status": "in_progress", "elapsed_sec": int(elapsed)}
            audio_lock.unlink(missing_ok=True)
        except (json.JSONDecodeError, KeyError, ValueError):
            audio_lock.unlink(missing_ok=True)

    try:
        fd = os.open(str(audio_lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"started_at": _now_iso(), "pid": os.getpid()}, f)
    except FileExistsError:
        return {"status": "in_progress"}

    try:
        log.info("brief_audio.start", date=target_date)
        brief_md = brief_path.read_text(encoding="utf-8")
        # Phase 32-ii: 3-konuşmacı podcast format (Filiz/Mehmet/Burak)
        # Format TR tarih için python tarafında render: "{gün} {ay} {yıl} {haftagünü}"
        date_tr = _format_date_tr(target_date)
        prompt = render(
            load_prompt("brief_podcast_script"),
            date=date_tr,
            brief_md=brief_md,
        )
        audio_script_raw = (await synthesize_with_claude(prompt)).strip()
        if not audio_script_raw:
            raise RuntimeError("brief_audio: claude empty output")

        # JSON dialog parse
        dialog = _parse_podcast_dialog(audio_script_raw)
        if not dialog:
            raise RuntimeError(
                "brief_audio: podcast JSON ayrıştırılamadı; "
                f"ham çıktı önizleme: {audio_script_raw[:200]!r}"
            )

        # Debug için JSON script'i kaydet
        script_path = target_dir / "00-brief.audio.json"
        tmp_script = script_path.with_suffix(script_path.suffix + ".tmp")
        tmp_script.write_text(json.dumps(dialog, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp_script), str(script_path))

        from llm.tts import (
            PODCAST_VOICES_ELEVENLABS_BRIEF,
            get_active_voice_mapping,
            synthesize_podcast,
        )

        # Phase 35-i: ElevenLabs-only TTS (Edge/XTTS path'leri silindi).
        # Voice'lar /voices sayfasından override edilebilir.
        elevenlabs_active = get_active_voice_mapping(
            provider="elevenlabs",
            role="brief",
            default_mapping=PODCAST_VOICES_ELEVENLABS_BRIEF,
        )
        await synthesize_podcast(
            dialog=dialog,
            output_path=audio_path,
            voices=elevenlabs_active,
        )
        audio_bytes = audio_path.stat().st_size

        log.info(
            "brief_audio.done",
            date=target_date,
            bytes=audio_bytes,
            segments=len(dialog),
        )
        return {
            "status": "done",
            "audio_url": f"/archive/{target_date}/00-brief.mp3",
            "bytes": audio_bytes,
            "segments": len(dialog),
        }
    except Exception as e:
        err = str(e)[:500]
        log.error("brief_audio.failed", date=target_date, err=err[:200])
        return {"status": "failed", "detail": err}
    finally:
        audio_lock.unlink(missing_ok=True)


# ── Phase 32-ii: Podcast yardımcıları ───────────────────────────────


_TR_MONTHS = (
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)
_TR_WEEKDAYS = (
    "Pazartesi",
    "Salı",
    "Çarşamba",
    "Perşembe",
    "Cuma",
    "Cumartesi",
    "Pazar",
)


def _format_date_tr(iso_date: str) -> str:
    """``2026-05-17`` → ``"17 Mayıs 2026 Pazar"``.

    TTS prompt'una verilince sayısal tarih okunmasını önler.
    """
    try:
        from datetime import date as _date

        d = _date.fromisoformat(iso_date)
    except ValueError:
        return iso_date
    return f"{d.day} {_TR_MONTHS[d.month - 1]} {d.year} {_TR_WEEKDAYS[d.weekday()]}"


def _parse_podcast_dialog(raw: str) -> list[dict[str, str]]:
    """LLM çıktısından JSON dialog array çıkar.

    Tolerant parser:
      1. Direkt json.loads dene.
      2. ```json ... ``` code block içindeyse içeriği çek.
      3. İlk `[` ile son `]` arası substring'i dene.
      4. Yine başarısızsa boş liste.

    Her satırda speaker + text zorunlu; eksik satırlar atılır.
    """
    candidates: list[str] = [raw.strip()]
    # Code block içeriyse
    if "```" in raw:
        parts = raw.split("```")
        for p in parts:
            stripped = p.strip()
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                candidates.append(stripped)
    # [ ... ] substring
    if "[" in raw and "]" in raw:
        first = raw.find("[")
        last = raw.rfind("]")
        if first < last:
            candidates.append(raw[first : last + 1])

    for c in candidates:
        try:
            data = json.loads(c)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, list):
            continue
        dialog: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            speaker = str(item.get("speaker") or "").strip()
            text = str(item.get("text") or "").strip()
            if speaker and text:
                dialog.append({"speaker": speaker, "text": text})
        if dialog:
            return dialog
    return []
