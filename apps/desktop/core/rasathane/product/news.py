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

from rasathane.product.store import ProductStore, fold

MAX_SUMMARY_CHARS = 900
MAX_AUDIO_BYTES = 8 * 1024 * 1024
_speech_lock = threading.Lock()
_STOP_WORDS = frozenset(
    "bir bu ve ile için olan olarak da de ise veya gibi daha en kadar sonra önce".split()
)


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


def _extract(text: str, title: str) -> str:
    """Cümleleri yeniden yazmadan seçer; kesilen tek uzun cümleyi açıkça işaretler."""
    if len(text) <= MAX_SUMMARY_CHARS:
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
    remaining = MAX_SUMMARY_CHARS
    for _, index, sentence in sorted(ranked, key=lambda item: (-item[0], item[1])):
        if len(sentence) <= remaining:
            selected.append((index, sentence))
            remaining -= len(sentence) + 1
        if len(selected) >= 3:
            break
    if selected:
        return " ".join(sentence for _, sentence in sorted(selected))
    return text[: MAX_SUMMARY_CHARS - 1].rsplit(" ", 1)[0] + "…"


def summarize_article(store: ProductStore, article_id: str) -> dict[str, Any]:
    rows = store.rows("SELECT * FROM articles WHERE id=?", (article_id,))
    if not rows:
        raise ValueError("Haber bulunamadı.")
    article = rows[0]
    provenance = article.get("provenance") or {}
    scope = provenance.get("text_scope", "feed_excerpt")
    text = _plain_text(str(article.get("summary") or ""))
    title = _plain_text(str(article["title"]))
    unavailable = scope == "official_metadata" or not text or fold(text) == fold(title)
    summary = "" if unavailable else _extract(text, title)
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
        "article_id": article_id,
        "title": title,
        "url": article["url"],
        "status": "unavailable" if unavailable else "ready",
        "summary": summary,
        "method": "extractive",
        "label": "Kaynak metninden kısa özet",
        "text_scope": scope,
        "source_chars": len(text),
        "summary_chars": len(summary),
        "source_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "notice": notice,
    }


def speak_article(store: ProductStore, article_id: str) -> bytes:
    """Yalnız mevcut Windows Türkçe sesi; dosya yolu veya metin istemciden alınmaz."""
    result = summarize_article(store, article_id)
    if result["status"] != "ready":
        raise ValueError(result["notice"])
    if not _speech_lock.acquire(blocking=False):
        raise ValueError("Bir sesli özet hazırlanıyor. Tamamlandığında yeniden deneyin.")
    try:
        with tempfile.TemporaryDirectory(prefix="rasathane-news-") as directory:
            audio_path = Path(directory) / "summary.wav"
            output = WindowsTTS().seslendir(result["summary"], audio_path)
            if output.durum == "ses_modeli_yok":
                raise ValueError(
                    "Türkçe Windows sesi bulunamadı. Windows Dil ve Konuşma ayarlarından "
                    "Türkçe ses paketini kurun."
                )
            if output.durum != "uretildi" or not audio_path.is_file():
                raise ValueError("Sesli özet oluşturulamadı. Yeniden deneyin.")
            if audio_path.stat().st_size > MAX_AUDIO_BYTES:
                raise ValueError("Sesli özet izin verilen boyutu aşıyor.")
            try:
                with wave.open(str(audio_path), "rb") as audio:
                    if audio.getnframes() == 0 or audio.getframerate() == 0:
                        raise ValueError("Sesli özet boş döndü. Yeniden deneyin.")
            except (wave.Error, EOFError) as error:
                raise ValueError("Sesli özet biçimi doğrulanamadı. Yeniden deneyin.") from error
            return audio_path.read_bytes()
    finally:
        _speech_lock.release()
