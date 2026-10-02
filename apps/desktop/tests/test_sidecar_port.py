"""Motor portu sözleşmesi: sabit 8765 çakışması 'Motor başlatılamadı' üretmesin.

Kök neden (2026-08-06): 8765'i başka bir uygulama tutunca sidecar WinError 10048 ile
ölüyor, arayüz yalnız "Motor başlatılamadı" gösteriyordu. Artık kabuk boş port seçer,
sidecar'a env ile sürer, arayüze query ile bildirir. Üç taraf (Python/Electron/UI/CSP)
aynı aday listesinde kalmalı — bu testler listeleri ayrışırsa kırılır.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KOK / "infra"))

import sidecar_entry  # noqa: E402

ADAY_PORTLAR = [8765, 8766, 8767, 8768]


def test_port_env_yoksa_varsayilan(monkeypatch):
    monkeypatch.delenv("RASATHANE_SIDECAR_PORT", raising=False)
    assert sidecar_entry._http_portu() == 8765


def test_port_env_gecerliyse_onurlandirilir(monkeypatch):
    monkeypatch.setenv("RASATHANE_SIDECAR_PORT", "8766")
    assert sidecar_entry._http_portu() == 8766


def test_gecersiz_port_varsayilana_duser_ve_uyarir(monkeypatch, capsys):
    for ham in ("abc", "80", "70000", "-1", ""):
        monkeypatch.setenv("RASATHANE_SIDECAR_PORT", ham)
        assert sidecar_entry._http_portu() == 8765
    # boş string sessiz (env set edilmemiş gibi), diğerleri stderr'e uyarı yazmalı
    assert capsys.readouterr().err.count("RASATHANE_SIDECAR_PORT gecersiz") == 4


def test_electron_kabugu_bos_port_secip_sidecara_surer():
    main = (KOK / "gui/electron/main.cjs").read_text(encoding="utf-8")
    adaylar = re.search(r"const ADAY_PORTLAR = \[([^\]]+)\]", main)
    assert adaylar, "kabukta ADAY_PORTLAR tanımı yok"
    assert [int(p) for p in adaylar.group(1).split(",")] == ADAY_PORTLAR
    assert "RASATHANE_SIDECAR_PORT: String(port)" in main
    assert "nodeNet.createServer()" in main  # port gerçekten bind denenerek seçiliyor
    assert "?sidecarPort=${port}" in main  # seçilen port arayüze bildiriliyor


def test_arayuz_ve_csp_aday_portlarla_uyumlu():
    js = (KOK / "gui/ui/src/main.js").read_text(encoding="utf-8")
    html = (KOK / "gui/ui/index.html").read_text(encoding="utf-8")

    js_adaylar = re.search(r"const ADAY_PORTLAR = \[([^\]]+)\]", js)
    assert js_adaylar, "arayüzde ADAY_PORTLAR tanımı yok"
    assert [int(p) for p in js_adaylar.group(1).split(",")] == ADAY_PORTLAR

    csp = re.search(r'Content-Security-Policy"\s+content="([^"]+)"', html)
    assert csp, "index.html'de CSP yok"
    connect = re.search(r"connect-src ([^;]+);", csp.group(1))
    assert connect
    for port in ADAY_PORTLAR:
        assert f"http://127.0.0.1:{port}" in connect.group(1), (
            "loopback preview seçilen portu kullanabilmeli"
        )
    frame = re.search(r"frame-src ([^;]+);", csp.group(1))
    assert frame and frame.group(1) == "blob:"
    assert "http:" not in frame.group(1) and "https:" not in frame.group(1)
    # Paket renderer'ı preview CSP iznini kullanarak ağ açamaz; main tüm ağı engeller.
    main = (KOK / "gui/electron/main.cjs").read_text(encoding="utf-8")
    assert "webRequest.onBeforeRequest" in main and "cancel: true" in main
    for scheme in ("http://*/*", "https://*/*", "ws://*/*", "wss://*/*"):
        assert scheme in main
