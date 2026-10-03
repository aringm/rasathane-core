from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ytcore.models import IndexKaydi
from ytcore.text.slug import slugify

IMZA = "Av. Mehmet Arın Gülüm"


def _analiz_dizin_adi(kayit: IndexKaydi) -> str:
    """<YYYY-MM-DD>_<slug>_<video_id>. video_id çakışma-önleyici: aynı kanal+başlık+gün
    farklı videolar (slug çarpışması ya da [:48] kesilmesi) birbirini SESSİZCE EZMESİN.
    Hata-yolunda video_slug zaten video_id olabilir → tekrar ekleme."""
    taban = f"{kayit.analiz_tarihi}_{kayit.video_slug}"
    ham_id = kayit.video_id.strip()
    # GitHub/HF doğal kimliği `/`, Reddit/arXiv kimliği `:` gibi path karakterleri
    # taşıyabilir. YouTube legacy klasör sözleşmesini aynen koru; diğerlerini güvenli slug yap.
    vid = ham_id if kayit.kaynak_turu == "youtube" else slugify(ham_id, fallback="kaynak")[:64]
    return f"{taban}_{vid}" if vid and vid != kayit.video_slug else taban


def _motor_satir(motor: dict[str, Any]) -> str:
    """00_kapak.md için tek satırlık motor kökeni (kullanıcı isteği 2026-08-24).

    llamacpp: 'llamacpp · LLM gemma-…gguf · Embedding bge-m3-…gguf · profil ram8 · ctx 8192'
    ollama  : 'ollama · LLM qwen2.5:14b · Embedding bge-m3 · host 127.0.0.1:11434 · ctx 8192'
    """
    if not motor:
        return ""
    if motor.get("backend") == "llamacpp":
        return (
            f"Motor: llamacpp · LLM {motor.get('llm_model')} · "
            f"Embedding {motor.get('embedding_model')} · profil {motor.get('profil')} · "
            f"ctx {motor.get('num_ctx')}\n"
        )
    return (
        f"Motor: {motor.get('backend', 'ollama')} · LLM {motor.get('llm_model')} · "
        f"Embedding {motor.get('embedding_model')} · host {motor.get('ollama_host')} · "
        f"ctx {motor.get('num_ctx')}\n"
    )


def analiz_klasoru_yaz(
    kayit: IndexKaydi, output_base: Path, *, output_run_id: str | None = None
) -> Path:
    """Rasathane gözlem klasörünü konu/sahip/kimlik hiyerarşisinde yaz."""
    dizin_adi = _analiz_dizin_adi(kayit)
    if output_run_id is not None:
        if not re.fullmatch(r"[a-f0-9]{32}", output_run_id):
            raise ValueError("Geçersiz output run kimliği.")
        dizin_adi += f"_{output_run_id}"
    klasor = output_base / slugify(kayit.konu) / kayit.uretici_slug / dizin_adi
    # Ürün run'ı değişmez bir makbuzdur: başka çağrı aynı run'a yeniden yazamaz.
    # Legacy çağrılarda tarih/kaynak hiyerarşisi ve tekrar analiz davranışı korunur.
    klasor.mkdir(parents=True, exist_ok=output_run_id is None)
    (klasor / "00_index.json").write_text(kayit.model_dump_json(indent=2), encoding="utf-8")
    sahip_etiketi = "Kanal" if kayit.kaynak_turu == "youtube" else "Sahip/Yazar"
    sahip = kayit.kaynak_sahibi or kayit.kanal
    motor_satir = _motor_satir(kayit.motor)
    (klasor / "00_kapak.md").write_text(
        f"# Rasathane · {kayit.baslik}\n\nKaynak: {kayit.kaynak_turu}\n"
        f"{sahip_etiketi}: {sahip}\nKonu: {kayit.konu}\n{motor_satir}\n---\n_{IMZA}_\n",
        encoding="utf-8",
    )
    return klasor
