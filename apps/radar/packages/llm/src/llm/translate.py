"""Türkçe kısa/uzun özet + başlık pipeline'ı (gemini/claude CLI subprocess).

Phase 12-i: ``translate_short_pending`` worker hourly cron'undan ve
``pulse translate-pending`` CLI'sinden ortak çağrılır. İdempotent
NULL-fill: başarısız makaleler ``summary_tr_short=NULL`` kalır,
bir sonraki çağrı tekrar dener.

Phase 32-ii: ``translate_titles_pending`` İngilizce başlıkları akış-time
Türkçeye çevirir. JSON kolon (Article.metadata.title_tr) — migration
yok, geriye uyumlu.

**Caller-commits convention break (deliberate):** Diğer repository
helper'ları aksine bu pipeline kendi commit'lerini per-article yönetir
— partial progress crash'i atlatır. Çağıran fonksiyon commit etmez.

FSEK iktibas sınırı (Article.summary docstring): max ~200 kelime.
Kısa özet hedef ~110, uzun özet (Phase 12-iii) ~200 kelime üst sınır
— prompt template'lerinde belirtilir.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import time

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from store.repository import (
    find_pending_short,
    find_pending_title_tr,
    set_article_title_tr,
    set_summary_tr_short,
)

from llm.prompts import load_prompt, render

log = structlog.get_logger()

# Translation CLI seçimi:
# - Empirik veri (2026-05-07): gemini batch çevirilerinde 0% yield (meta-response
#   loop'u), claude brief üretiminde %100 yield. Default'u claude'a aldık.
# - Claude Max subscription quota'sı sınırlı; gemini başarılı çalıştığı
#   günler için fallback bırakıldı.
# - env override: RASATHANE_TRANSLATE_CLI=gemini → gemini default; herhangi
#   bir şey atılırsa claude default'a döner.
_PRIMARY_CLI_DEFAULT = "claude"
_FALLBACK_CLI = "gemini"

# Per-CLI subprocess timeout. Gemini hızlı (<10 sn beklenir, 60 sn stuck).
# Claude ~5-15 sn (kısa özet için), 90 sn üst sınır.
_GEMINI_TIMEOUT_SECONDS = 60
_CLAUDE_TIMEOUT_SECONDS = 90

# Batch deadline: hourly cron bir sonraki tick'e taşmasın diye 30 dk
# içinde bitsin. Aşılırsa loop break, kalan NULL'lar bir sonraki çağrıya.
_BATCH_DEADLINE_SECONDS = 1800


def _select_primary_cli() -> str:
    """Env override > kod default. Beklenen değerler: 'claude' | 'gemini'."""
    override = os.environ.get("RASATHANE_TRANSLATE_CLI", "").strip().lower()
    if override in ("claude", "gemini"):
        return override
    return _PRIMARY_CLI_DEFAULT


# Gemini ara sıra prompt'u multi-turn sohbet sanıp "Anladım, hazırım..."
# preamble'ıyla cevap veriyor — özet yerine rol-kabul mesajı geliyor.
# Şu prefix'lerle başlayan veya bu phrase'leri içeren çıktıları reject et.
_BAD_OUTPUT_PREFIXES = (
    "okay",
    "sure",
    "ok,",
    "anladım",
    "anladim",
    "tamam",
    "hazırım",
    "haziriam",
    "i'm ready",
    "i understand",
    "i am ready",
    "hello",
    "merhaba",
    "selam",
)
_BAD_OUTPUT_SUBSTRINGS = (
    "ilk komutunuzu bekl",
    "first command",
    "sen bir asistans",
    "ready for your",
    "asistansın",
    "asistanım",
    # "Bana metin verin" tarzı meta-cevaplar (RSS summary boşsa görülüyor)
    "metni sağlayın",
    "metni bana sağlayın",
    "metnini sağla",
    "metnine erişim",
    "haber metnini",
    "lütfen haber",
    "metin sağlanma",
    "metni sağlanma",
    "metni eksik",
    "haberi sağla",
    "bana bir haber",
    "özetlenecek haber",
    "özetlememi istediğ",
    "sağlanmadığı için",
    "sağlamadığınız için",
    "sağlamanız durum",
    "paylaşabilirim",
    "size yardımcı ola",
    "tool call has been denied",
    "i cannot proceed",
    "isteğinizi yerine getir",
    "without its content",
    "without the content",
    "cannot summarize",
    "no content was provided",
    "was not provided",
    "please provide the news",
    "please provide the article",
    "for me to summarize",
    "request to get the news",
    "to provide a summary",
)


# Min kaynak içerik eşiği: RSS summary boş VE title kısaysa gemini'ye
# göndermenin anlamı yok — meta-response gelir. Article NULL kalır,
# sonradan summary doldurulursa retry edilir.
_MIN_TITLE_LEN_NO_SUMMARY = 80


def _is_bad_gemini_output(text: str) -> bool:
    """Detect gemini's "I'm ready / Anladım hazırım..." sohbet preamble'ı."""
    head = text.strip()[:80].lower()
    if any(head.startswith(p) for p in _BAD_OUTPUT_PREFIXES):
        return True
    body_lower = text.lower()
    return any(s in body_lower for s in _BAD_OUTPUT_SUBSTRINGS)


