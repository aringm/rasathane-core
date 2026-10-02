from __future__ import annotations

from pathlib import Path

from ytcore.uretim.tts import FakeTTS, PiperTTS, seslendirme_karari, tts_al


def test_tts_al_fixture(monkeypatch):
    monkeypatch.setenv("YT_TTS_FIXTURE", "1")
    assert isinstance(tts_al("piper"), FakeTTS)
    assert isinstance(tts_al("cloud"), FakeTTS)


def test_tts_al_piper_subprocess(monkeypatch):
    # Fixture YOKsa piper yolu ARTIK ayrı-proses (SubprocessPiperTTS) — frozen GUI'de de sentez.
    from ytcore.uretim.tts import SubprocessPiperTTS

    monkeypatch.delenv("YT_TTS_FIXTURE", raising=False)
    assert isinstance(tts_al("piper"), SubprocessPiperTTS)


def test_fake_tts_dosya_uretir(tmp_path):
    s = FakeTTS().seslendir("Merhaba dünya.", tmp_path / "04_ozet.wav")
    assert s.durum == "uretildi"
    assert (tmp_path / "04_ozet.wav").exists()
    assert (tmp_path / "04_ozet.wav").stat().st_size > 0  # boş≠başarı: gerçek dosya


def test_fake_tts_bos_metin_icerik_yok(tmp_path):
    s = FakeTTS().seslendir("   ", tmp_path / "o.wav")
    assert s.durum == "icerik_yok"
    assert not (tmp_path / "o.wav").exists()


def test_seslendirme_karari_kvkk_fail_closed():
    # PII varsa → her durumda PIPER (cloud reddedilir). Şüphede yerel.
    assert seslendirme_karari(pii_var=True, cloud_acik=True, anahtar_var=True)[0] == "piper"
    # PII-temiz + cloud açık + anahtar var → cloud serbest.
    assert seslendirme_karari(pii_var=False, cloud_acik=True, anahtar_var=True)[0] == "cloud"
    # PII-temiz ama cloud kapalı → piper (bilinçli opt-in yok).
    assert seslendirme_karari(pii_var=False, cloud_acik=False, anahtar_var=True)[0] == "piper"
    # PII-temiz, cloud açık ama anahtar yok → piper (inert).
    assert seslendirme_karari(pii_var=False, cloud_acik=True, anahtar_var=False)[0] == "piper"


def test_piper_ses_modeli_yok_durust(tmp_path, monkeypatch):
    # Voice modeli yoksa → 'ses_modeli_yok' (sessiz başarı YOK), çökmez.
    monkeypatch.setenv("YT_PIPER_VOICE_DIR", str(tmp_path / "bos"))
    s = PiperTTS().seslendir("Merhaba.", tmp_path / "o.wav")
    assert s.durum == "ses_modeli_yok"
    assert not (tmp_path / "o.wav").exists()


def test_cloud_tts_anahtarsiz_inert():
    from ytcore.uretim.tts import CloudTTS

    s = CloudTTS(api_key=None).seslendir("Merhaba.", Path("x.mp3"))
    assert s.durum == "anahtar_yok"  # inert (SerperSearch deseni)
    assert s.kaynak is None


def test_ses_dosyasi_gecerli(tmp_path):
    # boş≠başarı yardımcısı: dosya gerçekten oluştu + boş-değil mi?
    from ytcore.uretim.tts import _ses_dosyasi_gecerli

    assert _ses_dosyasi_gecerli(tmp_path / "yok.wav") is False  # yok
    bos = tmp_path / "bos.wav"
    bos.write_bytes(b"")
    assert _ses_dosyasi_gecerli(bos) is False  # boş
    dolu = tmp_path / "dolu.wav"
    dolu.write_bytes(b"\x00" * 100)
    assert _ses_dosyasi_gecerli(dolu) is True


def test_cloud_tts_bos_yanit_hata(tmp_path, monkeypatch):
    # Cloud 200 döndü ama gövde boş (proxy/truncate) → 'uretildi' DEĞİL 'hata' (boş≠başarı).
    from ytcore.uretim.tts import CloudTTS

    class _Bos:
        content = b""

        def raise_for_status(self) -> None: ...

    monkeypatch.setattr("httpx.post", lambda *a, **k: _Bos())
    s = CloudTTS(api_key="sk-x").seslendir("Merhaba.", tmp_path / "o.mp3")
    assert s.durum == "hata"
    assert not (tmp_path / "o.mp3").exists()  # boş dosya yazılmadı


def test_cloud_tts_kod_hatasi_reraise(tmp_path, monkeypatch):
    # KOD_HATALARI (TypeError) provider sınırında MASKE DEĞİL — görünür çök (node re-raise eder).
    import pytest
    from ytcore.uretim.tts import CloudTTS

    def _bug(*a, **k):
        raise TypeError("kod bug")

    monkeypatch.setattr("httpx.post", _bug)
    with pytest.raises(TypeError):
        CloudTTS(api_key="sk-x").seslendir("Merhaba.", tmp_path / "o.mp3")


