from __future__ import annotations

from pathlib import Path

from ytcore.uretim.node import seslendirme_node


def _state(tmp_path: Path, ozet: str):
    klasor = tmp_path / "analiz"
    klasor.mkdir()
    return {"ozet": {"kisa": ozet}, "klasor": str(klasor), "sonuc": {}, "metadata": {}}


def test_kvkk_pii_ozet_cloud_cagrilmaz(tmp_path, monkeypatch):
    # Cloud TAM açık (opt-in + anahtar) ama özet PII → cloud HTTP HİÇ çağrılmamalı (FAIL-CLOSED).
    monkeypatch.delenv("YT_TTS_FIXTURE", raising=False)  # gerçek provider seçimi
    monkeypatch.setenv("YT_TTS_CLOUD", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    # Piper'i inert yap (voice yok) → cloud seçilseydi HTTP'ye giderdi; gate kesmeli.
    monkeypatch.setenv("YT_PIPER_VOICE_DIR", str(tmp_path / "bos"))
    cagrilar: list[str] = []

    def _yakala(*a, **k):
        cagrilar.append(str(k.get("json", {}).get("input", "")))
        raise AssertionError("KVKK İHLALİ: PII metni cloud TTS'e gönderildi!")

    monkeypatch.setattr("httpx.post", _yakala)
    state = _state(tmp_path, "Müvekkil ahmet@example.com ve 0532 123 45 67 numarasından.")
    out = seslendirme_node(state)
    assert cagrilar == []  # cloud HİÇ çağrılmadı
    assert out["ses_kaynak"] == "piper"  # PII → piper'a yönlendi (fail-closed)
    assert out["ses_durum"] == "ses_modeli_yok"  # piper voice yok (ama cloud'a GİTMEDİ)


def test_kvkk_temiz_ozet_cloud_metni_pii_siz(tmp_path, monkeypatch):
    # PII-temiz + cloud açık → cloud çağrılır AMA gönderilen metin PII içermez (doğrula).
    from ytcore.router.pii_gate import pii_iceriyor_mu

    monkeypatch.delenv("YT_TTS_FIXTURE", raising=False)
    monkeypatch.setenv("YT_TTS_CLOUD", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    gonderilen: list[str] = []

    class _Yanit:
        content = b"FAKEMP3"

        def raise_for_status(self) -> None: ...

    def _post(*a, **k):
        gonderilen.append(str(k.get("json", {}).get("input", "")))
        return _Yanit()

    monkeypatch.setattr("httpx.post", _post)
    state = _state(tmp_path, "Enflasyon 2025'te yüzde 40 arttı; ekonomi yavaşladı.")
    out = seslendirme_node(state)
    assert out["ses_kaynak"] == "cloud" and out["ses_durum"] == "uretildi"
    assert gonderilen and all(not pii_iceriyor_mu(m).var for m in gonderilen)  # PII-siz


def test_kvkk_ner_kisi_adi_cloud_reddedilir(tmp_path, monkeypatch):
    # Faz 5: pattern-PII YOK ama çıplak ad-soyad VAR (pii_gate kaçırır — GÜNCELLEME 5/6
    # bloker). FakeNER (YT_NER_FIXTURE, conftest default) 'Ahmet Yılmaz'ı yakalar → cloud
    # REDDEDİLİR (fail-closed; şüphede yerel).
    monkeypatch.delenv("YT_TTS_FIXTURE", raising=False)
    monkeypatch.setenv("YT_TTS_CLOUD", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("YT_PIPER_VOICE_DIR", str(tmp_path / "bos"))

    def _yakala(*a, **k):
        raise AssertionError("KVKK İHLALİ: kişi adlı metin cloud TTS'e gönderildi!")

    monkeypatch.setattr("httpx.post", _yakala)
    state = _state(tmp_path, "Ahmet Yılmaz konferansta yapay zekâ düzenlemelerini anlattı.")
    out = seslendirme_node(state)
    assert out["ses_kaynak"] == "piper"  # NER → yerel (fail-closed)


def test_kvkk_ner_guard_mutasyon_kontrolu(tmp_path, monkeypatch):
    # MUTASYON-KONTROL (Faz 3/4 dersi): NER sinyali sökülürse (kişi tespiti hep False) AYNI
    # metin cloud'a GİDERDİ — üstteki test gerçekten NER guard'ını ölçüyor (vacuous değil).
    monkeypatch.delenv("YT_TTS_FIXTURE", raising=False)
    monkeypatch.setenv("YT_TTS_CLOUD", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class _KorNER:
        def kisi_var_mi(self, metinler: list[str]) -> list[bool]:
            return [False for _ in metinler]

    monkeypatch.setattr("ytcore.router.ner.ner_al", lambda: _KorNER())
    gonderilen: list[str] = []

    class _Yanit:
        content = b"FAKEMP3"

        def raise_for_status(self) -> None: ...

    def _post(*a, **k):
        gonderilen.append(str(k.get("json", {}).get("input", "")))
        return _Yanit()

    monkeypatch.setattr("httpx.post", _post)
    state = _state(tmp_path, "Ahmet Yılmaz konferansta yapay zekâ düzenlemelerini anlattı.")
    out = seslendirme_node(state)
    assert out["ses_kaynak"] == "cloud" and gonderilen  # guard'sız ad cloud'a giderdi (kanıt)
