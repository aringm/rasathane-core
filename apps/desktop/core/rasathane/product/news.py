"""Kayıtlı haber metninden izlenebilir kısa özet ve yerel sesli okuma."""

from __future__ import annotations

import hashlib
import re
import tempfile
import threading
import wave
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from ytcore.uretim.tts import WindowsTTS

from rasathane.product.store import ProductStore, digest, fold, json_text
from rasathane.product.web import validate_public_url

MAX_SUMMARY_CHARS = 900
MAX_AUDIO_BYTES = 8 * 1024 * 1024
_speech_lock = threading.Lock()
_STOP_WORDS = frozenset(
    "bir bu ve ile için olan olarak da de ise veya gibi daha en kadar sonra önce".split()
)
_TURKISH_WORDS = frozenset(
    (
        "bir ve ile için olarak yayımlandı haber haberi kaynak yeni kaynağın kaynaklar veri "
        "kişisel araştırma yapılan edildi yapıldı değil henüz kabul itiraz yönetmelik başvuru "
        "süresi açıklama sonucu inceleme bu doğrulama modelin gündür çalışıyor çalışır"
    ).split()
)


def looks_turkish(text: str) -> bool:
    words = set(re.findall(r"\w+", text.lower()))
    matched = len(words & _TURKISH_WORDS)
    return matched >= 2 or (matched >= 1 and bool(re.search(r"[ğĞşŞıİçÇöÖüÜ]", text)))


def restricted_source(text: str) -> bool:
    folded = fold(text)
    if any(
        marker in folded[:200]
        for marker in (
            "verify you are human",
            "checking your browser",
            "just a moment",
            "insan oldugunuzu dogrulayin",
            "erisim engellendi",
        )
    ):
        return True
    if len(text) > 1500:
        return False
    return any(
        marker in folded
        for marker in (
            "verify you are human",
            "enable javascript",
            "access denied",
            "checking your browser",
            "subscribe to continue",
            "sign in to continue",
            "subscription required",
            "insan oldugunuzu dogrulayin",
            "erisim engellendi",
            "okumaya devam etmek icin abone",
            "cerezleri kabul edin",
            "accept all cookies",
        )
    )


def article_target(article: dict[str, Any]) -> str:
    text = _plain_text(str(article.get("summary") or ""))
    target = re.search(r"Article URL:\s*(https?://[^\s<>]+)", text)
    if target and "Comments URL:" in text:
        return validate_public_url(target.group(1))
    return validate_public_url(article["url"])


def article_input_hash(article: dict[str, Any]) -> str:
    return digest(json_text({k: article.get(k) for k in ("title", "url", "summary", "provenance")}))


def display_summary(store: ProductStore, article: dict[str, Any]) -> dict[str, Any]:
    signature = article_input_hash(article)
    cached = store.rows(
        "SELECT payload FROM article_summaries WHERE article_id=? AND input_hash=?",
        (article["id"], signature),
    )
    if cached:
        return dict(cached[0]["payload"])
    result = _saved_summary(article)
    if result["status"] == "ready" or result["text_scope"] == "official_metadata":
        return result
    jobs = store.rows(
        "SELECT id,status,error FROM jobs WHERE kind='article_summary' "
        "AND json_extract(request,'$.article_id')=? AND json_extract(request,'$.input_hash')=? "
        "ORDER BY created_at DESC LIMIT 1",
        (article["id"], signature),
    )
    return _with_summary_job(result, jobs[0] if jobs else None)


def _with_summary_job(result: dict[str, Any], job: dict[str, Any] | None) -> dict[str, Any]:
    if job is not None:
        result["job_id"] = job["id"]
        if job["status"] in {"queued", "running", "cancel_requested"}:
            result.update(status="pending", label="Türkçe özet hazırlanıyor")
        if job["status"] in {"failed", "interrupted", "cancelled"}:
            result.update(
                status="failed",
                error=job["error"],
                label="Türkçe özet hazırlanamadı",
                notice="Türkçe özet hazırlanamadı. Yeniden denemek için Özetle düğmesini kullanın.",
            )
    return result


