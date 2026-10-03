"""Phase 14: deep-dive analyze orchestrator.

`POST /api/analyze/deep` çağrısı bir URL alır, türüne göre heavy fetch
yapar (yt-dlp transcript / repomix dump / arxiv abstract), claude
CLI'ya prompt'la birlikte verir, sonucu ``archive/deep/{job_id}/``
altına atomik yazar. Endpoint 202 Accepted döner; UI ``GET
/api/analyze/deep/{job_id}`` ile polling yapar.

State machine (filesystem-authoritative):
- ``not_found``: dizin/result yok, `.lock` yok → hiç başlamamış.
- ``running``: ``.lock`` taze (<10 dk).
- ``done``: ``result.md`` var.
- ``failed``: ``.last-error.txt`` var, ``result.md`` yok.

Job_id deterministic SHA256(url|type)[:16] — aynı URL ikinci defa istense
mevcut cache'i döner (force=True yeniden üretmek için).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from llm.claude_client import synthesize_with_claude
from llm.prompts import load_prompt, render

from rasathane_mcp.core.paths import ARCHIVE_ROOT

log = structlog.get_logger()

# Phase 36-ii: module-level DEEP_DIR sabit — test'ler monkeypatch ile ezer,
# audio_only() bu sabite göre target_dir hesaplar.
DEEP_DIR: Path = ARCHIVE_ROOT / "deep"

LOCKFILE_NAME = ".lock"
LAST_ERROR_NAME = ".last-error.txt"
META_NAME = "meta.json"
RESULT_NAME = "result.md"  # GitHub/arXiv tek-shot çıktı
# Phase 17-i: YouTube için multi-artifact çıktı seti
SUMMARY_NAME = "summary.md"  # primary artifact (analiz)
TRANSCRIPT_NAME = "transcript.md"  # claude-cleaned readable transcript
MINDMAP_NAME = "mindmap.html"  # Phase 17-ii
AUDIO_NAME = "audio.mp3"  # Phase 17-iii
LOCKFILE_STALE_SECONDS = 1200  # 20 dk; multi-stage YouTube ~5-8 dk beklenebilir
REPOMIX_CHAR_CEILING = 200_000  # Claude prompt'u ~250K civarı sığdırır
ARXIV_PDF_CHAR_CEILING = 150_000  # Phase 25-ii: ~50-80k tipik, 150k güvenli
ARXIV_PDF_TIMEOUT_SECONDS = 30  # Heavy fetch — ama tek http GET, fast fail
SUPPORTED_TYPES = ("youtube", "github", "arxiv")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def detect_url_type(url: str) -> str:
    lower = url.lower()
    if "youtube.com" in lower or "youtu.be" in lower:
        return "youtube"
    if "github.com" in lower:
        return "github"
    if "arxiv.org" in lower:
        return "arxiv"
    return "unknown"


def compute_job_id(url: str, detected_type: str) -> str:
    """Deterministic 16-hex job_id; aynı URL+type → aynı job_id (cache key)."""
    digest = hashlib.sha256(f"{detected_type}|{url}".encode()).hexdigest()
    return digest[:16]


def job_dir(*, archive_root: Path, job_id: str) -> Path:
    return archive_root / "deep" / job_id


def _primary_artifact_path(target_dir: Path) -> Path | None:
    """Hangi dosya 'done' işareti? YouTube → summary.md, others → result.md.

    Geriye uyumluluk: eski jobs result.md ile bitti — fallback olarak
    o da 'done' sayılır.
    """
    summary = target_dir / SUMMARY_NAME
    if summary.is_file():
        return summary
    legacy = target_dir / RESULT_NAME
    if legacy.is_file():
        return legacy
    return None


def _list_artifacts(target_dir: Path) -> dict[str, str]:
    """Bu job için var olan artifact'lerin web-erişilebilir URL'leri.

    UI bunları doğrudan iframe / audio src olarak kullanabilsin.
    Yol şeması: /archive/deep/{job_id}/{filename}.
    Yalnız var olan dosyalar listelenir.
    """
    artifacts: dict[str, str] = {}
    job_id = target_dir.name
    base = f"/archive/deep/{job_id}"
    for key, fname in (
        ("summary", SUMMARY_NAME),
        ("transcript", TRANSCRIPT_NAME),
        ("mindmap", MINDMAP_NAME),
        ("audio", AUDIO_NAME),
        ("legacy_result", RESULT_NAME),
    ):
        if (target_dir / fname).is_file():
            artifacts[key] = f"{base}/{fname}"
    return artifacts


def _is_running(target_dir: Path) -> bool:
    """Lockfile taze mi? (Phase 23: delete_job + list_all_jobs ortak kullanır.)"""
    lockfile = target_dir / LOCKFILE_NAME
    if not lockfile.is_file():
        return False
    try:
        data = json.loads(lockfile.read_text(encoding="utf-8"))
        started = datetime.fromisoformat(data["started_at"])
        elapsed = (datetime.now(UTC) - started).total_seconds()
        return elapsed < LOCKFILE_STALE_SECONDS
    except (json.JSONDecodeError, KeyError, ValueError):
        return False


def list_all_jobs(*, archive_root: Path) -> list[dict[str, Any]]:
    """Phase 23: ``archive/deep/`` altındaki tüm job dizinlerini listele.

    Filesystem-only — DB'ye dokunmaz. Endpoint katmanı `in_library`
    bilgisini ayrıca compose eder. Her job için lookup_status'tan dönen
    payload'la aynı shape (status, artifacts, meta) + "modified_at"
    sıralama ipucu eklenir. Liste mtime DESC sıralı (en yeni üstte).

    `.tmp/` gibi rezerve dizinler atlanır. job_id formatı 16 hex değilse
    (manuel oluşturulmuş klasör) yine listelenir — UI'da görünür ki
    kullanıcı el ile temizleyebilsin.
    """
    deep_root = archive_root / "deep"
    if not deep_root.is_dir():
        return []

    jobs: list[dict[str, Any]] = []
    for entry in deep_root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue  # .tmp/ ve diğer dot-prefixed
        job_id = entry.name
        status = lookup_status(archive_root=archive_root, job_id=job_id)
        # Sıralama için "modified_at": primary artifact mtime > meta mtime > dir mtime
        primary = _primary_artifact_path(entry)
        meta_path = entry / META_NAME
        if primary is not None:
            mtime = primary.stat().st_mtime
        elif meta_path.is_file():
            mtime = meta_path.stat().st_mtime
        else:
            mtime = entry.stat().st_mtime
        modified_at = datetime.fromtimestamp(mtime, UTC).isoformat()

        # UI rendering kolaylığı: artifact varlığını bool flag'lere indir
        artifacts = status.get("artifacts", {})
        meta = status.get("meta") or {}
        # "result" alanı listede gerekmez (kart UI özetlenmiş gösterir)
        status.pop("result", None)
        jobs.append(
            {
                **status,
                "url": meta.get("url"),
                "type": meta.get("type", "unknown"),
                "title": meta.get("title"),
                "channel": meta.get("channel"),
                "modified_at": modified_at,
                "has_summary": "summary" in artifacts,
                "has_transcript": "transcript" in artifacts,
                "has_mindmap": "mindmap" in artifacts,
                "has_audio": "audio" in artifacts,
                "has_legacy_result": "legacy_result" in artifacts,
            }
        )

    jobs.sort(key=lambda j: j["modified_at"], reverse=True)
    return jobs


_TAGS_COMMENT_RE = re.compile(
    r"<!--\s*TAGS\s*:\s*(?P<tags>[^>]+?)\s*-->",
    re.IGNORECASE,
)


def extract_tags_from_summary(md: str) -> list[str]:
    """Phase 32-v.3: Summary markdown'ından ``<!-- TAGS: ... -->`` parse.

    Claude summary prompt'una eklenen HTML comment direktifinden tag
    listesini çıkar. Boş, çok kısa veya çok uzun etiketler atlanır.
    Lowercase + whitespace-strip + dedupe.

    Returns:
        [] eğer hiç tag bulunamadıysa veya parse fail. List of unique
        tag strings (alfabetik değil, kaynaktaki sıra korunur).
    """
    if not md:
        return []
    match = _TAGS_COMMENT_RE.search(md)
    if not match:
        return []
    raw = match.group("tags").strip()
    # Comma-separated. Each tag: lowercase, strip, length 2-40.
    candidates = [t.strip() for t in raw.split(",")]
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        # Köşeli paren / quote / tire stripping
        clean = c.strip(" \t\n\"'<>").lower()
        if not (2 <= len(clean) <= 40):
            continue
        if clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _collect_analyzed_urls(archive_root: Path) -> set[str]:
    """Tüm deep job meta.json'larından analiz edilmiş URL'leri topla.

    URL eşleştirme için kullanılır (`list_unanalyzed_youtube_videos`).
    Filesystem-only — DB sorgusu yok.
    """
    deep_root = archive_root / "deep"
    if not deep_root.is_dir():
        return set()
    urls: set[str] = set()
    for entry in deep_root.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        meta_path = entry / META_NAME
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            url = meta.get("url")
            if url:
                urls.add(url.strip())
        except (OSError, json.JSONDecodeError):
            continue
    return urls


async def list_unanalyzed_youtube_videos(
    session: Any,
    *,
    archive_root: Path,
    limit: int = 20,
    days: int = 14,
) -> list[dict[str, Any]]:
    """Phase 32-v.3: Henüz deep-analyze edilmemiş YouTube videolarını listele.

    DB'den son ``days`` gün içinde fetch edilmiş, source.type=``youtube_channel``
    olan article'ları al; deep job meta.json'larındaki URL set'inden ÇIKAR.
    Kalan = henüz analiz edilmemiş yeni videolar.

    Analyze sayfasında "Yeni Videolar" panelinde gösterilir — kullanıcı
    tek tıkla analiz tetikleyebilir.

    Returns:
        list of {url, title, channel_name, published_at, fetched_at}
        en yeni önce, max ``limit``.
    """
    from datetime import timedelta

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from store.models import Article

    since = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        select(Article)
        .options(selectinload(Article.source))
        .where(Article.fetched_at >= since)
        .order_by(Article.fetched_at.desc())
        .limit(limit * 3)  # buffer — filter sonrası limit'e indir
    )
    result = await session.execute(stmt)
    articles = result.scalars().all()

    analyzed_urls = _collect_analyzed_urls(archive_root)

    out: list[dict[str, Any]] = []
    for art in articles:
        if art.source.type != "youtube_channel":
            continue
        if art.url in analyzed_urls:
            continue
        out.append(
            {
                "url": art.url,
                "title": art.title,
                "channel_name": art.source.name,
                "published_at": art.published_at.isoformat() if art.published_at else None,
                "fetched_at": art.fetched_at.isoformat() if art.fetched_at else None,
            }
        )
        if len(out) >= limit:
            break
    return out


def delete_job(*, archive_root: Path, job_id: str) -> str:
    """Phase 23: bir deep-dive job dizinini kalıcı sil.

    Returns: ``"deleted"`` | ``"not_found"`` | ``"running"``.

    Running durumda silmeyi reddediyoruz — arka plan task'i yarı yazılmış
    dosyaya rename yapmaya çalışırsa parent dir yok diye crash eder. UI
    "running" job için sil butonunu disabled gösterir; bu 409 kontrolü
    defensive.
    """
    target_dir = job_dir(archive_root=archive_root, job_id=job_id)
    if not target_dir.is_dir():
        return "not_found"
    if _is_running(target_dir):
        return "running"

    import shutil

    shutil.rmtree(target_dir)
    return "deleted"


def lookup_status(*, archive_root: Path, job_id: str) -> dict[str, Any]:
    """Filesystem'i okur; state machine payload'u döndürür.

    Sözleşme:
    - ``status: "not_found"`` → hiç başlamamış (dizin yok)
    - ``status: "running"`` → lockfile taze
    - ``status: "done"`` → primary artifact (summary.md veya legacy result.md) var
    - ``status: "failed"`` → last-error.txt var, primary artifact yok

    Phase 17-i: ``artifacts`` alanı her artifact'in URL'sini içerir
    (transcript / mindmap / audio için UI doğrudan link verir).
    """
    target_dir = job_dir(archive_root=archive_root, job_id=job_id)
    if not target_dir.is_dir():
        return {"job_id": job_id, "status": "not_found"}

    lockfile = target_dir / LOCKFILE_NAME
    last_error_path = target_dir / LAST_ERROR_NAME
    meta_path = target_dir / META_NAME

    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}

    artifacts = _list_artifacts(target_dir)

    # Running? (taze lockfile)
    if lockfile.is_file():
        try:
            lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
            started_at = datetime.fromisoformat(lock_data["started_at"])
            elapsed = int((datetime.now(UTC) - started_at).total_seconds())
            if elapsed < LOCKFILE_STALE_SECONDS:
                return {
                    "job_id": job_id,
                    "status": "running",
                    "started_at": lock_data["started_at"],
                    "elapsed_sec": elapsed,
                    "stage": lock_data.get("stage"),
                    "meta": meta,
                    "artifacts": artifacts,
                }
        except (json.JSONDecodeError, KeyError, ValueError):
            pass  # Bozuk lockfile; cleanup yapsın acquire

    # Done?
    primary = _primary_artifact_path(target_dir)
    if primary is not None:
        result_md = primary.read_text(encoding="utf-8")
        # Phase 32-v.3: tags ya meta'da kayıtlı ya da summary'den parse et.
        # Tek-seferlik lazy compute — ileride meta'ya kaydedilebilir.
        if "tags" not in meta:
            parsed_tags = extract_tags_from_summary(result_md)
            if parsed_tags:
                meta = {**meta, "tags": parsed_tags}
        return {
            "job_id": job_id,
            "status": "done",
            "result": result_md,
            "generated_at": datetime.fromtimestamp(primary.stat().st_mtime, UTC).isoformat(),
            "meta": meta,
            "artifacts": artifacts,
        }

    # Failed?
    if last_error_path.is_file():
        return {
            "job_id": job_id,
            "status": "failed",
            "error": last_error_path.read_text(encoding="utf-8")[:500],
            "meta": meta,
            "artifacts": artifacts,
        }

    return {"job_id": job_id, "status": "not_found", "meta": meta, "artifacts": artifacts}


def _acquire_lockfile(target_dir: Path, *, url: str, detected_type: str) -> Path:
    """Atomik lockfile create. Stale ise temizle, fresh ise FileExistsError raise.

    Pattern brief.py'den; meta.json'a url+type da yazıyoruz ki polling
    geri istemci ne işin tamamlandığını öğrenebilsin (UI title rendering).
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    lockfile = target_dir / LOCKFILE_NAME

    if lockfile.is_file():
        try:
            lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
            started_at = datetime.fromisoformat(lock_data["started_at"])
            elapsed = (datetime.now(UTC) - started_at).total_seconds()
            if elapsed >= LOCKFILE_STALE_SECONDS:
                lockfile.unlink(missing_ok=True)
                log.warning("deep_analyze.stale_lockfile_cleared", elapsed_sec=int(elapsed))
        except (json.JSONDecodeError, KeyError, ValueError):
            lockfile.unlink(missing_ok=True)

    fd = os.open(str(lockfile), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(
            {
                "started_at": _now_iso(),
                "pid": os.getpid(),
                "url": url,
                "type": detected_type,
            },
            f,
        )
    return lockfile


def _write_meta(target_dir: Path, *, url: str, detected_type: str, extra: dict[str, Any]) -> None:
    meta_path = target_dir / META_NAME
    payload = {
        "url": url,
        "type": detected_type,
        "started_at": _now_iso(),
        **extra,
    }
    meta_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# ─── Per-type fetch + prompt build ──────────────────────────────────────


def _atomic_write_text(path: Path, text: str) -> None:
    """Tmp + os.replace pattern — okuyucular yarı-yazılı dosya görmesin."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


def _wrap_markmap_html(markdown_tree: str, *, title: str) -> str:
    """Phase 17-ii / 28-iii / 28-v: markdown ağacı → standalone markmap HTML.

    Phase 28-v: markmap-autoloader kaldırıldı (CDN sürüm uyumsuzluğu —
    SVG render etmiyordu, sessiz fail). Yerine **manuel pipeline**:
    d3 + markmap-view + markmap-lib + markmap-toolbar explicit yüklenir,
    `Transformer.transform(md)` ile YAML frontmatter ve markdown parse
    edilir, `Markmap.create()` ile SVG'ye mount edilir. Toolbar render
    sonrası eklenir. Manuel pipeline kütüphane sürüm değişikliklerinden
    etkilenmez.

    Frontmatter (`---\\nmarkmap:\\n  maxWidth: 320\\n...`) markmap-lib
    Transformer'ı tarafından otomatik parse edilir — features.markmap
    Markmap.create options'a feed olur.
    """
    # `</script>` JS string içine düşmesin (template script tag erken kapanmasın)
    safe_md = markdown_tree.replace("</script>", "<\\/script>")
    safe_title = (title or "Zihin Haritası").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<title>{safe_title} · Zihin Haritası</title>
<style>
  html, body {{
    margin: 0; padding: 0; height: 100%;
    background: linear-gradient(135deg, #faf6ec 0%, #f0e9d8 100%);
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  }}
  #mindmap {{ width: 100%; height: 100%; }}
  /* NotebookLM benzeri yumuşak node görünümü */
  .markmap-node text {{
    font-family: 'Segoe UI', system-ui, sans-serif !important;
    font-size: 13px !important;
  }}
  .markmap-node-circle {{ stroke-width: 1.5px; }}
  .markmap-node-text strong {{ font-weight: 600; }}
  .header {{
    position: absolute; top: 12px; left: 16px; right: 16px; pointer-events: none;
    color: #5a4a32; font-size: 12px; font-weight: 500;
    z-index: 2;
  }}
  .header strong {{ color: #2e2418; font-weight: 600; }}
  .mm-toolbar {{
    position: absolute; bottom: 16px; right: 16px;
    background: rgba(255,255,255,0.9);
    border: 1px solid #d8c9a6;
    border-radius: 8px;
    padding: 4px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    z-index: 2;
  }}
  .mm-error {{
    position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
    color: #b54b3a; font-family: monospace; font-size: 13px;
    background: #fff8f5; border: 1px solid #f0c8be; border-radius: 6px;
    padding: 12px 18px; max-width: 80%;
  }}
</style>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/markmap-toolbar@0.18/dist/style.css">
</head>
<body>
<div class="header">
  Rasathane · zihin haritası — <strong>{safe_title}</strong>
</div>
<svg id="mindmap"></svg>
<div class="mm-toolbar" id="mm-toolbar"></div>
<!-- Phase 28-v: markdown'ı script template'inde tut. Backtick/dollar
     escape gerektirmez (browser script tag textContent'ini raw döner).
     Tek escape: </script> kapanışı (üstte zaten yapıldı). -->
<script type="text/template" id="mm-md">
{safe_md}
</script>
<!-- ESM modules — UMD bundle'ların window.markmap namespace çakışması
     yerine her paket kendi import scope'unda. esm.run jsdelivr'ın ESM
     bundle servisi (https://www.jsdelivr.com/esm); paketleri otomatik
     ESM'e dönüştürür ve dependency graph'ı resolve eder. -->
<script type="module">
  try {{
    const [{{ Transformer }}, {{ Markmap }}, {{ Toolbar }}] = await Promise.all([
      import('https://cdn.jsdelivr.net/npm/markmap-lib@0.18/+esm'),
      import('https://cdn.jsdelivr.net/npm/markmap-view@0.18/+esm'),
      import('https://cdn.jsdelivr.net/npm/markmap-toolbar@0.18/+esm'),
    ]);
    const md = document.getElementById('mm-md').textContent;
    const transformer = new Transformer();
    const {{ root, frontmatter }} = transformer.transform(md);
    // Frontmatter `markmap:` bloğunu options'a ver; bizim default'lar
    // frontmatter ile override edilir.
    const fmOpts = (frontmatter && frontmatter.markmap) || {{}};
    const opts = Object.assign({{
      duration: 500,
      maxWidth: 320,
      initialExpandLevel: 2,
      colorFreezeLevel: 2,
    }}, fmOpts);
    const svg = document.getElementById('mindmap');
    const mm = Markmap.create(svg, opts, root);
    window.__mmInstance = mm;
    // Toolbar
    const t = Toolbar.create(mm);
    if (typeof t.setBrand === 'function') t.setBrand(false);
    document.getElementById('mm-toolbar').appendChild(t.el);
  }} catch (e) {{
    console.error('markmap render failed', e);
    const err = document.createElement('div');
    err.className = 'mm-error';
    err.textContent = 'Zihin haritası render hatası: ' + (e && e.message || e);
    document.body.appendChild(err);
  }}
</script>
</body>
</html>
"""


async def _run_youtube_artifacts(
    url: str,
    *,
    target_dir: Path,
    update_lock_stage: Callable[[str], None] | None = None,
    use_whisper: bool = False,
) -> dict[str, Any]:
    """Phase 21-i: YouTube için 3-stage core pipeline (audio ayrıldı).

    Aşamalar (sıralı, claude rate limit için):
      1. fetch_metadata + transcript (yt-dlp altyazı; whisper API fallback)
      2. transcript_clean → transcript.md
      3. summary → summary.md
      4. mindmap → mindmap.html

    Audio stage ayrıldı (Phase 21-i): kullanıcı "🔊 Sesli özet üret" butonuyla
    ayrıca tetikler — POST /api/analyze/deep/{job_id}/audio endpoint'i.

    Phase 27: tasarım kuralı — **altyazı önce, whisper opt-in**.
    yt-dlp video'nun orijinal dilinde altyazı çeker (manuel > auto;
    orig > en > tr priority). Çoğu teknik/akademik video'da altyazı
    var → claude o transkripte göre **Türkçe** analiz üretir. Whisper
    sadece ``use_whisper=True`` ise devreye girer (manuel checkbox);
    ``WHISPER_API_URL`` env varsa bile **otomatik aktif değil** çünkü
    transcribe maliyeti gereksiz olabilir.

    use_whisper: kullanıcı UI'da checkbox'ı işaretledi mi? Default
                 False — altyazı yoksa hata + whisper aktivasyon rehberi.
    """
    from ingestion.youtube import fetch_metadata, fetch_subs_via_ytdlp, fetch_transcript

    meta = await fetch_metadata(url)
    if use_whisper:
        # Manuel opt-in: yt-dlp altyazı dene, yoksa whisper API/lokal'e düş
        transcript = await fetch_transcript(url)
    else:
        # Default hızlı yol: yalnız altyazı; yoksa hata
        transcript = await fetch_subs_via_ytdlp(url)
    if transcript is None or not transcript.text.strip():
        if use_whisper:
            raise RuntimeError(
                "transcript_unavailable: altyazı yok + whisper transcription da başarısız."
            )
        raise RuntimeError(
            "transcript_unavailable: bu video için altyazı bulunamadı "
            "(orijinal dil + İngilizce + Türkçe denendi). Sesi indirip "
            "whisper ile çevirmek için 'Whisper kullan' seçeneğini "
            "işaretleyip yeniden deneyin (~30-60 sn, GPU hazır)."
        )

    duration_min = f"{meta.duration_seconds // 60}" if meta.duration_seconds else "?"
    title = meta.title or "(başlıksız)"
    channel = meta.channel or "(bilinmiyor)"

    # Stage A: transcript clean. Phase 29 → local LLM (gemma-4-26b-a4b/qwen3:8b)
    # 100K+ char input'ta heavy bootstrap timeout'unu çözmüştü, ama 1h47m TR
    # video'da (88K token) instruction non-compliance: prompt "özetleme, anlamı
    # kısaltma" derken model 355K → 6K (60x kompresyon) özet üretti. 262K
    # context window overflow değil — long-context modellerin "özet üretme
    # prior'ı talimatı eziyor" patolojisi. Claude'a geri taşındı (Phase 29
    # hardening flag'leri heavy bootstrap'ı zaten çözüyor; long-context
    # instruction-following Claude'da kuvvetli).
    if update_lock_stage:
        update_lock_stage("transcript_clean")
    log.info("youtube.stage.transcript_clean", url=url, raw_chars=len(transcript.text))
    clean_prompt = render(
        load_prompt("youtube_transcript_clean"),
        title=title,
        channel=channel,
        transcript=transcript.text,
    )
    clean_md = (await synthesize_with_claude(clean_prompt)).strip()
    if not clean_md:
        raise RuntimeError("transcript_clean: claude empty output")
    _atomic_write_text(target_dir / TRANSCRIPT_NAME, clean_md)

    # Stage B: summary
    if update_lock_stage:
        update_lock_stage("summary")
    log.info("youtube.stage.summary", url=url, clean_chars=len(clean_md))
    summary_prompt = render(
        load_prompt("youtube_summary"),
        title=title,
        channel=channel,
        duration_minutes=duration_min,
        transcript=clean_md,  # cleaned'i kullan — daha kısa, daha kaliteli özet
    )
    summary_md = (await synthesize_with_claude(summary_prompt)).strip()
    if not summary_md:
        raise RuntimeError("summary: claude empty output")
    _atomic_write_text(target_dir / SUMMARY_NAME, summary_md)

    # Phase 28-ii: mindmap stage'i kaldırıldı — artık ayrı buton
    # (`run_mindmap_only_for_existing_job`). Default core pipeline:
    # transcript_clean + summary; mindmap kullanıcı talebine bırakıldı.
    return {
        "title": meta.title,
        "channel": meta.channel,
        "video_id": meta.video_id,
        "transcript_source": transcript.source,
        "transcript_raw_chars": len(transcript.text),
        "transcript_clean_chars": len(clean_md),
        "summary_chars": len(summary_md),
        "mindmap_chars": 0,  # legacy field for compat — 0 = not generated
    }


async def _run_youtube_mindmap_only(
    *,
    target_dir: Path,
    title: str,
    channel: str,
    clean_md: str,
    update_lock_stage: Callable[[str], None] | None,
) -> dict[str, int]:
    """Phase 21-i: YouTube core pipeline'da yalnız mindmap stage'i.

    Audio Phase 21-i'de ayrı endpoint'e (`/audio`) taşındı — kullanıcı
    "🔊 Sesli özet üret" butonuyla manuel tetikler. YouTube prompt'ları
    `{{transcript}}` placeholder kullanır (Phase 17-ii spec'i).
    """
    # Mindmap stage
    if update_lock_stage:
        update_lock_stage("mindmap")
    log.info("youtube.stage.mindmap")
    mindmap_chars = 0
    try:
        mindmap_prompt = render(
            load_prompt("youtube_mindmap"),
            title=title,
            channel=channel,
            transcript=clean_md,
        )
        mindmap_md = (await synthesize_with_claude(mindmap_prompt)).strip()
        if mindmap_md:
            if mindmap_md.startswith("```"):
                mindmap_md = "\n".join(
                    line for line in mindmap_md.split("\n") if not line.startswith("```")
                ).strip()
            mindmap_html = _wrap_markmap_html(mindmap_md, title=title)
            _atomic_write_text(target_dir / MINDMAP_NAME, mindmap_html)
            mindmap_chars = len(mindmap_md)
        else:
            log.warning("youtube.stage.mindmap.empty")
    except Exception as e:
        log.error("youtube.stage.mindmap.failed", err=str(e)[:200])

    return {"mindmap_chars": mindmap_chars}


async def _run_github_artifacts(
    url: str,
    *,
    target_dir: Path,
    archive_root: Path,
    update_lock_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Phase 18-i: GitHub için 3-stage pipeline (summary + mindmap + audio).

    Stage A: fetch_repo_metadata + run_repomix (heavy fetch — yt-dlp
    pendant). Stage B: summary prompt (eski deep_analyze_github →
    github_summary). Stage C+D: ortak mindmap+audio helper.
    """
    from ingestion.github import fetch_repo_metadata, run_repomix

    # Stage A: heavy fetch
    if update_lock_stage:
        update_lock_stage("fetch_repo")
    log.info("github.stage.fetch", url=url)
    repo = await fetch_repo_metadata(url)

    dump_path = archive_root / "deep" / ".tmp" / f"repomix-{repo.full_name.replace('/', '_')}.txt"
    project_root = archive_root.parent
    await run_repomix(url, output_path=dump_path, project_root=project_root, timeout_seconds=600)
    raw = dump_path.read_text(encoding="utf-8", errors="replace")
    truncated = len(raw) > REPOMIX_CHAR_CEILING
    repomix_text = raw[:REPOMIX_CHAR_CEILING]
    if truncated:
        repomix_text += (
            f"\n\n[NOT: dump {len(raw):,} karakter idi, ilk {REPOMIX_CHAR_CEILING:,} "
            "karaktere kırpıldı. Üst seviye dosyalar ve README öncelikli.]"
        )

    # Stage B: summary
    if update_lock_stage:
        update_lock_stage("summary")
    log.info("github.stage.summary", url=url)
    summary_prompt = render(
        load_prompt("github_summary"),
        full_name=repo.full_name,
        description=repo.description or "(açıklama yok)",
        primary_language=repo.primary_language or "(belirsiz)",
        stars=str(repo.stars),
        forks=str(repo.forks),
        repomix_dump=repomix_text,
    )
    summary_md = (await synthesize_with_claude(summary_prompt)).strip()
    if not summary_md:
        raise RuntimeError("github summary: claude empty output")
    _atomic_write_text(target_dir / SUMMARY_NAME, summary_md)

    # Phase 28-ii: mindmap stage kaldırıldı — ayrı buton (run_mindmap_only)
    return {
        "full_name": repo.full_name,
        "stars": repo.stars,
        "primary_language": repo.primary_language,
        "repomix_chars_raw": len(raw),
        "repomix_truncated": truncated,
        "summary_chars": len(summary_md),
        "mindmap_chars": 0,
    }


async def fetch_arxiv_pdf_text(arxiv_id: str) -> str | None:
    """Phase 25-ii: arXiv PDF'i indir + pypdf ile metin çıkar.

    Best-effort: network/PDF parse fail durumunda None döner.
    ``ARXIV_PDF_CHAR_CEILING`` ile prompt bloat'ından korunur.

    pypdf senkron — `asyncio.to_thread` ile sarmalanır ki HTTP server
    eventloop'u bloke olmasın.
    """
    import asyncio

    import httpx as _httpx

    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    try:
        async with _httpx.AsyncClient(
            timeout=ARXIV_PDF_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            resp = await client.get(pdf_url)
            resp.raise_for_status()
            pdf_bytes = resp.content
    except Exception as exc:
        log.warning(
            "arxiv.pdf.fetch_failed",
            arxiv_id=arxiv_id,
            err=str(exc)[:200],
        )
        return None

    def _extract_sync(data: bytes) -> str | None:
        from io import BytesIO

        from pypdf import PdfReader
        from pypdf.errors import PyPdfError

        try:
            reader = PdfReader(BytesIO(data))
            chunks = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(chunks)
        except (PyPdfError, ValueError, KeyError) as e:
            log.warning("arxiv.pdf.parse_failed", err=str(e)[:200])
            return None

    text = await asyncio.to_thread(_extract_sync, pdf_bytes)
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    if len(text) > ARXIV_PDF_CHAR_CEILING:
        text = (
            text[:ARXIV_PDF_CHAR_CEILING] + f"\n\n[NOT: PDF metni {len(text):,} karakter idi, "
            f"ilk {ARXIV_PDF_CHAR_CEILING:,} karaktere kırpıldı.]"
        )
    return text


async def _run_arxiv_artifacts(
    url: str,
    *,
    target_dir: Path,
    update_lock_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Phase 18-ii: arXiv için 3-stage pipeline.

    Stage A: Atom API'den abstract çek. Stage B: summary prompt
    (deep_analyze_arxiv → arxiv_summary). Stage C+D: ortak helper.
    """
    import re as _re
    import xml.etree.ElementTree as _ET  # noqa: N814

    import httpx as _httpx

    # Stage A: fetch abstract
    if update_lock_stage:
        update_lock_stage("fetch_abstract")
    m = _re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", url)
    if not m:
        raise RuntimeError(f"arxiv_id_parse_failed: {url}")
    arxiv_id = m.group(1).removesuffix(".pdf")

    # Phase 27.5: arxiv.org 2024+ HTTP→HTTPS zorunlu redirect veriyor.
    # https:// doğrudan + follow_redirects=True (defansif).
    # Phase 27.5b: arxiv API rate-limit (1 req / 3 sn) → 429 alırsa
    # exponential backoff + descriptive User-Agent (arxiv "respectful
    # client" politikası — UA'sız client'lar daha sıkı throttle edilir).
    import asyncio as _asyncio

    api_url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
    headers = {
        "User-Agent": "Rasathane/1.0 (https://github.com/aringm/rasathane; nemezis@tutamail.com)"
    }
    async with _httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as c:
        # 3 deneme, exponential backoff: 0 / 5 / 15 sn
        delays = (0, 5, 15)
        last_resp = None
        for attempt, delay in enumerate(delays):
            if delay:
                log.warning("arxiv.api.retry", attempt=attempt + 1, delay_sec=delay)
                await _asyncio.sleep(delay)
            r = await c.get(api_url)
            last_resp = r
            if r.status_code != 429:
                break
        if last_resp is None or last_resp.status_code == 429:
            raise RuntimeError(
                "arxiv_rate_limited: API 3 denemeden sonra hala 429 — "
                "birkaç dakika sonra tekrar dene (resmi sınır: 1 istek/3 sn)."
            )
        r = last_resp
        r.raise_for_status()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = _ET.fromstring(r.text)
    entry = root.find("a:entry", ns)
    if entry is None:
        raise RuntimeError(f"arxiv_id_not_found: {arxiv_id}")

    title_el = entry.find("a:title", ns)
    summary_el = entry.find("a:summary", ns)
    authors_list = [
        (a_name.text or "").strip()
        for a in entry.findall("a:author", ns)
        if (a_name := a.find("a:name", ns)) is not None
    ]
    title = (title_el.text or "").strip() if title_el is not None else ""
    abstract = (summary_el.text or "").strip() if summary_el is not None else ""
    authors_str = ", ".join(authors_list) or "(yazarlar bilinmiyor)"

    # Stage A.5: full PDF text (best-effort, abstract fallback) — Phase 25-ii
    if update_lock_stage:
        update_lock_stage("fetch_pdf")
    log.info("arxiv.stage.fetch_pdf", arxiv_id=arxiv_id)
    pdf_text = await fetch_arxiv_pdf_text(arxiv_id)
    if pdf_text:
        paper_text = pdf_text
        text_source = "full_pdf"
        log.info("arxiv.pdf.using_full_text", arxiv_id=arxiv_id, chars=len(pdf_text))
    else:
        paper_text = abstract or "(abstract bulunamadı)"
        text_source = "abstract_only"
        log.info("arxiv.pdf.fallback_abstract", arxiv_id=arxiv_id)

    # Stage B: summary
    if update_lock_stage:
        update_lock_stage("summary")
    log.info("arxiv.stage.summary", url=url, arxiv_id=arxiv_id, source=text_source)
    summary_prompt = render(
        load_prompt("arxiv_summary"),
        title=title or "(başlıksız)",
        authors=authors_str,
        arxiv_id=arxiv_id,
        paper_text=paper_text,
    )
    summary_md = (await synthesize_with_claude(summary_prompt)).strip()
    if not summary_md:
        raise RuntimeError("arxiv summary: claude empty output")
    _atomic_write_text(target_dir / SUMMARY_NAME, summary_md)

    # Phase 28-ii: mindmap stage kaldırıldı — ayrı buton (run_mindmap_only)
    return {
        "title": title,
        "authors": authors_list,
        "arxiv_id": arxiv_id,
        "abstract_chars": len(abstract),
        "pdf_chars": len(pdf_text) if pdf_text else 0,
        "text_source": text_source,
        "summary_chars": len(summary_md),
        "mindmap_chars": 0,
    }


async def _generate_mindmap_stage(
    *,
    target_dir: Path,
    prompt_mindmap_name: str,
    title_for_mindmap: str,
    summary_md: str,
    update_lock_stage: Callable[[str], None] | None = None,
    extra_render_vars: dict[str, str] | None = None,
) -> dict[str, int]:
    """Phase 21-i: GitHub/arXiv için mindmap stage'i (audio ayrıldı).

    Audio ayrıca çağrılabilir: `run_audio_only_for_existing_job`. Best-effort
    failure: mindmap fail summary'i invalide etmez.
    """
    extras = extra_render_vars or {}
    if update_lock_stage:
        update_lock_stage("mindmap")
    log.info("deep.stage.mindmap", target=str(target_dir))
    mindmap_chars = 0
    try:
        mindmap_prompt = render(
            load_prompt(prompt_mindmap_name),
            summary=summary_md,
            **extras,
        )
        mindmap_md = (await synthesize_with_claude(mindmap_prompt)).strip()
        if mindmap_md:
            if mindmap_md.startswith("```"):
                mindmap_md = "\n".join(
                    line for line in mindmap_md.split("\n") if not line.startswith("```")
                ).strip()
            mindmap_html = _wrap_markmap_html(mindmap_md, title=title_for_mindmap)
            _atomic_write_text(target_dir / MINDMAP_NAME, mindmap_html)
            mindmap_chars = len(mindmap_md)
        else:
            log.warning("deep.stage.mindmap.empty", target=str(target_dir))
    except Exception as e:
        log.error("deep.stage.mindmap.failed", err=str(e)[:200])

    return {"mindmap_chars": mindmap_chars}


async def run_mindmap_only_for_existing_job(
    *,
    archive_root: Path,
    job_id: str,
) -> dict[str, Any]:
    """Phase 28-ii: mevcut bir deep-dive job'unun zihin haritasını ayrı
    tetikle (audio_only pattern'iyle simetrik).

    Önkoşul: ``archive/deep/{job_id}/summary.md`` (veya legacy ``result.md``)
    var. mindmap.html üretilir. İdempotent: zaten varsa cache döner.

    Phase 28-ii'de core pipeline'dan mindmap stage'i kaldırıldı; artık
    her zaman bu fonksiyon ya da ``POST /api/analyze/deep/{job_id}/mindmap``
    endpoint'iyle tetiklenir. Kullanıcı UI'da "🧠 Zihin haritası üret"
    butonuyla manuel çağırır.

    Returns: {"status": "done" | "already_exists" | "summary_missing" |
              "in_progress" | "failed", ...}
    """
    target_dir = job_dir(archive_root=archive_root, job_id=job_id)
    if not target_dir.is_dir():
        return {"status": "summary_missing", "detail": "job dizini yok"}

    summary_path = target_dir / SUMMARY_NAME
    legacy_path = target_dir / RESULT_NAME
    transcript_path = target_dir / TRANSCRIPT_NAME
    if summary_path.is_file():
        summary_md = summary_path.read_text(encoding="utf-8")
    elif legacy_path.is_file():
        summary_md = legacy_path.read_text(encoding="utf-8")
    else:
        return {"status": "summary_missing", "detail": "summary.md/result.md yok"}

    mindmap_path = target_dir / MINDMAP_NAME
    if mindmap_path.is_file():
        return {
            "status": "already_exists",
            "mindmap_url": f"/archive/deep/{job_id}/{MINDMAP_NAME}",
            "bytes": mindmap_path.stat().st_size,
        }

    # Mindmap için ayrı lockfile
    mm_lock = target_dir / ".mindmap.lock"
    if mm_lock.is_file():
        try:
            data = json.loads(mm_lock.read_text(encoding="utf-8"))
            started = datetime.fromisoformat(data["started_at"])
            elapsed = (datetime.now(UTC) - started).total_seconds()
            if elapsed < LOCKFILE_STALE_SECONDS:
                return {"status": "in_progress", "elapsed_sec": int(elapsed)}
            mm_lock.unlink(missing_ok=True)
        except (json.JSONDecodeError, KeyError, ValueError):
            mm_lock.unlink(missing_ok=True)

    try:
        fd = os.open(str(mm_lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"started_at": _now_iso(), "pid": os.getpid()}, f)
    except FileExistsError:
        return {"status": "in_progress"}

    # Meta'dan tip ve prompt seçimi
    meta: dict[str, Any] = {}
    if (target_dir / META_NAME).is_file():
        try:
            meta = json.loads((target_dir / META_NAME).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}

    detected_type = meta.get("type", "youtube")
    prompt_name = {
        "youtube": "youtube_mindmap",
        "github": "github_mindmap",
        "arxiv": "arxiv_mindmap",
    }.get(detected_type, "youtube_mindmap")
    title = meta.get("title") or "Analiz"

    # YouTube prompt'u {{transcript}} bekler; GitHub/arXiv {{summary}} bekler
    if detected_type == "youtube":
        extras: dict[str, str] = {
            "title": title,
            "channel": meta.get("channel") or "(bilinmiyor)",
            "transcript": (
                transcript_path.read_text(encoding="utf-8")
                if transcript_path.is_file()
                else summary_md
            ),
        }
    elif detected_type == "github":
        extras = {
            "full_name": meta.get("full_name") or title,
            "primary_language": meta.get("primary_language") or "(belirsiz)",
            "summary": summary_md,
        }
    else:  # arxiv
        extras = {
            "title": title,
            "authors": ", ".join(meta.get("authors", []) or ["(bilinmiyor)"]),
            "summary": summary_md,
        }

    try:
        log.info("mindmap_only.start", job_id=job_id, type=detected_type)
        mindmap_prompt = render(load_prompt(prompt_name), **extras)
        mindmap_md = (await synthesize_with_claude(mindmap_prompt)).strip()
        if not mindmap_md:
            raise RuntimeError("mindmap: claude empty output")
        # Markdown fence stripping (claude bazen ```markdown wrap'lar)
        if mindmap_md.startswith("```"):
            mindmap_md = "\n".join(
                line for line in mindmap_md.split("\n") if not line.startswith("```")
            ).strip()
        mindmap_html = _wrap_markmap_html(mindmap_md, title=title)
        _atomic_write_text(mindmap_path, mindmap_html)
        log.info("mindmap_only.done", job_id=job_id, chars=len(mindmap_md))
        return {
            "status": "done",
            "mindmap_url": f"/archive/deep/{job_id}/{MINDMAP_NAME}",
            "mindmap_chars": len(mindmap_md),
            "bytes": mindmap_path.stat().st_size,
        }
    except Exception as e:
        err = str(e) or repr(e) or e.__class__.__name__
        log.error("mindmap_only.failed", job_id=job_id, err=err[:200])
        return {"status": "failed", "detail": err[:500]}
    finally:
        mm_lock.unlink(missing_ok=True)


def _write_audio_meta(
    *,
    target_dir: Path,
    preset: Any,  # AudioPreset — circular import guard for typing
    voices_used: dict[str, dict[str, Any]],
    duration_sec: float | None,
    char_count: int,
) -> None:
    """Phase 36-ii: archive/deep/{job_id}/audio_meta.json yazar/günceller.

    regen_count: ilk üretimde 1; mevcut meta varsa +1 (force=True her çağrı).
    """
    meta_path = target_dir / "audio_meta.json"
    regen_count = 1
    if meta_path.is_file():
        try:
            old = json.loads(meta_path.read_text(encoding="utf-8-sig"))
            regen_count = int(old.get("regen_count", 0)) + 1
        except (json.JSONDecodeError, OSError, ValueError):
            regen_count = 1
    payload = {
        "preset_id": preset.id,
        "preset_name": preset.name,
        "generated_at": datetime.now(UTC).isoformat(),
        "voices_used": {
            speaker: cfg.get("voice_id", "")
            for speaker, cfg in voices_used.items()
        },
        "voice_settings": {
            speaker: {
                k: v for k, v in cfg.items()
                if k in {"stability", "similarity_boost", "style"}
            }
            for speaker, cfg in voices_used.items()
        },
        "duration_sec": duration_sec,
        "char_count": char_count,
        "regen_count": regen_count,
    }
    _atomic_write_text(meta_path, json.dumps(payload, ensure_ascii=False, indent=2))


async def audio_only(
    job_id: str,
    *,
    force: bool = False,
    preset_id: str = "klasik_panel",
) -> dict[str, Any]:
    """Phase 36-ii: preset-driven audio regen.

    `DEEP_DIR / job_id` altındaki summary/transcript'i okur, preset
    çözümler, podcast script üretir, ElevenLabs ile sentezler ve
    `audio_meta.json` sidecar yazar.

    `force=True` — mevcut audio.mp3'ü silip yeniden üretir.
    `preset_id` — `klasik_panel` default; bilinmeyen ID fallback ile
    `klasik_panel`'a düşer.

    Returns: {"status": "done" | "already_exists" | "summary_missing" |
              "in_progress" | "failed", ...}
    """
    target_dir = DEEP_DIR / job_id
    if not target_dir.is_dir():
        return {"status": "summary_missing", "detail": "job dizini yok"}

    # Primary summary'i bul
    summary_path = target_dir / SUMMARY_NAME
    legacy_path = target_dir / RESULT_NAME
    if summary_path.is_file():
        summary_md = summary_path.read_text(encoding="utf-8")
    elif legacy_path.is_file():
        summary_md = legacy_path.read_text(encoding="utf-8")
    else:
        return {"status": "summary_missing", "detail": "summary.md/result.md yok"}

    audio_path = target_dir / AUDIO_NAME
    if audio_path.is_file() and not force:
        return {
            "status": "already_exists",
            "audio_url": f"/archive/deep/{job_id}/{AUDIO_NAME}",
            "bytes": audio_path.stat().st_size,
        }
    if audio_path.is_file() and force:
        audio_path.unlink(missing_ok=True)

    # Audio için ayrı lockfile (core lockfile zaten serbestlemiş olmalı)
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

    # Acquire audio lock
    try:
        fd = os.open(str(audio_lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"started_at": _now_iso(), "pid": os.getpid()}, f)
    except FileExistsError:
        return {"status": "in_progress"}

    # Meta'dan tip + title oku — prompt seçimi için
    meta: dict[str, Any] = {}
    if (target_dir / META_NAME).is_file():
        try:
            meta = json.loads((target_dir / META_NAME).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}

    detected_type = meta.get("type", "youtube")
    prompt_name = {
        "youtube": "youtube_audio_script",
        "github": "github_audio_script",
        "arxiv": "arxiv_audio_script",
    }.get(detected_type, "youtube_audio_script")

    title = meta.get("title") or "Analiz"
    extras: dict[str, str] = {}
    if detected_type == "youtube":
        extras["title"] = title
        extras["channel"] = meta.get("channel") or "(bilinmiyor)"
        # YouTube prompt'u {{transcript}} placeholder kullanır
        # Burada cleaned transcript varsa kullan, yoksa summary
        transcript_path = target_dir / TRANSCRIPT_NAME
        if transcript_path.is_file():
            extras["transcript"] = transcript_path.read_text(encoding="utf-8")
        else:
            extras["transcript"] = summary_md
    elif detected_type == "github":
        extras["full_name"] = meta.get("full_name") or title
        extras["summary"] = summary_md
    else:  # arxiv
        extras["title"] = title
        extras["authors"] = ", ".join(meta.get("authors", []) or ["(bilinmiyor)"])
        extras["summary"] = summary_md

    try:
        log.info("audio_only.start", job_id=job_id, type=detected_type)

        # Phase 32-ii: YouTube için 3-konuşmacı podcast modu (Filiz/Burak/Esra)
        # Phase 36-ii: preset-driven routing (klasik_panel | hizli_brifing | derin_uzman | elestirel_munazara)
        # GitHub ve arXiv için eski tek-spiker akışı korunur (sonraki phase'de
        # genişletilebilir).
        if detected_type == "youtube":
            from llm.presets import resolve_preset

            preset = resolve_preset(preset_id)
            podcast_prompt = render(load_prompt(preset.prompt_variant), **extras)
            raw = (await synthesize_with_claude(podcast_prompt)).strip()
            if not raw:
                raise RuntimeError("audio: claude empty output (podcast)")
            # Brief.py'daki _parse_podcast_dialog'ı reuse et (DRY)
            from rasathane_mcp.core.brief import _parse_podcast_dialog

            dialog = _parse_podcast_dialog(raw)
            if not dialog:
                raise RuntimeError(f"audio: podcast JSON parse failed; preview: {raw[:200]!r}")
            _atomic_write_text(
                target_dir / "audio_script.json",
                json.dumps(dialog, ensure_ascii=False, indent=2),
            )
            from llm.tts import (
                PODCAST_VOICES_ELEVENLABS_YOUTUBE,
                get_active_voice_mapping,
                synthesize_podcast,
            )

            # Phase 35-i: ElevenLabs-only TTS (Edge/XTTS path'leri silindi).
            # Voice'lar /voices sayfasından override edilebilir.
            elevenlabs_active = get_active_voice_mapping(
                provider="elevenlabs",
                role="youtube",
                default_mapping=PODCAST_VOICES_ELEVENLABS_YOUTUBE,
            )
            # Phase 36-ii: preset voices override (kullanıcı preset'i bir voice değiştirmişse)
            for speaker, vid in preset.voices.items():
                if speaker in elevenlabs_active:
                    elevenlabs_active[speaker] = {
                        **elevenlabs_active[speaker],
                        "voice_id": vid,
                    }
            # Phase 36-ii: preset voice_settings override (style/stability tuning)
            for speaker, settings in preset.voice_settings.items():
                if speaker in elevenlabs_active:
                    elevenlabs_active[speaker] = {
                        **elevenlabs_active[speaker],
                        **settings,
                    }
            await synthesize_podcast(
                dialog=dialog,
                output_path=audio_path,
                voices=elevenlabs_active,
            )
            audio_bytes = audio_path.stat().st_size

            # Phase 36-ii: audio_meta.json sidecar
            _write_audio_meta(
                target_dir=target_dir,
                preset=preset,
                voices_used=elevenlabs_active,
                duration_sec=None,  # ffprobe Phase 37 (şimdilik None ok)
                char_count=sum(len(seg["text"]) for seg in dialog),
            )
            log.info(
                "audio_only.done",
                job_id=job_id,
                bytes=audio_bytes,
                segments=len(dialog),
                mode="podcast",
                preset_id=preset.id,
            )
            return {
                "status": "done",
                "audio_url": f"/archive/deep/{job_id}/{AUDIO_NAME}",
                "bytes": audio_bytes,
                "segments": len(dialog),
                "mode": "podcast",
                "preset_id": preset.id,
            }

        # GitHub / arXiv: tek-spiker (legacy)
        audio_prompt = render(load_prompt(prompt_name), **extras)
        audio_script = (await synthesize_with_claude(audio_prompt)).strip()
        if not audio_script:
            raise RuntimeError("audio: claude empty output")

        _atomic_write_text(target_dir / "audio_script.txt", audio_script)
        from llm.tts import synthesize_to_mp3

        await synthesize_to_mp3(audio_script, output_path=audio_path)
        audio_bytes = audio_path.stat().st_size

        log.info("audio_only.done", job_id=job_id, bytes=audio_bytes, mode="single")
        return {
            "status": "done",
            "audio_url": f"/archive/deep/{job_id}/{AUDIO_NAME}",
            "bytes": audio_bytes,
            "audio_chars": len(audio_script),
            "mode": "single",
        }
    except Exception as e:
        err = str(e)[:500]
        log.error("audio_only.failed", job_id=job_id, err=err[:200])
        return {"status": "failed", "detail": err}
    finally:
        audio_lock.unlink(missing_ok=True)


async def run_audio_only_for_existing_job(
    *,
    archive_root: Path,
    job_id: str,
) -> dict[str, Any]:
    """Backward-compat shim (Phase 21-i API).

    Phase 36-ii sonrası core path: ``audio_only(job_id, *, force, preset_id)``
    + module-level ``DEEP_DIR``. Eski API'yi koruyarak app.py + diğer
    çağrılarda kırılma olmasın. archive_root parametresi DEEP_DIR'i geçici
    olarak override eder (multi-root test desteği için).
    """
    global DEEP_DIR
    saved = DEEP_DIR
    try:
        DEEP_DIR = archive_root / "deep"
        return await audio_only(job_id)
    finally:
        DEEP_DIR = saved


# ─── Orchestrator ───────────────────────────────────────────────────────


async def run_deep_analyze(
    url: str,
    *,
    archive_root: Path,
    force: bool = False,
    use_whisper: bool = False,
) -> dict[str, Any]:
    """Synchronous (background-friendly) entry point.

    Returns ``{"job_id": ..., "status": "done" | "failed" | "in_progress" |
    "already_exists" | "unsupported"}`` early; uzun çalışma background
    task'inde devam eder. Caller bu fonksiyonu ``BackgroundTasks.add_task``
    veya ``asyncio.create_task`` ile sarmalar.
    """
    detected = detect_url_type(url)
    if detected == "unknown":
        return {
            "job_id": None,
            "status": "unsupported",
            "error": "Bilinmeyen URL türü; youtube/github/arxiv bekleniyor",
        }

    job_id = compute_job_id(url, detected)
    target_dir = job_dir(archive_root=archive_root, job_id=job_id)

    # Cache hit? Phase 18: tüm tipler primary=summary.md.
    # Legacy result.md fallback Phase 14 jobs için backward compat.
    primary_path = target_dir / SUMMARY_NAME
    legacy_path = target_dir / RESULT_NAME
    cached_path = (
        primary_path if primary_path.is_file() else (legacy_path if legacy_path.is_file() else None)
    )
    if cached_path is not None and not force:
        return {
            "job_id": job_id,
            "status": "already_exists",
            "generated_at": datetime.fromtimestamp(cached_path.stat().st_mtime, UTC).isoformat(),
        }

    # Lockfile acquire
    try:
        lockfile = _acquire_lockfile(target_dir, url=url, detected_type=detected)
    except FileExistsError:
        return {"job_id": job_id, "status": "in_progress"}

    last_error_path = target_dir / LAST_ERROR_NAME
    last_error_path.unlink(missing_ok=True)
    started_at = _now_iso()

    def _update_stage(stage: str) -> None:
        """Lockfile içindeki ``stage`` field'ını güncelle (UI polling görür)."""
        try:
            data = json.loads(lockfile.read_text(encoding="utf-8"))
            data["stage"] = stage
            lockfile.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass  # stage update best-effort

    try:
        log.info(
            "deep_analyze.start",
            job_id=job_id,
            url=url,
            type=detected,
        )

        # Phase 18: tüm tipler multi-stage artifact pipeline.
        if detected == "youtube":
            meta_extras = await _run_youtube_artifacts(
                url,
                target_dir=target_dir,
                update_lock_stage=_update_stage,
                use_whisper=use_whisper,
            )
        elif detected == "github":
            meta_extras = await _run_github_artifacts(
                url,
                target_dir=target_dir,
                archive_root=archive_root,
                update_lock_stage=_update_stage,
            )
        elif detected == "arxiv":
            meta_extras = await _run_arxiv_artifacts(
                url, target_dir=target_dir, update_lock_stage=_update_stage
            )
        else:
            raise RuntimeError(f"unhandled_type: {detected}")
        _write_meta(target_dir, url=url, detected_type=detected, extra=meta_extras)

        log.info("deep_analyze.done", job_id=job_id, type=detected)
        return {
            "job_id": job_id,
            "status": "done",
            "started_at": started_at,
        }
    except Exception as e:
        # Phase 27.5c: bazı exception'lar (httpx.HTTPStatusError gibi) boş
        # __str__ döner — repr + traceback ile teşhis edilebilir hata bırak.
        import traceback as _tb

        err_msg = str(e) or repr(e) or e.__class__.__name__
        err_text = (f"{err_msg}\n\n--- traceback ---\n{_tb.format_exc()}")[:2000]
        last_error_path.write_text(err_text, encoding="utf-8")
        log.error(
            "deep_analyze.failed",
            job_id=job_id,
            url=url,
            err=err_msg[:200],
            exc_class=e.__class__.__name__,
        )
        return {
            "job_id": job_id,
            "status": "failed",
            "detail": err_text[:500],
        }
    finally:
        lockfile.unlink(missing_ok=True)