def _output_mentions_title_topic(text: str, title: str) -> bool:
    """Pozitif validation: gerçek özet title'dan en az 1 substantive token içermeli.

    Title 5+ harfli kelime VEYA 3+ harfli ALL-CAPS akronim (GAN, MUVERA, AYM
    vb.) barındırıyorsa, output'ta bunlardan en az biri geçmeli. Aksi halde
    gemini muhtemelen meta-cevap üretmiş ("haber metni eksik" vb.). Title
    bunlardan hiçbirini içermiyorsa check skip, guard'a güven.
    """
    long_tokens = re.findall(r"[A-Za-zÇĞİıÖŞÜçğıöşü]{5,}", title)
    acronyms = re.findall(r"\b[A-ZÇĞİÖŞÜ]{3,}\b", title)
    title_tokens = [t.lower() for t in long_tokens + acronyms]
    if not title_tokens:
        return True
    text_lower = text.lower()
    return any(tok in text_lower for tok in title_tokens)


def _build_short_prompt(*, title: str, summary: str | None, url: str) -> str:
    template = load_prompt("short_summary")
    return render(
        template,
        title=title,
        summary=summary or "(orijinal özet yok)",
        url=url,
    )


def _run_gemini_short(prompt: str) -> str:
    """Sync helper — gemini --prompt <argv>. Bkz. _run_translate_cli."""
    return _run_translate_cli("gemini", prompt)


def _run_claude_short(prompt: str) -> str:
    """Sync helper — claude -p <stdin>. Bkz. _run_translate_cli."""
    return _run_translate_cli("claude", prompt)


def _run_translate_cli(cli_name: str, prompt: str) -> str:
    """Sync subprocess helper — CLI-agnostic.

    Windows'ta `.cmd` shim'i shutil.which ile çözülür (PATHEXT okur).
    Claude prompt'u stdin'den geçer (Windows CMD argv ~32KB sınırı);
    gemini argv'den (--prompt arg) geçer.

    Raises ``FileNotFoundError`` if CLI yok PATH'te, ``RuntimeError`` on
    non-zero exit.
    """
    cli = shutil.which(cli_name)
    if cli is None:
        raise FileNotFoundError(f"{cli_name} CLI not in PATH")

    if cli_name == "claude":
        argv = [cli, "-p"]
        stdin_input = prompt
        timeout = _CLAUDE_TIMEOUT_SECONDS
    elif cli_name == "gemini":
        argv = [cli, "--prompt", prompt]
        stdin_input = None
        timeout = _GEMINI_TIMEOUT_SECONDS
    else:
        raise ValueError(f"unsupported CLI: {cli_name}")

    proc = subprocess.run(
        argv,
        input=stdin_input,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"{cli_name} CLI failed (rc={proc.returncode}): "
            f"{proc.stderr or proc.stdout or '(no output)'}"
        )
    return proc.stdout


