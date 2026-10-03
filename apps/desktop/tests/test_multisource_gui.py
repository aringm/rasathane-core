from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).parents[1] / "gui" / "ui"


def test_cok_kaynak_girdi_ve_spektrum_sozlesmesi() -> None:
    html = (UI / "index.html").read_text(encoding="utf-8")

    assert "Kaynak bağlantısı" in html
    assert "YouTube bağlantısı" not in html
    for tur in ("youtube", "github", "arxiv", "reddit", "huggingface", "web"):
        assert f'data-kaynak="{tur}"' in html
    assert 'id="kaynak-cip"' in html
    assert 'id="kaynak-sinyalleri"' in html
    assert 'id="kutuphane-kaynak"' in html


def test_html_idleri_tekil() -> None:
    html = (UI / "index.html").read_text(encoding="utf-8")
    ids = re.findall(r'\bid="([^"]+)"', html)
    tekrar = sorted({id_ for id_ in ids if ids.count(id_) > 1})

    assert not tekrar


def test_js_kaynak_algisi_generic_render_ve_xss_guvenligi() -> None:
    js = (UI / "src" / "main.js").read_text(encoding="utf-8")

    assert "function kaynakTuruBul" in js
    assert "function kaynakAlgisiniGuncelle" in js
    assert "function renderKaynakSinyalleri" in js
    assert "kaynak_metrikleri" in js
    assert "kaynak_sahibi" in js
    assert "kutuphane-kaynak" in js
    assert 'kaynakTuru === "youtube" && asrEl.checked' in js
    assert ".innerHTML" not in js


def test_demo_alti_kaynakta_sidecarsiz_akis_sunar() -> None:
    demo = (UI / "src" / "demo-veri.js").read_text(encoding="utf-8")
    js = (UI / "src" / "main.js").read_text(encoding="utf-8")

    for tur in ("youtube", "github", "arxiv", "reddit", "huggingface", "web"):
        assert re.search(rf"^  {tur}: \{{", demo, re.MULTILINE)
    assert "DEMO_KUTUPHANE" in demo
    assert "DEMO_AYARLAR" in demo
    assert "demoVerisi(kaynakTuru)" in js
    assert "demoAktif && demoPaket" in js


def test_genel_web_kaynagi_iframee_yuklenmez() -> None:
    js = (UI / "src" / "main.js").read_text(encoding="utf-8")
    html = (UI / "index.html").read_text(encoding="utf-8")

    # Uzak URL/HTML çalıştırılmaz. IPC byte'ları trusted SVG/canvas renderer'a gider.
    assert "`${SIDECAR}/gui/dosya" in js
    frame = js.split("async function frameDosyaYukle", 1)[1].split("function frameBirak", 1)[0]
    assert "await sidecarFetch" in frame
    assert "await response.arrayBuffer()" in frame
    assert "await renderArtifact" in frame
    assert "kanonikUrl" not in frame
    assert "clearArtifact" in frame
    assert not re.search(r"\.src\s*=\s*kanonikUrl", js)
    frames = re.findall(r"<iframe\b([^>]+)>", html, re.DOTALL)
    assert len(frames) == 0
    assert "srcdoc" not in js
    assert 'id="harita-cerceve"' in html and 'id="izleyici-cerceve"' in html
    assert "window.rasathane.request" in js
