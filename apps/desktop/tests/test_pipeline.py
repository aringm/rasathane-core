from __future__ import annotations

import pytest
from ytcore.local.ollama_ping import ollama_erisilebilir
from ytcore.obs.tracer import bellek_tracer_kur
from ytcore.pipeline.api import analiz_et


def test_temiz_metin_altyazi_sonuc(tmp_output_base, tmp_path, monkeypatch):
    # Faz 1: fixture-clean altyazı → gerçek transkript (stub DEĞİL) + 01_transcript yazılır.
    monkeypatch.setenv("YT_FORCE_COMPLEX", "0")
    bellek_tracer_kur()
    from pathlib import Path

    sonuc = analiz_et(
        url="https://youtu.be/abc", konu="genel", thread_id="t1", checkpoint_dir=tmp_path
    )
    assert sonuc.stub is False
    assert sonuc.transkript_durumu == "altyazi"
    assert sonuc.cloud_cagrisi_sayisi == 0
    assert Path(sonuc.klasor).is_dir()
    assert (Path(sonuc.klasor) / "01_transcript_orijinal.md").exists()


def test_gui_icerik_sozlesmesi_sonuca_tasinir(tmp_output_base, tmp_path, monkeypatch):
    # Faz 9: GUI inline gösterim — özet/kişisel/fact-check METNİ sonuçta yaşamalı (dosyaya
    # yazılanla aynı kaynak; boş≠başarı: içerik üretildiyse alanlar dolu). Regresyon kilidi.
    monkeypatch.setenv("YT_FORCE_COMPLEX", "0")
    sonuc = analiz_et(
        url="https://youtu.be/abc", konu="hukuk", thread_id="ticerik", checkpoint_dir=tmp_path
    )
    # özet üretildi → 3 katman da (kisa/orta/detay) sonuçta (04_ozet.md ile aynı kaynak — ozet dict)
    assert sonuc.ozet_kisa.strip() and sonuc.ozet_orta.strip() and sonuc.ozet_detay.strip()
    # kişisel analiz metni taşındı (durum 'uretildi' ile tutarlı)
    assert sonuc.kisisel_durum != "uretildi" or sonuc.kisisel_analiz.strip()
    # fact-check iddialar TİPLİ liste (FactIddia) — GUI kart render; her birinde iddia+karar var
    assert isinstance(sonuc.factcheck_iddialar, list)
    assert len(sonuc.factcheck_iddialar) == sonuc.factcheck_iddia_sayisi
    for it in sonuc.factcheck_iddialar:
        assert it.iddia.strip() and it.karar.strip()


def test_hata_detaylari_ve_motor_sonuca_tasinir(tmp_output_base, tmp_path, monkeypatch):
    """2026-08-24 saha dersi: node'lar *_hata'yı state'e yazıyor ama AnalizSonucu'na hiç
    taşınmıyordu → GUI yalnız 'Hata' gösteriyordu, kök neden kayıptı. Artık her *durum='hata'
    yanında detay metni sonuca + 00_index.json'a (motor kökeniyle) taşınır."""
    import json
    from pathlib import Path

    class _PatlayanEmbed:
        def embed(self, metinler):  # noqa: ANN001 - stub
            raise RuntimeError("bge-m3 sunucusu 500 döndü (simülasyon)")

    monkeypatch.setattr("ytcore.intel.node.embedding_al", lambda: _PatlayanEmbed())
    sonuc = analiz_et(
        url="https://youtu.be/abc", konu="genel", thread_id="thata", checkpoint_dir=tmp_path
    )
    # degerleme graceful 'hata' + DETAY sonuca taşındı (önceden alan yoktu)
    assert sonuc.degerleme_durum == "hata"
    assert "500" in sonuc.degerleme_hata
    # Hata olmayan alanlar boş string (durum=hata ⇔ detay dolu sözleşmesi)
    assert sonuc.kisisel_durum != "hata" or sonuc.kisisel_hata
    assert sonuc.factcheck_durum != "hata" or sonuc.factcheck_hata
    # Motor kökeni doldu (kullanıcı isteği: hangi model/araç görünür)
    assert sonuc.motor["backend"] in ("llamacpp", "ollama")
    assert sonuc.motor["llm_model"]
    assert sonuc.motor["embedding_model"]
    # 00_index.json'da da motor bloğu var (kalıcı köken kanıtı)
    index_json = json.loads((Path(sonuc.klasor) / "00_index.json").read_text(encoding="utf-8"))
    assert index_json["motor"]["backend"] == sonuc.motor["backend"]
    assert index_json["motor"]["llm_model"] == sonuc.motor["llm_model"]
    # Kapak md'de görünür motor satırı
    kapak = (Path(sonuc.klasor) / "00_kapak.md").read_text(encoding="utf-8")
    assert "Motor:" in kapak and sonuc.motor["llm_model"] in kapak


