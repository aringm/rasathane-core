from __future__ import annotations

from ytcore.uretim.markmap import markmap_html


def _veri():
    return {
        "content": "Kök",
        "children": [
            {"content": "Dal A", "children": []},
            {"content": 'Dal B <a href="https://youtu.be/x?t=10s">⏱</a>', "children": []},
        ],
    }


def test_markmap_html_veri_gomulu():
    h = markmap_html(_veri(), baslik="Test Harita")
    assert "Test Harita" in h
    assert "Kök" in h and "Dal A" in h
    assert "<svg" in h and "Markmap.create" in h


def test_markmap_html_offline_cdn_yok():
    # Değişmez: standalone offline → harici <script src> YOK (tüm JS inline gömülü).
    h = markmap_html(_veri(), baslik="X").lower()
    assert "<script src=" not in h  # harici script yüklemesi yok
    assert "cdn.jsdelivr" not in h and "unpkg.com" not in h  # CDN bağımlılığı yok


def test_markmap_html_d3_view_inline():
    h = markmap_html(_veri(), baslik="X")
    assert "markmap" in h.lower()  # markmap-view inline
    assert "d3" in h  # d3 inline


def test_markmap_html_deriveoptions_kullanir():
    # Faz 6 (#2) regresyon: color ARRAY'i create()'e HAM verince markmap 0 düğüm çizer
    # (canlı kanıt). deriveOptions ŞART (array→scaleOrdinal fonksiyonu). Bu guard onu pinler.
    h = markmap_html(_veri(), baslik="X")
    assert "deriveOptions(" in h  # ham color array değil, deriveOptions üzerinden
    assert "initialExpandLevel" in h  # derin açılım (alt-ağaçlar görünür)


def test_markmap_html_baslik_html_escape():
    # Faz 6 (denetim): başlık DIŞ-veri (YouTube) → HTML-escape (overlay/<title> enjeksiyonu).
    h = markmap_html(_veri(), baslik='<script>x</script> "tırnak" & <b>')
    assert "<script>x</script>" not in h  # ham script enjekte edilmedi
    assert "&lt;script&gt;" in h  # escape edildi