def test_cloud_tts_ag_hatasi_graceful(tmp_path, monkeypatch):
    # Ağ/HTTP ham hata (KOD_HATALARI DEĞİL) sınırda graceful → 'hata' durumu.
    import httpx
    from ytcore.uretim.tts import CloudTTS

    def _net(*a, **k):
        raise httpx.ConnectError("ağ kesik")

    monkeypatch.setattr("httpx.post", _net)
    s = CloudTTS(api_key="sk-x").seslendir("Merhaba.", tmp_path / "o.mp3")
    assert s.durum == "hata"


def test_subprocess_piper_ses_modeli_yok_spawn_etmez(tmp_path, monkeypatch):
    # Voice yoksa SPAWN ETMEDEN 'ses_modeli_yok' (boş≠başarı + gereksiz proses yok; KVKK
    # testleri bu erken-dönüşe güvenir).
    import ytcore.uretim.tts as tts_mod
    from ytcore.uretim.tts import SubprocessPiperTTS

    monkeypatch.setenv("YT_PIPER_VOICE_DIR", str(tmp_path / "bos"))

    def _patlasin(*a, **k):
        raise AssertionError("model yokken subprocess spawn EDİLMEMELİ")

    monkeypatch.setattr(tts_mod.subprocess, "run", _patlasin)
    s = SubprocessPiperTTS().seslendir("Merhaba.", tmp_path / "o.wav")
    assert s.durum == "ses_modeli_yok" and not (tmp_path / "o.wav").exists()


def test_subprocess_piper_frozen_self_spawn_guard(tmp_path, monkeypatch):
    # Frozen exe + python==exe → self-spawn (stdio MCP hang, ner.py:122 deseni) ENGELLENİR:
    # spawn etmeden 'piper_kurulu_degil' döner.
    import sys

    import ytcore.uretim.tts as tts_mod
    from ytcore.uretim.tts import SubprocessPiperTTS

    vd = tmp_path / "v"
    vd.mkdir()
    (vd / "tr_TR-dfki-medium.onnx").write_bytes(b"x")
    (vd / "tr_TR-dfki-medium.onnx.json").write_text("{}")
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    def _patlasin(*a, **k):
        raise AssertionError("frozen self-spawn guard subprocess'i ENGELLEMELİ")

    monkeypatch.setattr(tts_mod.subprocess, "run", _patlasin)
    s = SubprocessPiperTTS(python=sys.executable, voice_dir=vd).seslendir(
        "Merhaba.", tmp_path / "o.wav"
    )
    assert s.durum == "piper_kurulu_degil"


def test_subprocess_piper_worker_meta_uretildi(tmp_path, monkeypatch):
    # Spawn + parse yolu: worker'ı taklit eden sahte subprocess meta {"durum":"uretildi"} + geçerli
    # WAV yazar → engine 'uretildi' döner (gerçek piper olmadan spawn/parse mantığını test eder).
    import ytcore.uretim.tts as tts_mod
    from ytcore.uretim.tts import SubprocessPiperTTS

    vd = tmp_path / "v"
    vd.mkdir()
    (vd / "tr_TR-dfki-medium.onnx").write_bytes(b"x")
    (vd / "tr_TR-dfki-medium.onnx.json").write_text("{}")

    def _sahte_run(cmd, **k):
        out = Path(cmd[cmd.index("--out") + 1])
        meta = Path(cmd[cmd.index("--meta") + 1])
        out.write_bytes(b"\x00" * 100)  # geçerli-boyut WAV taklidi
        meta.write_text('{"durum": "uretildi"}', encoding="utf-8")

        class _P:
            returncode = 0
            stderr = ""

        return _P()

    monkeypatch.setattr(tts_mod.subprocess, "run", _sahte_run)
    s = SubprocessPiperTTS(voice_dir=vd).seslendir("Merhaba.", tmp_path / "o.wav")
    assert s.durum == "uretildi" and s.kaynak == "piper"


def test_piper_kurulu_degil_graceful(tmp_path, monkeypatch):
    # review tur-1 HIGH: frozen exe'de piper bundle'da YOK; voice dosyalari VARSA import
    # ModuleNotFoundError = KOD_HATALARI -> analiz cokerdi. Ortam-eksikligi kod-bug degildir:
    # graceful 'piper_kurulu_degil' donmeli.
    import sys

    from ytcore.uretim.tts import PiperTTS

    vd = tmp_path / "voices"
    vd.mkdir()
    (vd / "tr_TR-dfki-medium.onnx").write_bytes(b"x")
    (vd / "tr_TR-dfki-medium.onnx.json").write_text("{}")
    monkeypatch.setitem(sys.modules, "piper", None)  # import -> ImportError simulasyonu
    s = PiperTTS(voice_dir=vd).seslendir("Merhaba dunya.", tmp_path / "o.wav")
    assert s.durum == "piper_kurulu_degil"
