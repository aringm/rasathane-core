from __future__ import annotations

from typing import Any

from ytcore.content.llm import LLMClient
from ytcore.content.segment import cumlelere_bol
from ytcore.errors import KOD_HATALARI as _KOD_HATALARI
from ytcore.intel.anonim import anonimlestir, egress_pii_var_mi
from ytcore.intel.websearch import AramaSonuc, WebSearch
from ytcore.router.ner import NERTespit

_CLAIM_SISTEM = (
    "Sen bir olgu-çıkarıcısın. Verilen metinden DOĞRULANABİLİR olgusal iddiaları "
    "(istatistik, tarih, olay, sayı) tek tek satır olarak çıkar. Görüş/yorum DEĞİL. "
    "Her satır tek iddia. (iddia listesi)"
)
_VERDICT_SISTEM = (
    "Sen bir doğruluk denetçisisin. İDDİA verilen KANIT'larca doğrulanıyor mu? "
    "Yalnız tek kelime yanıtla: DESTEKLİYOR, ÇELİŞİYOR veya BELİRSİZ. (verdict)"
)
_BAGLAM_LIMIT = 6000


def _karar_bul(yanit: str) -> str | None:
    """Yanıttan karar kelimesini TR-güvenli katlamayla bul (review tur-1 HIGH).

    'destekliyor'.upper()='DESTEKLIYOR' (ASCII I) ≠ 'DESTEKLİYOR' (U+0130) → upper()-tabanlı
    eşleme küçük/karışık-harf yanıtı sessizce BELİRSİZ'e düşürür. Katlama: lower + combining-
    dot söküm + ı→i indirgeme (complexity._katlanmis ile aynı desen).
    """
    k = yanit.strip().lower().replace("̇", "").replace("ı", "i")
    # Konum-bazlı İLK eşleşme (review tur-2 LOW): "destekliyor olamaz, çelişiyor" gibi çok
    # kelimeli yanıtta sabit-öncelik sırası yanlış karar seçmesin; metinde önce geçen kazanır.
    bulunanlar = [
        (k.find(anahtar), karar)
        for karar, anahtar in (
            ("DESTEKLİYOR", "destekliyor"),
            ("ÇELİŞİYOR", "çelişiyor"),
            ("BELİRSİZ", "belirsiz"),
        )
        if anahtar in k
    ]
    return min(bulunanlar)[1] if bulunanlar else None


def iddialari_cikar(metin: str, llm: LLMClient, *, model: str | None = None) -> list[str]:
    """Metinden TR atomik olgusal iddialar. LLM satır-bazlı; boş → cümle fallback."""
    if not metin.strip():
        return []
    yanit = llm.uret(_CLAIM_SISTEM, metin[:_BAGLAM_LIMIT], model=model).strip()
    iddialar = [s.strip("-* ").strip() for s in yanit.splitlines() if s.strip()]
    iddialar = [i for i in iddialar if len(i) > 10]
    if not iddialar:  # FakeLLM/boş → cümle fallback (boş≠başarı: yine de değerlendir)
        iddialar = [c for c in cumlelere_bol(metin) if len(c) > 10][:10]
    return iddialar[:15]


def _verdict(
    iddia: str,
    kanit: list[AramaSonuc],
    llm: LLMClient,
    model: str | None,
    cloud: Any | None = None,
) -> tuple[str, str]:
    """Evidence→claim NLI. Kanıt yoksa BELİRSİZ (LLM-as-judge tek başına KARAR VERMEZ).

    Faz 5 Mod B: `cloud` verilirse verdict önce cloud'dan denenir (anonim iddia + web-kanıt;
    CloudClient.cagir KVKK guard'ı İÇERİDE). Cloud reddi/hatası analizi ÇÖKERTMEZ → local
    qwen'e graceful düşer (anahtarsız davranış Faz 3 ile birebir).
    """
    if not kanit:
        return "BELİRSİZ", "Web doğrulaması yapılamadı (kaynak yok)."
    kanit_metin = "\n".join(f"- {k.ozet}" for k in kanit)
    if cloud is not None:
        try:
            # Kanıt da anonimleştirilir (review tur-1: iddia ile simetri — web snippet'i
            # pattern-PII taşıyabilir; cagir-içi guard son backstop ama maskele önce).
            y = cloud.cagir(
                f"İDDİA: {anonimlestir(iddia)[0]}\n\n"
                f"KANIT:\n{anonimlestir(kanit_metin[:_BAGLAM_LIMIT])[0]}",
                system=_VERDICT_SISTEM,
            )
            karar_cloud = _karar_bul(y.metin)
            if karar_cloud is not None:
                return karar_cloud, f"Kanıtlara göre: {karar_cloud.lower()} (cloud verdict)."
        except _KOD_HATALARI:
            raise  # gerçek kod hatası (mock-drift/typo) görünür çök — Faz 1/2/3 dersi
        except Exception:  # noqa: BLE001 — KVKK reddi/ağ hatası → local fallback (çökme YOK)
            pass
    soru = f"İDDİA: {iddia}\n\nKANIT:\n{kanit_metin[:_BAGLAM_LIMIT]}"
    karar = _karar_bul(llm.uret(_VERDICT_SISTEM, soru, model=model))
    if karar is not None:
        return karar, f"Kanıtlara göre: {karar.lower()}."
    return "BELİRSİZ", "Verdict belirlenemedi (kanıt yetersiz/çelişkili)."


