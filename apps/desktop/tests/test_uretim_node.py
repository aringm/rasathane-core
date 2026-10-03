from __future__ import annotations

from pathlib import Path

from ytcore.uretim.node import harita_node, seslendirme_node


def _temel_state(tmp_path: Path, govde="Sözleşme hukuku irade beyanı tazminat üzerinedir."):
    klasor = tmp_path / "analiz"
    klasor.mkdir()
    return {
        "ozet": {"detay": govde},
        "metadata": {
            "video_url": "https://youtu.be/abc",
            "video_id": "abc",
            "baslik": "B",
            "anadil": "tr",
            "kanal": "K",
            "konu": "genel",
            "uretici_slug": "k",
            "video_slug": "abc",
            "analiz_tarihi": "2026-06-08",
        },
        "klasor": str(klasor),
        "sonuc": {},
        "transkript_metni": govde,
    }


def test_harita_node_html_yazar(tmp_path, monkeypatch):
    monkeypatch.setenv("YT_LLM_FIXTURE", "1")
    state = _temel_state(tmp_path)
    out = harita_node(state)
    assert out["harita_durum"] == "uretildi"
    assert out["harita_dugum_sayisi"] >= 2
    assert (tmp_path / "analiz" / "05_zihin-haritasi.html").exists()
    assert out["sonuc"]["harita_durum"] == "uretildi"  # sonuc patch'lendi


def test_harita_node_icerik_yok(tmp_path, monkeypatch):
    monkeypatch.setenv("YT_LLM_FIXTURE", "1")
    state = _temel_state(tmp_path, govde="")
    state["ozet"] = {}
    state["transkript_metni"] = ""
    out = harita_node(state)
    assert out["harita_durum"] == "icerik_yok"
    assert not (tmp_path / "analiz" / "05_zihin-haritasi.html").exists()


def test_seslendirme_node_wav_yazar(tmp_path, monkeypatch):
    monkeypatch.setenv("YT_TTS_FIXTURE", "1")
    state = _temel_state(tmp_path)
    state["ozet"] = {"kisa": "Sözleşme hukuku önemlidir."}
    out = seslendirme_node(state)
    assert out["ses_durum"] == "uretildi"
    assert (tmp_path / "analiz" / "04_ozet.wav").exists()
    assert out["sonuc"]["ses_durum"] == "uretildi"


def test_seslendirme_node_pii_piper_secer(tmp_path, monkeypatch):
    # Bu test: PII karar mantığı → hedef uzantı wav (cloud mp3 DEĞİL). YT_TTS_FIXTURE açık
    # olduğundan FakeTTS çalışır; GERÇEK cloud HTTP-engeli testi DEĞİL (o: test_tts_kvkk.py::
    # test_kvkk_pii_ozet_cloud_cagrilmaz — fixture'sız, httpx mock'lu, mutasyon-dayanıklı).
    monkeypatch.setenv("YT_TTS_FIXTURE", "1")
    monkeypatch.setenv("YT_TTS_CLOUD", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    state = _temel_state(tmp_path)
    state["ozet"] = {"kisa": "Müvekkil ahmet@example.com adresinden ulaşılabilir."}
    out = seslendirme_node(state)
    assert out["ses_durum"] == "uretildi"
    assert (tmp_path / "analiz" / "04_ozet.wav").exists()  # piper yolu = wav (cloud mp3 değil)
    assert not (tmp_path / "analiz" / "04_ozet.mp3").exists()
