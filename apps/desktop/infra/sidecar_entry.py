from __future__ import annotations

import os
import sys

VARSAYILAN_HTTP_PORT = 8765


def _http_portu() -> int:
    """GUI HTTP portu: RASATHANE_SIDECAR_PORT verilirse o, yoksa 8765.

    Sabit 8765 tek çakışma noktasıydı: portu başka bir uygulama tutuyorsa sidecar
    WinError 10048 ile ölüyor ve arayüz yalnız 'Motor başlatılamadı' gösteriyordu.
    Electron kabuğu açılışta boş bir port seçip bu env ile sürer; geçersiz değer
    sessizce yok sayılmaz, stderr'e yazılır (log'da görünür) ve varsayılana düşer.
    """
    ham = os.environ.get("RASATHANE_SIDECAR_PORT", "").strip()
    if not ham:
        return VARSAYILAN_HTTP_PORT
    try:
        port = int(ham)
    except ValueError:
        port = -1
    if not 1024 <= port <= 65535:
        print(
            f"[uyari] RASATHANE_SIDECAR_PORT gecersiz: {ham!r} — "
            f"{VARSAYILAN_HTTP_PORT} kullanilacak.",
            file=sys.stderr,
        )
        return VARSAYILAN_HTTP_PORT
    return port


def _phoenix_baslat() -> None:
    """Arize Phoenix local trace'i yalnız açık opt-in ile register et.

    Collector yokken exporter retry'larının analiz süresini uzatmaması için varsayılan kapalıdır.
    YT_PHOENIX=1 açıkça verildiğinde batch exporter kullanılır.
    """
    if os.environ.get("YT_PHOENIX", "0") != "1":
        return
    try:
        from ytcore.obs.tracer import phoenix_tracer_kur

        phoenix_tracer_kur()
    except Exception as e:  # noqa: BLE001 — gözlemlenebilirlik kritik yol değil
        print(f"[uyari] Phoenix tracer baslatilamadi (graceful): {e}", file=sys.stderr)


def _fixture_guard() -> None:
    """Üretim (http/stdio) modunda DIŞARIDAN sızan test fixture env'lerini etkisizleştir.

    YT_*_FIXTURE ve RASATHANE_SOURCE_FIXTURE seam'leri YALNIZ hermetik
    test ve selftest içindir. Üretim sunucusunda (GUI/MCP) set olurlarsa motor gerçek video
    yerine KANNED fixture içeriği üretir — kullanıcı 'alakasız/rezalet' sonuç alır ve hiçbir
    uyarı görmez (gerçek URL dosyaya yazıldığı için sahte olduğu bile belli olmaz). KÖK NEDEN
    DÜZELTMESİ (fail-loud): varsayılan = pop + gürültülü stderr uyarısı (gerçek işe zorla);
    bilinçli demo için YT_ALLOW_FIXTURES=1. selftest BU FONKSİYONU ÇAĞIRMAZ (kendi fixture'larını
    mod-branch'inde set eder) → etkilenmez.
    """
    aktif = sorted(
        k
        for k in os.environ
        if "FIXTURE" in k and (k.startswith("YT_") or k.startswith("RASATHANE_"))
    )
    if not aktif:
        return
    if os.environ.get("YT_ALLOW_FIXTURES") == "1":
        print(
            f"[UYARI] Fixture env BİLİNÇLİ aktif (YT_ALLOW_FIXTURES=1): {aktif} — "
            "GERÇEK video İŞLENMEYECEK, kanned test içeriği döner.",
            file=sys.stderr,
        )
        return
    for k in aktif:
        os.environ.pop(k, None)
    print(
        f"[UYARI] Test fixture env'leri saptandı ve YOK SAYILDI: {aktif}. Üretimde (GUI/MCP) "
        "SET OLMAMALI — aksi halde gerçek video yerine sahte içerik üretilir. Gerçek mod aktif.",
        file=sys.stderr,
    )


