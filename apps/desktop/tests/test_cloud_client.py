from __future__ import annotations

import httpx
import pytest
from ytcore.router.cloud_client import (
    CloudAnahtarYok,
    CloudClient,
    CloudYanit,
    KVKKEgressEngellendi,
)


def _yanit_json():
    return {
        "content": [{"type": "text", "text": "DESTEKLİYOR"}],
        "usage": {"input_tokens": 120, "output_tokens": 8},
        "stop_reason": "end_turn",
    }


def test_anahtarsiz_cagri_fail_closed():
    cc = CloudClient(api_key=None)
    with pytest.raises(CloudAnahtarYok):
        cc.cagir("temiz metin", system="test")
    assert cc.cagri_sayisi == 0  # 0-cloud kanıtı bozulmadı


def test_kvkk_guard_pattern_pii_engeller():
    cc = CloudClient(api_key="sk-ant-test")
    with pytest.raises(KVKKEgressEngellendi):
        cc.cagir("TCKN 12345678901 doğrulansın", system="test")
    assert cc.cagri_sayisi == 0


def test_kvkk_guard_ner_kisi_adi_engeller(monkeypatch):
    # Pattern-temiz AMA çıplak ad-soyad → NER guard (cagir İÇİNDE) engeller (Faz 5 bloker).
    monkeypatch.setenv("YT_NER_FIXTURE", "1")
    cc = CloudClient(api_key="sk-ant-test")
    with pytest.raises(KVKKEgressEngellendi):
        cc.cagir("Ahmet Yılmaz şirketi 2020'de sattı.", system="test")
    assert cc.cagri_sayisi == 0


def test_temiz_metin_gercek_cagri_ve_token_sayaci(monkeypatch):
    # httpx.post mock'la — istek şeması + sayaçlar + yanıt parse (gerçek ağ YOK).
    yakalanan: dict = {}

    def sahte_post(url, headers=None, json=None, timeout=None):
        yakalanan.update({"url": url, "headers": headers, "json": json})
        return httpx.Response(200, json=_yanit_json(), request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", sahte_post)
    monkeypatch.setenv("YT_NER_FIXTURE", "1")
    cc = CloudClient(api_key="sk-ant-test", model="claude-sonnet-4-6")
    y = cc.cagir("Video yapay zekâ tarihini anlatıyor.", system="Doğruluk denetçisisin.")
    assert isinstance(y, CloudYanit) and y.metin == "DESTEKLİYOR"
    assert yakalanan["url"] == "https://api.anthropic.com/v1/messages"
    assert yakalanan["headers"]["x-api-key"] == "sk-ant-test"
    assert yakalanan["headers"]["anthropic-version"] == "2023-06-01"
    assert yakalanan["json"]["model"] == "claude-sonnet-4-6"
    assert yakalanan["json"]["messages"][0]["role"] == "user"
    assert cc.cagri_sayisi == 1
    assert cc.toplam_girdi_token == 120 and cc.toplam_cikti_token == 8


def test_model_default_configten(monkeypatch):
    monkeypatch.delenv("YT_ANTHROPIC_MODEL", raising=False)
    assert CloudClient(api_key=None).model == "claude-sonnet-4-6"


def test_guard_mutasyon_kontrolu(monkeypatch):
    # MUTASYON-KONTROL (Faz 3/4 dersi): guard sökülürse (egress hep temiz say) PII'li metin
    # httpx'e ULAŞIR — üstteki engelleme testleri gerçekten guard'ı ölçüyor (vacuous değil).
    import ytcore.router.cloud_client as m

    gonderildi: list[dict] = []

    def sahte_post(url, **kw):
        gonderildi.append(kw["json"])
        return httpx.Response(200, json=_yanit_json(), request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", sahte_post)
    monkeypatch.setattr(m, "_egress_temiz_mi", lambda *a: True)  # guard sökük simülasyonu
    cc = CloudClient(api_key="sk-ant-test")
    cc.cagir("TCKN 12345678901", system="t")
    assert gonderildi  # guard'sız PII httpx'e ulaştı → guard yük taşıyor (kanıt)


def test_ner_instance_reuse(monkeypatch):
    # review tur-1 MED: cagir-başına YENİ SubprocessNER spawn edilmez — instance memo'lu
    # tek NER paylaşır (15 iddia = 15 BERT yüklemesi DEĞİL).
    import ytcore.router.ner as nermod

    sayac = {"n": 0}
    gercek_ner_al = nermod.ner_al

    def sayan_ner_al():
        sayac["n"] += 1
        return gercek_ner_al()

    monkeypatch.setenv("YT_NER_FIXTURE", "1")
    monkeypatch.setattr(nermod, "ner_al", sayan_ner_al)
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, **kw: httpx.Response(
            200, json=_yanit_json(), request=httpx.Request("POST", url)
        ),
    )
    cc = CloudClient(api_key="sk-ant-test")
    cc.cagir("Temiz metin bir.", system="t")
    cc.cagir("Temiz metin iki.", system="t")
    assert sayac["n"] == 1  # tek instance, iki çağrı


def test_sistem_alani_da_taranir(monkeypatch):
    # review tur-1 LOW: guard system'i de tarar (gelecekteki dinamik-system çağıranı için).
    monkeypatch.setenv("YT_NER_FIXTURE", "1")
    cc = CloudClient(api_key="sk-ant-test")
    with pytest.raises(KVKKEgressEngellendi):
        cc.cagir("temiz içerik", system="Müvekkil TCKN 12345678901 hakkında")


def test_basarisiz_http_de_sayilir(monkeypatch):
    # review tur-1 LOW: 429/500 yanıtı da GERÇEK egress — dürüst sayaç saymalı.
    monkeypatch.setenv("YT_NER_FIXTURE", "1")
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, **kw: httpx.Response(
            429, json={"error": "rate"}, request=httpx.Request("POST", url)
        ),
    )
    cc = CloudClient(api_key="sk-ant-test")
    with pytest.raises(httpx.HTTPStatusError):
        cc.cagir("temiz metin", system="t")
    assert cc.cagri_sayisi == 1  # POST gerçekleşti → sayıldı