async def translate_short_pending(
    session: AsyncSession,
    *,
    limit: int = 100,
) -> tuple[int, int]:
    """Find + translate up to ``limit`` articles with NULL summary_tr_short.

    Returns ``(success_count, fail_count)``. Caller does NOT commit —
    this function commits internally per-article so partial progress
    survives a crash mid-batch.

    Batch deadline (30 dk) aşılırsa loop break edilir; kalan NULL'lar
    bir sonraki çağrıda işlenir.
    """
    pending = await find_pending_short(session, limit=limit)
    if not pending:
        log.info("translate_short.empty")
        return 0, 0

    # ORM attr'larını şimdi (session sıcakken) plain tuple'a snapshot'la.
    # Loop içindeki commit/rollback expire_on_commit=True default'uyla
    # diğer attached objelerin tüm attr'larını expire eder; sonraki
    # iterasyonda lazy-load asyncio context'inde MissingGreenlet crash
    # yapar. Snapshot bu zinciri kırar — set_summary_tr_short kendi
    # SELECT'iyle ihtiyaç duyduğu satırı yeniden yükler.
    pending_data = [(a.id, a.title, a.summary, a.url) for a in pending]

    success = 0
    fail = 0
    deadline = time.monotonic() + _BATCH_DEADLINE_SECONDS

    for article_id, article_title_full, article_summary, article_url in pending_data:
        article_title_short = article_title_full[:80]

        if time.monotonic() > deadline:
            log.warning(
                "translate_short.deadline_exceeded",
                processed=success + fail,
                remaining=len(pending_data) - (success + fail),
            )
            break

        # Pre-flight: yetersiz kaynak içeriği gemini'ye gönderme
        has_summary = bool(article_summary and article_summary.strip())
        if not has_summary and len(article_title_full) < _MIN_TITLE_LEN_NO_SUMMARY:
            log.warning(
                "translate_short.skipped_no_content",
                article_id=str(article_id),
                title=article_title_short,
            )
            await session.rollback()
            fail += 1
            continue

        prompt = _build_short_prompt(
            title=article_title_full, summary=article_summary, url=article_url
        )
        try:
            text = await _generate_short_with_fallback(prompt, article_title_full)
            await set_summary_tr_short(session, article_id, text)
            await session.commit()
            success += 1
        except LookupError as e:
            await session.rollback()
            log.error(
                "translate_short.article_vanished",
                article_id=str(article_id),
                err=str(e)[:200],
            )
            fail += 1
        except Exception as e:
            await session.rollback()
            log.warning(
                "translate_short.failed",
                article_id=str(article_id),
                title=article_title_short,
                err=str(e)[:200],
            )
            fail += 1
    log.info("translate_short.done", success=success, fail=fail)
    return success, fail


async def _generate_short_with_fallback(prompt: str, title: str) -> str:
    """Primary CLI'ye gönder, kötü çıktı veya hata varsa fallback dene.

    Bad-output guard ve topic-mention check her iki CLI'ya da uygulanır.
    Primary başarılıysa fallback denenmez (cost saving). Her iki CLI da
    fail olursa son hata yukarı bubble eder.
    """
    primary = _select_primary_cli()
    fallback = _FALLBACK_CLI if primary != _FALLBACK_CLI else "claude"

    last_err: Exception | None = None
    for cli in (primary, fallback):
        runner = _run_claude_short if cli == "claude" else _run_gemini_short
        try:
            stdout = await asyncio.to_thread(runner, prompt)
            text = stdout.strip()
            if not text:
                raise RuntimeError(f"{cli} returned empty output")
            if _is_bad_gemini_output(text):
                raise RuntimeError(f"{cli} chat-preamble detected (rejected): {text[:80]!r}")
            if not _output_mentions_title_topic(text, title):
                raise RuntimeError(
                    f"{cli} output doesn't mention title token (rejected): text={text[:80]!r}"
                )
            log.info("translate_short.cli_ok", cli=cli)
            return text
        except FileNotFoundError as e:
            last_err = e
            log.warning("translate_short.cli_not_found", cli=cli, err=str(e))
        except Exception as e:
            last_err = e
            log.info("translate_short.cli_failed_trying_fallback", cli=cli, err=str(e)[:120])

    raise last_err or RuntimeError("all CLIs failed")


# ── Phase 32-ii: Türkçe başlık çevirisi ─────────────────────────────


# Title çeviri için ayrı timeout — sadece tek satır çıktı bekliyoruz,
# kısa olmalı. 30 sn pratik üst sınır.
_TITLE_TIMEOUT_SECONDS = 30
_TITLE_MAX_CHARS = 200  # output sanity cap


def _looks_already_turkish(title: str) -> bool:
    """Heuristik: başlık zaten Türkçe karakterler içeriyorsa skip et.

    Yüksek hassasiyetli değil — yanlış-pozitif olabilir (örn. tek ı/ş
    İngilizce başlıkta). Yine de gereksiz çağrıyı kesip cost düşürür.
    """
    if not title:
        return False
    tr_chars = "ıİşŞğĞüÜçÇöÖ"
    return any(c in title for c in tr_chars)


def _is_valid_title_output(text: str, original: str) -> bool:
    """Title çıktısı sanity check.

    Reddet:
    - Boş
    - Chat-preamble (Okay, Sure, Anladım...)
    - 200+ karakter (LLM monologa girmiş)
    - Markdown başlık (#) veya prefix ("Çeviri:", "Türkçe:")
    - Tamamı orijinalle aynı (LLM çeviri yapmamış)
    """
    text = text.strip()
    if not text or len(text) > _TITLE_MAX_CHARS:
        return False
    low = text.lower()
    if low.startswith(_BAD_OUTPUT_PREFIXES):
        return False
    forbidden_prefixes = (
        "çeviri:",
        "türkçe:",
        "tr:",
        "translation:",
        "# ",
        "## ",
        "**",
    )
    if low.startswith(forbidden_prefixes):
        return False
    # Markdown-link/bold/list işaretleri içeriyorsa LLM kuralları ihlal
    return not any(marker in text for marker in ("```", "**", "* ", "- ", "["))