def test_local_ping_hatasi_analizi_cokertmez(monkeypatch):
    # HIGH (denetim): _local_ping_node TANI amaçlı (ollama_ping_ms). Ollama ayakta ama
    # chat-model yok / HTTP hatası → ollama_ping() RuntimeError fırlatır; node bunu YUTMALI
    # (analizi çökertmemeli), ms=None döndürmeli. Guard silinse bu test KIRMIZI olur.
    import ytcore.pipeline.graph as g

    monkeypatch.setenv("YT_OLLAMA_PING", "1")
    monkeypatch.setattr(g, "ollama_erisilebilir", lambda: True)

    def _patla() -> object:
        raise RuntimeError("Ollama'da kullanılabilir chat modeli yok")

    monkeypatch.setattr(g, "ollama_ping", _patla)
    out = g._local_ping_node({"url": "https://youtu.be/x"})  # exception YOK
    assert out == {"ollama_ping_ms": None}


def test_pii_transkriptte_local_0_cloud(tmp_output_base, tmp_path, monkeypatch):
    # Faz 1 değişmez #1: PII GERÇEK transkript metninde (fixture-pii) + COMPLEX ->
    # gate yine de local'e zorlar, cloud 0 (fail-closed, gerçek metinle kanıt).
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "pii")
    monkeypatch.setenv("YT_FORCE_COMPLEX", "1")
    sonuc = analiz_et(
        url="https://youtu.be/abc", konu="genel", thread_id="t2", checkpoint_dir=tmp_path
    )
    assert sonuc.pii_tespit is True
    assert sonuc.cloud_cagrisi_sayisi == 0


def test_cloud_yolu_calisinca_hedef_cloud_sayac_durust(tmp_output_base, tmp_path, monkeypatch):
    # PII-temiz transkript (fixture-clean) + COMPLEX -> routing kararı CLOUD (gate'in PII'de
    # bunu kestiğini kanıtlayan kontrast testi — artık hedef alanından). Faz 5: stub kalktı,
    # sayaç yalnız GERÇEK CloudClient çağrısı sayar; anahtarsız koşuda 0 (dürüst 0-cloud).
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "clean")
    monkeypatch.setenv("YT_FORCE_COMPLEX", "1")
    sonuc = analiz_et(
        url="https://youtu.be/abc", konu="genel", thread_id="t3", checkpoint_dir=tmp_path
    )
    assert sonuc.pii_tespit is False
    assert sonuc.hedef == "cloud"  # routing kararı (kontrast: PII testinde local)
    assert sonuc.cloud_cagrisi_sayisi == 0  # gerçek çağrı YOK (anahtar yok — env-gated)


def test_altyazi_yok_asr_izinsiz_sormali(tmp_output_base, tmp_path, monkeypatch):
    # DoD: altyazı yoksa & asr_izin yoksa SESSİZ Whisper YOK -> 'altyazi_yok'.
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "altyazi_yok")
    sonuc = analiz_et(
        url="https://youtu.be/abc", konu="genel", thread_id="t4", checkpoint_dir=tmp_path
    )
    assert sonuc.transkript_durumu == "altyazi_yok"


def test_icerik_yokken_cloud_cagrilmaz(tmp_output_base, tmp_path, monkeypatch):
    # Review M1: altyazi_yok + COMPLEX -> analiz edilecek içerik YOK -> cloud ARMING etme.
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "altyazi_yok")
    monkeypatch.setenv("YT_FORCE_COMPLEX", "1")
    sonuc = analiz_et(
        url="https://youtu.be/abc", konu="genel", thread_id="t5", checkpoint_dir=tmp_path
    )
    assert sonuc.transkript_durumu == "altyazi_yok"
    assert sonuc.cloud_cagrisi_sayisi == 0  # içerik yokken cloud çağrısı yok