def fact_check(
    metin: str,
    llm: LLMClient,
    web: WebSearch,
    *,
    model: str | None = None,
    ner: NERTespit | None = None,
    cloud: Any | None = None,
    web_mumkun: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """claim→anonim→web→verdict. KVKK: web sorgusu HER ZAMAN anonimleştirilir.

    durum: 'uretildi' (web aktif/fixture) | 'web_yok' (anahtar yok) | 'web_hata' (ağ/429/500
    — anahtar-yok'tan AYRI, yeniden-denenebilir) | 'icerik_yok'. LLM-as-judge tek başına KARAR
    VERMEZ — kanıt yoksa BELİRSİZ (dürüst). KVKK fail-closed: anonimleştirme sonrası hâlâ PII
    içeren sorgu web'e GÖNDERİLMEZ (pii_var_mi backstop — anonim'in kaçırdığı adres/kimlik/ayraçlı).

    Faz 5 `ner`: çıplak ad-soyad pattern-gate'i ATLATIR (GÜNCELLEME 5/6 bloker) — kişi adı
    içeren sorgu web'e GİTMEZ. ner=None → çağıran web-egress'i mümkün görmedi (anahtarsız
    kurulum; subprocess spawn maliyeti yok). Egress-mümkün yolda HER ZAMAN ner_al() geçirilir.
    """
    iddialar = iddialari_cikar(metin, llm, model=model)
    if not iddialar:
        return [], "icerik_yok"
    sonuc: list[dict[str, Any]] = []
    web_aktif = False
    web_hata = False
    atlanan_var = False  # en az bir iddia PII/NER gate'iyle atlandı mı (hepsi_atlandi ayrımı)
    sorgular = [anonimlestir(i)[0] for i in iddialar]
    # NER tek TOPLU çağrı: ayrı-proses spawn maliyeti iddia-başına değil analiz-başına.
    ner_kisi = ner.kisi_var_mi(sorgular) if ner is not None else [False] * len(sorgular)
    for iddia, sorgu, kisi_var in zip(iddialar, sorgular, ner_kisi, strict=True):
        # KVKK: önce best-effort maskele, SONRA deny-by-default son-kontrol (egress_pii_var_mi):
        # KVKK FAIL-CLOSED (tur-4) — pii_gate'in gördüğü TÜM PII (email/iban/tckn/telefon/adres +
        # TÜM kimlik-bağlam, demografik 'nüfus' dahil) BLOKLANIR; yalnız PII'siz iddia web'e gider.
        if egress_pii_var_mi(sorgu):
            # Anonimleştirme yetersiz (adres vb. maskelenemez PII) → web'e GÖNDERME (fail-closed).
            sonuc.append(
                {
                    "iddia": iddia,
                    "karar": "BELİRSİZ",
                    "guven": 0.0,
                    "gerekce": "PII riski: anonimleştirme sonrası kişisel veri kaldı, "
                    "web doğrulaması atlandı (KVKK fail-closed).",
                    "kaynaklar": [],
                }
            )
            atlanan_var = True
            continue
        if kisi_var:
            # Faz 5: çıplak ad-soyad (NER) — pattern temiz olsa da web'e GÖNDERME (fail-closed).
            sonuc.append(
                {
                    "iddia": iddia,
                    "karar": "BELİRSİZ",
                    "guven": 0.0,
                    "gerekce": "PII riski: kişi adı tespit edildi ya da NER doğrulanamadı, "
                    "web doğrulaması atlandı (KVKK fail-closed).",
                    "kaynaklar": [],
                }
            )
            atlanan_var = True
            continue
        if hasattr(web, "ara_durumlu"):
            kanit, durum = web.ara_durumlu(sorgu, 3)
        else:
            kanit, durum = web.ara(sorgu, 3), "aktif"
        if durum in ("aktif", "fixture"):
            web_aktif = True
        elif durum.startswith("hata") or durum in (
            "baglanti_yok",
            "searxng_403",
            "uzak_engellendi",
        ):
            # SearXNG kurulabilir/düzeltilebilir durumlar: 'web_hata' (yeniden-denenebilir),
            # 'web_yok' (hiç servis yok) ile AYRI yüzeylenir (GUI'de farklı mesaj).
            web_hata = True
        karar, gerekce = _verdict(iddia, kanit, llm, model, cloud)
        sonuc.append(
            {
                "iddia": iddia,
                "karar": karar,
                "guven": 0.6 if kanit else 0.0,
                "gerekce": gerekce,
                "kaynaklar": [k.url for k in kanit],
            }
        )
    if web_aktif:
        return sonuc, "uretildi"
    if web_hata:
        return sonuc, "web_hata"
    # Servis VARDI (web_mumkun) ama TÜM iddialar PII/NER gate'iyle atlandı → 'web_yok' (servis yok)
    # DEĞİL, ayrı 'hepsi_atlandi' (KVKK; "arama servisi yok" yanlış teşhisi önlenir — review LOW).
    if atlanan_var and web_mumkun:
        return sonuc, "hepsi_atlandi"
    # Hiç aktif sorgu yok: gerçek servis hatası mı yoksa anahtar/servis mi yok?
    return sonuc, "web_yok"