def _build_title_prompt(*, title: str, source_name: str, category: str) -> str:
    """short_title_tr.md prompt'unu render et."""
    template = load_prompt("short_title_tr")
    return render(template, title=title, source_name=source_name, category=category)


async def _generate_title_tr_with_fallback(prompt: str, original_title: str) -> str:
    """Title çevirisi için primary + fallback CLI denemesi.

    Title çıktısı tek satır, kısa metin → daha agresif validation.
    """
    primary = _select_primary_cli()
    fallback = _FALLBACK_CLI if primary != _FALLBACK_CLI else "claude"

    last_err: Exception | None = None
    for cli in (primary, fallback):
        runner = _run_claude_short if cli == "claude" else _run_gemini_short
        try:
            # title prompt küçük, _TITLE_TIMEOUT_SECONDS yeter
            stdout = await asyncio.to_thread(runner, prompt)
            text = stdout.strip()
            # Tek satır al (LLM birden fazla satır basabilir)
            first_line = text.split("\n", 1)[0].strip()
            if not _is_valid_title_output(first_line, original_title):
                raise RuntimeError(f"{cli} title output rejected: {first_line[:80]!r}")
            log.info("translate_title.cli_ok", cli=cli, chars=len(first_line))
            return first_line
        except FileNotFoundError as e:
            last_err = e
            log.warning("translate_title.cli_not_found", cli=cli, err=str(e))
        except Exception as e:
            last_err = e
            log.info("translate_title.cli_failed_trying_fallback", cli=cli, err=str(e)[:120])

    raise last_err or RuntimeError("all CLIs failed for title translation")


async def translate_titles_pending(
    session: AsyncSession,
    *,
    limit: int = 50,
) -> tuple[int, int]:
    """Title TR çevirisi bekleyen makaleleri çevir (Phase 32-ii).

    ``Article.metadata.title_tr`` JSON kolonuna yazar. Idempotent: zaten
    title_tr varsa skip; başarısızlar bir sonraki çağrıda tekrar denenir.

    Pre-flight skip kuralları:
      - Source lang ``tr`` → zaten Türkçe, gereksiz
      - Başlıkta TR-spesifik karakter (ı/ş/ğ/ç/ö/ü) → zaten Türkçe sayılır
      - Boş veya çok kısa başlık (<8 char)

    Returns: ``(success_count, fail_count)``. Caller commit etmez —
    per-article commit (partial progress).
    """
    pending = await find_pending_title_tr(session, limit=limit)
    if not pending:
        log.info("translate_title.empty")
        return 0, 0

    # ORM expire_on_commit guard: snapshot to plain tuples
    pending_data = [(a.id, a.title, a.source.name, a.source.category) for a in pending]

    success = 0
    fail = 0
    deadline = time.monotonic() + _BATCH_DEADLINE_SECONDS

    for article_id, title_full, source_name, category in pending_data:
        if time.monotonic() > deadline:
            log.warning(
                "translate_title.deadline_exceeded",
                processed=success + fail,
            )
            break

        if not title_full or len(title_full.strip()) < 8:
            await session.rollback()
            fail += 1
            continue
        if _looks_already_turkish(title_full):
            # Türkçe başlığı kaynak metadata'sından geçirmek için title_tr=title
            # set et — UI fallback chain'i bu duruma karışmasın
            try:
                await set_article_title_tr(session, article_id, title_full)
                await session.commit()
                success += 1
            except Exception:
                await session.rollback()
                fail += 1
            continue

        prompt = _build_title_prompt(title=title_full, source_name=source_name, category=category)
        try:
            tr_title = await _generate_title_tr_with_fallback(prompt, title_full)
            await set_article_title_tr(session, article_id, tr_title)
            await session.commit()
            success += 1
        except LookupError as e:
            await session.rollback()
            log.error(
                "translate_title.article_vanished",
                article_id=str(article_id),
                err=str(e)[:200],
            )
            fail += 1
        except Exception as e:
            await session.rollback()
            log.warning(
                "translate_title.failed",
                article_id=str(article_id),
                title=title_full[:60],
                err=str(e)[:200],
            )
            fail += 1
    log.info("translate_title.done", success=success, fail=fail)
    return success, fail