def display_summaries(
    store: ProductStore, articles: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Sayfanın cache ve iş durumunu iki toplu sorguda okur; hiçbir iş başlatmaz."""
    if not articles:
        return {}
    signatures = {article["id"]: article_input_hash(article) for article in articles}
    placeholders = ",".join("?" for _ in signatures)
    cached = {
        row["article_id"]: row["payload"]
        for row in store.rows(
            f"SELECT article_id,input_hash,payload FROM article_summaries "
            f"WHERE article_id IN ({placeholders})",
            tuple(signatures),
        )
        if row["input_hash"] == signatures[row["article_id"]]
    }
    results = {
        article["id"]: dict(cached[article["id"]])
        if article["id"] in cached
        else _saved_summary(article)
        for article in articles
    }
    pending_ids = [
        item_id
        for item_id, result in results.items()
        if item_id not in cached
        and result["status"] != "ready"
        and result["text_scope"] != "official_metadata"
    ]
    if pending_ids:
        placeholders = ",".join("?" for _ in pending_ids)
        jobs = store.rows(
            "SELECT id,status,error,json_extract(request,'$.article_id') AS article_id,"
            "json_extract(request,'$.input_hash') AS input_hash FROM jobs "
            "WHERE kind='article_summary' AND json_extract(request,'$.article_id') "
            f"IN ({placeholders}) ORDER BY created_at DESC",
            tuple(pending_ids),
        )
        seen = set()
        for job in jobs:
            item_id = job["article_id"]
            if item_id in seen or job["input_hash"] != signatures[item_id]:
                continue
            seen.add(item_id)
            _with_summary_job(results[item_id], job)
    return results


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"br", "p", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _PlainText()
    parser.feed(value[:200_000])
    parser.close()
    return " ".join("".join(parser.parts).split())


def _words(value: str) -> list[str]:
    return [
        word
        for word in re.findall(r"\w+", fold(value))
        if len(word) > 2 and word not in _STOP_WORDS
    ]


def _extract(text: str, title: str, limit: int = MAX_SUMMARY_CHARS) -> str:
    """Cümleleri yeniden yazmadan seçer; kesilen tek uzun cümleyi açıkça işaretler."""
    if len(text) <= limit:
        return text
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ0-9])", text)
    frequency = Counter(_words(text))
    title_words = set(_words(title))
    ranked: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences):
        words = set(_words(sentence))
        score = sum(min(frequency[word], 5) for word in words) / max(1, len(words))
        score += len(words & title_words) * 2 + (2 if index == 0 else 0)
        ranked.append((score, index, sentence))
    selected: list[tuple[int, str]] = []
    remaining = limit
    for _, index, sentence in sorted(ranked, key=lambda item: (-item[0], item[1])):
        if len(sentence) <= remaining:
            selected.append((index, sentence))
            remaining -= len(sentence) + 1
        if len(selected) >= 3:
            break
    if selected:
        return " ".join(sentence for _, sentence in sorted(selected))
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def summarize_article(store: ProductStore, article_id: str) -> dict[str, Any]:
    rows = store.rows("SELECT * FROM articles WHERE id=?", (article_id,))
    if not rows:
        raise ValueError("Haber bulunamadı.")
    return display_summary(store, rows[0])


def _saved_summary(article: dict[str, Any]) -> dict[str, Any]:
    provenance = article.get("provenance") or {}
    scope = provenance.get("text_scope", "feed_excerpt")
    text = _plain_text(str(article.get("summary") or ""))
    title = _plain_text(str(article["title"]))
    boilerplate = "Article URL:" in text and "Comments URL:" in text
    usable = bool(
        text and fold(text) != fold(title) and not boilerplate and scope != "link_metadata"
    )
    unavailable = (
        scope == "official_metadata"
        or restricted_source(text)
        or (not usable and not boilerplate and scope != "link_metadata")
    )
    turkish = usable and looks_turkish(text)
    summary = _extract(text, title) if turkish and not unavailable else ""
    notice = (
        "Bu kayıtta özetlenebilecek haber metni bulunmuyor. Tam metin için kaynağı açın."
        if unavailable
        else "Özet, kayıtlı haber metninden cümle seçilerek oluşturuldu; tam metin okunmadı."
    )
    if not unavailable and scope == "managed_summary":
        notice = (
            "Özet, kaynak servisinin sağladığı özet metninden seçildi; tam karar metni okunmadı."
        )
    if provenance.get("summary_kind") == "ai_generated" and not unavailable:
        notice += " Kaynak metin AI tarafından oluşturulmuş bir özettir."
    return {
        "article_id": article["id"],
        "title": title,
        "url": article_target(article),
        "status": "unavailable" if unavailable else ("ready" if turkish else "not_prepared"),
        "summary": summary,
        "method": "extractive" if turkish else "pending",
        "label": "Kaynak metninden Türkçe kısa özet"
        if turkish
        else "Türkçe özet henüz hazırlanmadı",
        "language": "tr",
        "text_scope": scope,
        "source_chars": len(text),
        "summary_chars": len(summary),
        "source_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "notice": notice
        if unavailable or turkish
        else "Türkçe özet henüz hazırlanmadı. Kaynak metni edinilerek yerel modelle hazırlanacak.",
    }


def speak_article(store: ProductStore, article_id: str) -> bytes:
    """Yalnız mevcut Windows Türkçe sesi; dosya yolu veya metin istemciden alınmaz."""
    result = summarize_article(store, article_id)
    if result["status"] != "ready":
        raise ValueError(result["notice"])
    return speak_text(result["summary"])


def speak_text(text: str, *, max_audio_bytes: int = MAX_AUDIO_BYTES) -> bytes:
    """Sunucuda üretilen kaynak özetini yerel sesle okur; API serbest metin kabul etmez."""
    if not _speech_lock.acquire(blocking=False):
        raise ValueError("Bir sesli özet hazırlanıyor. Tamamlandığında yeniden deneyin.")
    try:
        with tempfile.TemporaryDirectory(prefix="rasathane-news-") as directory:
            audio_path = Path(directory) / "summary.wav"
            output = WindowsTTS().seslendir(text, audio_path)
            if output.durum == "ses_modeli_yok":
                raise ValueError(
                    "Türkçe Windows sesi bulunamadı. Windows Dil ve Konuşma ayarlarından "
                    "Türkçe ses paketini kurun."
                )
            if output.durum != "uretildi" or not audio_path.is_file():
                raise ValueError("Sesli özet oluşturulamadı. Yeniden deneyin.")
            if audio_path.stat().st_size > max_audio_bytes:
                raise ValueError("Sesli özet izin verilen boyutu aşıyor. Daha az haber seçin.")
            try:
                with wave.open(str(audio_path), "rb") as audio:
                    if audio.getnframes() == 0 or audio.getframerate() == 0:
                        raise ValueError("Sesli özet boş döndü. Yeniden deneyin.")
            except (wave.Error, EOFError) as error:
                raise ValueError("Sesli özet biçimi doğrulanamadı. Yeniden deneyin.") from error
            return audio_path.read_bytes()
    finally:
        _speech_lock.release()