def test_bos_altyazi_sessiz_basari_degil(tmp_output_base, tmp_path, monkeypatch):
    # Review HIGH: track var ama boş-temizlenir -> 'altyazi' başarısı raporlanMAMALI.
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "bos")
    sonuc = analiz_et(
        url="https://youtu.be/abc", konu="genel", thread_id="t6", checkpoint_dir=tmp_path
    )
    assert sonuc.transkript_durumu == "altyazi_yok"
    assert sonuc.transkript_karakter == 0


def test_fetch_hatasi_graceful(tmp_output_base, tmp_path, monkeypatch):
    # Review M5/spec §8: ağ/erişim hatası -> çökme YOK, durum='hata', klasör+index yazılır.
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "hata")
    from pathlib import Path

    sonuc = analiz_et(
        url="https://youtu.be/silinmis", konu="genel", thread_id="t7", checkpoint_dir=tmp_path
    )
    assert sonuc.transkript_durumu == "hata"
    assert sonuc.cloud_cagrisi_sayisi == 0
    assert Path(sonuc.klasor).is_dir()
    assert (Path(sonuc.klasor) / "01_transcript_orijinal.md").exists()


def test_na_duration_transkripti_kaybetmez(tmp_output_base, tmp_path, monkeypatch):
    # Re-review R1: duration='NA' başarılı transkripti 'hata' yapMAMALI (regresyon).
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "na")
    sonuc = analiz_et(
        url="https://youtu.be/canli", konu="genel", thread_id="t8", checkpoint_dir=tmp_path
    )
    assert sonuc.transkript_durumu == "altyazi"  # transkript korundu, 'hata' değil
    assert sonuc.transkript_karakter > 0
    assert sonuc.index.sure_sn is None  # NA -> None (çökmeden)


def test_kod_hatasi_maskelenmez(tmp_output_base, tmp_path, monkeypatch):
    # Re-review R4: gerçek kod hatası (AttributeError) 'video erişilemedi' gibi
    # MASKELENMEMELİ -> görünür çök (debug edilebilir).
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "kod_bug")
    import pytest

    with pytest.raises(AttributeError):
        analiz_et(url="https://youtu.be/x", konu="genel", thread_id="t9", checkpoint_dir=tmp_path)


@pytest.mark.skipif(not ollama_erisilebilir(), reason="Ollama erişilemez")
def test_pipeline_ollama_entegrasyonu(tmp_output_base, tmp_path, monkeypatch):
    # Pipeline'ın local inference yolunu GERÇEKTEN çağırdığını kanıtla (round-trip).
    monkeypatch.setenv("YT_OLLAMA_PING", "1")
    s = analiz_et(
        url="https://youtu.be/ollama", konu="genel", thread_id="oint", checkpoint_dir=tmp_path
    )
    assert s.ollama_ping_ms is not None and s.ollama_ping_ms >= 0


def test_resume_state_diskten_devam_ediyor(tmp_output_base, tmp_path):
    # GERÇEK restart kanıtı: analiz_et conn'u kapatır; TAZE checkpointer aynı db'den
    # state'i okuyabilmeli (sidecar restart sonrası thread_id devam eder).
    analiz_et(url="https://youtu.be/resume", thread_id="tr", checkpoint_dir=tmp_path)
    assert (tmp_path / "checkpoints.sqlite").exists()

    # Yeni bir checkpointer + graph (ayrı proses simülasyonu) state'i bulmalı
    from ytcore.pipeline.checkpoint import get_checkpointer
    from ytcore.pipeline.graph import graph_olustur

    cp = get_checkpointer(tmp_path / "checkpoints.sqlite")
    try:
        app = graph_olustur(cp)
        st = app.get_state(config={"configurable": {"thread_id": "tr"}})
        assert st.values  # persist edilmiş state var
        assert st.values.get("url") == "https://youtu.be/resume"
    finally:
        cp.conn.close()


def test_analiz_commit_pipeline_uzerinden(tmp_output_base, tmp_path):
    # Adversarial review #2/#5: commit invariant'ı pipeline'dan çalışmalı (izole değil).
    import subprocess

    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_output_base, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=tmp_output_base, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_output_base, check=True)

    s = analiz_et(url="https://youtu.be/commit", thread_id="cm", checkpoint_dir=tmp_path)
    assert s.commit_yapildi is True
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=tmp_output_base, capture_output=True, text=True
    )
    assert "analiz:" in log.stdout