def main() -> int:
    """Sidecar giriş: mod seçici (stdio | http | selftest)."""
    mod = sys.argv[1] if len(sys.argv) > 1 else "stdio"

    if mod not in ("stdio", "http", "selftest"):
        # Bilinmeyen argv stdio'ya DÜŞMESİN (review tur-1 HIGH): frozen exe'de bir subprocess
        # yanlışlıkla exe'yi '-m ...' ile spawn ederse child burada ANINDA rc=2 ile ölür
        # (fail-closed hızlı; 180s stdio-blok + stdin çalma yok).
        print(f"bilinmeyen mod: {mod} (stdio|http|selftest)", file=sys.stderr)
        return 2

    if mod == "selftest":
        # exe smoke: çekirdek import + stub analiz (cloud çağrısı 0)
        import json
        import tempfile
        from pathlib import Path

        from ytcore.pipeline.api import analiz_et

        with tempfile.TemporaryDirectory() as d:
            os.environ["YT_OUTPUT_BASE"] = d
            os.environ["YT_FORCE_COMPLEX"] = "0"
            os.environ["YT_OLLAMA_PING"] = "0"  # smoke hızlı: ping kanıtı dedicated testlerde
            # Faz 1: fixture-clean → ağsız/torch'suz deterministik transkript (frozen exe
            # içine kod inject edilemez; env ile sürülür). Gerçek yt-dlp/ASR yolu Faz 5 exe-e2e.
            os.environ["YT_TRANSCRIPT_FIXTURE"] = "clean"
            # Faz 2: içerik hattı (çeviri/döküm/özet) fake LLM/embed ile (torch'suz/Ollama'sız
            # → exe selftest 02/03/04 üretimini de doğrular, #2 değişmez exe'de korunur).
            os.environ["YT_LLM_FIXTURE"] = "1"
            os.environ["YT_EMBED_FIXTURE"] = "1"
            # Faz 4: harita ASSET BUNDLE GERÇEK doğrulanır — FakeLLM (YT_LLM_FIXTURE) geçerli
            # ağaç JSON üretir → markmap_html() → _asset() frozen exe'de d3/markmap-view
            # bundle'ını OKUR → 05_zihin-haritasi.html yazar (fixture bunu sessizce KAPATMAZ;
            # markmap_html çağrısı fixture'dan geçer). TTS FakeTTS (piper/onnxruntime exe-DIŞI —
            # ASR deseni, <200MB korunur).
            os.environ["YT_TTS_FIXTURE"] = "1"
            # Faz 5: NER hermetik (FakeNER) — frozen exe'de harici python spawn edilmez
            # (SubprocessNER zaten fail-closed ama selftest deterministik kalmalı). Gerçek
            # NER dev-env'de @ner; cloud verdict anahtarsız env-gated (0-cloud korunur).
            os.environ["YT_NER_FIXTURE"] = "1"
            # Selftest HERMETİK (review tur-1 MED): makinede dış-servis anahtarı/opt-in'i
            # olsa bile selftest ağa çıkmaz ve assert'ler deterministik kalır (web fixture;
            # cloud TTS/verdict opt-in'leri ve anahtarlar temizlenir).
            os.environ["YT_WEBSEARCH_FIXTURE"] = "1"
            for k in (
                "SERPER_API_KEY",
                "TAVILY_API_KEY",
                "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY",
                "YT_TTS_CLOUD",
                "YT_CLOUD_VERDICT",
            ):
                os.environ.pop(k, None)
            # Faz 3: index/bellek GERÇEK (LanceDB — fixture set ETME) → frozen exe'de bundle'lı
            # lancedb'nin çalıştığını DOĞRULAR (exe-build mock'un göremediğini yakalar). Web =
            # gerçek Serper (anahtar yok → web_yok, fact-check yine 06 üretir). LLM/embed fake.
            s = analiz_et(
                url="https://youtu.be/selftest",
                konu="genel",
                thread_id="selftest",
                checkpoint_dir=Path(d),
            )
            assert not s.stub and s.cloud_cagrisi_sayisi == 0
            assert s.transkript_durumu == "altyazi"
            assert Path(s.klasor).is_dir()
            assert (Path(s.klasor) / "01_transcript_orijinal.md").is_file()
            # Faz 2 çıktıları (kaynak TR → çeviri atlanır, döküm+özet üretilir)
            assert (Path(s.klasor) / "03_dokum.md").is_file()
            assert (Path(s.klasor) / "04_ozet.md").is_file()
            assert s.dokum_segment_sayisi >= 1
            # Faz 3 çıktıları (gerçek LanceDB index frozen exe'de → 06/07/08 + puan + index ekle)
            assert (Path(s.klasor) / "06_fact-check.md").is_file()
            assert (Path(s.klasor) / "07_kisisel-analiz.md").is_file()
            assert (Path(s.klasor) / "08_degerleme.md").is_file()
            assert s.degerleme_puani is not None
            assert s.index_eklendi is True  # gerçek LanceDB write frozen exe'de çalıştı
            # Faz 4 çıktıları (harita GERÇEK markmap bundle frozen exe'de; ses FakeTTS WAV)
            assert (Path(s.klasor) / "05_zihin-haritasi.html").is_file()
            assert (Path(s.klasor) / "04_ozet.wav").is_file()
            assert s.harita_durum == "uretildi"  # markmap bundle frozen exe'de render etti
            assert s.ses_durum == "uretildi"  # FakeTTS WAV (piper exe-dışı, selftest fixture)
            assert s.cloud_cagrisi_sayisi == 0
            # Faz 5: gerçek complexity sınıflandırma frozen exe'de çalıştı + maliyet alanları 0
            # (anahtarsız: dürüst 0-cloud — stub kalktı, sayaç yalnız gerçek çağrı sayar).
            assert s.hedef in ("local", "cloud") and s.karmasiklik != ""
            assert s.cloud_girdi_token == 0 and s.cloud_cikti_token == 0
            print(
                json.dumps(
                    {
                        "selftest": "ok",
                        "durum": s.transkript_durumu,
                        "dokum_segment": s.dokum_segment_sayisi,
                        "degerleme_puani": s.degerleme_puani,
                        "index_eklendi": s.index_eklendi,
                        "harita_durum": s.harita_durum,
                        "ses_durum": s.ses_durum,
                        "klasor": s.klasor,
                    }
                )
            )
        return 0

    if mod == "http":
        _fixture_guard()  # GUI gerçek video işlesin (sızan fixture sessizce onurlandırılmasın)
        _phoenix_baslat()
        from ytmcp.server import gui_http_middleware, mcp

        port = _http_portu()
        print(f"[bilgi] GUI HTTP portu: {port}", file=sys.stderr)
        mcp.run(
            transport="http",
            host="127.0.0.1",
            port=port,
            middleware=gui_http_middleware(),
        )
        return 0

    # stdio (Claude Desktop / Code)
    _fixture_guard()  # MCP gerçek video işlesin (fixture sızıntısı = sessiz kanned çıktı)
    _phoenix_baslat()
    from ytmcp.server import mcp

    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
